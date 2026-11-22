"""Состояние LLM и генерация текстов для HR."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import HR_ONLY, STAFF, require_role
from app.db.models import Pair, Signal, User
from app.db.session import get_db
from app.services.llm import client, tasks

router = APIRouter(prefix="/api", tags=["LLM"])


class OutcomesIn(BaseModel):
    text: str


def _pair(db: Session, user: User, pair_id: int) -> Pair:
    pair = db.get(Pair, pair_id)
    if pair is None or pair.program_id != user.program_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пара не найдена.")
    return pair


def pair_signals(db: Session, pair: Pair) -> list[dict]:
    """Сигналы пары за последний месяц с данными."""
    last = db.query(Signal.period).filter(Signal.pair_id == pair.id).order_by(Signal.period.desc()).first()
    if not last:
        return []
    rows = db.query(Signal).filter(Signal.pair_id == pair.id, Signal.period == last[0]).all()
    return [{"type": s.type, "description": s.description, "cause": s.cause, "facts": s.facts} for s in rows]


@router.get("/llm/status")
def llm_status(check: bool = False, user: User = Depends(require_role(*STAFF))) -> dict:
    return client.status(check=check)


@router.post("/pairs/{pair_id}/explain")
def explain(pair_id: int, user: User = Depends(require_role(*STAFF)), db: Session = Depends(get_db)) -> dict:
    pair = _pair(db, user, pair_id)
    return tasks.explain_signal(pair.code, pair_signals(db, pair))


@router.post("/pairs/{pair_id}/agenda")
def agenda(pair_id: int, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)) -> dict:
    pair = _pair(db, user, pair_id)
    return tasks.meeting_agenda(pair.code, [s for s in pair_signals(db, pair) if s["type"] != "missing"])


@router.post("/pairs/{pair_id}/outcomes")
def outcomes(
    pair_id: int,
    data: OutcomesIn,
    user: User = Depends(require_role(*HR_ONLY)),
    db: Session = Depends(get_db),
) -> dict:
    pair = _pair(db, user, pair_id)
    return tasks.meeting_outcomes(data.text, pair.intern.external_id, pair.mentor.external_id)
