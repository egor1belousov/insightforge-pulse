"""Программа, участники и пары."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import HR_ONLY, STAFF, require_role
from app.db.models import Pair, PairMentorHistory, Participant, Program, User
from app.db.session import get_db
from app.services import program as program_svc
from app.services import streams

router = APIRouter(prefix="/api", tags=["программа"])


class ParticipantIn(BaseModel):
    external_id: str
    side: str
    department: str | None = None


class PairIn(BaseModel):
    intern_id: int
    mentor_id: int


class MentorChangeIn(BaseModel):
    mentor_id: int
    period: int


def _program(db: Session, user: User) -> Program:
    prog = db.get(Program, user.program_id) if user.program_id else None
    if prog is None or prog.organization_id != user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Программа не найдена.")
    return prog


@router.get("/programs")
def list_programs(user: User = Depends(require_role(*STAFF)), db: Session = Depends(get_db)) -> list[dict]:
    return streams.overview(db, user)


class StreamIn(BaseModel):
    name: str
    start: date | None = None
    months: int = 6
    copy_questionnaires: bool = True


@router.post("/programs")
def create_program(
    data: StreamIn, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    try:
        prog = streams.create(db, user, data.name, data.start, data.months, data.copy_questionnaires)
    except streams.StreamError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"id": prog.id, "name": prog.name}


@router.post("/programs/{program_id}/switch")
def switch_program(
    program_id: int, user: User = Depends(require_role(*STAFF)), db: Session = Depends(get_db)
) -> dict:
    try:
        prog = streams.switch(db, user, program_id)
    except streams.StreamError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    return {"id": prog.id, "name": prog.name}


@router.delete("/users/{user_id}")
def remove_user(
    user_id: int, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    """Отключает доступ сотрудника. Потоки, пары и заметки остаются у компании."""
    target = db.get(User, user_id)
    if target is None or target.organization_id != user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден.")
    if target.id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя отключить себя.")
    if (
        target.role == "hr"
        and db.query(User).filter(User.organization_id == user.organization_id, User.role == "hr").count()
        <= 1
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "В компании должен остаться хотя бы один HR.")
    db.delete(target)
    db.commit()
    return {"ok": True}


@router.get("/participants")
def list_participants(
    user: User = Depends(require_role(*STAFF)), db: Session = Depends(get_db)
) -> list[dict]:
    prog = _program(db, user)
    return [program_svc.participant_out(p) for p in program_svc.participants(db, prog.id)]


@router.post("/participants")
def add_participant(
    data: ParticipantIn, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    prog = _program(db, user)
    try:
        part = program_svc.add_participant(db, prog.id, data.external_id, data.side, data.department)
    except program_svc.ProgramError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return program_svc.participant_out(part)


@router.get("/pairs")
def list_pairs(user: User = Depends(require_role(*STAFF)), db: Session = Depends(get_db)) -> list[dict]:
    prog = _program(db, user)
    return program_svc.pairs_overview(db, prog)


@router.post("/pairs")
def create_pair(
    data: PairIn, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    prog = _program(db, user)
    try:
        pair = program_svc.create_pair(db, prog.id, data.intern_id, data.mentor_id)
    except program_svc.ProgramError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"id": pair.id, "code": pair.code}


@router.post("/pairs/{pair_id}/mentor")
def change_mentor(
    pair_id: int,
    data: MentorChangeIn,
    user: User = Depends(require_role(*HR_ONLY)),
    db: Session = Depends(get_db),
) -> dict:
    prog = _program(db, user)
    pair = db.get(Pair, pair_id)
    mentor = db.get(Participant, data.mentor_id)
    if not pair or pair.program_id != prog.id or not mentor or mentor.side != "mentor":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пара или наставник не найдены.")
    db.add(
        PairMentorHistory(
            pair_id=pair.id,
            old_mentor_id=pair.mentor_participant_id,
            new_mentor_id=mentor.id,
            period=data.period,
        )
    )
    pair.mentor_participant_id = mentor.id
    db.commit()
    return {"ok": True}


@router.get("/pairs/{pair_id}/candidates")
def mentor_candidates(
    pair_id: int, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> list[dict]:
    prog = _program(db, user)
    return program_svc.rank_mentors(db, prog.id, intern_participant_id=None, pair_id=pair_id)


@router.get("/participants/{participant_id}/candidates")
def intern_candidates(
    participant_id: int, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> list[dict]:
    prog = _program(db, user)
    return program_svc.rank_mentors(db, prog.id, intern_participant_id=participant_id, pair_id=None)
