"""Данные дашборда и карточки пары. Расчёты берутся из analytics.core, тексты — по прототипу."""

from collections import defaultdict

from sqlalchemy.orm import Session

from app.db.models import (
    Action,
    HrNote,
    Pair,
    PairMentorHistory,
    Participant,
    Program,
    Response,
    Signal,
    TalkRequest,
    User,
)
from app.services.analytics.core import (
    SIDES,
    TOPIC_RU,
    PairResult,
    PairSeries,
    evaluate,
    personal_norm,
    slope_of,
)
from app.services.analytics.service import analytics_config, load_series, month_name
from app.services.llm.fallback import tone_label

ST = {
    "ok": {"label": "Согласны, растут", "bg": "var(--ok-bg)", "fg": "var(--ok-fg)", "dot": "#1F8F4E"},
    "over": {"label": "Переоценивает себя", "bg": "var(--over-bg)", "fg": "var(--over-fg)", "dot": "#C26F00"},
    "under": {
        "label": "Недооценивает себя",
        "bg": "var(--under-bg)",
        "fg": "var(--under-fg)",
        "dot": "#2F6FDB",
    },
    "both": {"label": "Оба тревожатся", "bg": "var(--both-bg)", "fg": "var(--both-fg)", "dot": "#C93434"},
    "words": {"label": "Слова ≠ цифры", "bg": "var(--words-bg)", "fg": "var(--words-fg)", "dot": "#6C4FD6"},
    "neutral": {
        "label": "Сигналов нет",
        "bg": "var(--neutral-bg)",
        "fg": "var(--neutral-fg)",
        "dot": "#8A93A6",
    },
    "new": {
        "label": "Новая пара · данных нет",
        "bg": "var(--neutral-bg)",
        "fg": "var(--muted)",
        "dot": "#B0B7C6",
    },
}
TYPE_UP = {
    "level": "УРОВЕНЬ",
    "growth": "ТРЕНД",
    "lag": "ЗАПАЗДЫВАНИЕ",
    "words": "СЛОВА ≠ ЦИФРЫ",
    "decline": "ОБЩЕЕ ПАДЕНИЕ",
}
TITLE = {
    "over": "Оценки расходятся: стажёр выше",
    "under": "Стажёр недооценивает себя",
    "both": "Оба снижают оценки",
    "words": "Высокие баллы, тревожный текст",
}
SIDE_LABEL = {"intern": "Стажёр", "mentor": "Наставник"}
TOPIC_NAME = {k: v.capitalize() for k, v in TOPIC_RU.items()}
RECOMMEND = {
    "growth": ("meeting", "Встреча втроём: стажёр, наставник, HR", "на этой неделе"),
    "level": ("expect", "Сверить ожидания: что значит «хорошо» для каждого", "сверка ожиданий"),
    "lag": ("show", "Показать расхождение стороне, которая не видит спада", "короткий разговор"),
    "words": ("talk", "Личная беседа один на один", "HR"),
    "decline": ("load", "HR и руководитель: решить нагрузку наставника", "срочно"),
    "missing": ("remind", "Напомнить об анкете", "рассылка"),
}
STATUS_RU = {"assigned": "Назначено", "done": "Выполнено", "effect_checked": "Эффект проверен"}


def _signals_at(db: Session, program: Program, period: int) -> dict[int | None, list[Signal]]:
    out: dict[int | None, list[Signal]] = defaultdict(list)
    for s in db.query(Signal).filter(Signal.program_id == program.id, Signal.period == period):
        out[s.pair_id].append(s)
    return out


def _state(res: PairResult | None, ps: PairSeries) -> str:
    if res is None:
        return "new"
    real = [s for s in res.signals if s.type != "missing"]
    if real:
        return res.state
    first, last = ps.periods[0], res.period
    rising = all((ps.overall(s, last) or 0) >= (ps.overall(s, first) or 0) for s in SIDES)
    return "ok" if rising and len(ps.periods) > 1 else "neutral"


