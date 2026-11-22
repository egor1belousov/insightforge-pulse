"""Демо-данные: `python -m app.seed [--reset]`.

Создаёт организацию, программу, демо-аккаунты всех ролей. На следующих этапах
сюда добавляются анкеты и синтетические ответы.
"""

import argparse
from datetime import date

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.core.settings import get_settings
from app.db.models import Organization, Participant, Program, Response, User
from app.db.session import Base, SessionLocal, engine
from app.services.accounts import ensure_topics
from app.services.analytics.service import recompute_program
from app.services.ingest.persist import persist
from app.services.ingest.pipeline import Record
from ml.synth import COMMENT_INTERN, COMMENT_MENTOR, INTERN_QUESTIONS, MENTOR_QUESTIONS, PAIRS, to_scale

SCALE = (1, 10)
MISSING = {("mentor", "Н-204", 6)}
EXTRA_PEOPLE = [
    ("С-106", "intern", "Сеть ШПД"),
    ("Н-206", "mentor", "Сеть ШПД"),
    ("Н-207", "mentor", "Монтаж"),
]

DEMO_USERS = [
    ("hr@pulse.demo", "Анна Смирнова", "hr", None),
    ("lead@pulse.demo", "Олег Петров", "lead", None),
    ("mentor@pulse.demo", "Наставник Н-204", "mentor", "Н-204"),
    ("intern@pulse.demo", "Стажёр С-104", "intern", "С-104"),
]


def reset_db() -> None:
    """Удаляет и создаёт заново все таблицы."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def seed_accounts(db: Session) -> Program:
    """Создаёт организацию, программу и демо-аккаунты, если их нет."""
    existing = db.query(User).filter(User.email == "hr@pulse.demo").first()
    if existing:
        return db.get(Program, existing.program_id)
    org = Organization(name="МГТС (демо)")
    db.add(org)
    db.flush()
    prog = Program(organization_id=org.id, name="Стажировка 2026", start_date=date(2026, 6, 1), months=6)
    db.add(prog)
    db.flush()
    ensure_topics(db, org.id)
    pwd = hash_password(get_settings().demo_password)
    for email, name, role, ext in DEMO_USERS:
        user = User(
            email=email, password_hash=pwd, name=name, role=role, organization_id=org.id, program_id=prog.id
        )
        db.add(user)
        db.flush()
        if ext:
            db.add(Participant(program_id=prog.id, external_id=ext, side=role, user_id=user.id))
    db.commit()
    return prog


def demo_schema() -> dict:
    """Анкеты демо-программы в формате схемы загрузки."""
    lo, hi = SCALE

    def qs(letter: str, items: list[tuple[str, str]], comment: str, other: str) -> list[dict]:
        out = [
            {
                "key": f"{letter}{i}",
                "text": text,
                "qtype": "scale",
                "min": lo,
                "max": hi,
                "labels": [],
                "options": [],
                "code": None,
                "inverse": False,
                "topic": topic,
                "topic_conf": 1.0,
                "mirror": f"{other}{i}",
                "mirror_conf": 1.0,
            }
            for i, (text, topic) in enumerate(items, 1)
        ]
        out.append(
            {
                "key": f"{letter}{len(items) + 1}",
                "text": comment,
                "qtype": "text",
                "min": None,
                "max": None,
                "labels": [],
                "options": [],
                "code": None,
                "inverse": False,
                "topic": None,
                "topic_conf": 1.0,
                "mirror": None,
                "mirror_conf": 0,
            }
        )
        return out

    return {
        "questionnaires": {
            "intern": {
                "title": "Анкета стажёра",
                "source": "builder",
                "questions": qs("I", INTERN_QUESTIONS, COMMENT_INTERN, "M"),
            },
            "mentor": {
                "title": "Анкета наставника",
                "source": "builder",
                "questions": qs("M", MENTOR_QUESTIONS, COMMENT_MENTOR, "I"),
            },
        },
        "pairs": [{"intern": p.intern_id, "mentor": p.mentor_id, "conf": 1.0, "how": "демо"} for p in PAIRS],
    }


def demo_records() -> list[Record]:
    """Синтетические анкеты 5 пар за 6 месяцев."""
    lo, hi = SCALE
    recs = []
    for p in PAIRS:
        for side, ext, items, letter in (
            ("intern", p.intern_id, INTERN_QUESTIONS, "I"),
            ("mentor", p.mentor_id, MENTOR_QUESTIONS, "M"),
        ):
            for m in range(6):
                if (side, ext, m + 1) in MISSING:
                    continue
                r = Record(side=side, ext_id=ext, period=m + 1, department=p.department)
                for i, (_, topic) in enumerate(items, 1):
                    raw = to_scale(p.value(side, topic, m), lo, hi)
                    r.scores[f"{letter}{i}"] = (str(raw), round((raw - lo) / (hi - lo), 4))
                text = p.comments.get(side, {}).get(m)
                if text:
                    r.texts[f"{letter}{len(items) + 1}"] = text
                recs.append(r)
    return recs


def seed_demo_data(db: Session, prog: Program) -> None:
    """Загружает демо-анкеты и пересчитывает аналитику."""
    persist(db, prog, demo_schema(), demo_records(), source="import")
    have = {(p.side, p.external_id) for p in db.query(Participant).filter(Participant.program_id == prog.id)}
    for ext, side, dept in EXTRA_PEOPLE:
        if (side, ext) not in have:
            db.add(Participant(program_id=prog.id, external_id=ext, side=side, department=dept))
    db.commit()
    recompute_program(db, prog)


def main() -> None:
    parser = argparse.ArgumentParser(description="Демо-данные «Пульс адаптации»")
    parser.add_argument("--reset", action="store_true", help="очистить базу перед заполнением")
    args = parser.parse_args()
    if args.reset:
        reset_db()
    with SessionLocal() as db:
        prog = seed_accounts(db)
        if args.reset or not db.query(Response).count():
            seed_demo_data(db, prog)
        print(f"Готово: программа «{prog.name}», демо-аккаунты @pulse.demo")


if __name__ == "__main__":
    main()
