"""Программа, участники и пары."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import HR_ONLY, STAFF, require_role
from app.db.models import Pair, PairMentorHistory, Participant, Program, User
from app.db.session import get_db
from app.services import program as program_svc

router = APIRouter(prefix="/api", tags=["программа"])


class ProgramIn(BaseModel):
    name: str
    months: int = 6


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
    rows = db.query(Program).filter(Program.organization_id == user.organization_id)
    return [
        {"id": p.id, "name": p.name, "months": p.months, "current": p.id == user.program_id} for p in rows
    ]


@router.post("/programs")
def create_program(
    data: ProgramIn, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    if not data.name.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Введите название программы.")
    prog = Program(organization_id=user.organization_id, name=data.name.strip(), months=data.months)
    db.add(prog)
    db.flush()
    user.program_id = prog.id
    db.commit()
    return {"id": prog.id, "name": prog.name}


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