def _last_known(ps: PairSeries, side: str, upto: int) -> float | None:
    """Последняя известная средняя оценка стороны (при пропуске анкеты)."""
    for p in reversed([x for x in ps.periods if x <= upto]):
        v = ps.overall(side, p)
        if v is not None:
            return round(v, 3)
    return None


def periods_of(db: Session, program: Program) -> list[int]:
    """Месяцы программы, по которым есть данные."""
    rows = (
        db.query(Response.period)
        .join(Participant, Participant.id == Response.participant_id)
        .filter(Participant.program_id == program.id)
        .distinct()
        .all()
    )
    return sorted(r[0] for r in rows) or [1]


def _context(db: Session, program: Program) -> tuple[dict, list[PairSeries], dict[int, Pair]]:
    cfg = analytics_config(db, program.organization_id)
    series = load_series(db, program, use_llm=False)
    pairs = {p.id: p for p in db.query(Pair).filter(Pair.program_id == program.id)}
    return cfg, series, pairs


def _forecast(abs_pts: list[tuple[int, float]]) -> float | None:
    if len(abs_pts) < 2:
        return None
    return max(0.0, abs_pts[-1][1] + slope_of(abs_pts[-3:]))


def dashboard(
    db: Session, program: Program, user: User, period: int | None = None, dept: str | None = None
) -> dict:
    """Все виджеты дашборда на выбранный месяц и подразделение."""
    cfg, series, pairs = _context(db, program)
    months = periods_of(db, program)
    last = months[-1]
    m = last if period is None else max(months[0], min(period, last))
    depts = sorted({(p.intern.department or p.mentor.department or "—") for p in pairs.values()})
    rows = []
    for ps in series:
        pair = pairs[ps.pair_id]
        d = pair.intern.department or pair.mentor.department or "—"
        if dept and dept != "all" and d != dept:
            continue
        if m not in ps.periods:
            res = None
        else:
            res = evaluate(ps, m, cfg, lambda p: month_name(program, p))
        state = _state(res, ps)
        abs_pts = []
        for p in ps.periods:
            if p > m:
                break
            r = evaluate(ps, p, cfg) if p != m else res
            if r and r.abs_delta is not None:
                abs_pts.append((p, r.abs_delta))
        real = [s for s in (res.signals if res else []) if s.type != "missing"]
        rows.append(
            {
                "id": ps.pair_id,
                "code": pair.code,
                "intern": pair.intern.external_id,
                "mentor": pair.mentor.external_id,
                "dept": d,
                "state": state,
                "st": ST[state],
                "health": res.index if res else None,
                "visible": bool(real),
                "signals": [s.type for s in (res.signals if res else [])],
                "i": _last_known(ps, "intern", m),
                "m": _last_known(ps, "mentor", m),
                "abs": [[p, v] for p, v in abs_pts],
                "forecast": _forecast(abs_pts) if m == last else None,
                "abs_now": res.abs_delta if res else None,
                "penalties": res.penalties if res else {},
                "missing": res.missing if res else [],
                "res": res,
            }
        )
    attn = [r for r in rows if r["visible"]]
    n = len(rows)
    healths = [r["health"] for r in rows if r["health"] is not None]
    now = [r["abs_now"] for r in rows if r["abs_now"] is not None]
    prev = []
    for r in rows:
        prev += [v for p, v in r["abs"] if p == m - 1]
    states = defaultdict(int)
    for r in attn:
        states[r["state"]] += 1
    sub_parts = []
    if states["over"] + states["under"] >= 2:
        sub_parts.append(
            f"{states['over'] + states['under']} пары расходятся в разные стороны"
            if states["over"] and states["under"]
            else f"{states['over'] + states['under']} пары расходятся"
        )
    elif states["over"] + states["under"] == 1:
        sub_parts.append("одна пара расходится")
    if states["both"]:
        sub_parts.append("одна падает целиком" if states["both"] == 1 else f"{states['both']} падают целиком")
    if states["words"]:
        sub_parts.append(
            "в одной слова не совпадают с цифрами"
            if states["words"] == 1
            else f"в {states['words']} слова не совпадают с цифрами"
        )
    if m < last:
        sub = f"Так выглядела программа в {month_name(program, m, 'in')}. Сдвигайте ползунок, чтобы увидеть, когда появился каждый сигнал."
    elif sub_parts:
        sub = (", ".join(sub_parts) + ".").capitalize()
    else:
        sub = "Сигналов нет: оценки сторон согласованы."
    responded = {r.participant_id for r in db.query(Response).filter(Response.period == m)}
    expected = []
    for r in rows:
        pr = pairs[r["id"]]
        expected += [pr.intern, pr.mentor]
    got = sum(1 for p in expected if p.id in responded)
    pending = [p.external_id for p in expected if p.id not in responded]

    def plural(k: int, a: str, b: str, c: str) -> str:
        return (
            a if k % 10 == 1 and k % 100 != 11 else b if 2 <= k % 10 <= 4 and not 12 <= k % 100 <= 14 else c
        )

    talk = db.query(TalkRequest).filter(TalkRequest.answered.is_(False)).order_by(TalkRequest.id.desc()).all()
    talk = [t for t in talk if (pt := db.get(Participant, t.participant_id)) and pt.program_id == program.id]
    alerts = []
    if user.role in ("hr", "lead") and m == last:
        for t in talk:
            pt = db.get(Participant, t.participant_id)
            pr = next(
                (p for p in pairs.values() if pt.id in (p.intern_participant_id, p.mentor_participant_id)),
                None,
            )
            alerts.append(
                {
                    "pair": pr.code if pr else pt.external_id,
                    "pair_id": pr.id if pr else None,
                    "dot": "#E38B00",
                    "type": "ПРЯМОЙ ЗАПРОС",
                    "title": f"{pt.external_id} хочет поговорить с HR",
                    "why": f"Тема: {t.topic}. {t.text or 'Без комментария.'}",
                }
            )
    for r in sorted(attn, key=lambda r: r["health"] if r["health"] is not None else 100):
        res: PairResult = r["res"]
        types = [s.type for s in res.signals if s.type in TYPE_UP]
        main = next((s for s in res.signals if s.type in ("words", "decline")), None) or next(
            (s for s in res.signals if s.type in TYPE_UP), None
        )
        alerts.append(
            {
                "pair": r["code"],
                "pair_id": r["id"],
                "dot": r["st"]["dot"],
                "type": " + ".join(TYPE_UP[t] for t in dict.fromkeys(types)),
                "title": TITLE.get(r["state"], "Нужен разговор"),
                "why": main.description if main else "",
            }
        )

    prog_hist = (
        db.query(Signal)
        .filter(Signal.program_id == program.id, Signal.pair_id.is_(None), Signal.period <= m)
        .order_by(Signal.period)
        .all()
    )
    topics = sorted(
        set.intersection(*(set(ps.topics()) for ps in series)) if series else set(),
        key=lambda t: list(TOPIC_RU).index(t) if t in TOPIC_RU else 99,
    )
    heat_rows = []
    for t in topics:
        cells = []
        for p in months:
            vals = [ps.values[s][t][p] for ps in series for s in SIDES if p in ps.values[s].get(t, {})]
            v = sum(vals) / len(vals) if vals else None
            ring = any(s.topic == t and s.period == p for s in prog_hist)
            cells.append({"p": p, "v": None if v is None or p > m else round(v, 2), "ring": ring and p <= m})
        heat_rows.append({"topic": t, "name": TOPIC_NAME.get(t, t), "cells": cells})
    latest_prog = prog_hist[-1] if prog_hist else None
    if latest_prog:
        same = [s for s in prog_hist if s.period == latest_prog.period]
        names = " и ".join(f"«{TOPIC_NAME.get(s.topic, s.topic)}»" for s in same)
        prog_box = {
            "title": f"Системно: {names} проседают в {month_name(program, latest_prog.period, 'in')} у {len(latest_prog.facts['pairs'])} пар из {latest_prog.facts['total']}",
            "text": f"Это {latest_prog.period}-й месяц программы — проблема программы, а не отдельных людей. Предложение: плановая встреча втроём в начале {latest_prog.period}-го месяца для всех пар.",
        }
    else:
        prog_box = None

    feed = []
    for ps in series:
        pr = pairs[ps.pair_id]
        d = pr.intern.department or pr.mentor.department or "—"
        if dept and dept != "all" and d != dept:
            continue
        for c in ps.comments:
            if c.period in (m, m - 1):
                who = pr.intern.external_id if c.side == "intern" else pr.mentor.external_id
                feed.append(
                    {
                        "pair": pr.code,
                        "pair_id": pr.id,
                        "who": who,
                        "text": c.text,
                        "tone": tone_label(c.tone),
                        "anxiety": c.anxiety,
                        "period": c.period,
                        "month": month_name(program, c.period),
                        "fallback": c.fallback,
                    }
                )
    feed.sort(key=lambda x: (-x["period"], -x["anxiety"]))

    tasks = _tasks(db, program, user, rows, pending, talk) if user.role == "hr" else []
    return {
        "period": m,
        "months": [
            {"p": p, "short": month_name(program, p, "short"), "full": month_name(program, p)} for p in months
        ],
        "last": last,
        "next_short": month_name(program, last + 1, "short"),
        "tag": f"{month_name(program, m).upper()} · {m}-Й МЕСЯЦ ПРОГРАММЫ"
        + (f" · {dept.upper()}" if dept and dept != "all" else ""),
        "headline": "Сигналов нет — пары в норме"
        if not attn
        else f"{len(attn)} {plural(len(attn), 'пара', 'пары', 'пар')} из {n} {'требует' if len(attn) == 1 else 'требуют'} внимания",
        "sub": sub,
        "depts": depts,
        "dept": dept or "all",
        "kpis": [
            {
                "label": "Пар в зоне внимания",
                "value": f"{len(attn)} из {n}",
                "note": "по четырём типам расхождения",
                "color": "var(--over)" if attn else "var(--ok-fg)",
                "help": "Пары, у которых сработал хотя бы один сигнал",
            },
            {
                "label": "Средний индекс здоровья",
                "value": str(round(sum(healths) / len(healths))) if healths else "—",
                "note": "от 0 до 100, выше — лучше",
                "color": "var(--ink)",
                "help": "100 минус штрафы; подробности в справочнике",
            },
            {
                "label": f"Среднее |Δ|, {month_name(program, m)}",
                "value": f"{sum(now) / len(now):.2f}" if now else "—",
                "note": f"месяцем раньше {sum(prev) / len(prev):.2f}"
                if prev
                else "первый месяц — не с чем сравнить",
                "color": "var(--accent)",
                "help": "Средняя разница оценок стажёра и наставника",
            },
            {
                "label": f"Анкет за {month_name(program, m)}",
                "value": f"{got}/{len(expected)}",
                "note": ("ждём: " + ", ".join(pending)) if pending else "все получены",
                "color": "var(--ink)",
                "help": "Сколько анкет пришло в этом месяце",
            },
        ],
        "alerts": alerts,
        "pairs": [{k: v for k, v in r.items() if k != "res"} for r in rows],
        "program": {
            "rows": heat_rows,
            "box": prog_box,
            "months": [month_name(program, p, "short") for p in months],
        },
        "forms": {"got": got, "total": len(expected), "pending": pending, "month": month_name(program, m)},
        "feed": feed[:8],
        "tasks": tasks,
        "red_zone": cfg["red_zone"],
    }


