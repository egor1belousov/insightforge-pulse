"""Ответы из внешних форм (Яндекс Формы, Google Forms): сопоставление полей с вопросами анкеты."""

import re
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Participant, Program, User
from app.services.forms.submit import SubmitError, active_questionnaire, submit_response
from app.services.ingest.text import ID_RE, canon_id, question_code, similarity

ID_WORDS = ("id", "код", "участник", "табельн", "ваш номер")
COMMENT_WORDS = ("коммент", "что мешает", "что получается", "пожелан", "своими словами")
MATCH_MIN = 0.6
DATE_RE = re.compile(r"^\d{1,4}[./-]\d{1,2}[./-]\d{1,4}([ T]\d{1,2}:\d{2}(:\d{2})?)?$")


def find_participant(db: Session, program: Program, fields: dict[str, Any]) -> Participant | None:
    """Участник по полю с ID или по рабочей почте."""
    parts = db.query(Participant).filter(Participant.program_id == program.id).all()
    by_canon = {canon_id(p.external_id): p for p in parts}
    for label, value in fields.items():
        v = str(value or "").strip()
        if not v:
            continue
        if "@" in v:
            user = db.query(User).filter(User.email == v.lower()).first()
            if user:
                p = next((x for x in parts if x.user_id == user.id), None)
                if p:
                    return p
        if ID_RE.match(v) and (any(w in label.lower() for w in ID_WORDS) or canon_id(v) in by_canon):
            p = by_canon.get(canon_id(v))
            if p:
                return p
    return None


def map_fields(
    db: Session, program: Program, side: str, fields: dict[str, Any]
) -> tuple[dict[int, Any], str, list[str]]:
    """Сопоставляет поля формы вопросам анкеты стороны.

    Returns:
        (question_id → значение, комментарий, нераспознанные поля).
    """
    qn = active_questionnaire(db, program.id, side)
    if qn is None:
        raise SubmitError("Анкета стороны не настроена.")
    scale_qs = [q for q in qn.questions if q.qtype != "text"]
    answers: dict[int, Any] = {}
    comments: list[str] = []
    unknown: list[str] = []
    for label, value in fields.items():
        v = "" if value is None else str(value).strip()
        if not v or ID_RE.match(v) or "@" in v or DATE_RE.match(v):
            continue
        code = question_code(label)
        q = next((x for x in scale_qs if code and x.order + 1 == int(code[1:])), None)
        if q is None:
            scored = sorted(
                ((similarity(label, x.text), x) for x in scale_qs if x.id not in answers), key=lambda t: -t[0]
            )
            if scored and scored[0][0] >= MATCH_MIN:
                q = scored[0][1]
        if q is not None:
            answers[q.id] = v
        elif any(w in label.lower() for w in COMMENT_WORDS) or len(v) > 15:
            comments.append(v)
        else:
            unknown.append(label)
    return answers, "\n".join(comments), unknown


def ingest_external(db: Session, program: Program, fields: dict[str, Any], source: str) -> dict:
    """Обрабатывает один ответ внешней формы по живой цепочке.

    Raises:
        SubmitError: если участник не найден или ответы неполные.
    """
    part = find_participant(db, program, fields)
    if part is None:
        raise SubmitError("В ответе формы не найден ID участника или рабочая почта.")
    answers, comment, _ = map_fields(db, program, part.side, fields)
    return submit_response(db, program, part, answers, comment, source=source)
