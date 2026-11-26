"""Своя форма, анкета по ссылке, внешние формы, демо-ответ, события SSE, уведомления."""

import asyncio
import json
import random

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import (
    HR_ONLY,
    SIDE_ROLES,
    STAFF,
    current_user,
    current_user_optional,
    own_participant,
    require_role,
)
from app.core.security import make_survey_token, read_survey_token
from app.core.settings import get_settings
from app.db.models import Notification, Participant, Program, Response, TalkRequest, User
from app.db.session import SessionLocal, get_db
from app.seed import DEMO_MENTOR
from app.services import integrations
from app.services.events.bus import bus
from app.services.forms import connectors
from app.services.forms.me import my_data
from app.services.forms.submit import SubmitError, active_questionnaire, current_period, submit_response

router = APIRouter(prefix="/api", tags=["формы"])


class AnswersIn(BaseModel):
    answers: dict[int, str | float | int]
    comment: str = ""


class TalkIn(BaseModel):
    topic: str
    text: str = ""


def _program(db: Session, program_id: int | None) -> Program:
    prog = db.get(Program, program_id) if program_id else None
    if prog is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Программа не найдена.")
    return prog


def _me_part(db: Session, user: User) -> Participant:
    part = own_participant(db, user)
    if part is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Вы ещё не привязаны к паре. Обратитесь к HR.")
    return part


@router.get("/me")
def me(user: User = Depends(require_role(*SIDE_ROLES)), db: Session = Depends(get_db)) -> dict:
    part = _me_part(db, user)
    data = my_data(db, _program(db, user.program_id), part)
    talk = (
        db.query(TalkRequest).filter(TalkRequest.user_id == user.id).order_by(TalkRequest.id.desc()).first()
    )
    data["talk_request"] = (
        None if talk is None else {"topic": talk.topic, "answered": talk.answered, "answer": talk.answer_text}
    )
    return data


@router.post("/responses")
def submit_own(
    data: AnswersIn, user: User = Depends(require_role(*SIDE_ROLES)), db: Session = Depends(get_db)
) -> dict:
    part = _me_part(db, user)
    try:
        ev = submit_response(
            db, _program(db, user.program_id), part, data.answers, data.comment, source="own_form"
        )
    except SubmitError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"ok": True, "period": ev["period"]}


@router.post("/me/talk")
def talk_to_hr(
    data: TalkIn, user: User = Depends(require_role(*SIDE_ROLES)), db: Session = Depends(get_db)
) -> dict:
    part = _me_part(db, user)
    db.add(
        TalkRequest(user_id=user.id, participant_id=part.id, topic=data.topic[:100], text=data.text[:2000])
    )
    for hr in db.query(User).filter(User.program_id == user.program_id, User.role == "hr"):
        db.add(
            Notification(
                user_id=hr.id,
                title=f"{part.external_id} просит разговор с HR",
                sub=f"Тема: {data.topic}",
                link="/dashboard",
                level="warn",
            )
        )
    db.commit()
    bus.publish(user.program_id, "talk_request", {"who": part.external_id, "topic": data.topic})
    return {"ok": True}


def _survey_part(db: Session, token: str) -> Participant:
    pid = read_survey_token(token)
    part = db.get(Participant, pid) if pid else None
    if part is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Ссылка на анкету недействительна. Попросите HR прислать новую."
        )
    return part


@router.get("/survey/{token}")
def survey_get(token: str, db: Session = Depends(get_db)) -> dict:
    part = _survey_part(db, token)
    prog = _program(db, part.program_id)
    d = my_data(db, prog, part)
    return {k: d[k] for k in ("participant", "period", "period_name", "submitted", "questionnaire")}


@router.post("/survey/{token}")
def survey_post(token: str, data: AnswersIn, db: Session = Depends(get_db)) -> dict:
    part = _survey_part(db, token)
    try:
        ev = submit_response(
            db, _program(db, part.program_id), part, data.answers, data.comment, source="own_form"
        )
    except SubmitError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"ok": True, "period": ev["period"]}


@router.get("/survey-links")
def survey_links(user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)) -> list[dict]:
    parts = (
        db.query(Participant)
        .filter(Participant.program_id == user.program_id)
        .order_by(Participant.external_id)
    )
    return [
        {"external_id": p.external_id, "side": p.side, "link": f"/survey/{make_survey_token(p.id)}"}
        for p in parts
    ]


@router.get("/forms/status")
def forms_status(user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)) -> dict:
    return connectors.status(db, user.organization_id)