def _tasks(
    db: Session, program: Program, user: User, rows: list[dict], pending: list[str], talk: list[TalkRequest]
) -> list[dict]:
    from app.db.models import DashboardLayout

    lay = db.get(DashboardLayout, user.id)
    done = (lay.layout or {}).get("tdone", {}) if lay else {}
    out = []
    for t in talk:
        pt = db.get(Participant, t.participant_id)
        out.append(
            {
                "k": f"talk{t.id}",
                "title": f"Ответить {pt.external_id} на запрос разговора",
                "sub": f"тема: {t.topic}",
                "link": "/pairs",
                "auto": False,
            }
        )
    acts = db.query(Action).filter(Action.pair_id.in_([r["id"] for r in rows] or [0])).all()
    by_pair = defaultdict(list)
    for a in acts:
        by_pair[a.pair_id].append(a)
    for r in sorted([r for r in rows if r["visible"]], key=lambda r: r["health"] or 100):
        if by_pair[r["id"]]:
            continue
        main = next((t for t in ("decline", "growth", "words", "lag", "level") if t in r["signals"]), None)
        if main:
            _, title, kind = RECOMMEND[main]
            out.append(
                {
                    "k": f"rec{r['id']}",
                    "title": title,
                    "sub": f"{r['code']} · {kind}",
                    "link": f"/pairs?id={r['id']}&tab=act",
                    "auto": False,
                }
            )
    for a in acts:
        if a.status == "assigned":
            pr = next(r for r in rows if r["id"] == a.pair_id)
            out.append(
                {
                    "k": f"a{a.id}",
                    "title": f"Проверить: {a.title}",
                    "sub": pr["code"],
                    "link": f"/pairs?id={a.pair_id}&tab=act",
                    "auto": False,
                }
            )
    for ext in pending:
        out.append(
            {
                "k": f"rem{ext}",
                "title": f"Напомнить {ext} об анкете",
                "sub": "рассылка месяца",
                "link": "/forms",
                "auto": False,
            }
        )
    paired = {p.intern_participant_id for p in db.query(Pair).filter(Pair.program_id == program.id)}
    for p in db.query(Participant).filter(Participant.program_id == program.id, Participant.side == "intern"):
        if p.id not in paired:
            out.append(
                {
                    "k": f"pair{p.id}",
                    "title": f"Подобрать наставника для {p.external_id}",
                    "sub": "Программа · новый стажёр",
                    "link": "/program",
                    "auto": False,
                }
            )
    for t in out:
        t["done"] = bool(done.get(t["k"]))
    return out[:8]


