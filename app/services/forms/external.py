"""Ответы из внешних форм (Яндекс Формы, Google Forms): сопоставление полей с вопросами анкеты."""

import re
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Participant, Program, User
from app.services.forms.submit import SubmitError, active_questionnaire, submit_response
from app.services.ingest.text import ID_RE, canon_id, norm, question_code, similarity

ID_WORDS = ("id", "код", "участник", "табельн", "ваш номер")
COMMENT_WORDS = ("коммент", "что мешает", "что получается", "пожелан", "своими словами", "сложност")
SERVICE_WORDS = ("подразделен", "направлени", "отметка времени", "timestamp", "почта", "email")
PERIOD_WORDS = ("период", "контрольн", "месяц")
PERIOD_RE = re.compile(r"(\d{1,2})")
MATCH_MIN = 0.6
DATE_RE = re.compile(r"^\d{1,4}[./-]\d{1,2}[./-]\d{1,4}([ T]\d{1,2}:\d{2}(:\d{2})?)?$")


def find_participant(db: Session, program: Program, fields: dict[str, Any]) -> Participant | None:
    """Участник по полю с ID или по рабочей почте.

    В форме наставника есть и его ID, и ID стажёра: тогда отвечает наставник.
    """
    parts = db.query(Participant).filter(Participant.program_id == program.id).all()
    by_canon = {canon_id(p.external_id): p for p in parts}
    found = []
    for value in fields.values():
        v = str(value or "").strip()
        if v and "@" not in v and ID_RE.match(v) and (p := by_canon.get(canon_id(v))):
            found.append(p)
    if len({p.side for p in found}) == 2:
        return next(p for p in found if p.side == "mentor")
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


def _label_match(label: str, q) -> float:
    """Похожесть подписи поля формы на вопрос: по формулировке и по названию показателя (столбца в данных)."""
    s = similarity(label, q.text)
    key = q.column_key or ""
    if key and not re.fullmatch(r"[IM]\d+", key):
        s = max(s, 1.0 if norm(label) == norm(key) else similarity(label, key))
    return s


def form_period(fields: dict[str, Any]) -> int | None:
    """Контрольный период из поля формы: «Месяц 3», «3», «3-й месяц»."""
    for label, value in fields.items():
        if any(w in label.lower() for w in PERIOD_WORDS):
            m = PERIOD_RE.search(str(value or ""))
            if m and 1 <= int(m.group(1)) <= 24:
                return int(m.group(1))
    return None


def map_fields(
    db: Session, program: Program, side: str, fields: dict[str, Any]
) -> tuple[dict[int, Any], str, list[str]]:
    """Сопоставляет поля формы вопросам анкеты стороны.

    Returns:
        (question_id → значение, включая открытые вопросы; комментарий без вопроса; нераспознанные поля).
    """
    qn = active_questionnaire(db, program.id, side)
    if qn is None:
        raise SubmitError("Анкета стороны не настроена.")
    scale_qs = [q for q in qn.questions if q.qtype != "text"]
    text_qs = [q for q in qn.questions if q.qtype == "text"]
    answers: dict[int, Any] = {}
    comments: list[str] = []
    unknown: list[str] = []
    for label, value in fields.items():
        v = "" if value is None else str(value).strip()
        low = label.lower()
        if not v or ID_RE.match(v) or "@" in v or DATE_RE.match(v):
            continue
        if any(w in low for w in SERVICE_WORDS) or (
            any(w in low for w in PERIOD_WORDS) and len(v) <= 12 and PERIOD_RE.search(v)
        ):
            continue
        code = question_code(label)
        q = next((x for x in scale_qs if code and x.order + 1 == int(code[1:])), None)
        if q is None:
            scored = sorted(
                ((_label_match(label, x), x) for x in scale_qs if x.id not in answers), key=lambda t: -t[0]
            )
            if scored and scored[0][0] >= MATCH_MIN:
                q = scored[0][1]
        if q is not None:
            answers[q.id] = v
            continue
        scored = sorted(
            ((_label_match(label, x), x) for x in text_qs if x.id not in answers), key=lambda t: -t[0]
        )
        if scored and scored[0][0] >= MATCH_MIN:
            answers[scored[0][1].id] = v
        elif any(w in low for w in COMMENT_WORDS) or len(v) > 15:
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
    return submit_response(db, program, part, answers, comment, source=source, period=form_period(fields))