@router.post("/forms/yandex/webhook")
async def yandex_webhook(
    request: Request, background: BackgroundTasks, token: str = "", db: Session = Depends(get_db)
) -> dict:
    """Вебхук Яндекс Формы: организация определяется по секрету в адресе."""
    org = integrations.org_by_secret(db, "yandex", token)
    if org is None and get_settings().yandex_webhook_secret and token == get_settings().yandex_webhook_secret:
        first = db.query(Program).order_by(Program.id).first()
        org = first.organization_id if first else None
    if org is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Неверный токен вебхука.")
    raw = (await request.body()).decode("utf-8", errors="ignore")
    try:
        body = json.loads(raw)
        if isinstance(body, dict) and isinstance(body.get("params"), dict):
            body = body["params"]  # JSON-RPC
        fields = connectors.parse_yandex_answer(body if isinstance(body, dict) else {"data": body})[1]
        if not any(isinstance(v, (str, int, float)) for v in fields.values()):
            fields = connectors.parse_mail_body(raw)
    except json.JSONDecodeError:
        fields = connectors.parse_mail_body(raw)
    integrations.log(db, org, "yandex", f"Вебхук получен: {raw[:160]}")
    if not connectors.find_id(fields):
        integrations.log(db, org, "yandex", "Ответ не принят: в форме нет ID участника", ok=False)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "В ответе формы не найден ID участника или рабочая почта."
        )
    # Яндекс ждёт ответа 5 секунд: раскладываем ответ по организациям уже после ответа
    background.add_task(_deliver_webhook, org, fields)
    return {"ok": True, "message": "Ответ принят"}


def _deliver_webhook(org: int, fields: dict) -> None:
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        try:
            ev = connectors.deliver(db, org, fields, "yandex")
        except SubmitError as e:
            integrations.log(db, org, "yandex", f"Ответ не принят: {e}", ok=False)
            return
        integrations.log(db, org, "yandex", f"Ответ по вебхуку: {ev['pair']}, получателей: {ev['delivered']}")


@router.post("/demo/test-response")
def demo_response(user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)) -> dict:
    if not get_settings().demo_mode:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Доступно только в демо-режиме.")
    prog = _program(db, user.program_id)
    period = current_period(db, prog)
    parts = db.query(Participant).filter(Participant.program_id == prog.id).all()
    have = {r.participant_id for r in db.query(Response).filter(Response.period == period)}
    target = next((p for p in parts if p.external_id == DEMO_MENTOR and p.id not in have), None)
    target = target or next(
        (p for p in parts if p.id not in have and active_questionnaire(db, prog.id, p.side)), None
    )
    target = target or next(p for p in parts if p.external_id == DEMO_MENTOR)
    qn = active_questionnaire(db, prog.id, target.side)
    last = (
        db.query(Response)
        .filter(Response.participant_id == target.id)
        .order_by(Response.period.desc())
        .first()
    )
    prev = {a.question_id: a.value_norm for a in (last.answers if last else []) if a.value_norm is not None}
    rng = random.Random()
    answers = {}
    for q in qn.questions:
        if q.qtype == "text":
            continue
        base = prev.get(q.id, 0.5) - rng.uniform(0.03, 0.12)
        lo, hi = q.scale_min or 1, q.scale_max or 5
        answers[q.id] = str(round(lo + max(0.0, min(1.0, base)) * (hi - lo)))
    comment = (
        "Нет времени заниматься стажёром, объекты горят, обучение снова перенесли"
        if target.side == "mentor"
        else "Нагрузка большая, боюсь не успеть к аттестации"
    )
    try:
        ev = submit_response(db, prog, target, answers, comment, source="demo")
    except SubmitError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return ev


@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    # Сессия БД — только на проверку входа: поток живёт, пока открыта вкладка,
    # и не должен держать соединение из пула.
    with SessionLocal() as db:
        user = require_role(*STAFF)(current_user(request, current_user_optional(request, db)))
        program_id = user.program_id
    q = bus.subscribe(program_id)

    async def gen():
        try:
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"event: {msg['event']}\ndata: {msg['data']}\n\n"
                except TimeoutError:
                    yield ": ping\n\n"
        finally:
            bus.unsubscribe(program_id, q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/notifications")
def notifications(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == user.id)
        .order_by(Notification.id.desc())
        .limit(20)
        .all()
    )
    return {
        "unread": sum(1 for n in rows if not n.read),
        "items": [
            {
                "id": n.id,
                "title": n.title,
                "sub": n.sub,
                "link": n.link,
                "level": n.level,
                "read": n.read,
                "at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in rows
        ],
    }


@router.post("/notifications/read")
def notifications_read(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    db.query(Notification).filter(Notification.user_id == user.id, Notification.read.is_(False)).update(
        {"read": True}
    )
    db.commit()
    return {"ok": True}
