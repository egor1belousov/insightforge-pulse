"""Обучение: курсы, назначения, тесты (генерация LLM с проверкой HR), справочник по методике."""

import json
import random
import re
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import Assignment, Course, Participant, Program, Test, TestQuestion
from app.services.llm.client import chat_json, prompt

DOCS = Path(__file__).resolve().parent.parent.parent / "docs"
WORD_RE = re.compile(r"[А-Яа-яЁё]{6,}")


def guide() -> list[dict]:
    """Статьи справочника из docs/METHODOLOGY.md: заголовок и абзацы."""
    path = DOCS / "METHODOLOGY.md"
    if not path.exists():
        return []
    items, cur = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            cur = {"title": line[3:].strip(), "blocks": []}
            items.append(cur)
        elif cur is not None and line.strip():
            cur["blocks"].append(line.rstrip())
    return items


def validation_table() -> dict | None:
    """Итоги ml/validate.py для справочника."""
    path = DOCS / "validation.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


class GenQuestion(BaseModel):
    text: str
    options: list[str] = Field(min_length=3, max_length=4)
    correct: int = Field(ge=0, le=3)
    explanation: str = ""


class GenTest(BaseModel):
    questions: list[GenQuestion] = Field(min_length=1, max_length=6)


def _rules_questions(content: str, n: int) -> list[dict]:
    """Запасной вариант: вопросы-пропуски по предложениям материала."""
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", content) if len(s.split()) >= 6]
    words = list(dict.fromkeys(w for s in sents for w in WORD_RE.findall(s)))
    rng = random.Random(len(content))
    out = []
    for s in sents:
        cands = [
            w for w in WORD_RE.findall(s) if w.lower() not in ("которые", "который", "стажёра", "стажера")
        ]
        if not cands:
            continue
        key = max(cands, key=len)
        distract = [w for w in words if w != key and w not in s][:20]
        if len(distract) < 2:
            continue
        opts = [key] + rng.sample(distract, 2)
        rng.shuffle(opts)
        out.append(
            {
                "text": "Вставьте пропущенное слово: «" + s.replace(key, "_____", 1) + "»",
                "options": opts,
                "correct": opts.index(key),
                "explanation": s,
            }
        )
        if len(out) >= n:
            break
    return out


def generate_test(db: Session, program: Program, course: Course, n: int = 3) -> Test:
    """Черновик теста по материалу курса. Публикует HR после проверки."""
    content = (course.content or course.description or "")[:6000]
    res = chat_json(
        prompt("system"),
        prompt("generate_test", title=course.title, content=content, n=str(n)),
        GenTest,
        timeout=90,
    )
    qs, by = [], "rules"
    if res is not None:
        for q in res.questions:
            opts = [o.strip() for o in q.options if o.strip()]
            if len(opts) >= 3 and q.correct < len(opts) and q.text.strip():
                qs.append(
                    {
                        "text": q.text.strip(),
                        "options": opts,
                        "correct": q.correct,
                        "explanation": q.explanation.strip(),
                    }
                )
        by = "llm" if qs else by
    if not qs:
        qs = _rules_questions(content, n)
    test = Test(
        program_id=program.id,
        course_id=course.id,
        title=f"Проверка: {course.title}",
        status="draft",
        generated_by=by,
    )
    for q in qs[:n]:
        test.questions.append(
            TestQuestion(
                text=q["text"], options=q["options"], correct=q["correct"], explanation=q["explanation"]
            )
        )
    db.add(test)
    db.commit()
    return test


def test_out(t: Test, with_answers: bool) -> dict:
    """Тест для API; стороне — без правильных ответов."""
    qs = [q for q in t.questions if q.enabled or with_answers]
    return {
        "id": t.id,
        "title": t.title,
        "status": t.status,
        "course_id": t.course_id,
        "generated_by": t.generated_by,
        "questions": [
            {
                "id": q.id,
                "text": q.text,
                "options": q.options,
                "enabled": q.enabled,
                **({"correct": q.correct, "explanation": q.explanation} if with_answers else {}),
            }
            for q in qs
        ],
    }


def course_out(c: Course, assigned: list[str] | None = None, progress: int | None = None) -> dict:
    return {
        "id": c.id,
        "kind": c.kind,
        "title": c.title,
        "description": c.description,
        "topic": c.topic,
        "duration": c.duration,
        "audience": c.audience,
        "file_name": c.file_name,
        "assigned": assigned or [],
        "progress": progress,
    }


def assign(
    db: Session,
    participant: Participant,
    *,
    course: Course | None = None,
    test: Test | None = None,
    reason: str = "",
) -> Assignment:
    """Назначает курс или тест участнику (повторно не дублирует)."""
    q = db.query(Assignment).filter(Assignment.participant_id == participant.id)
    q = q.filter(Assignment.course_id == course.id) if course else q.filter(Assignment.test_id == test.id)
    a = q.first()
    if a is None:
        a = Assignment(
            participant_id=participant.id,
            course_id=course.id if course else None,
            test_id=test.id if test else None,
            reason=reason,
        )
        db.add(a)
        db.commit()
    return a
