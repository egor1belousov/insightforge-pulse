"""Проверка детектора на синтетике: `python -m ml.validate [--n 200] [--seed 7]`.

Для каждого сценария генерирует N пар с шумом, закладывает проблему с месяца s
и смотрит, на каком месяце сработал ожидаемый сигнал. На здоровых парах считает
долю ложных тревог. Итог — docs/VALIDATION.md и docs/validation.json.
"""

import argparse
import json
import random
from pathlib import Path

from app.core.settings import DEFAULT_ANALYTICS
from app.services.analytics.core import Comment, PairSeries, evaluate

TOPICS = ["tasks", "auto", "support", "load", "feedback", "growth"]
PERIODS = [1, 2, 3, 4, 5, 6]
ROOT = Path(__file__).resolve().parent.parent

SCENARIOS = {
    "overestimate": ("Стажёр переоценивает себя, расхождение растёт", {"level", "growth", "lag"}),
    "blind": ("Стажёр тревожится, наставник не видит", {"level", "growth", "lag"}),
    "overload": ("Общее падение, наставник перегружен", {"decline", "lag"}),
    "words": ("Высокие баллы, тревожный текст", {"words"}),
    "healthy": ("Здоровая пара", set()),
}
SCALES = {"без округления": None, "1–10": (1, 10), "1–5": (1, 5)}


def quantize(v: float, scale: tuple[int, int] | None) -> float:
    v = max(0.0, min(1.0, v))
    if scale is None:
        return v
    lo, hi = scale
    return (round(lo + v * (hi - lo)) - lo) / (hi - lo)


def make_pair(kind: str, start: int, rng: random.Random, scale: tuple[int, int] | None) -> PairSeries:
    """Пара с заложенным сценарием с месяца start."""
    base = {"intern": rng.uniform(0.55, 0.75), "mentor": rng.uniform(0.5, 0.75)}
    if kind == "words":
        base = {"intern": rng.uniform(0.75, 0.85), "mentor": rng.uniform(0.72, 0.85)}
    off = {s: {t: rng.gauss(0, 0.03) for t in TOPICS} for s in base}
    growth = {s: rng.uniform(0.0, 0.025) for s in base}
    values: dict = {"intern": {t: {} for t in TOPICS}, "mentor": {t: {} for t in TOPICS}}
    comments = []
    for p in PERIODS:
        k = max(0, p - start + 1)  # сколько месяцев действует сценарий
        trend = {s: base[s] + growth[s] * (p - 1) for s in base}
        if kind == "overestimate":
            trend["intern"] += 0.05 * k
            trend["mentor"] -= 0.07 * k
        elif kind == "blind":
            trend["intern"] -= 0.08 * k
            trend["mentor"] += 0.03 * k
        elif kind == "overload":
            trend["intern"] -= 0.06 * k
            trend["mentor"] -= 0.06 * k
        for s in base:
            for t in TOPICS:
                values[s][t][p] = quantize(trend[s] + off[s][t] + rng.gauss(0, 0.04), scale)
        anxious = kind == "words" and k > 0
        anx = rng.uniform(0.6, 0.9) if anxious else rng.uniform(0.0, 0.35)
        score = sum(values["intern"][t][p] for t in TOPICS) / len(TOPICS)
        contra = anx * max(0.0, min(1.0, (score - 0.4) / 0.35))
        comments.append(
            Comment("intern", p, "", anxiety=round(anx, 2), contradiction=round(contra, 2), tone=0.0)
        )
    return PairSeries(0, kind, PERIODS, values, comments)


def detect(ps: PairSeries, expected: set[str]) -> tuple[int | None, set[str]]:
    """Первый месяц, когда сработал ожидаемый сигнал, и все сработавшие типы."""
    fired: set[str] = set()
    first = None
    for p in PERIODS:
        types = {s.type for s in evaluate(ps, p, DEFAULT_ANALYTICS).signals} - {"missing"}
        fired |= types
        if first is None and types & expected:
            first = p
    return first, fired


