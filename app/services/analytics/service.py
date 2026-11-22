"""Пересчёт аналитики программы: ряды из БД → сигналы и индексы в БД."""

import hashlib
from collections import defaultdict
from datetime import date

from sqlalchemy.orm import Session

from app.core.settings import DEFAULT_ANALYTICS
from app.db.models import (
    Answer,
    AppSetting,
    CommentAnalysis,
    HealthSnapshot,
    Pair,
    PairMentorHistory,
    Program,
    Question,
    Response,
    Signal,
    Topic,
)
from app.services.analytics.core import Comment, PairResult, PairSeries, evaluate, program_signals
from app.services.llm import comments as comment_llm

MONTHS = [
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
]
MONTHS_SHORT = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]
MONTHS_IN = [
    "январе",
    "феврале",
    "марте",
    "апреле",
    "мае",
    "июне",
    "июле",
    "августе",
    "сентябре",
    "октябре",
    "ноябре",
    "декабре",
]


def analytics_config(db: Session, organization_id: int) -> dict:
    """Пороги и веса: стартовые значения, переопределённые таблицей settings."""
    cfg = dict(DEFAULT_ANALYTICS)
    row = (
        db.query(AppSetting)
        .filter(AppSetting.organization_id == organization_id, AppSetting.key == "analytics")
        .first()
    )
    if row and isinstance(row.value, dict):
        cfg.update({k: v for k, v in row.value.items() if k in cfg})
    return cfg


def month_index(program: Program, period: int) -> int:
    """Номер календарного месяца (0–11) для периода программы."""
    start = program.start_date or date(2026, 6, 1)
    return (start.month - 1 + period - 1) % 12


def month_name(program: Program, period: int, form: str = "full") -> str:
    """Подпись месяца программы: full — «июль», short — «Июл», in — «июле»."""
    i = month_index(program, period)
    return {"full": MONTHS, "short": MONTHS_SHORT, "in": MONTHS_IN}[form][i]


def _mentor_by_period(db: Session, pair: Pair, periods: list[int]) -> dict[int, int]:
    hist = (
        db.query(PairMentorHistory)
        .filter(PairMentorHistory.pair_id == pair.id)
        .order_by(PairMentorHistory.period)
        .all()
    )
    out = {}
    for p in periods:
        mid = pair.mentor_participant_id
        for h in reversed(hist):
            if p < h.period:
                mid = h.old_mentor_id or mid
        out[p] = mid
    return out


def ensure_comment_analysis(db: Session, answer: Answer, score: float | None) -> CommentAnalysis:
    """Разбор комментария с кэшем по хешу текста."""
    text = answer.text or ""
    h = hashlib.sha256(text.strip().encode()).hexdigest()
    ca = db.query(CommentAnalysis).filter(CommentAnalysis.answer_id == answer.id).first()
    if ca and ca.text_hash == h:
        return ca
    cached = db.query(CommentAnalysis).filter(CommentAnalysis.text_hash == h).first()
    if cached:
        res = {
            "topics": cached.topics,
            "tone": cached.tone,
            "anxiety": cached.anxiety,
            "quote": cached.quote,
            "model": cached.model,
            "fallback": cached.fallback,
        }
        res["contradiction"] = comment_llm.contradiction(res["anxiety"], score)
    else:
        res = comment_llm.analyze(text, score)
    if ca is None:
        ca = CommentAnalysis(answer_id=answer.id, text_hash=h)
        db.add(ca)
    ca.text_hash = h
    for k in ("topics", "tone", "anxiety", "contradiction", "quote", "model", "fallback"):
        setattr(ca, k, res[k])
    return ca


