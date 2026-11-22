"""Сигналы, личная норма, индекс здоровья, прогноз (docs/SPEC.md, раздел 6).

Чистые функции над рядами оценок, без обращения к БД. Все оценки — на шкале 0–1.
Периоды — номера месяцев программы, начиная с 1.
"""

from dataclasses import dataclass, field
from statistics import median

SIDES = ("intern", "mentor")
SIDE_RU = {"intern": "Стажёр", "mentor": "Наставник"}
SIDE_RU_GEN = {"intern": "стажёра", "mentor": "наставника"}
TOPIC_RU = {
    "tasks": "понимание задач",
    "auto": "самостоятельность",
    "support": "поддержка",
    "load": "нагрузка",
    "feedback": "обратная связь",
    "growth": "перспективы",
}
SIGNAL_RU = {
    "level": "Уровень",
    "growth": "Растущий разрыв",
    "lag": "Запаздывание",
    "words": "Слова ≠ цифры",
    "decline": "Общее падение",
    "missing": "Нет анкеты",
    "program": "Сигнал программы",
}
ACTION_RU = {
    "level": "Сверить ожидания",
    "growth": "Встреча втроём",
    "lag": "Показать расхождение той стороне, что не видит",
    "words": "Личная беседа",
    "decline": "Решение по нагрузке и обучению",
    "missing": "Напомнить об анкете",
    "program": "Проверить программу",
}


@dataclass
class Comment:
    """Разобранный комментарий стороны пары."""

    side: str
    period: int
    text: str
    anxiety: float
    contradiction: float
    tone: float
    quote: str = ""
    topics: list[str] = field(default_factory=list)
    fallback: bool = True


@dataclass
class PairSeries:
    """Ряды оценок пары: values[сторона][тема][период]."""

    pair_id: int
    code: str
    periods: list[int]
    values: dict[str, dict[str, dict[int, float]]]
    comments: list[Comment] = field(default_factory=list)
    start_period: int = 1

    def topics(self) -> list[str]:
        """Темы, по которым есть оценки обеих сторон."""
        a = set(self.values.get("intern", {}))
        b = set(self.values.get("mentor", {}))
        return sorted(a & b)

    def has(self, side: str, period: int) -> bool:
        """Есть ли анкета стороны в периоде."""
        return any(period in s for s in self.values.get(side, {}).values())

    def overall(self, side: str, period: int) -> float | None:
        """Средняя оценка стороны по общим темам в периоде."""
        vals = [self.values[side][t][period] for t in self.topics() if period in self.values[side].get(t, {})]
        return sum(vals) / len(vals) if vals else None


@dataclass
class Signal:
    """Сработавший сигнал."""

    type: str
    topic: str | None
    strength: float
    description: str
    cause: str
    facts: dict


@dataclass
class PairResult:
    """Состояние пары на месяц."""

    pair_id: int
    period: int
    index: int
    penalties: dict[str, float]
    signals: list[Signal]
    delta: float | None
    abs_delta: float | None
    cal_delta: float | None
    slope: float
    forecast: float | None
    months_to_red: float | None
    lag_months: int
    lag_side: str | None
    state: str
    intern: float | None
    mentor: float | None
    topic_delta: dict[str, float]
    missing: list[str]


def personal_norm(series: dict[int, float], periods: list[int]) -> float | None:
    """Норма человека по теме: медиана первых двух месяцев с данными."""
    first = [series[p] for p in periods if p in series][:2]
    return median(first) if first else None


def slope_of(points: list[tuple[int, float]]) -> float:
    """Наклон линейной регрессии по точкам (период, значение) в единицах за месяц."""
    if len(points) < 2:
        return 0.0
    n = len(points)
    mx = sum(p for p, _ in points) / n
    my = sum(v for _, v in points) / n
    den = sum((p - mx) ** 2 for p, _ in points)
    return sum((p - mx) * (v - my) for p, v in points) / den if den else 0.0


def _avg(vals: list[float]) -> float | None:
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def pair_delta(
    ps: PairSeries, period: int, calibrated: bool = False
) -> tuple[float | None, dict[str, float]]:
    """Δ = стажёр − наставник по паре (среднее по темам) и по каждой теме.

    При calibrated=True сравниваются отклонения от личной нормы каждой стороны.
    """
    per_topic: dict[str, float] = {}
    for t in ps.topics():
        i = ps.values["intern"][t].get(period)
        m = ps.values["mentor"][t].get(period)
        if i is None or m is None:
            continue
        if calibrated:
            ni = personal_norm(ps.values["intern"][t], ps.periods)
            nm = personal_norm(ps.values["mentor"][t], ps.periods)
            if ni is None or nm is None:
                continue
            per_topic[t] = (i - ni) - (m - nm)
        else:
            per_topic[t] = i - m
    return _avg(list(per_topic.values())), per_topic


