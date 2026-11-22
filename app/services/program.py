"""Участники, пары, подбор наставника."""

from sqlalchemy.orm import Session

from app.db.models import HealthSnapshot, Pair, Participant, Program, Signal


class ProgramError(ValueError):
    """Ошибка с понятным пользователю текстом."""


def participants(db: Session, program_id: int) -> list[Participant]:
    """Все участники программы."""
    return (
        db.query(Participant)
        .filter(Participant.program_id == program_id)
        .order_by(Participant.external_id)
        .all()
    )


def participant_out(p: Participant) -> dict:
    """Сведения об участнике для API."""
    return {
        "id": p.id,
        "external_id": p.external_id,
        "side": p.side,
        "department": p.department,
        "has_user": p.user_id is not None,
    }


def add_participant(
    db: Session, program_id: int, external_id: str, side: str, department: str | None
) -> Participant:
    """Добавляет участника программы.

    Raises:
        ProgramError: если сторона неизвестна или ID занят.
    """
    ext = external_id.strip()
    if side not in ("intern", "mentor") or not ext:
        raise ProgramError("Укажите ID и сторону: стажёр или наставник.")
    if (
        db.query(Participant)
        .filter(Participant.program_id == program_id, Participant.external_id == ext)
        .first()
    ):
        raise ProgramError(f"Участник {ext} уже есть.")
    part = Participant(program_id=program_id, external_id=ext, side=side, department=department)
    db.add(part)
    db.commit()
    return part


def next_pair_code(db: Session, program_id: int) -> str:
    """Следующий код пары: П-01, П-02, …"""
    n = db.query(Pair).filter(Pair.program_id == program_id).count()
    return f"П-{n + 1:02d}"


def create_pair(db: Session, program_id: int, intern_id: int, mentor_id: int, start_period: int = 1) -> Pair:
    """Создаёт пару стажёр–наставник.

    Raises:
        ProgramError: если участники не найдены или стажёр уже в паре.
    """
    intern = db.get(Participant, intern_id)
    mentor = db.get(Participant, mentor_id)
    if not intern or not mentor or intern.program_id != program_id or mentor.program_id != program_id:
        raise ProgramError("Участники не найдены в программе.")
    if intern.side != "intern" or mentor.side != "mentor":
        raise ProgramError("Пара — это стажёр и наставник.")
    busy = db.query(Pair).filter(Pair.intern_participant_id == intern.id, Pair.status == "active").first()
    if busy:
        raise ProgramError(f"{intern.external_id} уже в паре {busy.code}.")
    pair = Pair(
        program_id=program_id,
        code=next_pair_code(db, program_id),
        intern_participant_id=intern.id,
        mentor_participant_id=mentor.id,
        start_period=start_period,
    )
    db.add(pair)
    db.commit()
    return pair


def pairs_overview(db: Session, prog: Program) -> list[dict]:
    """Список пар с последним индексом здоровья и числом сигналов."""
    out = []
    for p in db.query(Pair).filter(Pair.program_id == prog.id).order_by(Pair.code):
        snap = (
            db.query(HealthSnapshot)
            .filter(HealthSnapshot.pair_id == p.id)
            .order_by(HealthSnapshot.period.desc())
            .first()
        )
        last = snap.period if snap else None
        nsig = db.query(Signal).filter(Signal.pair_id == p.id, Signal.period == last).count() if last else 0
        out.append(
            {
                "id": p.id,
                "code": p.code,
                "intern": p.intern.external_id,
                "mentor": p.mentor.external_id,
                "department": p.intern.department or p.mentor.department,
                "status": p.status,
                "health": snap.index if snap else None,
                "signals": nsig,
            }
        )
    return out


def rank_mentors(
    db: Session, program_id: int, *, intern_participant_id: int | None, pair_id: int | None
) -> list[dict]:
    """Ранжирует свободных наставников для стажёра или для замены в паре.

    Баллы: то же подразделение, текущая загрузка, история сигналов в прошлых парах.
    Решение принимает HR.
    """
    pair = db.get(Pair, pair_id) if pair_id else None
    intern = (
        db.get(Participant, intern_participant_id)
        if intern_participant_id
        else (pair.intern if pair else None)
    )
    if intern is None:
        return []
    dept = intern.department
    out = []
    for m in db.query(Participant).filter(Participant.program_id == program_id, Participant.side == "mentor"):
        if pair and m.id == pair.mentor_participant_id:
            continue
        mpairs = db.query(Pair).filter(Pair.mentor_participant_id == m.id, Pair.status == "active").all()
        load = len(mpairs)
        sig = sum(db.query(Signal).filter(Signal.pair_id == mp.id).count() for mp in mpairs)
        score = (
            (45 if dept and m.department == dept else 12) + (35 if load == 0 else 8) + max(0, 16 - 4 * sig)
        )
        reasons = [
            "то же подразделение" if dept and m.department == dept else "другое подразделение",
            "свободен" if load == 0 else f"уже ведёт {load}",
            "сигналов не было" if sig == 0 else f"сигналов в парах: {sig}",
        ]
        out.append(
            {
                "id": m.id,
                "external_id": m.external_id,
                "department": m.department,
                "score": min(98, score),
                "reasons": reasons,
            }
        )
    return sorted(out, key=lambda x: -x["score"])