def load_series(db: Session, program: Program) -> list[PairSeries]:
    """Ряды оценок всех пар программы по темам и месяцам."""
    topics = {t.id: t.code for t in db.query(Topic).filter(Topic.organization_id == program.organization_id)}
    pairs = db.query(Pair).filter(Pair.program_id == program.id).order_by(Pair.code).all()
    out = []
    for pair in pairs:
        mentor_ids = {pair.mentor_participant_id} | {
            h.old_mentor_id
            for h in db.query(PairMentorHistory).filter(PairMentorHistory.pair_id == pair.id)
            if h.old_mentor_id
        }
        resps = (
            db.query(Response)
            .filter(Response.participant_id.in_({pair.intern_participant_id} | mentor_ids))
            .order_by(Response.period, Response.submitted_at)
            .all()
        )
        periods = sorted({r.period for r in resps})
        mentor_at = _mentor_by_period(db, pair, periods)
        values: dict[str, dict[str, dict[int, float]]] = {
            "intern": defaultdict(dict),
            "mentor": defaultdict(dict),
        }
        texts: list[tuple[str, int, Answer]] = []
        for r in resps:
            if r.participant_id == pair.intern_participant_id:
                side = "intern"
            elif r.participant_id == mentor_at.get(r.period):
                side = "mentor"
            else:
                continue
            acc: dict[str, list[float]] = defaultdict(list)
            for a in r.answers:
                q: Question | None = a.question
                if a.text and (q is None or q.qtype == "text"):
                    texts.append((side, r.period, a))
                    continue
                if a.value_norm is None or q is None or q.topic_id is None:
                    continue
                acc[topics.get(q.topic_id, "other")].append(a.value_norm)
            for t, vs in acc.items():
                values[side][t][r.period] = sum(vs) / len(vs)
        ps = PairSeries(
            pair.id,
            pair.code,
            periods,
            {s: dict(v) for s, v in values.items()},
            start_period=pair.start_period,
        )
        for side, period, a in texts:
            ca = ensure_comment_analysis(db, a, ps.overall(side, period))
            ps.comments.append(
                Comment(
                    side=side,
                    period=period,
                    text=a.text or "",
                    anxiety=ca.anxiety,
                    contradiction=ca.contradiction,
                    tone=ca.tone,
                    quote=ca.quote,
                    topics=list(ca.topics or []),
                    fallback=ca.fallback,
                )
            )
        out.append(ps)
    return out


def recompute_program(db: Session, program: Program) -> dict[int, dict[int, PairResult]]:
    """Пересчитывает сигналы и индекс всех пар за все месяцы и сохраняет их.

    Returns:
        Результаты: pair_id → период → состояние.
    """
    cfg = analytics_config(db, program.organization_id)
    series = load_series(db, program)
    verdicts = {
        (s.pair_id, s.period, s.type, s.topic): s.verdict
        for s in db.query(Signal).filter(Signal.program_id == program.id, Signal.verdict.isnot(None))
    }
    db.query(Signal).filter(Signal.program_id == program.id).delete()
    pair_ids = [ps.pair_id for ps in series]
    if pair_ids:
        db.query(HealthSnapshot).filter(HealthSnapshot.pair_id.in_(pair_ids)).delete()
    results: dict[int, dict[int, PairResult]] = {}
    all_periods = sorted({p for ps in series for p in ps.periods})
    name = lambda p: month_name(program, p)  # noqa: E731
    for ps in series:
        results[ps.pair_id] = {}
        for p in ps.periods:
            res = evaluate(ps, p, cfg, name)
            results[ps.pair_id][p] = res
            db.add(HealthSnapshot(pair_id=ps.pair_id, period=p, index=res.index, penalties=res.penalties))
            for s in res.signals:
                db.add(
                    Signal(
                        pair_id=ps.pair_id,
                        program_id=program.id,
                        period=p,
                        type=s.type,
                        topic=s.topic,
                        strength=s.strength,
                        description=s.description,
                        cause=s.cause,
                        facts=s.facts | {"state": res.state},
                        verdict=verdicts.get((ps.pair_id, p, s.type, s.topic)),
                    )
                )
    for p in all_periods:
        for s in program_signals([ps for ps in series if p in ps.periods], p, cfg):
            db.add(
                Signal(
                    pair_id=None,
                    program_id=program.id,
                    period=p,
                    type=s.type,
                    topic=s.topic,
                    strength=s.strength,
                    description=s.description,
                    cause=s.cause,
                    facts=s.facts,
                )
            )
    db.commit()
    return results
