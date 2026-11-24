"""Обучение (курсы, тесты, справочник) и ИИ-ассистент."""

import io
import json

from docx import Document
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import HR_ONLY, SIDE_ROLES, current_user, own_participant, require_role
from app.db.models import Assignment, Course, Pair, Participant, Program, Test, TestQuestion, User
from app.db.session import get_db
from app.services import assistant, learning

TOPIC_CODES = ("tasks", "auto", "support", "load", "feedback", "growth")

router = APIRouter(prefix="/api", tags=["обучение"])


def _program(db: Session, user: User) -> Program:
    prog = db.get(Program, user.program_id) if user.program_id else None
    if prog is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Программа не найдена.")
    return prog


def _course(db: Session, user: User, cid: int) -> Course:
    c = db.get(Course, cid)
    if c is None or c.program_id != user.program_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Курс не найден.")
    return c


def _test(db: Session, user: User, tid: int) -> Test:
    t = db.get(Test, tid)
    if t is None or t.program_id != user.program_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Тест не найден.")
    return t


@router.get("/learn")
def learn(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    prog = _program(db, user)
    staff = user.role in ("hr", "lead")
    parts = {p.id: p.external_id for p in db.query(Participant).filter(Participant.program_id == prog.id)}
    if staff:
        courses = []
        for c in db.query(Course).filter(Course.program_id == prog.id).order_by(Course.id):
            who = [
                parts[a.participant_id]
                for a in db.query(Assignment).filter(Assignment.course_id == c.id)
                if a.participant_id in parts
            ]
            courses.append(learning.course_out(c, who))
        tests = []
        for t in db.query(Test).filter(Test.program_id == prog.id).order_by(Test.id.desc()):
            o = learning.test_out(t, with_answers=user.role == "hr")
            res = [a for a in db.query(Assignment).filter(Assignment.test_id == t.id)]
            o["assigned"] = [parts.get(a.participant_id) for a in res]
            o["results"] = [
                {"who": parts.get(a.participant_id), "score": a.score} for a in res if a.score is not None
            ]
            tests.append(o)
        return {
            "courses": courses,
            "tests": tests,
            "guide": learning.guide(),
            "validation": learning.validation_table(),
        }
    part = own_participant(db, user)
    courses, tests = [], []
    for a in db.query(Assignment).filter(Assignment.participant_id == (part.id if part else -1)):
        if a.course_id:
            courses.append(
                learning.course_out(db.get(Course, a.course_id), progress=a.progress) | {"reason": a.reason}
            )
        elif a.test_id:
            t = db.get(Test, a.test_id)
            if t.status == "published":
                tests.append(
                    learning.test_out(t, with_answers=False)
                    | {
                        "score": a.score,
                        "passed": a.score is not None and a.score >= t.pass_score,
                        "attempts": a.attempts or 0,
                        "result": a.answers if a.score is not None else None,
                    }
                )
    return {"courses": courses, "tests": tests, "guide": [], "validation": None}


def _read_file(name: str, raw: bytes) -> str:
    if name.lower().endswith(".docx"):
        doc = Document(io.BytesIO(raw))
        lines = []
        for p in doc.paragraphs:
            if not p.text.strip():
                continue
            style = (p.style.name or "").lower() if p.style is not None else ""
            lines.append(("- " if "list" in style else "") + p.text.strip())
        return "\n".join(lines)
    if name.lower().endswith((".txt", ".md")):
        return raw.decode("utf-8", errors="ignore")
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST, "Материал: .docx, .txt или .md. Видео и PDF — ссылкой в тексте раздела."
    )


def _tags(raw: str | list | None) -> list[str]:
    if isinstance(raw, list):
        items = raw
    else:
        try:
            items = json.loads(raw) if raw and raw.strip().startswith("[") else (raw or "").split(",")
        except json.JSONDecodeError:
            items = (raw or "").split(",")
    return list(dict.fromkeys(str(t).strip()[:40] for t in items if str(t).strip()))[:8]


def _fill(c: Course, *, title, kind, topic, audience, duration, tags, sections, status_) -> None:
    if not str(title or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Введите название материала.")
    if not sections:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Добавьте хотя бы один раздел с текстом.")
    c.title = str(title).strip()[:300]
    c.kind = kind if kind in learning.KINDS else "Курс"
    c.topic = topic if topic in TOPIC_CODES else None
    c.audience = audience if audience in ("intern", "mentor", "all") else "intern"
    c.tags = _tags(tags)
    c.sections = sections
    c.content = learning.sections_text(sections)[:20000]
    c.description = (c.content[:240] + "…") if len(c.content) > 240 else c.content
    c.duration = (duration or "").strip()[:40] or f"{learning.minutes(sections)} мин"
    c.status = "draft" if status_ == "draft" else "published"


@router.post("/courses/parse")
async def parse_material(file: UploadFile = File(...), user: User = Depends(require_role(*HR_ONLY))) -> dict:
    """Файл → разделы для конструктора (ничего не сохраняет)."""
    text = _read_file(file.filename or "", await file.read())
    secs = learning.split_sections(text)
    if not secs:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "В файле не нашлось текста.")
    return {"file_name": file.filename, "sections": secs, "minutes": learning.minutes(secs)}


