"""Живая цепочка: новый ответ → нормализация → разбор комментария → пересчёт → событие SSE.

Пересчёт сразу идёт на правилах (быстро), затем в фоне комментарий разбирает LLM
и, если результат изменился, отправляется уточнённое событие.
"""

import logging
import threading
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.db.models import (
    Answer,
    HealthSnapshot,
    Notification,
    Pair,
    Participant,
    Program,
    Question,
    Questionnaire,
    Response,
    Signal,
    User,
)
from app.db.session import SessionLocal
from app.services.analytics.core import SIGNAL_RU
from app.services.analytics.service import recompute_program
from app.services.events.bus import bus
from app.services.ingest.text import norm

log = logging.getLogger("pulse.forms")
SOURCE_RU = {
    "own_form": "своя форма",
    "yandex": "Яндекс Форма",
    "google": "Google Forms",
    "demo": "тестовый ответ",
    "import": "загрузка",
}


class SubmitError(ValueError):
    """Ошибка с понятным пользователю текстом."""


def current_period(db: Session, program: Program) -> int:
    """Текущий месяц программы: по дате начала, но не дальше месяца после последних данных."""
    start = program.start_date or date.today().replace(day=1)
    today = date.today()
    by_date = (today.year - start.year) * 12 + today.month - start.month + 1
    last = (
        db.query(Response.period)
        .join(Participant, Participant.id == Response.participant_id)
        .filter(Participant.program_id == program.id)
        .order_by(Response.period.desc())
        .first()
    )
    last_p = last[0] if last else 1
    return max(1, min(by_date, last_p + 1, max(program.months, last_p)))


def active_questionnaire(db: Session, program_id: int, side: str) -> Questionnaire | None:
    """Действующая анкета стороны."""
    return (
        db.query(Questionnaire)
        .filter(
            Questionnaire.program_id == program_id, Questionnaire.side == side, Questionnaire.active.is_(True)
        )
        .order_by(Questionnaire.version.desc())
        .first()
    )


def pair_of(db: Session, participant: Participant) -> Pair | None:
    """Пара участника (для наставника — первая активная)."""
    col = Pair.intern_participant_id if participant.side == "intern" else Pair.mentor_participant_id
    return db.query(Pair).filter(col == participant.id, Pair.status == "active").order_by(Pair.id).first()


def _norm_value(q: Question, raw: object) -> tuple[str | None, float | None]:
    if raw is None or str(raw).strip() == "":
        return None, None
    if q.scale_labels and len(q.scale_labels) > 2:
        labels = [norm(x) for x in q.scale_labels]
        v = norm(raw)
        if v in labels:
            x = labels.index(v) / (len(labels) - 1)
            return str(raw), round(1 - x if q.inverse else x, 4)
    try:
        num = float(str(raw).replace(",", "."))
    except ValueError:
        return str(raw), None
    lo, hi = q.scale_min, q.scale_max
    if lo is None or hi is None or hi == lo:
        return str(raw), None
    if not lo <= num <= hi:
        raise SubmitError(f"Ответ «{raw}» вне шкалы {lo:g}–{hi:g}.")
    x = (num - lo) / (hi - lo)
    return str(raw), round(1 - x if q.inverse else x, 4)


def _snapshot(db: Session, pair: Pair | None, period: int) -> dict:
    if pair is None:
        return {}
    h = (
        db.query(HealthSnapshot)
        .filter(HealthSnapshot.pair_id == pair.id, HealthSnapshot.period == period)
        .first()
    )
    sig = db.query(Signal).filter(Signal.pair_id == pair.id, Signal.period == period).all()
    return {
        "index": h.index if h else None,
        "signals": sorted({s.type for s in sig if s.type != "missing"}),
        "state": next(
            (s.facts.get("state") for s in sig if s.facts and s.facts.get("state")), "ok" if h else None
        ),
        "abs_delta": next((s.facts.get("abs_delta", [None])[-1] for s in sig if s.type == "growth"), None),
    }


def _message(who: str, pair: Pair | None, before: dict, after: dict) -> str:
    if pair is None:
        return f"{who} отправил анкету."
    parts = []
    new = [
        SIGNAL_RU.get(t, t).lower() for t in after.get("signals", []) if t not in before.get("signals", [])
    ]
    gone = [
        SIGNAL_RU.get(t, t).lower() for t in before.get("signals", []) if t not in after.get("signals", [])
    ]
    if new:
        parts.append(f"новый сигнал {pair.code}: {', '.join(new)}")
    if gone:
        parts.append(f"снят сигнал: {', '.join(gone)}")
    b, a = before.get("index"), after.get("index")
    if a is not None:
        parts.append(f"индекс {b if b is not None else '—'} → {a}")
    return f"{who} ответил: " + ("; ".join(parts) if parts else "без изменений")