def _abs_series(ps: PairSeries, upto: int, calibrated: bool = False) -> list[tuple[int, float]]:
    out = []
    for p in ps.periods:
        if p > upto:
            break
        d, _ = pair_delta(ps, p, calibrated)
        if d is not None:
            out.append((p, abs(d)))
    return out


def _months_between(periods: list[int], a: int, b: int) -> int:
    return sum(1 for p in periods if a <= p <= b)


def evaluate(ps: PairSeries, period: int, cfg: dict, month_name=lambda p: f"месяц {p}") -> PairResult:
    """Считает сигналы, штрафы, индекс и прогноз пары на месяц.

    Args:
        ps: Ряды оценок пары.
        period: Месяц программы, на который считается состояние.
        cfg: Пороги и веса (см. DEFAULT_ANALYTICS).
        month_name: Функция подписи месяца (в предложном падеже не нужна).

    Returns:
        Состояние пары с разложением индекса.
    """
    periods = [p for p in ps.periods if p <= period]
    signals: list[Signal] = []
    missing = [s for s in SIDES if not ps.has(s, period)]
    intern, mentor = ps.overall("intern", period), ps.overall("mentor", period)
    delta, topic_delta = pair_delta(ps, period)
    cal_delta, cal_topic = pair_delta(ps, period, calibrated=True)

    # 1. Уровень: |Δ| пары по личной шкале ≥ порога N месяцев подряд, одного знака.
    need = int(cfg["level_months"])
    prev_periods = periods[-need:]
    if len(prev_periods) == need:
        cal = [pair_delta(ps, p, calibrated=True) for p in prev_periods]
        vals = [c[0] for c in cal]
        if (
            all(v is not None and abs(v) >= cfg["level_threshold"] for v in vals)
            and len({v > 0 for v in vals}) == 1
        ):
            v = vals[-1]
            per_topic = cal[-1][1]
            t = max(per_topic, key=lambda k: abs(per_topic[k])) if per_topic else None
            who = (
                "Стажёр оценивает себя выше, чем наставник"
                if v > 0
                else "Стажёр оценивает себя ниже, чем наставник"
            )
            tname = f", сильнее всего — «{TOPIC_RU.get(t, t)}» ({abs(per_topic[t]):.2f})" if t else ""
            signals.append(
                Signal(
                    "level",
                    t,
                    round(abs(v), 3),
                    f"{who}: расхождение {abs(v):.2f} по личной шкале {need} мес. подряд{tname}.",
                    "Стороны по-разному понимают ожидания. Начать со сверки: что значит «хорошо» для каждого.",
                    {
                        "topic": t,
                        "cal_delta": round(v, 3),
                        "raw_delta": None if delta is None else round(delta, 3),
                        "topics": {k: round(x, 3) for k, x in per_topic.items()},
                    },
                )
            )

    # 2. Растущий разрыв: наклон |Δ| за последние 3 месяца.
    abs_pts = _abs_series(ps, period)
    last3 = abs_pts[-3:]
    growth = slope_of(last3) if len(last3) >= 3 else 0.0
    if len(last3) >= 3 and growth >= cfg["growth_slope"]:
        signals.append(
            Signal(
                "growth",
                None,
                round(growth, 3),
                f"Расхождение растёт: +{growth:.2f} в месяц за последние 3 месяца (сейчас |Δ| = {last3[-1][1]:.2f}).",
                "Люди перестают понимать друг друга — нужна встреча втроём, пока разрыв не закрепился.",
                {
                    "slope": round(growth, 3),
                    "abs_delta": [round(v, 3) for _, v in last3],
                    "periods": [p for p, _ in last3],
                },
            )
        )

    # 3. Запаздывание: одна сторона устойчиво (2 месяца подряд) снизила оценку ≥ порога, другая — нет.
    def side_series(side: str) -> dict[int, float]:
        return {p: v for p in ps.periods if (v := ps.overall(side, p)) is not None}

    def sustained_drop(series: dict[int, float]) -> int | None:
        norm = personal_norm(series, ps.periods)
        if norm is None:
            return None
        run_start, prev_low = None, False
        for p in periods:
            low = p in series and series[p] <= norm - cfg["lag_drop"] + 1e-9
            if low and prev_low:
                return run_start
            run_start = p if low and not prev_low else run_start
            prev_low = low if p in series else prev_low
        return None

    lag_months, lag_side, lag_topic, lag_from = 0, None, None, None
    firsts = {s: sustained_drop(side_series(s)) for s in SIDES}
    for side in SIDES:
        other = "mentor" if side == "intern" else "intern"
        if firsts[side] is not None and firsts[other] is None:
            months = _months_between(periods, firsts[side], period)
            if months > lag_months:
                lag_months, lag_side, lag_from = months, side, firsts[side]
    if lag_side:
        drops_t = {}
        for t in ps.topics():
            ser = ps.values[lag_side][t]
            n0 = personal_norm(ser, ps.periods)
            last = [ser[p] for p in periods if p in ser]
            if n0 is not None and last:
                drops_t[t] = n0 - last[-1]
        lag_topic = max(drops_t, key=lambda k: drops_t[k]) if drops_t else None
    if lag_months >= 1 and lag_side:
        blind = "mentor" if lag_side == "intern" else "intern"
        topic_txt = f", сильнее всего «{TOPIC_RU.get(lag_topic, lag_topic)}»" if lag_topic else ""
        signals.append(
            Signal(
                "lag",
                lag_topic,
                float(lag_months),
                f"{SIDE_RU[lag_side]} снижает оценки с месяца «{month_name(lag_from)}»{topic_txt}; "
                f"{SIDE_RU_GEN[blind]} спада не видит: {lag_months} мес.",
                f"Одна сторона уже заметила проблему, вторая — ещё нет. Показать расхождение {SIDE_RU_GEN[blind]}.",
                {
                    "side": lag_side,
                    "blind": blind,
                    "topic": lag_topic,
                    "since": lag_from,
                    "months": lag_months,
                },
            )
        )

    # 4. Слова ≠ цифры: высокая оценка и тревожный комментарий.
    words_contra = 0.0
    for c in ps.comments:
        if c.period != period:
            continue
        sc = ps.overall(c.side, period)
        topical = [ps.values[c.side][t].get(period) for t in c.topics if t in ps.values.get(c.side, {})]
        topical = [v for v in topical if v is not None]
        score = max(topical) if topical else sc
        if score is None:
            continue
        words_contra = max(words_contra, c.contradiction)
        if score >= cfg["words_score"] and c.anxiety >= cfg["words_anxiety"]:
            signals.append(
                Signal(
                    "words",
                    (c.topics or [None])[0],
                    round(c.anxiety, 2),
                    f"{SIDE_RU[c.side]}: баллы {score:.2f}, а в комментарии тревога ({c.anxiety:.2f}). «{c.quote}»",
                    "Цифры говорят «всё хорошо», текст — нет. Нужна личная беседа один на один.",
                    {
                        "side": c.side,
                        "score": round(score, 3),
                        "anxiety": c.anxiety,
                        "quote": c.quote,
                        "fallback": c.fallback,
                    },
                )
            )
            break

    # Общее падение: обе стороны снизили оценки относительно первого месяца.
    first_p = periods[0] if periods else None
    drops = {}
    for s in SIDES:
        a = ps.overall(s, first_p) if first_p else None
        known = [p for p in periods if ps.overall(s, p) is not None]
        b = ps.overall(s, known[-1]) if known else None  # при пропуске анкеты — последнее известное значение
        drops[s] = (a - b) if a is not None and b is not None else 0.0
    worst_drop = max(0.0, *drops.values())
    if min(drops.values()) >= cfg["lag_drop"] and (delta is None or abs(delta) < cfg["level_threshold"]):
        signals.append(
            Signal(
                "decline",
                None,
                round(min(drops.values()), 3),
                f"Обе стороны снижают оценки: стажёр −{drops['intern']:.2f}, наставник −{drops['mentor']:.2f} с начала программы.",
                "Спора нет — есть общая проблема: нагрузка, время наставника или обучение.",
                {"drop_intern": round(drops["intern"], 3), "drop_mentor": round(drops["mentor"], 3)},
            )
        )

    if missing:
        signals.append(
            Signal(
                "missing",
                None,
                0.0,
                "Нет анкеты: " + ", ".join(SIDE_RU_GEN[s] for s in missing) + ".",
                "Это неполнота данных, а не проблема пары.",
                {"sides": missing},
            )
        )

    # Индекс здоровья.
    avg = _avg([intern, mentor])
    slope2_pts = abs_pts[-3:]
    slope2 = (
        (slope2_pts[-1][1] - slope2_pts[0][1]) / max(1, slope2_pts[-1][0] - slope2_pts[0][0])
        if len(slope2_pts) >= 2
        else 0.0
    )
    if len(slope2_pts) == 3:
        slope2 = (slope2_pts[2][1] - slope2_pts[0][1]) / 2
    pen = {
        "level": abs(cal_delta) * cfg["w_level"] if cal_delta is not None else 0.0,
        "growth": max(0.0, slope2) * cfg["w_growth"],
        "drop": worst_drop * cfg["w_drop"],
        "low": max(0.0, cfg["low_level"] - avg) * cfg["w_low"] if avg is not None else 0.0,
        "words": words_contra * cfg["w_words"],
        "lag": lag_months * cfg["w_lag"],
        "missing": cfg["w_missing"] if missing else 0.0,
    }
    pen = {k: round(v, 1) for k, v in pen.items()}
    index = int(round(max(cfg["index_floor"], 100 - sum(pen.values()))))

    # Прогноз: последнее |Δ| + наклон.
    trend = slope_of(abs_pts[-3:]) if len(abs_pts) >= 2 else 0.0
    last_abs = abs_pts[-1][1] if abs_pts else None
    forecast = max(0.0, last_abs + trend) if last_abs is not None and len(abs_pts) >= 2 else None
    to_red = None
    if last_abs is not None:
        if last_abs >= cfg["red_zone"]:
            to_red = 0.0
        elif trend > 0.005:
            to_red = round((cfg["red_zone"] - last_abs) / trend, 1)

    real = [s for s in signals if s.type not in ("missing",)]
    types = {s.type for s in real}
    if "words" in types:
        state = "words"
    elif "decline" in types:
        state = "both"
    elif types & {"level", "growth", "lag"}:
        d = delta if delta is not None else 0.0
        if lag_side and abs(d) < 0.05:
            d = 1.0 if lag_side == "mentor" else -1.0
        state = "over" if d > 0 else "under"
    else:
        state = "ok"

    return PairResult(
        pair_id=ps.pair_id,
        period=period,
        index=index,
        penalties=pen,
        signals=signals,
        delta=None if delta is None else round(delta, 3),
        abs_delta=None if last_abs is None else round(last_abs, 3),
        cal_delta=None if cal_delta is None else round(cal_delta, 3),
        slope=round(trend, 3),
        forecast=None if forecast is None else round(forecast, 3),
        months_to_red=to_red,
        lag_months=lag_months,
        lag_side=lag_side,
        state=state,
        intern=None if intern is None else round(intern, 3),
        mentor=None if mentor is None else round(mentor, 3),
        topic_delta={k: round(v, 3) for k, v in topic_delta.items()},
        missing=missing,
    )


def program_signals(series: list[PairSeries], period: int, cfg: dict) -> list[Signal]:
    """Сигнал программы: тема проседает у ≥ доли пар в одном месяце."""
    prev = period - 1
    if prev < 1:
        return []
    topics = set.intersection(*(set(ps.topics()) for ps in series)) if series else set()
    out = []
    for t in sorted(topics):
        hit, total = [], 0
        for ps in series:
            vals_now = [ps.values[s][t].get(period) for s in SIDES]
            vals_prev = [ps.values[s][t].get(prev) for s in SIDES]
            if None in vals_now or None in vals_prev:
                continue
            total += 1
            if sum(vals_prev) / 2 - sum(vals_now) / 2 >= cfg["program_drop"] - 1e-9:
                hit.append(ps.code)
        if total and len(hit) / total >= cfg["program_share"]:
            out.append(
                Signal(
                    "program",
                    t,
                    round(len(hit) / total, 2),
                    f"«{TOPIC_RU.get(t, t).capitalize()}» проседает у {len(hit)} пар из {total} в одном месяце.",
                    "Это проблема программы, а не отдельных людей: проверить, что происходит на этом этапе стажировки.",
                    {"topic": t, "pairs": hit, "total": total},
                )
            )
    return out