# ---------- карточка пары ----------


def _chart_series(ps: PairSeries, side: str, topic: str, calibrated: bool) -> list[tuple[int, float]]:
    pts = []
    for p in ps.periods:
        if topic == "all":
            v = ps.overall(side, p)
        else:
            v = ps.values.get(side, {}).get(topic, {}).get(p)
        if v is not None:
            pts.append((p, v))
    if calibrated and pts:
        if topic == "all":
            ser = {p: v for p, v in pts}
        else:
            ser = ps.values[side][topic]
        n0 = personal_norm(ser, ps.periods) or 0.5
        pts = [(p, max(0.0, min(1.0, 0.5 + v - n0))) for p, v in pts]
    return pts


def _flags(res: PairResult, ps: PairSeries, pair: Pair, period: int) -> tuple[list, list]:
    red, amb, grn, vio = (
        ("var(--both-bg)", "var(--both-fg)"),
        ("var(--over-bg)", "var(--over-fg)"),
        ("var(--ok-bg)", "var(--ok-fg)"),
        ("var(--words-bg)", "var(--words-fg)"),
    )
    fi, fm = [], []
    types = {s.type: s for s in res.signals}
    first = ps.periods[0]
    drop_i = (ps.overall("intern", first) or 0) - (
        ps.overall("intern", period) or ps.overall("intern", first) or 0
    )
    if res.state == "over":
        fi.append(("уверен в себе", amb))
    if res.state in ("under", "both") and drop_i >= 0.15:
        fi.append(("ранний признак риска ухода", red))
    if "words" in types and types["words"].facts.get("side") == "intern":
        fi.append(("слова ≠ цифры", vio))
    if res.state == "ok":
        fi.append(("растёт", grn))
        fm.append(("согласован со стажёром", grn))
    lag = types.get("lag")
    if lag and lag.facts.get("blind") == "mentor":
        fm.append(("не видит тревоги", amb))
    if lag and lag.facts.get("side") == "mentor":
        fm.append(("снижает оценки", red))
    mcom = [c for c in ps.comments if c.side == "mentor"]
    if "decline" in types and any(c.anxiety >= 0.4 for c in mcom):
        fm.append(("перегружен", red))
    if "mentor" in res.missing:
        fm.append(("анкета не сдана", amb))
    if "intern" in res.missing:
        fi.append(("анкета не сдана", amb))
    if mcom and all(len(c.text) <= 12 for c in mcom[-2:]):
        fm.append(("формальные ответы", amb))
    return [{"text": t, "bg": c[0], "fg": c[1]} for t, c in fi], [
        {"text": t, "bg": c[0], "fg": c[1]} for t, c in fm
    ]


