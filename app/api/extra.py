"""Программа (итоги потока), рассылки, конструктор анкет, настройки, доступы, отчёт, поиск."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import HR_ONLY, STAFF, current_user, require_role
from app.core.security import make_survey_token
from app.core.settings import DEFAULT_ANALYTICS, get_settings
from app.db.models import (
    Answer,
    AppSetting,
    Notification,
    Pair,
    Participant,
    Program,
    Question,
    Questionnaire,
    Topic,
    User,
)
from app.db.models import (
    Response as Resp,
)
from app.db.session import get_db
from app.services import reports
from app.services.analytics.service import analytics_config, month_name, recompute_program
from app.services.dashboard import dashboard, periods_of
from app.services.forms import connectors
from app.services.forms.submit import active_questionnaire, current_period
from app.services.llm import client, tasks
from app.services.sandbox import public_email

router = APIRouter(prefix="/api", tags=["разделы"])

MIRROR_TEMPLATES = {
    "tasks": {
        "intern": "Понимает ли стажёр, зачем он делает свои задачи?",
        "mentor": "Понятно ли вам, зачем вы делаете свои задачи?",
    },
    "auto": {
        "intern": "Насколько стажёр справляется без вашей помощи?",
        "mentor": "Можете ли вы выполнять задачи без помощи?",
    },
    "support": {
        "intern": "Хватает ли вам времени на стажёра?",
        "mentor": "Чувствуете ли вы поддержку наставника?",
    },
    "load": {
        "intern": "Соответствует ли объём задач возможностям стажёра?",
        "mentor": "Успеваете ли вы выполнять задачи в срок?",
    },
    "feedback": {
        "intern": "Как часто вы даёте стажёру обратную связь по его работе?",
        "mentor": "Получаете ли вы обратную связь по своей работе?",
    },
    "growth": {
        "intern": "Видите ли вы стажёра в штате после программы?",
        "mentor": "Понятны ли вам перспективы после стажировки?",
    },
}
CHANNELS = {"email": True, "tg": True, "site": True, "auto": True}
RULES = {
    "health": {"on": True, "value": 50},
    "delta": {"on": True, "value": 0.4},
    "days": {"on": True, "value": 3},
    "talk": {"on": True, "value": None},
}


def _program(db: Session, user: User) -> Program:
    prog = db.get(Program, user.program_id) if user.program_id else None
    if prog is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Программа не найдена.")
    return prog


def _setting(db: Session, org: int, key: str, default):
    row = db.query(AppSetting).filter(AppSetting.organization_id == org, AppSetting.key == key).first()
    if row is None or row.value is None:
        return default
    if isinstance(default, dict) and isinstance(row.value, dict):
        return default | row.value
    return row.value


def _save(db: Session, org: int, key: str, value) -> None:
    row = db.query(AppSetting).filter(AppSetting.organization_id == org, AppSetting.key == key).first()
    if row is None:
        row = AppSetting(organization_id=org, key=key)
        db.add(row)
    row.value = value
    db.commit()


# ---------- программа ----------


class OutcomeIn(BaseModel):
    outcome: str | None


@router.post("/pairs/{pair_id}/outcome")
def set_outcome(
    pair_id: int, data: OutcomeIn, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    pair = db.get(Pair, pair_id)
    if pair is None or pair.program_id != user.program_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пара не найдена.")
    if data.outcome not in (None, "stay", "no", "left"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Итог: в штате, не оставлен или ушёл сам.")
    pair.outcome = data.outcome
    db.commit()
    return {"ok": True}


@router.get("/program/overview")
def program_overview(user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)) -> dict:
    prog = _program(db, user)
    pairs = db.query(Pair).filter(Pair.program_id == prog.id).order_by(Pair.code).all()
    paired_i = {p.intern_participant_id for p in pairs if p.status == "active"}
    load = {}
    for p in pairs:
        load[p.mentor_participant_id] = load.get(p.mentor_participant_id, 0) + 1
    parts = (
        db.query(Participant)
        .filter(Participant.program_id == prog.id)
        .order_by(Participant.side.desc(), Participant.external_id)
        .all()
    )
    users = {u.id: u for u in db.query(User).filter(User.program_id == prog.id)}
    return {
        "unpaired": [
            {"id": p.id, "external_id": p.external_id, "department": p.department}
            for p in parts
            if p.side == "intern" and p.id not in paired_i
        ],
        "free_mentors": [
            {"id": p.id, "external_id": p.external_id, "department": p.department}
            for p in parts
            if p.side == "mentor" and p.id not in load
        ],
        "people": [
            {
                "id": p.id,
                "external_id": p.external_id,
                "side": p.side,
                "department": p.department,
                "email": public_email(users[p.user_id].email) if p.user_id in users else None,
                "joined": p.user_id is not None,
                "survey": f"/survey/{make_survey_token(p.id)}",
            }
            for p in parts
        ],
        "outcomes": [
            {
                "pair_id": p.id,
                "code": p.code,
                "intern": p.intern.external_id,
                "dept": p.intern.department,
                "outcome": p.outcome,
            }
            for p in pairs
        ],
    }


# ---------- рассылки ----------


@router.get("/forms/mailing")
def mailing(user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)) -> dict:
    prog = _program(db, user)
    period = periods_of(db, prog)[-1]
    got = {r.participant_id: r for r in db.query(Resp).filter(Resp.period == period)}
    reminded = set(_setting(db, prog.organization_id, f"reminded_{period}", []))
    rows = []
    pairs = db.query(Pair).filter(Pair.program_id == prog.id).order_by(Pair.code).all()
    for pr in pairs:
        for p in (pr.intern, pr.mentor):
            qn = active_questionnaire(db, prog.id, p.side)
            n = len([q for q in qn.questions if q.qtype != "text"]) if qn else 0
            r = got.get(p.id)
            rows.append(
                {
                    "external_id": p.external_id,
                    "side": p.side,
                    "pair": pr.code,
                    "questions": n,
                    "status": "заполнено"
                    if r
                    else ("напомнили" if p.external_id in reminded else "не заполнено"),
                    "source": r.source if r else None,
                    "response_id": r.id if r else None,
                    "link": f"/survey/{make_survey_token(p.id)}",
                }
            )
    return {
        "period": period,
        "month": month_name(prog, period),
        "next": month_name(prog, period + 1),
        "rows": rows,
        "got": sum(1 for r in rows if r["status"] == "заполнено"),
        "total": len(rows),
        "channels": _setting(db, prog.organization_id, "channels", CHANNELS),
    }


@router.get("/forms/responses/{response_id}")
def response_view(
    response_id: int, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    """Заполненная анкета участника — только для чтения."""
    prog = _program(db, user)
    r = db.get(Resp, response_id)
    if r is None or r.participant.program_id != prog.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Анкета не найдена.")
    answers = db.query(Answer).filter(Answer.response_id == r.id).order_by(Answer.question_id).all()
    return {
        "external_id": r.participant.external_id,
        "side": r.participant.side,
        "month": month_name(prog, r.period),
        "source": r.source,
        "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
        "answers": [
            {
                "question": a.question.text if a.question else "Вопрос удалён",
                "qtype": a.question.qtype if a.question else "scale",
                "topic": a.question.topic.name if a.question and a.question.topic else None,
                "value": a.value_raw,
                "min": a.question.scale_min if a.question else None,
                "max": a.question.scale_max if a.question else None,
                "text": a.text,
            }
            for a in answers
        ],
    }


class RemindIn(BaseModel):
    ids: list[str]


@router.post("/forms/remind")
def remind(
    data: RemindIn, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    prog = _program(db, user)
    period = periods_of(db, prog)[-1]
    key = f"reminded_{period}"
    done = set(_setting(db, prog.organization_id, key, []))
    channels = _setting(db, prog.organization_id, "channels", CHANNELS)
    for ext in data.ids:
        p = (
            db.query(Participant)
            .filter(Participant.program_id == prog.id, Participant.external_id == ext)
            .first()
        )
        if p and p.user_id:
            db.add(
                Notification(
                    user_id=p.user_id,
                    title=f"Заполните анкету за {month_name(prog, period)}",
                    sub="Напоминание HR",
                    link="/me",
                    level="warn",
                )
            )
        done.add(ext)
    _save(db, prog.organization_id, key, sorted(done))
    via = (
        ", ".join(n for k, n in (("email", "почта"), ("tg", "Telegram"), ("site", "сайт")) if channels.get(k))
        or "сайт"
    )
    return {"ok": True, "message": f"Напоминание отправлено: {', '.join(data.ids)} ({via})"}


@router.put("/forms/channels")
def set_channels(
    data: dict, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    prog = _program(db, user)
    value = CHANNELS | {k: bool(v) for k, v in data.items() if k in CHANNELS}
    _save(db, prog.organization_id, "channels", value)
    return value


# ---------- конструктор ----------


@router.get("/questionnaires")
def questionnaires(user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)) -> dict:
    prog = _program(db, user)
    topics = {
        t.id: (t.code, t.name) for t in db.query(Topic).filter(Topic.organization_id == prog.organization_id)
    }
    out = {}
    for side in ("intern", "mentor"):
        qn = active_questionnaire(db, prog.id, side)
        versions = (
            db.query(Questionnaire)
            .filter(Questionnaire.program_id == prog.id, Questionnaire.side == side)
            .order_by(Questionnaire.version)
            .all()
        )
        out[side] = {
            "id": qn.id if qn else None,
            "version": qn.version if qn else 0,
            "source": qn.source if qn else None,
            "versions": [
                {
                    "version": v.version,
                    "source": v.source,
                    "active": v.active,
                    "created": v.created_at.strftime("%d.%m.%Y") if v.created_at else "",
                }
                for v in versions
            ],
            "questions": [
                {
                    "id": q.id,
                    "text": q.text,
                    "qtype": q.qtype,
                    "min": q.scale_min,
                    "max": q.scale_max,
                    "topic": topics.get(q.topic_id, (None, None))[0],
                    "topic_name": topics.get(q.topic_id, (None, "—"))[1],
                    "mirror": q.mirror_question_id,
                }
                for q in (qn.questions if qn else [])
            ],
        }
    covered = []
    for code, name in sorted({v for v in topics.values()}):
        i = sum(1 for q in out["intern"]["questions"] if q["topic"] == code)
        m = sum(1 for q in out["mentor"]["questions"] if q["topic"] == code)
        covered.append({"topic": code, "name": name, "intern": i, "mentor": m})
    return out | {"coverage": covered}


class SuggestIn(BaseModel):
    text: str
    side: str


@router.post("/questions/suggest")
def suggest(
    data: SuggestIn, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    prog = _program(db, user)
    other = "mentor" if data.side == "intern" else "intern"
    oq = active_questionnaire(db, prog.id, other)
    others = [q.text for q in (oq.questions if oq else []) if q.qtype != "text"]
    res = tasks.map_question_topic(data.text, data.side, others)
    mirror_text = (
        others[res["mirror"] - 1]
        if res["mirror"]
        else MIRROR_TEMPLATES.get(res["topic"], {}).get(data.side, "")
    )
    return {
        "topic": res["topic"],
        "topic_name": tasks.TOPICS.get(res["topic"], res["topic"]),
        "confidence": res["confidence"],
        "mirror_text": mirror_text,
        "mirror_exists": bool(res["mirror"]),
        "fallback": res["fallback"],
    }


class AddQuestionIn(BaseModel):
    side: str
    text: str
    topic: str
    mirror_text: str | None = None
    scale_min: float = 1
    scale_max: float = 5


def _new_version(db: Session, prog: Program, side: str) -> tuple[Questionnaire, dict[int, Question]]:
    old = active_questionnaire(db, prog.id, side)
    qn = Questionnaire(
        program_id=prog.id,
        side=side,
        version=(old.version + 1) if old else 1,
        source="builder",
        title=old.title if old else "",
    )
    db.add(qn)
    db.flush()
    mapping = {}
    for q in old.questions if old else []:
        nq = Question(
            questionnaire_id=qn.id,
            text=q.text,
            qtype=q.qtype,
            scale_min=q.scale_min,
            scale_max=q.scale_max,
            scale_labels=q.scale_labels,
            options=q.options,
            topic_id=q.topic_id,
            inverse=q.inverse,
            order=q.order,
            column_key=q.column_key,
        )
        db.add(nq)
        mapping[q.id] = nq
    if old:
        old.active = False
    db.flush()
    return qn, mapping


def _relink_mirrors(db: Session, prog: Program) -> None:
    """Переносит зеркальные связи на вопросы действующих версий анкет (по тексту)."""
    qi, qm = active_questionnaire(db, prog.id, "intern"), active_questionnaire(db, prog.id, "mentor")
    if not qi or not qm:
        return
    for a, b in ((qi, qm), (qm, qi)):
        ids = {q.id for q in b.questions}
        by_text = {q.text: q for q in b.questions}
        for q in a.questions:
            if q.mirror_question_id and q.mirror_question_id not in ids:
                src = db.get(Question, q.mirror_question_id)
                q.mirror_question_id = by_text[src.text].id if src and src.text in by_text else None


@router.post("/questions")
def add_question(
    data: AddQuestionIn, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    prog = _program(db, user)
    if not data.text.strip() or data.side not in ("intern", "mentor"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Введите текст вопроса.")
    topic = (
        db.query(Topic)
        .filter(Topic.organization_id == prog.organization_id, Topic.code == data.topic)
        .first()
    )
    sides = [(data.side, data.text)] + (
        [("mentor" if data.side == "intern" else "intern", data.mirror_text)] if data.mirror_text else []
    )
    created = {}
    for side, text in sides:
        qn, mapping = _new_version(db, prog, side)
        old_mirror = {}
        for old_id, nq in mapping.items():
            old_mirror[nq] = db.get(Question, old_id).mirror_question_id
        text_q = [q for q in mapping.values() if q.qtype == "text"]
        order = max([q.order for q in mapping.values()] or [-1]) + 1
        for tq in text_q:
            tq.order = order + 1
        q = Question(
            questionnaire_id=qn.id,
            text=text.strip(),
            qtype="scale",
            scale_min=data.scale_min,
            scale_max=data.scale_max,
            topic_id=topic.id if topic else None,
            order=order,
        )
        db.add(q)
        db.flush()
        created[side] = (q, qn, mapping, old_mirror)
    # зеркальные связи: старые переносим по тексту, новые связываем друг с другом
    for side, (q, _qn, _mapping, old_mirror) in created.items():
        other = "mentor" if side == "intern" else "intern"
        other_qn = created[other][1] if other in created else active_questionnaire(db, prog.id, other)
        by_text = {x.text: x for x in other_qn.questions} if other_qn else {}
        for nq, om in old_mirror.items():
            if om:
                src = db.get(Question, om)
                nq.mirror_question_id = by_text[src.text].id if src and src.text in by_text else None
        if other in created:
            q.mirror_question_id = created[other][0].id
    _relink_mirrors(db, prog)
    db.commit()
    recompute_program(db, prog, use_llm=False)
    return {"ok": True, "versions": {s: v[1].version for s, v in created.items()}}


# ---------- настройки ----------


@router.get("/settings")
def get_settings_api(user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)) -> dict:
    prog = _program(db, user)
    cfg = analytics_config(db, prog.organization_id)
    rules = _setting(db, prog.organization_id, "rules", RULES)
    return {
        "analytics": cfg,
        "defaults": DEFAULT_ANALYTICS,
        "rules": rules,
        "preview": _preview(db, prog, user, rules),
        "llm": client.status(),
        "forms": connectors.status(),
        "demo": get_settings().demo_mode,
        "users": [
            {"email": public_email(u.email), "name": u.name, "role": u.role}
            for u in db.query(User).filter(
                User.organization_id == prog.organization_id, User.role.in_(("hr", "lead"))
            )
        ],
    }


def _preview(db: Session, prog: Program, user: User, rules: dict) -> dict:
    d = dashboard(db, prog, user)
    pending = d["forms"]["pending"]
    return {
        "health": [
            p["code"]
            for p in d["pairs"]
            if p["health"] is not None
            and rules["health"]["value"] is not None
            and p["health"] < rules["health"]["value"]
        ],
        "delta": [
            p["code"]
            for p in d["pairs"]
            if p["abs_now"] is not None and p["abs_now"] >= (rules["delta"]["value"] or 1) - 1e-9
        ],
        "days": pending if (rules["days"]["value"] or 99) <= 4 else [],
    }


class SettingsIn(BaseModel):
    analytics: dict | None = None
    rules: dict | None = None


@router.put("/settings")
def put_settings(
    data: SettingsIn, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    prog = _program(db, user)
    if data.analytics is not None:
        clean = {k: float(v) for k, v in data.analytics.items() if k in DEFAULT_ANALYTICS}
        _save(db, prog.organization_id, "analytics", analytics_config(db, prog.organization_id) | clean)
        recompute_program(db, prog, use_llm=False)
    if data.rules is not None:
        _save(
            db,
            prog.organization_id,
            "rules",
            _setting(db, prog.organization_id, "rules", RULES)
            | {k: v for k, v in data.rules.items() if k in RULES},
        )
    return get_settings_api(user, db)


@router.post("/settings/reset")
def reset_settings(user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)) -> dict:
    prog = _program(db, user)
    _save(db, prog.organization_id, "analytics", dict(DEFAULT_ANALYTICS))
    recompute_program(db, prog, use_llm=False)
    return get_settings_api(user, db)


# ---------- отчёт ----------


@router.get("/reports")
def report(
    fmt: str = "pdf",
    period: str = "all",
    parts: str = "sum,pairs,signals,actions",
    dept: str | None = None,
    user: User = Depends(require_role(*STAFF)),
    db: Session = Depends(get_db),
) -> Response:
    prog = _program(db, user)
    chosen = {p for p in parts.split(",") if p in reports.PARTS}
    if not chosen:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Выберите хотя бы один раздел отчёта.")
    data = reports.collect(db, prog, user, period, dept if dept and dept != "all" else None)
    name = f"pulse_{date.today():%Y-%m-%d}"
    if fmt == "xlsx":
        return Response(
            reports.xlsx(data, chosen),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'},
        )
    return Response(
        reports.pdf(data, chosen),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'},
    )


# ---------- поиск ----------


@router.get("/search")
def search(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    out = []
    if user.role in STAFF:
        for p in db.query(Pair).filter(Pair.program_id == user.program_id).order_by(Pair.code):
            out.append(
                {
                    "group": "Пара",
                    "label": f"{p.code} · {p.intern.external_id} + {p.mentor.external_id} · {p.intern.department or ''}",
                    "url": f"/pairs?id={p.id}",
                }
            )
    return out


@router.get("/program/period")
def program_period(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    prog = _program(db, user)
    p = current_period(db, prog)
    return {"period": p, "month": month_name(prog, p)}
