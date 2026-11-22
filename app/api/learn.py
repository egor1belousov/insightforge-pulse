"""Обучение (курсы, тесты, справочник) и ИИ-ассистент."""

import io

from docx import Document
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import HR_ONLY, SIDE_ROLES, current_user, own_participant, require_role
from app.db.models import Assignment, Course, Pair, Participant, Program, Test, TestQuestion, User
from app.db.session import get_db
from app.services import assistant, learning

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
                    | {"score": a.score, "result": a.answers if a.score is not None else None}
                )
    return {"courses": courses, "tests": tests, "guide": [], "validation": None}


@router.post("/courses")
async def create_course(
    title: str = Form(...),
    kind: str = Form("Курс"),
    topic: str = Form("tasks"),
    audience: str = Form("intern"),
    duration: str = Form(""),
    text: str = Form(""),
    file: UploadFile | None = File(None),
    user: User = Depends(require_role(*HR_ONLY)),
    db: Session = Depends(get_db),
) -> dict:
    prog = _program(db, user)
    content, fname = text, None
    if file is not None and file.filename:
        raw = await file.read()
        fname = file.filename
        if fname.lower().endswith(".docx"):
            content = "\n".join(p.text for p in Document(io.BytesIO(raw)).paragraphs if p.text.strip())
        elif fname.lower().endswith((".txt", ".md")):
            content = raw.decode("utf-8", errors="ignore")
        else:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Материал: .docx, .txt или .md. Видео и PDF — ссылкой в описании.",
            )
    if not title.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Введите название курса.")
    c = Course(
        program_id=prog.id,
        title=title.strip()[:300],
        kind=kind[:20],
        topic=topic,
        audience=audience,
        duration=duration[:40],
        description=(content[:240] + "…") if len(content) > 240 else content,
        content=content[:20000],
        file_name=fname,
    )
    db.add(c)
    db.commit()
    return learning.course_out(c)


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
            learning.assign(
                db,
                pair.intern if data.side == "intern" else pair.mentor,
                course=c,
                reason=data.reason or f"по сигналам {pair.code}",
            )
            n += 1
    return {"assigned": n}


class ProgressIn(BaseModel):
    progress: int


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
    a.progress = max(a.progress, min(100, max(0, data.progress)))
    db.commit()
    return {"progress": a.progress}


class GenIn(BaseModel):
    course_id: int
    n: int = 3


@router.post("/tests/generate")
def generate(
    data: GenIn, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    c = _course(db, user, data.course_id)
    t = learning.generate_test(db, _program(db, user), c, max(1, min(5, data.n)))
    if not t.questions:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "В материале мало текста для вопросов. Добавьте описание курса."
        )
    return learning.test_out(t, with_answers=True)


class QuestionToggle(BaseModel):
    enabled: bool


@router.put("/tests/{tid}/questions/{qid}")
def toggle_question(
    tid: int,
    qid: int,
    data: QuestionToggle,
    user: User = Depends(require_role(*HR_ONLY)),
    db: Session = Depends(get_db),
) -> dict:
    t = _test(db, user, tid)
    q = db.get(TestQuestion, qid)
    if q is None or q.test_id != t.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Вопрос не найден.")
    q.enabled = data.enabled
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
    answers: dict[int, int]


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
    qs = [q for q in t.questions if q.enabled]
    res = {
        str(q.id): {
            "chosen": data.answers.get(q.id),
            "correct": q.correct,
            "ok": data.answers.get(q.id) == q.correct,
            "explanation": q.explanation,
        }
        for q in qs
    }
    a.score = round(sum(1 for r in res.values() if r["ok"]) / len(qs), 2) if qs else 0
    a.answers = res
    db.commit()
    return {"score": a.score, "result": res}


class AskIn(BaseModel):
    message: str


@router.post("/assistant")
def ask(data: AskIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return assistant.ask(db, _program(db, user), user, data.message)
