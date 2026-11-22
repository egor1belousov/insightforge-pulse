"""Демо-данные: `python -m app.seed [--reset]`.

Создаёт организацию, программу, демо-аккаунты всех ролей. На следующих этапах
сюда добавляются анкеты и синтетические ответы.
"""

import argparse
from datetime import date

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.core.settings import get_settings
from app.db.models import Organization, Participant, Program, User
from app.db.session import Base, SessionLocal, engine
from app.services.accounts import ensure_topics

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Демо-данные «Пульс адаптации»")
    parser.add_argument("--reset", action="store_true", help="очистить базу перед заполнением")
    args = parser.parse_args()
    if args.reset:
        reset_db()
    with SessionLocal() as db:
        prog = seed_accounts(db)
        print(f"Готово: программа «{prog.name}», демо-аккаунты @pulse.demo")


if __name__ == "__main__":
    main()
