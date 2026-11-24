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
from app.services.learning import split_sections
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


def seed_demo_data(db: Session, prog: Program, use_llm: bool = True) -> None:
    """Загружает демо-анкеты и пересчитывает аналитику."""
    persist(db, prog, demo_schema(), demo_records(), source="import")
    have = {(p.side, p.external_id) for p in db.query(Participant).filter(Participant.program_id == prog.id)}
    for ext, side, dept in EXTRA_PEOPLE:
        if (side, ext) not in have:
            db.add(Participant(program_id=prog.id, external_id=ext, side=side, department=dept))
    db.commit()
    recompute_program(db, prog, use_llm=use_llm)


COURSES = [
    (
        "Курс",
        "Как принимать обратную связь",
        "auto",
        "intern",
        "15 мин",
        "С-102",
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
        "С-103",
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
        "С-104",
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
        "Н-204",
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
        "С-105",
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
    db.add(Assignment(participant_id=parts["С-104"].id, test_id=t.id, reason="по курсу"))
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
