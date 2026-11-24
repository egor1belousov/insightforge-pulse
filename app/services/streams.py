"""Потоки стажировки: принадлежат компании, все HR и руководители видят все потоки.

Текущий поток пользователя — `User.program_id`; переключение меняет только его.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.db.models import Pair, Participant, Program, Question, Questionnaire, Response, User
from app.services.forms.submit import current_period


class StreamError(ValueError):
    """Понятная HR ошибка при работе с потоками."""


def _status(db: Session, p: Program) -> tuple[str, int]:
    has = db.query(Response.id).join(Participant).filter(Participant.program_id == p.id).first()
    period = current_period(db, p) if has else 0
    if p.start_date and p.start_date > date.today():
        return "скоро", 0
    if period >= (p.months or 6):
        return "завершается" if period == (p.months or 6) else "завершён", period
    return ("идёт" if period else "набор"), period


def overview(db: Session, user: User) -> list[dict]:
    """Потоки компании со сводкой: пары, участники, месяц, состояние."""
    out = []
    for p in (
        db.query(Program).filter(Program.organization_id == user.organization_id).order_by(Program.id.desc())
    ):
        st, period = _status(db, p)
        out.append(
            {
                "id": p.id,
                "name": p.name,
                "start": p.start_date.isoformat() if p.start_date else None,
                "months": p.months,
                "period": period,
                "status": st,
                "pairs": db.query(Pair).filter(Pair.program_id == p.id).count(),
                "people": db.query(Participant).filter(Participant.program_id == p.id).count(),
                "current": p.id == user.program_id,
            }
        )
    return out


def switch(db: Session, user: User, program_id: int) -> Program:
    """Переключает текущий поток пользователя.

    Raises:
        StreamError: если поток чужой.
    """
    p = db.get(Program, program_id)
    if p is None or p.organization_id != user.organization_id:
        raise StreamError("Поток не найден.")
    user.program_id = p.id
    db.commit()
    return p


def copy_questionnaires(db: Session, src: Program, dst: Program) -> int:
    """Копирует активные анкеты обеих сторон с темами и зеркальными вопросами."""
    mapping: dict[int, Question] = {}
    n = 0
    for qn in db.query(Questionnaire).filter(
        Questionnaire.program_id == src.id, Questionnaire.active.is_(True)
    ):
        new = Questionnaire(
            program_id=dst.id, side=qn.side, version=1, source=qn.source, title=qn.title, active=True
        )
        db.add(new)
        db.flush()
        for q in qn.questions:
            nq = Question(
                questionnaire_id=new.id,
                order=q.order,
                text=q.text,
                qtype=q.qtype,
                scale_min=q.scale_min,
                scale_max=q.scale_max,
                scale_labels=q.scale_labels,
                options=q.options,
                topic_id=q.topic_id,
                inverse=q.inverse,
            )
            db.add(nq)
            db.flush()
            mapping[q.id] = nq
        n += 1
    for old_id, nq in mapping.items():
        old = db.get(Question, old_id)
        if old.mirror_question_id in mapping:
            nq.mirror_question_id = mapping[old.mirror_question_id].id
    db.commit()
    return n


def create(
    db: Session, user: User, name: str, start: date | None, months: int, copy_from_current: bool
) -> Program:
    """Новый поток компании; пользователь сразу в него переключается.

    Raises:
        StreamError: если название пустое или срок вне 1–24 месяцев.
    """
    name = name.strip()
    if not name:
        raise StreamError("Введите название потока.")
    if not 1 <= months <= 24:
        raise StreamError("Срок потока — от 1 до 24 месяцев.")
    if (
        db.query(Program)
        .filter(Program.organization_id == user.organization_id, Program.name == name)
        .first()
    ):
        raise StreamError("Поток с таким названием уже есть.")
    src = db.get(Program, user.program_id) if user.program_id else None
    p = Program(
        organization_id=user.organization_id,
        name=name,
        start_date=(start or date.today()).replace(day=1),
        months=months,
    )
    db.add(p)
    db.flush()
    if not (copy_from_current and src is not None and copy_questionnaires(db, src, p)):
        from app.services.accounts import default_questionnaires

        default_questionnaires(db, p)
    user.program_id = p.id
    db.commit()
    return p