def _notify_staff(db: Session, program: Program, title: str, sub: str, link: str) -> None:
    for u in db.query(User).filter(User.program_id == program.id, User.role.in_(("hr", "lead"))):
        db.add(Notification(user_id=u.id, title=title, sub=sub, link=link, level="info"))


def submit_response(
    db: Session,
    program: Program,
    participant: Participant,
    answers: dict[int, object],
    comment: str = "",
    source: str = "own_form",
    period: int | None = None,
    refine_async: bool = True,
) -> dict:
    """Записывает анкету участника и запускает пересчёт.

    Args:
        answers: question_id → значение (число шкалы или подпись словесной шкалы).
        comment: Свободный комментарий.
        source: own_form / yandex / google / demo.
        period: Месяц программы; по умолчанию — текущий.
        refine_async: Дообновить разбор комментария LLM в фоне.

    Returns:
        Данные события pair_updated.

    Raises:
        SubmitError: если анкета не найдена или ответы некорректны.
    """
    qn = active_questionnaire(db, program.id, participant.side)
    if qn is None:
        raise SubmitError("Анкета ещё не настроена. Обратитесь к HR.")
    qs = {q.id: q for q in qn.questions}
    scale_qs = [q for q in qn.questions if q.qtype != "text"]
    missing = [q.order + 1 for q in scale_qs if answers.get(q.id) in (None, "")]
    if missing:
        raise SubmitError(f"Ответьте на все вопросы: не заполнены № {', '.join(map(str, missing))}.")
    period = period or current_period(db, program)
    pair = pair_of(db, participant)
    before = _snapshot(db, pair, period)

    db.query(Response).filter(Response.participant_id == participant.id, Response.period == period).delete()
    resp = Response(
        participant_id=participant.id,
        questionnaire_id=qn.id,
        period=period,
        source=source,
        submitted_at=datetime.now(),
        complete=True,
    )
    for qid, raw in answers.items():
        q = qs.get(int(qid))
        if q is None or q.qtype == "text":
            continue
        value_raw, value_norm = _norm_value(q, raw)
        resp.answers.append(Answer(question_id=q.id, value_raw=value_raw, value_norm=value_norm))
    text_q = next((q for q in qn.questions if q.qtype == "text"), None)
    if comment.strip():
        resp.answers.append(Answer(question_id=text_q.id if text_q else None, text=comment.strip()[:2000]))
    db.add(resp)
    db.commit()

    recompute_program(db, program, use_llm=False)
    after = _snapshot(db, pair, period)
    who = participant.external_id
    data = {
        "pair_id": pair.id if pair else None,
        "pair": pair.code if pair else None,
        "who": who,
        "side": participant.side,
        "period": period,
        "before": before,
        "after": after,
        "message": _message(who, pair, before, after),
        "source": source,
        "refined": False,
    }
    _notify_staff(
        db,
        program,
        data["message"],
        f"Анкета · {SOURCE_RU.get(source, source)}",
        f"/pairs?id={pair.id}" if pair else "/dashboard",
    )
    db.commit()
    bus.publish(program.id, "pair_updated", data)
    if refine_async and comment.strip():
        threading.Thread(
            target=_refine, args=(program.id, pair.id if pair else None, period, data), daemon=True
        ).start()
    return data


def _refine(program_id: int, pair_id: int | None, period: int, first: dict) -> None:
    """Фоновый разбор нового комментария LLM и уточнённое событие."""
    from app.services.llm.client import enabled

    if not enabled():
        return
    try:
        with SessionLocal() as db:
            program = db.get(Program, program_id)
            pair = db.get(Pair, pair_id) if pair_id else None
            recompute_program(db, program, use_llm=True)
            after = _snapshot(db, pair, period)
            if after != first["after"]:
                data = first | {
                    "after": after,
                    "message": _message(first["who"], pair, first["before"], after) + " (уточнено ИИ)",
                    "refined": True,
                }
                bus.publish(program_id, "pair_updated", data)
    except Exception:  # noqa: BLE001
        log.exception("Не удалось дообновить разбор комментария")