@router.post("/courses")
async def create_course(
    title: str = Form(...),
    kind: str = Form("Курс"),
    topic: str = Form(""),
    audience: str = Form("intern"),
    duration: str = Form(""),
    text: str = Form(""),
    tags: str = Form(""),
    sections: str = Form(""),
    status_: str = Form("published", alias="status"),
    file: UploadFile | None = File(None),
    user: User = Depends(require_role(*HR_ONLY)),
    db: Session = Depends(get_db),
) -> dict:
    prog = _program(db, user)
    fname = None
    if file is not None and file.filename:
        fname = file.filename
        text = _read_file(fname, await file.read())
    try:
        secs = learning.clean_sections(json.loads(sections)) if sections else learning.split_sections(text)
    except json.JSONDecodeError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Разделы материала переданы неверно.") from e
    c = Course(program_id=prog.id, file_name=fname)
    _fill(
        c,
        title=title,
        kind=kind,
        topic=topic,
        audience=audience,
        duration=duration,
        tags=tags,
        sections=secs,
        status_=status_,
    )
    db.add(c)
    db.commit()
    return learning.course_out(c, full=True)


class CourseIn(BaseModel):
    title: str
    kind: str = "Курс"
    topic: str | None = None
    audience: str = "intern"
    duration: str = ""
    tags: list[str] = []
    sections: list[dict]
    status: str = "published"


