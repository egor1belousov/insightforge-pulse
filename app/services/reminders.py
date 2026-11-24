"""Автонапоминания по расписанию: раз в `reminders_check_minutes` минут для каждого потока."""

import logging
import threading
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.models import Organization, Pair, Participant, Program, Response
from app.db.session import SessionLocal
from app.services import notify
from app.services.dashboard import periods_of

log = logging.getLogger("pulse.reminders")


def roster(db: Session, program: Program) -> list[tuple[Participant, str]]:
    """Все, кому положена анкета: участники пар и те, кого ещё не поставили в пару."""
    out: list[tuple[Participant, str]] = []
    seen: set[int] = set()
    for pr in db.query(Pair).filter(Pair.program_id == program.id).order_by(Pair.code):
        for p in (pr.intern, pr.mentor):
            if p.id not in seen:
                out.append((p, pr.code))
                seen.add(p.id)
    rest = (
        db.query(Participant)
        .filter(Participant.program_id == program.id, Participant.id.notin_(seen or {-1}))
        .order_by(Participant.side.desc(), Participant.external_id)
    )
    out += [(p, "без пары") for p in rest if p.user_id or p.id in _answered(db, p.id)]
    return out


def _answered(db: Session, pid: int) -> set[int]:
    return {pid} if db.query(Response.id).filter(Response.participant_id == pid).first() else set()


def pending(db: Session, program: Program, period: int) -> list[Participant]:
    """Участники потока, не заполнившие анкету месяца."""
    got = {r.participant_id for r in db.query(Response).filter(Response.period == period)}
    return [p for p, _ in roster(db, program) if p.id not in got]


def run_program(db: Session, program: Program, now: datetime | None = None) -> dict:
    """Автонапоминания одного потока за последний месяц с данными."""
    periods = periods_of(db, program)
    if not periods:
        return {"sent": [], "escalated": [], "message": "В потоке ещё нет анкет."}
    period = periods[-1]
    return notify.run_auto(db, program, period, pending(db, program, period), now or datetime.now())


def _loop(stop: threading.Event) -> None:
    while not stop.wait(get_settings().reminders_check_minutes * 60):
        try:
            with SessionLocal() as db:
                orgs = db.query(Organization).filter(
                    (Organization.sandbox_token.is_(None)) | (Organization.sandbox_claimed_at.is_not(None))
                )
                for org in orgs:
                    for prog in db.query(Program).filter(Program.organization_id == org.id):
                        run_program(db, prog)
        except Exception:  # noqa: BLE001 — фоновая задача не должна падать навсегда
            log.exception("автонапоминания: ошибка")


def start() -> threading.Event:
    stop = threading.Event()
    if get_settings().auto_reminders:
        threading.Thread(target=_loop, args=(stop,), daemon=True, name="reminders").start()
    return stop
