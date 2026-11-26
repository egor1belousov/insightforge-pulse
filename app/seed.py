"""Демо-данные: `python -m app.seed [--reset]`.

Создаёт организацию, программу, демо-аккаунты всех ролей и загружает историю кейса МГТС
(`data/mgts`: две таблицы ответов и две анкеты Word) через обычный загрузчик.
"""

import argparse
import copy
from datetime import date
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.core.settings import get_settings
from app.db.models import Organization, Participant, Program, Response, User
from app.db.session import Base, SessionLocal, engine
from app.services.accounts import ensure_topics
from app.services.analytics.service import recompute_program
from app.services.ingest.persist import persist
from app.services.ingest.pipeline import Record, analyze, build_records
from app.services.learning import split_sections

CASE_DIR = Path(__file__).resolve().parent.parent / "data" / "mgts"
# Тестовая пара для живой анкеты: в истории кейса её нет, ответы заводятся на защите через формы.
DEMO_INTERN = "СТ-006"
DEMO_MENTOR = "Н-006"
DEMO_DEPT = "IT"

DEMO_USERS = [
    ("hr@pulse.demo", "Анна Смирнова", "hr", None),
    ("lead@pulse.demo", "Олег Петров", "lead", None),
    ("mentor@pulse.demo", f"Наставник {DEMO_MENTOR}", "mentor", DEMO_MENTOR),
    ("intern@pulse.demo", f"Стажёр {DEMO_INTERN}", "intern", DEMO_INTERN),
]