@router.get("/courses/{cid}")
def get_course(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    c = _course(db, user, cid)
    if user.role in ("hr", "lead"):
        return learning.course_out(c, full=True)
    part = own_participant(db, user)
    a = (
        db.query(Assignment)
        .filter(Assignment.participant_id == (part.id if part else -1), Assignment.course_id == c.id)
        .first()
    )
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Материал вам не назначен.")
    return learning.course_out(c, progress=a.progress, full=True, done=a.sections_done)


@router.put("/courses/{cid}")
def update_course(
    cid: int, data: CourseIn, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    c = _course(db, user, cid)
    _fill(
        c,
        title=data.title,
        kind=data.kind,
        topic=data.topic,
        audience=data.audience,
        duration=data.duration,
        tags=data.tags,
        sections=learning.clean_sections(data.sections),
        status_=data.status,
    )
    db.commit()
    return learning.course_out(c, full=True)


@router.delete("/courses/{cid}")
def delete_course(
    cid: int, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    db.delete(_course(db, user, cid))
    db.commit()
    return {"ok": True}


class AssignIn(BaseModel):
    pair_ids: list[int]
    side: str = "intern"
    reason: str = ""


@router.post("/courses/{cid}/assign")
def assign_course(
    cid: int, data: AssignIn, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    c = _course(db, user, cid)
    n = 0
    for pid in data.pair_ids:
        pair = db.get(Pair, pid)
        if pair and pair.program_id == user.program_id:
            side = c.audience if c.audience in ("intern", "mentor", "all") else data.side
            for who in (
                [pair.intern, pair.mentor]
                if side == "all"
                else [pair.intern if side == "intern" else pair.mentor]
            ):
                learning.assign(db, who, course=c, reason=data.reason or f"по сигналам {pair.code}")
            n += 1
    return {"assigned": n}


class ProgressIn(BaseModel):
    progress: int | None = None
    section: int | None = None


@router.post("/courses/{cid}/progress")
def course_progress(
    cid: int, data: ProgressIn, user: User = Depends(require_role(*SIDE_ROLES)), db: Session = Depends(get_db)
) -> dict:
    part = own_participant(db, user)
    a = (
        db.query(Assignment)
        .filter(Assignment.participant_id == (part.id if part else -1), Assignment.course_id == cid)
        .first()
    )
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Курс вам не назначен.")
    c = db.get(Course, cid)
    total = len(c.sections or []) or 1
    if data.section is not None and 0 <= data.section < total:
        a.sections_done = sorted(set(a.sections_done or []) | {data.section})
        a.progress = max(a.progress, round(len(a.sections_done) / total * 100))
    if data.progress is not None:
        a.progress = max(a.progress, min(100, max(0, data.progress)))
        if a.progress == 100:
            a.sections_done = list(range(total))
    db.commit()
    return {"progress": a.progress, "done": a.sections_done}


class GenIn(BaseModel):
    course_id: int
    n: int = 8
    difficulty: str = "medium"
    types: list[str] = ["single", "multi", "truefalse"]
    pass_score: float = 0.7


@router.post("/tests/generate")
def generate(
    data: GenIn, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    c = _course(db, user, data.course_id)
    t = learning.generate_test(
        db, _program(db, user), c, max(1, min(15, data.n)), data.difficulty, set(data.types), data.pass_score
    )
    if not t.questions:
        db.delete(t)
        db.commit()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "В материале мало текста для вопросов. Добавьте разделы с текстом."
        )
    return learning.test_out(t, with_answers=True)


class QuestionIn(BaseModel):
    enabled: bool | None = None
    text: str | None = None
    qtype: str | None = None
    options: list[str] | None = None
    correct: list[int] | None = None
    explanation: str | None = None


def _question(db: Session, t: Test, qid: int) -> TestQuestion:
    q = db.get(TestQuestion, qid)
    if q is None or q.test_id != t.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Вопрос не найден.")
    return q


def _apply(q: TestQuestion, data: QuestionIn) -> None:
    if data.enabled is not None:
        q.enabled = data.enabled
    if data.qtype is not None:
        q.qtype = data.qtype if data.qtype in learning.QTYPES else "single"
    if data.text is not None:
        if not data.text.strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Текст вопроса пустой.")
        q.text = data.text.strip()[:400]
    if q.qtype == "truefalse":
        q.options = ["Верно", "Неверно"]
    elif data.options is not None:
        opts = [o.strip()[:200] for o in data.options if o.strip()]
        if len(opts) < 2:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нужно минимум два варианта ответа.")
        q.options = opts
    if data.correct is not None:
        corr = sorted({c for c in data.correct if 0 <= c < len(q.options)})
        if not corr:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Отметьте верный ответ.")
        if q.qtype != "multi":
            corr = corr[:1]
        q.correct, q.correct_multi = corr[0], corr
    if data.explanation is not None:
        q.explanation = data.explanation.strip()[:400]


@router.put("/tests/{tid}/questions/{qid}")
def edit_question(
    tid: int,
    qid: int,
    data: QuestionIn,
    user: User = Depends(require_role(*HR_ONLY)),
    db: Session = Depends(get_db),
) -> dict:
    t = _test(db, user, tid)
    _apply(_question(db, t, qid), data)
    db.commit()
    return learning.test_out(t, with_answers=True)


@router.post("/tests/{tid}/questions")
def add_question(
    tid: int, data: QuestionIn, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    t = _test(db, user, tid)
    q = TestQuestion(text="", options=["", ""], qtype="single", source="добавлен HR")
    _apply(
        q,
        QuestionIn(
            qtype=data.qtype or "single",
            text=data.text or "Новый вопрос",
            options=data.options or ["Вариант 1", "Вариант 2", "Вариант 3"],
            correct=data.correct or [0],
            explanation=data.explanation or "",
        ),
    )
    t.questions.append(q)
    db.commit()
    return learning.test_out(t, with_answers=True)


@router.delete("/tests/{tid}/questions/{qid}")
def delete_question(
    tid: int, qid: int, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    t = _test(db, user, tid)
    db.delete(_question(db, t, qid))
    db.commit()
    db.refresh(t)
    return learning.test_out(t, with_answers=True)


@router.post("/tests/{tid}/questions/{qid}/regenerate")
def regenerate(
    tid: int, qid: int, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    t = _test(db, user, tid)
    learning.regenerate_question(db, t, _question(db, t, qid))
    return learning.test_out(t, with_answers=True)


class TestMeta(BaseModel):
    title: str | None = None
    pass_score: float | None = None


@router.put("/tests/{tid}")
def edit_test(
    tid: int, data: TestMeta, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    t = _test(db, user, tid)
    if data.title and data.title.strip():
        t.title = data.title.strip()[:300]
    if data.pass_score is not None:
        t.pass_score = max(0.3, min(1.0, data.pass_score))
    db.commit()
    return learning.test_out(t, with_answers=True)


@router.delete("/tests/{tid}")
def delete_test(
    tid: int, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    db.delete(_test(db, user, tid))
    db.commit()
    return {"ok": True}


@router.post("/tests/{tid}/publish")
def publish(tid: int, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)) -> dict:
    t = _test(db, user, tid)
    if not any(q.enabled for q in t.questions):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Оставьте хотя бы один вопрос.")
    t.status = "published"
    db.commit()
    n = 0
    if t.course_id:
        for a in db.query(Assignment).filter(Assignment.course_id == t.course_id).all():
            learning.assign(db, db.get(Participant, a.participant_id), test=t, reason="по курсу")
            n += 1
    return {"ok": True, "assigned": n}


class TestAnswers(BaseModel):
    answers: dict[int, int | list[int]]


@router.post("/tests/{tid}/answer")
def answer_test(
    tid: int,
    data: TestAnswers,
    user: User = Depends(require_role(*SIDE_ROLES)),
    db: Session = Depends(get_db),
) -> dict:
    t = _test(db, user, tid)
    part = own_participant(db, user)
    a = (
        db.query(Assignment)
        .filter(Assignment.participant_id == (part.id if part else -1), Assignment.test_id == t.id)
        .first()
    )
    if a is None or t.status != "published":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Тест вам не назначен.")
    score, res = learning.grade(t, data.answers)
    a.score, a.answers, a.attempts = score, res, (a.attempts or 0) + 1
    db.commit()
    return {
        "score": score,
        "passed": score >= t.pass_score,
        "pass_score": t.pass_score,
        "attempts": a.attempts,
        "result": res,
    }


class AskIn(BaseModel):
    message: str


@router.post("/assistant")
def ask(data: AskIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return assistant.ask(db, _program(db, user), user, data.message)
