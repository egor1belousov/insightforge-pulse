"""Дашборд, карточка пары, действия, заметки HR, отметки сигналов."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import HR_ONLY, STAFF, require_role
from app.db.models import (
    Action,
    DashboardLayout,
    HrNote,
    Notification,
    Pair,
    Program,
    Signal,
    TalkRequest,
    User,
)
from app.db.session import get_db
from app.services import dashboard as dash
from app.services.dashboard import periods_of
from app.services.llm import tasks

router = APIRouter(prefix="/api", tags=["дашборд"])

DEFAULT_LAYOUT = {
    "order": ["kpi", "tasks", "signals", "map", "trend", "system", "forms", "feed", "health"],
    "hidden": {},
    "preset": "hr",
    "tdone": {},
}


class LayoutIn(BaseModel):
    order: list[str] | None = None
    hidden: dict[str, bool] | None = None
    preset: str | None = None


class ActionIn(BaseModel):
    kind: str
    title: str


class StatusIn(BaseModel):
    status: str


class TextIn(BaseModel):
    text: str


class VerdictIn(BaseModel):
    verdict: str | None


def _program(db: Session, user: User) -> Program:
    prog = db.get(Program, user.program_id) if user.program_id else None
    if prog is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Программа не найдена.")
    return prog


def _pair(db: Session, user: User, pair_id: int) -> Pair:
    pair = db.get(Pair, pair_id)
    if pair is None or pair.program_id != user.program_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пара не найдена.")
    return pair


@router.get("/dashboard")
def get_dashboard(
    period: int | None = None,
    dept: str | None = None,
    user: User = Depends(require_role(*STAFF)),
    db: Session = Depends(get_db),
) -> dict:
    return dash.dashboard(db, _program(db, user), user, period, dept)


@router.get("/dashboard/layout")
def get_layout(user: User = Depends(require_role(*STAFF)), db: Session = Depends(get_db)) -> dict:
    lay = db.get(DashboardLayout, user.id)
    return DEFAULT_LAYOUT | (lay.layout if lay else {})


@router.put("/dashboard/layout")
def put_layout(
    data: LayoutIn, user: User = Depends(require_role(*STAFF)), db: Session = Depends(get_db)
) -> dict:
    lay = db.get(DashboardLayout, user.id)
    if lay is None:
        lay = DashboardLayout(user_id=user.id, layout=dict(DEFAULT_LAYOUT))
        db.add(lay)
    cur = DEFAULT_LAYOUT | dict(lay.layout or {})
    for k, v in data.model_dump(exclude_none=True).items():
        cur[k] = v
    lay.layout = cur
    db.commit()
    return cur


@router.post("/dashboard/tasks/{key}")
def toggle_task(
    key: str, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    lay = db.get(DashboardLayout, user.id)
    if lay is None:
        lay = DashboardLayout(user_id=user.id, layout=dict(DEFAULT_LAYOUT))
        db.add(lay)
    cur = DEFAULT_LAYOUT | dict(lay.layout or {})
    done = dict(cur.get("tdone") or {})
    done[key] = not done.get(key, False)
    cur["tdone"] = done
    lay.layout = cur
    db.commit()
    return {"done": done[key]}


@router.get("/signals")
def list_signals(
    period: int | None = None, user: User = Depends(require_role(*STAFF)), db: Session = Depends(get_db)
) -> list[dict]:
    prog = _program(db, user)
    p = period or periods_of(db, prog)[-1]
    rows = db.query(Signal).filter(Signal.program_id == prog.id, Signal.period == p).all()
    codes = {x.id: x.code for x in db.query(Pair).filter(Pair.program_id == prog.id)}
    return [
        {
            "id": s.id,
            "pair": codes.get(s.pair_id),
            "type": s.type,
            "topic": s.topic,
            "strength": s.strength,
            "description": s.description,
            "cause": s.cause,
            "verdict": s.verdict,
        }
        for s in rows
    ]


@router.post("/signals/{signal_id}/verdict")
def signal_verdict(
    signal_id: int,
    data: VerdictIn,
    user: User = Depends(require_role(*HR_ONLY)),
    db: Session = Depends(get_db),
) -> dict:
    s = db.get(Signal, signal_id)
    if s is None or s.program_id != user.program_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сигнал не найден.")
    if data.verdict not in (None, "confirmed", "false_alarm"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Отметка: подтверждаю или ложная тревога.")
    s.verdict = data.verdict
    db.commit()
    return {"ok": True}


@router.get("/pairs/{pair_id}/diagnosis")
def diagnosis(
    pair_id: int,
    topic: str = "all",
    scale: str = "raw",
    user: User = Depends(require_role(*STAFF)),
    db: Session = Depends(get_db),
) -> dict:
    return dash.diagnosis(db, _program(db, user), _pair(db, user, pair_id), user, topic, scale)


@router.post("/pairs/{pair_id}/actions")
def create_action(
    pair_id: int, data: ActionIn, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    pair = _pair(db, user, pair_id)
    prog = _program(db, user)
    a = Action(
        pair_id=pair.id,
        kind=data.kind[:40],
        title=data.title[:300],
        status="assigned",
        period=periods_of(db, prog)[-1],
    )
    db.add(a)
    db.commit()
    return {"id": a.id}


@router.post("/actions/{action_id}/status")
def action_status(
    action_id: int,
    data: StatusIn,
    user: User = Depends(require_role(*HR_ONLY)),
    db: Session = Depends(get_db),
) -> dict:
    a = db.get(Action, action_id)
    if a is None or _pair(db, user, a.pair_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Действие не найдено.")
    order = ["assigned", "done", "effect_checked"]
    if data.status not in order:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Статус: назначено, выполнено или эффект проверен.")
    a.status = data.status
    if data.status == "done":
        a.period = periods_of(db, _program(db, user))[-1]
    db.commit()
    return {"ok": True}


@router.delete("/actions/{action_id}")
def delete_action(
    action_id: int, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    a = db.get(Action, action_id)
    if a is None or _pair(db, user, a.pair_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Действие не найдено.")
    db.delete(a)
    db.commit()
    return {"ok": True}


@router.post("/actions/{action_id}/agenda")
def action_agenda(
    action_id: int, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    a = db.get(Action, action_id)
    pair = _pair(db, user, a.pair_id) if a else None
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Действие не найдено.")
    last = db.query(Signal.period).filter(Signal.pair_id == pair.id).order_by(Signal.period.desc()).first()
    sig = (
        db.query(Signal)
        .filter(
            Signal.pair_id == pair.id, Signal.period == (last[0] if last else 0), Signal.type != "missing"
        )
        .all()
    )
    res = tasks.meeting_agenda(
        pair.code, [{"type": s.type, "description": s.description, "cause": s.cause} for s in sig]
    )
    a.agenda = res["items"]
    db.commit()
    return res


@router.post("/actions/{action_id}/outcomes")
def action_outcomes(
    action_id: int, data: TextIn, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    a = db.get(Action, action_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Действие не найдено.")
    pair = _pair(db, user, a.pair_id)
    res = tasks.meeting_outcomes(data.text, pair.intern.external_id, pair.mentor.external_id)
    return res


class SaveOutcomesIn(BaseModel):
    text: str
    agreements: list[dict]


@router.put("/actions/{action_id}/outcomes")
def save_outcomes(
    action_id: int,
    data: SaveOutcomesIn,
    user: User = Depends(require_role(*HR_ONLY)),
    db: Session = Depends(get_db),
) -> dict:
    a = db.get(Action, action_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Действие не найдено.")
    _pair(db, user, a.pair_id)
    a.outcomes_text = data.text[:4000]
    a.agreements = [
        {
            "who": str(x.get("who", ""))[:80],
            "what": str(x.get("what", ""))[:300],
            "when": str(x.get("when", ""))[:80],
        }
        for x in data.agreements
    ][:10]
    a.status = "done"
    a.period = periods_of(db, _program(db, user))[-1]
    db.commit()
    return {"ok": True}


@router.get("/pairs/{pair_id}/notes")
def notes(
    pair_id: int, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> list[dict]:
    _pair(db, user, pair_id)
    return [
        {"text": n.text, "date": n.created_at.isoformat() if n.created_at else None}
        for n in db.query(HrNote).filter(HrNote.pair_id == pair_id).order_by(HrNote.id.desc())
    ]


@router.post("/pairs/{pair_id}/notes")
def add_note(
    pair_id: int, data: TextIn, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    _pair(db, user, pair_id)
    if not data.text.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Заметка пустая.")
    db.add(HrNote(pair_id=pair_id, author_id=user.id, text=data.text.strip()[:4000]))
    db.commit()
    return {"ok": True}


@router.post("/talk/{talk_id}/answer")
def answer_talk(
    talk_id: int, data: TextIn, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    t = db.get(TalkRequest, talk_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Запрос не найден.")
    t.answered = True
    t.answer_text = data.text[:500] or f"HR назначил встречу ({datetime.now():%d.%m})"
    db.add(
        Notification(
            user_id=t.user_id, title=t.answer_text, sub="Ответ на ваш запрос", link="/me", level="info"
        )
    )
    db.commit()
    return {"ok": True}