def reset_db() -> None:
    """Удаляет и создаёт заново все таблицы."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def create_org(db: Session, users=DEMO_USERS, sandbox_token: str | None = None) -> Program:
    """Создаёт организацию, программу и аккаунты всех ролей."""
    org = Organization(name="МГТС (демо)", sandbox_token=sandbox_token)
    db.add(org)
    db.flush()
    prog = Program(organization_id=org.id, name="Стажировка 2026", start_date=date(2026, 6, 1), months=6)
    db.add(prog)
    db.flush()
    ensure_topics(db, org.id)
    pwd = hash_password(get_settings().demo_password)
    for email, name, role, ext in users:
        user = User(
            email=email, password_hash=pwd, name=name, role=role, organization_id=org.id, program_id=prog.id
        )
        db.add(user)
        db.flush()
        if ext:
            db.add(Participant(program_id=prog.id, external_id=ext, side=role, user_id=user.id))
    db.commit()
    return prog


def seed_accounts(db: Session) -> Program:
    """Создаёт организацию, программу и демо-аккаунты, если их нет."""
    existing = db.query(User).filter(User.email == "hr@pulse.demo").first()
    if existing:
        return db.get(Program, existing.program_id)
    return create_org(db)


@lru_cache(maxsize=1)
def _case() -> tuple[dict, list[Record]]:
    """Исходная история кейса МГТС из `data/mgts`: распознаётся тем же загрузчиком, что и у HR."""
    files = sorted(CASE_DIR.iterdir())
    schema = analyze(files)
    for qn in schema["questionnaires"].values():
        qn["title"] = qn.get("title") or ""
    records = build_records(files, schema)
    schema["pairs"].append(
        {"intern": DEMO_INTERN, "mentor": DEMO_MENTOR, "conf": 1.0, "how": "тестовая пара"}
    )
    return schema, records


def demo_schema() -> dict:
    """Анкеты и пары демо-программы в формате схемы загрузки (структура анкет МГТС)."""
    return copy.deepcopy(_case()[0])


def demo_records() -> list[Record]:
    """Анкеты кейса: 5 пар, 6 контрольных периодов."""
    return copy.deepcopy(_case()[1])


def seed_demo_data(db: Session, prog: Program, use_llm: bool = True) -> None:
    """Загружает историю кейса МГТС и пересчитывает аналитику."""
    persist(db, prog, demo_schema(), demo_records(), source="import")
    for p in db.query(Participant).filter(
        Participant.program_id == prog.id, Participant.external_id.in_((DEMO_INTERN, DEMO_MENTOR))
    ):
        p.department = p.department or DEMO_DEPT
    db.commit()
    recompute_program(db, prog, use_llm=use_llm)


COURSES = [
    (
        "Курс",
        "Как принимать обратную связь",
        "feedback",
        "intern",
        "15 мин",
        "СТ-005",
        0,
        "Замечание — это не оценка личности, а описание работы. Получив замечание, запишите его своими словами и уточните критерий. "
        "Превратите каждое замечание в задачу с понятным результатом. Перед сдачей работы проверьте её по чек-листу. "
        "Раз в неделю попросите наставника о коротком разборе одной работы.",
    ),
    (
        "Курс",
        "Тайм-менеджмент стажёра",
        "load",
        "intern",
        "25 мин",
        "СТ-004",
        60,
        "Оценивайте сроки задачи вместе с наставником в начале работы. Если задача занимает вдвое больше времени, чем планировали, скажите об этом сразу. "
        "Фраза «не успеваю» — нормальный рабочий сигнал, а не признак слабости. Список приоритетов на день составляется утром. "
        "Короткий ежедневный созвон на десять минут снимает большую часть вопросов.",
    ),
    (
        "Курс",
        "Оборудование ШПД",
        "tasks",
        "intern",
        "60 мин",
        DEMO_INTERN,
        35,
        "Перед сваркой с волокна снимают защитное покрытие, очищают его спиртом и выполняют скол скалывателем. "
        "Качество сварного соединения проверяют рефлектометром. Если на объекте нет схемы разводки, работу останавливают и связываются с наставником. "
        "Оптический кросс маркируют по схеме подразделения. Перед выездом проверяют комплект инструмента по чек-листу.",
    ),
    (
        "Памятка",
        "Когда не хватает времени на стажёра",
        "support",
        "mentor",
        "5 мин",
        DEMO_MENTOR,
        0,
        "Договоритесь с руководителем о фиксированном часе наставничества в неделю. Делегируйте стажёру задачи, которые он уже умеет делать сам. "
        "Если объекты не позволяют уделять время, скажите HR — это нормальный запрос.",
    ),
    (
        "Материал",
        "Карта развития в МГТС",
        "growth",
        "intern",
        "10 мин",
        "СТ-002",
        0,
        "После стажировки стажёр может перейти в штат подразделения. Решение о предложении принимает руководитель вместе с HR. "
        "Критерии аттестации сообщаются не позднее чем за месяц до окончания программы.",
    ),
]
TAGS = {
    "Как принимать обратную связь": ["Коммуникация"],
    "Тайм-менеджмент стажёра": ["Планирование"],
    "Оборудование ШПД": ["Оборудование", "Охрана труда"],
    "Когда не хватает времени на стажёра": ["Наставничество"],
    "Карта развития в МГТС": ["Карьера"],
}
SECTIONED = {
    "Оборудование ШПД": "Подготовка волокна\nПеред сваркой с волокна снимают защитное покрытие, очищают его спиртом и выполняют скол скалывателем.\n"
    "Проверка соединения\nКачество сварного соединения проверяют рефлектометром.\n"
    "Если нет схемы\nЕсли на объекте нет схемы разводки, работу останавливают и связываются с наставником.\n"
    "Маркировка и выезд\n- Оптический кросс маркируют по схеме подразделения.\n- Перед выездом проверяют комплект инструмента по чек-листу.",
}
TEST_Q = [
    (
        "Что нужно сделать с волокном перед сваркой?",
        ["Снять покрытие, очистить и сколоть", "Сразу поместить в сварочный аппарат", "Нагреть для гибкости"],
        0,
        "Перед сваркой с волокна снимают покрытие, очищают его и выполняют скол.",
    ),
    (
        "Чем проверяют качество сварного соединения?",
        ["Мультиметром", "Рефлектометром", "Визуально"],
        1,
        "Качество проверяют рефлектометром.",
    ),
    (
        "Что делать, если на объекте нет схемы разводки?",
        ["Работать по памяти", "Спросить у клиента", "Остановить работу и связаться с наставником"],
        2,
        "Без схемы работу останавливают и связываются с наставником.",
    ),
]


def seed_learning(db: Session, prog: Program) -> None:
    """Демо-курсы, назначения и опубликованный тест."""
    from app.db.models import Assignment, Course, Test, TestQuestion

    if db.query(Course).filter(Course.program_id == prog.id).count():
        return
    parts = {p.external_id: p for p in db.query(Participant).filter(Participant.program_id == prog.id)}
    shpd = None
    for kind, title, topic, aud, dur, who, progress, text in COURSES:
        c = Course(
            program_id=prog.id,
            kind=kind,
            title=title,
            topic=topic,
            audience=aud,
            duration=dur,
            content=text,
            description=text.split(". ")[0] + ".",
            sections=split_sections(SECTIONED.get(title, text)),
            tags=TAGS.get(title, []),
        )
        db.add(c)
        db.flush()
        if who in parts:
            db.add(
                Assignment(
                    participant_id=parts[who].id, course_id=c.id, progress=progress, reason="по сигналам пары"
                )
            )
        if title == "Оборудование ШПД":
            shpd = c
    t = Test(
        program_id=prog.id,
        course_id=shpd.id,
        title="Оборудование ШПД: проверка",
        status="published",
        generated_by="llm",
    )
    for text, opts, ok, expl in TEST_Q:
        t.questions.append(TestQuestion(text=text, options=opts, correct=ok, explanation=expl))
    db.add(t)
    db.flush()
    for ext in ("СТ-001", DEMO_INTERN):  # тест по курсу: у стажёра кейса и у тестового
        db.add(Assignment(participant_id=parts[ext].id, test_id=t.id, reason="по курсу"))
    db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Демо-данные «Пульс адаптации»")
    parser.add_argument("--reset", action="store_true", help="очистить базу перед заполнением")
    parser.add_argument(
        "--fast", action="store_true", help="разбор комментариев правилами, без LLM (секунды вместо минут)"
    )
    args = parser.parse_args()
    if args.reset:
        reset_db()
    with SessionLocal() as db:
        prog = seed_accounts(db)
        if args.reset or not db.query(Response).count():
            print(
                "Загружаем демо-анкеты и пересчитываем сигналы"
                + ("" if args.fast else " (комментарии разбирает ИИ, до 2–3 минут)")
                + "…"
            )
            seed_demo_data(db, prog, use_llm=not args.fast)
        seed_learning(db, prog)
        print(f"Готово: программа «{prog.name}», демо-аккаунты @pulse.demo")


if __name__ == "__main__":
    main()