def _effect(db: Session, program: Program, a: Action, ps: PairSeries, cfg: dict) -> dict | None:
    if a.status not in ("done", "effect_checked") or a.period is None:
        return None
    later = [p for p in ps.periods if p > a.period]
    base = evaluate(ps, a.period, cfg) if a.period in ps.periods else None
    if not later or base is None or base.abs_delta is None:
        return {"text": "Эффект покажет следующая анкета.", "good": None}
    after = evaluate(ps, later[-1], cfg)
    if after.abs_delta is None:
        return {"text": "Эффект покажет следующая анкета.", "good": None}
    good = after.abs_delta < base.abs_delta - 0.02 or after.index > base.index + 3
    return {
        "text": f"{month_name(program, later[-1]).capitalize()}: |Δ| {base.abs_delta:.2f} → {after.abs_delta:.2f}, индекс {base.index} → {after.index}"
        + (" — расхождение сократилось." if good else " — изменений нет, нужен следующий шаг."),
        "good": good,
    }


def diagnosis(
    db: Session, program: Program, pair: Pair, user: User, topic: str = "all", scale: str = "raw"
) -> dict:
    """Карточка пары: разложение расхождения, график, штрафы, тепловая карта, люди, действия."""
    cfg, series, pairs = _context(db, program)
    ps = next((s for s in series if s.pair_id == pair.id), None)
    dept = pair.intern.department or pair.mentor.department or "—"
    head = {
        "id": pair.id,
        "code": pair.code,
        "intern": pair.intern.external_id,
        "mentor": pair.mentor.external_id,
        "dept": dept,
    }
    hist = (
        db.query(PairMentorHistory)
        .filter(PairMentorHistory.pair_id == pair.id)
        .order_by(PairMentorHistory.period.desc())
        .first()
    )
    if hist:
        old = db.get(Participant, hist.old_mentor_id) if hist.old_mentor_id else None
        head["swap"] = {
            "period": hist.period,
            "was": old.external_id if old else "—",
            "month": month_name(program, hist.period),
        }
    if ps is None or not ps.periods:
        return head | {"empty": True, "st": ST["new"]}
    last = ps.periods[-1]
    res = evaluate(ps, last, cfg, lambda p: month_name(program, p))
    state = _state(res, ps)
    cal = scale == "cal"
    si = _chart_series(ps, "intern", topic, cal)
    sm = _chart_series(ps, "mentor", topic, cal)

    def fc(pts: list[tuple[int, float]]) -> float | None:
        if len(pts) < 2:
            return None
        a = [v for _, v in pts]
        k = min(2, len(a) - 1)
        return max(0.0, min(1.0, a[-1] + (a[-1] - a[-1 - k]) / k))

    fi, fm = fc(si), fc(sm)
    d_now = (si[-1][1] - sm[-1][1]) if si and sm and si[-1][0] == sm[-1][0] else res.delta
    f_abs = abs(fi - fm) if fi is not None and fm is not None else None
    if res.abs_delta is not None and res.abs_delta >= cfg["red_zone"]:
        red = "пара уже в ней."
    elif res.months_to_red is not None:
        red = f"при текущем тренде — примерно {max(1, round(res.months_to_red))} мес."
    else:
        red = "пара к ней не приближается."
    if hist:
        red += " После смены наставника прогноз ненадёжен."
    types = {s.type: s for s in res.signals}
    words_c = max([c.contradiction for c in ps.comments if c.period == last] or [0.0])

    def dc(name: str, value: str, frac: float, text: str) -> dict:
        frac = max(0.0, min(1.0, frac))
        color = "#C93434" if frac > 0.66 else "#C26F00" if frac > 0.33 else "#1F8F4E"
        return {
            "name": name,
            "value": value,
            "pct": round(frac * 100),
            "color": color,
            "border": "#F0A3A3" if frac > 0.66 else "var(--line)",
            "text": text,
        }

    lvl = abs(res.cal_delta or 0)
    lag = types.get("lag")
    decomp = [
        dc(
            "Уровень",
            f"{lvl:.2f}",
            lvl / 0.6,
            (
                "Стажёр оценивает себя заметно выше, чем наставник."
                if (res.cal_delta or 0) > 0
                else "Стажёр оценивает себя заметно ниже, чем наставник."
            )
            if lvl > 0.2
            else "Оценки сторон близки (по личной шкале).",
        ),
        dc(
            "Тренд",
            f"{'+' if res.slope >= 0 else '−'}{abs(res.slope):.2f}/мес",
            max(res.slope, 0) / 0.08,
            "Расхождение увеличивается каждый месяц." if res.slope > 0.015 else "Расхождение не растёт.",
        ),
        dc(
            "Запаздывание",
            f"{res.lag_months} мес." if res.lag_months else "нет",
            res.lag_months / 5,
            lag.description if lag else "Стороны замечают изменения в одном и том же месяце.",
        ),
        dc(
            "Слова ≠ цифры",
            f"{words_c:.1f}",
            words_c,
            types["words"].description if "words" in types else "Комментарии согласуются с оценками.",
        ),
    ]
    heat = []
    for t in ps.topics():
        cells = []
        for p in ps.periods:
            a, b = ps.values["intern"][t].get(p), ps.values["mentor"][t].get(p)
            cells.append(None if a is None or b is None else round(a - b, 2))
        heat.append({"topic": t, "name": TOPIC_NAME.get(t, t), "cells": cells})
    pen_names = {
        "level": "Расхождение по уровню",
        "growth": "Расхождение растёт",
        "drop": "Оценки падают",
        "low": "Низкий общий уровень",
        "words": "Слова не совпадают с цифрами",
        "lag": "Запаздывание реакции",
        "missing": "Анкета не получена",
    }
    contrib = sorted(
        [{"name": pen_names[k], "v": round(v)} for k, v in res.penalties.items() if v >= 1],
        key=lambda x: -x["v"],
    )
    flags_i, flags_m = _flags(res, ps, pair, last)
    n_i = sum(1 for p in ps.periods if ps.has("intern", p))
    n_m = sum(1 for p in ps.periods if ps.has("mentor", p))
    people = [
        {
            "role": "СТАЖЁР",
            "id": pair.intern.external_id,
            "flags": flags_i,
            "note": f"Анкет сдано: {n_i} из {len(ps.periods)}. Средняя оценка сейчас {f'{res.intern:.2f}' if res.intern is not None else '—'}.",
        },
        {
            "role": "НАСТАВНИК",
            "id": pair.mentor.external_id,
            "flags": flags_m,
            "note": f"Анкет сдано: {n_m} из {len(ps.periods)}. Средняя оценка сейчас {f'{res.mentor:.2f}' if res.mentor is not None else '—'}.",
        },
    ]
    comments = [
        {
            "who": pair.intern.external_id if c.side == "intern" else pair.mentor.external_id,
            "side": c.side,
            "month": month_name(program, c.period),
            "period": c.period,
            "text": c.text,
            "tone": tone_label(c.tone),
            "anxiety": c.anxiety,
            "quote": c.quote,
            "topics": ", ".join(TOPIC_RU.get(t, t) for t in c.topics) or "без темы",
            "source": "правила" if c.fallback else "ИИ",
        }
        for c in sorted(ps.comments, key=lambda c: (-c.period, c.side))
    ]
    actions = []
    existing = db.query(Action).filter(Action.pair_id == pair.id).order_by(Action.id).all()
    for a in existing:
        actions.append(
            {
                "id": a.id,
                "kind": a.kind,
                "title": a.title,
                "status": a.status,
                "status_ru": STATUS_RU.get(a.status, a.status),
                "agenda": a.agenda,
                "agreements": a.agreements,
                "outcomes_text": a.outcomes_text,
                "effect": _effect(db, program, a, ps, cfg),
                "period": a.period,
            }
        )
    have = {a["kind"] for a in actions}
    recommended = []
    for t in ("decline", "growth", "level", "lag", "words", "missing"):
        if t in types and RECOMMEND[t][0] not in have:
            kind, title, note = RECOMMEND[t]
            recommended.append({"kind": kind, "title": title, "note": note})
    sig_list = [
        {"id": None, "type": s.type, "description": s.description, "cause": s.cause} for s in res.signals
    ]
    db_sigs = db.query(Signal).filter(Signal.pair_id == pair.id, Signal.period == last).all()
    for s in sig_list:
        row = next((x for x in db_sigs if x.type == s["type"]), None)
        if row:
            s["id"], s["verdict"] = row.id, row.verdict
    summary = (
        " ".join(dict.fromkeys(s.cause for s in res.signals if s.type != "missing"))
        or "Сигналов нет: оценки сторон близки."
    )
    notes = []
    if user.role == "hr":
        notes = [
            {"text": n.text, "date": n.created_at.strftime("%d.%m.%Y %H:%M") if n.created_at else ""}
            for n in db.query(HrNote).filter(HrNote.pair_id == pair.id).order_by(HrNote.id.desc())
        ]
    talk = None
    for t in db.query(TalkRequest).filter(
        TalkRequest.answered.is_(False),
        TalkRequest.participant_id.in_([pair.intern_participant_id, pair.mentor_participant_id]),
    ):
        pt = db.get(Participant, t.participant_id)
        talk = {"id": t.id, "who": pt.external_id, "topic": t.topic, "text": t.text}
    return head | {
        "empty": False,
        "state": state,
        "st": ST[state],
        "health": res.index,
        "summary": summary,
        "talk": talk,
        "months": [{"p": p, "short": month_name(program, p, "short")} for p in ps.periods],
        "next_short": month_name(program, last + 1, "short"),
        "topics": [{"k": "all", "n": "Все темы"}]
        + [{"k": t, "n": TOPIC_NAME.get(t, t)} for t in ps.topics()],
        "topic": topic,
        "scale": scale,
        "chart": {"intern": si, "mentor": sm, "fi": fi, "fm": fm, "swap": head.get("swap", {}).get("period")},
        "sig": {"delta": d_now, "forecast": f_abs, "red": red},
        "decomp": decomp,
        "contrib": contrib,
        "heat": heat,
        "people": people,
        "comments": comments,
        "actions": actions,
        "recommended": recommended,
        "signals": sig_list,
        "notes": notes,
        "can_act": user.role == "hr",
    }