def run(n: int, seed: int) -> dict:
    rng = random.Random(seed)
    out: dict = {}
    for scale_name, scale in SCALES.items():
        rows = []
        for kind, (title, expected) in SCENARIOS.items():
            delays, detected, any_alarm, alarm_months, total_months = [], 0, 0, 0, 0
            types_count: dict[str, int] = {}
            for _ in range(n):
                start = rng.choice([2, 3, 4])
                ps = make_pair(kind, start, rng, scale)
                if kind == "healthy":
                    for p in PERIODS:
                        total_months += 1
                        if {s.type for s in evaluate(ps, p, DEFAULT_ANALYTICS).signals} - {"missing"}:
                            alarm_months += 1
                    _, fired = detect(ps, {"level", "growth", "lag", "words", "decline"})
                    any_alarm += bool(fired)
                    for t in fired:
                        types_count[t] = types_count.get(t, 0) + 1
                    continue
                first, fired = detect(ps, expected)
                for t in fired & expected:
                    types_count[t] = types_count.get(t, 0) + 1
                if first is not None:
                    detected += 1
                    delays.append(first - start)
            row = {"kind": kind, "title": title, "n": n}
            if kind == "healthy":
                row |= {
                    "false_alarm_pairs": round(any_alarm / n, 3),
                    "false_alarm_months": round(alarm_months / total_months, 3),
                    "types": types_count,
                }
            else:
                delays.sort()
                row |= {
                    "recall": round(detected / n, 3),
                    "median_delay": delays[len(delays) // 2] if delays else None,
                    "mean_delay": round(sum(delays) / len(delays), 2) if delays else None,
                    "types": types_count,
                }
            rows.append(row)
        out[scale_name] = rows
    return out


def to_markdown(res: dict, n: int, seed: int) -> str:
    lines = [
        "# Проверка детектора",
        "",
        f"Отчёт сформирован `python -m ml.validate --n {n} --seed {seed}`. Цифры — из этого прогона, не подобраны вручную.",
        "",
        "Как проверяли: для каждого сценария генерируется N синтетических пар (6 месяцев, 6 тем, шум σ = 0,04, "
        "разброс исходного уровня и тем). Проблема закладывается со 2-го, 3-го или 4-го месяца. Детектор — тот же код, "
        "что в приложении (`app/services/analytics/core.py`), со стартовыми порогами. Задержка — на сколько месяцев позже "
        "заложенного сигнал сработал (0 — в тот же месяц).",
        "",
        "Оценки округляются до шкалы анкеты: при шкале 1–5 один шаг — это 0,25, поэтому шум округления сопоставим с порогами.",
        "",
    ]
    for scale, rows in res.items():
        lines += [
            f"## Шкала: {scale}",
            "",
            "| Сценарий | Нашли | Задержка, медиана (мес.) | Средняя задержка | Какие сигналы |",
            "|---|---|---|---|---|",
        ]
        for r in rows:
            types = ", ".join(f"{k}: {v}" for k, v in sorted(r["types"].items())) or "—"
            if r["kind"] == "healthy":
                lines.append(
                    f"| {r['title']} | ложные тревоги: {r['false_alarm_pairs'] * 100:.0f}% пар, {r['false_alarm_months'] * 100:.0f}% пар-месяцев | — | — | {types} |"
                )
            else:
                md = "—" if r["median_delay"] is None else r["median_delay"]
                mean = "—" if r["mean_delay"] is None else f"{r['mean_delay']:.2f}"
                lines.append(
                    f"| {r['title']} | {r['recall'] * 100:.0f}% из {r['n']} | {md} | {mean} | {types} |"
                )
        lines.append("")
    lines += [
        "## Чего система не обещает",
        "",
        "- Синтетика проверяет, что детектор ловит заложенные паттерны и как часто тревожит зря. Она не доказывает, что паттерны совпадают с реальным уходом стажёров.",
        "- Пять пар — это наблюдения, а не статистика. Пороги стартовые: согласуем с HR и калибруем на исторических данных (итоги потоков в разделе «Программа»).",
        "- Прогноз на месяц — продолжение тренда, ориентир, а не предсказание.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Проверка детектора на синтетике")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    res = run(args.n, args.seed)
    (ROOT / "docs" / "VALIDATION.md").write_text(to_markdown(res, args.n, args.seed), encoding="utf-8")
    (ROOT / "docs" / "validation.json").write_text(
        json.dumps({"n": args.n, "seed": args.seed, "results": res}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    for scale, rows in res.items():
        print(scale)
        for r in rows:
            print("  ", {k: v for k, v in r.items() if k != "title"})


if __name__ == "__main__":
    main()
