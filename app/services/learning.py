"""Обучение: курсы, назначения, тесты (генерация LLM с проверкой HR), справочник по методике."""

import json
import random
import re
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import Assignment, Course, Participant, Program, Test, TestQuestion
from app.services.ingest.text import similarity
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


KINDS = ("Курс", "Памятка", "Чек-лист", "Материал")
QTYPES = ("single", "multi", "truefalse")
DIFFICULTY = {
    "easy": "базовый: факты, которые прямо написаны в материале",
    "medium": "средний: понять правило и применить его к простой ситуации",
    "hard": "сложный: ситуация на объекте, где нужно выбрать правильное действие по материалу",
}
SECTION_KINDS = ("text", "list", "tip", "check")
TYPE_HINT = {
    "single": "Все вопросы типа single: 4 варианта, ровно один верный.",
    "multi": "Все вопросы типа multi: 5 вариантов, верных 2 или 3; в тексте вопроса напиши «Выберите все верные».",
    "truefalse": 'Все вопросы типа truefalse: text — утверждение по фрагменту (верное или искажённое), options = ["Верно", "Неверно"].',
}
HEAD_RE = re.compile(r"^(\d+[.)]\s+|#+\s+)?[А-ЯЁA-Z][^.!?]{2,80}$")


def split_sections(text: str) -> list[dict]:
    """Текст материала → разделы: заголовки по коротким строкам без точки, списки по маркерам."""
    secs: list[dict] = []
    cur: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        bullet = re.match(r"^([-•*–]|\d+[.)])\s+(.+)$", line)
        if HEAD_RE.match(line) and len(line.split()) <= 9 and not bullet:
            cur = {"kind": "text", "title": re.sub(r"^(\d+[.)]\s+|#+\s+)", "", line), "body": ""}
            secs.append(cur)
            continue
        if cur is None:
            cur = {"kind": "text", "title": "", "body": ""}
            secs.append(cur)
        if bullet:
            if cur["kind"] != "list" and cur["body"]:
                cur = {"kind": "list", "title": "", "body": ""}
                secs.append(cur)
            cur["kind"] = "list"
            cur["body"] += ("\n" if cur["body"] else "") + bullet.group(2)
        else:
            if cur["kind"] == "list":
                cur = {"kind": "text", "title": "", "body": ""}
                secs.append(cur)
            cur["body"] += (" " if cur["body"] else "") + line
    # длинный текст без заголовков — режем по 3–4 предложения
    out: list[dict] = []
    for sct in secs:
        sents = re.split(r"(?<=[.!?])\s+", sct["body"]) if sct["kind"] == "text" else [sct["body"]]
        if sct["kind"] == "text" and len(sents) > 5:
            for i in range(0, len(sents), 4):
                out.append(
                    {
                        "kind": "text",
                        "title": sct["title"] if i == 0 else "",
                        "body": " ".join(sents[i : i + 4]),
                    }
                )
        elif sct["body"] or sct["title"]:
            out.append(sct)
    return out


def clean_sections(sections: list) -> list[dict]:
    """Проверенные разделы из редактора."""
    out = []
    for sct in sections or []:
        if not isinstance(sct, dict):
            continue
        kind = sct.get("kind") if sct.get("kind") in SECTION_KINDS else "text"
        title, body = str(sct.get("title") or "").strip()[:200], str(sct.get("body") or "").strip()[:8000]
        if title or body:
            out.append({"kind": kind, "title": title, "body": body})
    return out[:60]


def sections_text(sections: list[dict]) -> str:
    """Плоский текст разделов — для ИИ и поиска."""
    return "\n".join(((s["title"] + ". ") if s.get("title") else "") + s.get("body", "") for s in sections)


def minutes(sections: list[dict]) -> int:
    """Оценка времени чтения: 150 слов в минуту, не меньше 2 минут."""
    words = len(sections_text(sections).split())
    return max(2, round(words / 150 + len(sections) * 0.5))


# ---------- тесты ----------


class GenQuestion(BaseModel):
    qtype: str = "single"
    text: str
    options: list[str] = Field(min_length=2, max_length=5)
    correct: list[int] = Field(min_length=1, max_length=4)
    explanation: str = ""
    source: str = ""


class GenTest(BaseModel):
    questions: list[GenQuestion] = Field(min_length=1, max_length=8)


def _sentences(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n+", text) if len(x.split()) >= 5]


def _grounded(source: str, chunk: str) -> bool:
    """Цитата-источник действительно из материала."""
    src = source.strip().strip('«»"')
    if len(src) < 12:
        return False
    if src.lower() in chunk.lower():
        return True
    return max((similarity(src, s) for s in _sentences(chunk)), default=0) >= 0.72


def _stems(text: str) -> set[str]:
    return {w.lower()[:5] for w in re.findall(r"[А-Яа-яЁёA-Za-z]{4,}", text)}


def _support(text: str, chunk: str) -> float:
    """Доля значимых слов варианта, которые есть во фрагменте."""
    words = _stems(text)
    return len(words & _stems(chunk)) / len(words) if words else 0.0


def _best_sentence(text: str, chunk: str) -> tuple[str, float]:
    sents = _sentences(chunk) or [chunk]
    best = max(sents, key=lambda x: similarity(text, x))
    return best, similarity(text, best)


def _valid(q: GenQuestion, chunk: str, kinds: set[str]) -> dict | None:
    """Вопрос модели → проверенный вопрос или None.

    Тип берём из запроса (модель часто пишет не тот), разметку «верно/неверно»
    ставим сами по сходству с материалом, верные варианты должны опираться на текст.
    """
    qt = next(iter(kinds)) if len(kinds) == 1 else (q.qtype if q.qtype in kinds else "single")
    text = q.text.strip()
    # дубли вариантов убираем, номера верных пересчитываем
    opts: list[str] = []
    remap: dict[int, int] = {}
    for i, o in enumerate(q.options):
        o = (o or "").strip()
        if not o:
            continue
        if o not in opts:
            opts.append(o)
        remap[i] = opts.index(o)
    correct = sorted({remap[c] for c in q.correct if c in remap})
    if not text:
        return None
    if qt == "truefalse":
        stmt = re.sub(r"^(верно ли( утверждение)?[:,]?\s*)", "", text, flags=re.I).strip('«»"? ')
        src, sim = _best_sentence(stmt, chunk)
        if sim >= 0.9:
            correct = [0]
        elif sim >= 0.55 and _support(stmt, chunk) >= 0.5:
            correct = [1]
        else:
            return None
        return {
            "qtype": "truefalse",
            "text": "Верно ли утверждение: «" + stmt.rstrip(".") + "»?",
            "options": ["Верно", "Неверно"],
            "correct": correct,
            "explanation": ("Да, в материале: " if correct == [0] else "Нет, в материале: ") + src,
            "source": src,
        }
    if not correct or len(opts) < 3:
        return None
    # вопрос должен быть вопросом, а варианты — не «Верно: …»
    if not (text.endswith("?") or "выберите" in text.lower() or "_____" in text):
        return None
    if any(re.match(r"^(верно|неверно)\b", o, re.I) for o in opts):
        return None
    if re.search(r"\bне (выполня|является|относится|делают|нужно)|\bкроме\b|\bневерн", text, re.I):
        return None  # вопросы с отрицанием модель размечает ненадёжно
    if any(_support(opts[c], chunk) < 0.7 for c in correct):
        return None
    if any(_stems(opts[c]) and _stems(opts[c]) <= _stems(text) for c in correct):
        return None  # ответ подсказан в самом вопросе
    if min(len(o.split()) for o in opts) < 2 and "_____" not in text:
        return None  # варианты-обрывки вроде заголовков разделов
    wrong = [o for i, o in enumerate(opts) if i not in correct]
    if qt == "multi" and any(
        _support(o, chunk) >= 0.9 and _best_sentence(o, chunk)[1] >= 0.75 for o in wrong
    ):
        return None  # «неверный» вариант дословно есть в материале — модель ошиблась
    if qt == "multi" and len(correct) < 2:
        qt = "single" if len(opts) >= 3 else qt
    if qt == "single" and len(correct) != 1:
        return None
    if qt == "multi" and len(correct) == len(opts):
        return None
    src = q.source.strip().strip('«»"')
    if not _grounded(src, chunk):
        src, sim = _best_sentence(text + " " + " ".join(opts[c] for c in correct), chunk)
        if sim < 0.35 and _support(" ".join(opts[c] for c in correct), chunk) < 0.6:
            return None
    return {
        "qtype": qt,
        "text": text[:400],
        "options": [o[:200] for o in opts],
        "correct": correct,
        "explanation": q.explanation.strip()[:400] or src,
        "source": src[:400],
    }


def _chunks(sections: list[dict], content: str) -> list[str]:
    """Куски материала для вопросов: по разделам, мелкие склеиваем."""
    parts = [((s["title"] + ". ") if s.get("title") else "") + s.get("body", "") for s in sections] or [
        content
    ]
    out, buf = [], ""
    for p_ in parts:
        buf = (buf + "\n" + p_).strip()
        if len(buf.split()) >= 45:
            out.append(buf)
            buf = ""
    if buf:
        if out and len(buf.split()) < 25:
            out[-1] += "\n" + buf
        else:
            out.append(buf)
    return [c[:2500] for c in out if len(c.split()) >= 8]


def _mutate(sent: str, words: list[str], rng: random.Random) -> str | None:
    """Правдоподобно искажённое утверждение: другое число, отрицание или подмена слова."""
    nums = re.findall(r"\d+", sent)
    if nums:
        n = rng.choice(nums)
        return sent.replace(n, str(int(n) + rng.choice([-2, 2, 5, 10]) if int(n) > 2 else int(n) + 3), 1)
    for verb in (" проверяют", " запрещены", " останавливают", " нужно", " можно", " обязательно"):
        if verb in sent:
            swap = {
                " запрещены": " разрешены",
                " нужно": " не нужно",
                " можно": " нельзя",
                " обязательно": " не обязательно",
            }
            return sent.replace(verb, swap.get(verb, " не" + verb), 1)
    cands = [w for w in WORD_RE.findall(sent)]
    if not cands:
        return None
    key = max(cands, key=len)
    # подмена словом той же формы, чтобы искажение звучало грамотно
    others = [w for w in words if w not in sent and w[-2:] == key[-2:] and w[0].isupper() == key[0].isupper()]
    return sent.replace(key, rng.choice(others), 1) if others else None


def _rules_questions(content: str, n: int, kinds: set[str] | None = None) -> list[dict]:
    """Запасной вариант без ИИ: пропуски, верно/неверно, выбор верных утверждений."""
    kinds = kinds or {"single"}
    sents = _sentences(content)
    words = list(dict.fromkeys(w for s in sents for w in WORD_RE.findall(s)))
    rng = random.Random(len(content))
    out: list[dict] = []
    order = [k for k in ("single", "truefalse", "multi") if k in kinds] or ["single"]
    for i, s in enumerate(sents):
        kind = order[i % len(order)]
        if kind == "truefalse":
            wrong = _mutate(s, words, rng)
            truth = rng.random() < 0.5 or wrong is None
            out.append(
                {
                    "qtype": "truefalse",
                    "text": "Верно ли утверждение: «" + (s if truth else wrong).rstrip(".") + "»?",
                    "options": ["Верно", "Неверно"],
                    "correct": [0 if truth else 1],
                    "explanation": (
                        "Да, так и написано в материале." if truth else "Нет. В материале: «" + s + "»"
                    ),
                    "source": s,
                }
            )
        elif kind == "multi" and len(sents) >= 2:
            t2 = sents[(i + 1) % len(sents)]
            if t2 == s:
                continue
            f1, f2 = _mutate(s, words, rng), _mutate(t2, words, rng)
            if not f1 or not f2 or f1 == s or f2 == t2:
                continue
            opts = [s, t2, f1, f2]
            rng.shuffle(opts)
            out.append(
                {
                    "qtype": "multi",
                    "text": "Какие утверждения верны по материалу? Выберите все верные.",
                    "options": opts,
                    "correct": sorted([opts.index(s), opts.index(t2)]),
                    "explanation": "Верны два утверждения, остальные искажены. В материале: «"
                    + s
                    + "» и «"
                    + t2
                    + "»",
                    "source": s,
                }
            )
        else:
            cands = [
                w for w in WORD_RE.findall(s) if w.lower() not in ("которые", "который", "стажёра", "стажера")
            ]
            distract = [w for w in words if w not in s]
            if not cands or len(distract) < 3:
                continue
            key = max(cands, key=len)
            # отвлекающие слова той же формы: совпадает окончание, чтобы ответ не угадывался по грамматике
            same = [w for w in distract if w[-2:] == key[-2:] and w[0].isupper() == key[0].isupper()]
            pool = same if len(same) >= 3 else same + [w for w in distract if w not in same]
            opts = [key] + rng.sample(pool[:25], 3)
            rng.shuffle(opts)
            out.append(
                {
                    "qtype": "single",
                    "text": "Вставьте пропущенное слово: «" + s.replace(key, "_____", 1) + "»",
                    "options": opts,
                    "correct": [opts.index(key)],
                    "explanation": s,
                    "source": s,
                }
            )
        if len(out) >= n:
            break
    return [q | {"rules": True} for q in out]


def _dedupe(qs: list[dict]) -> list[dict]:
    out: list[dict] = []
    for q in qs:
        if all(similarity(q["text"], x["text"]) < 0.8 for x in out):
            out.append(q)
    return out


def ask_llm(chunk: str, title: str, k: int, difficulty: str, kinds: set[str]) -> list[dict]:
    """Вопросы модели по одному куску материала, только проверенные."""
    res = chat_json(
        prompt("system"),
        prompt(
            "generate_test",
            title=title,
            content=chunk,
            n=str(k),
            difficulty=DIFFICULTY.get(difficulty, DIFFICULTY["medium"]),
            types=", ".join(
                {
                    "single": "single — один верный из 4",
                    "multi": "multi — 2–3 верных из 5",
                    "truefalse": "truefalse — утверждение, верно или неверно",
                }[t]
                for t in QTYPES
                if t in kinds
            ),
        ),
        GenTest,
        timeout=90,
    )
    if res is None:
        return []
    return [v for q in res.questions if (v := _valid(q, chunk, kinds))]


def generate_test(
    db: Session,
    program: Program,
    course: Course,
    n: int = 8,
    difficulty: str = "medium",
    kinds: set[str] | None = None,
    pass_score: float = 0.7,
) -> Test:
    """Черновик теста: вопросы по каждому разделу, у каждого — цитата из материала. Публикует HR."""
    kinds = (kinds or set(QTYPES)) & set(QTYPES) or {"single"}
    content = course.content or sections_text(course.sections or []) or course.description or ""
    chunks = _chunks(course.sections or [], content)
    order = [t for t in ("single", "truefalse", "multi") if t in kinds]
    # слоты: каждому вопросу — раздел и тип по кругу, чтобы типы чередовались
    slots: dict[tuple[int, str], int] = {}
    for i in range(n if chunks else 0):
        key = (i % len(chunks), order[i % len(order)])
        slots[key] = slots.get(key, 0) + 1
    qs: list[dict] = []
    for (ci, qt), k in sorted(slots.items()):
        # «верно/неверно» и «несколько ответов» строим по тексту: так ответ известен точно;
        # вопросы с одним ответом составляет модель, а проверка отсекает сомнительные
        if qt == "single":
            got = ask_llm(chunks[ci], course.title, k + 2, difficulty, {qt})[:k]
        else:
            got = []
        if len(got) < k:
            got += [x for x in _rules_questions(chunks[ci], k * 3, {qt}) if x["qtype"] == qt][: k - len(got)]
        qs += got
    qs = _dedupe(qs)
    from_llm = sum(1 for q in qs if not q.get("rules"))
    if len(qs) < n:
        have = {t: sum(1 for q in qs if q["qtype"] == t) for t in order}
        want = {t: sum(k for (_, qt), k in slots.items() if qt == t) for t in order}
        missing = {t for t in order if have[t] < want[t]} or set(order)
        extra = [
            q
            for q in _rules_questions(content, n * 3, missing)
            if all(similarity(q["text"], x["text"]) < 0.8 for x in qs)
        ]
        qs += extra
    by = "rules" if not from_llm else "llm" if from_llm >= min(n, len(qs)) else "llm+rules"
    # вперемешку по типам, но в порядке разделов
    qs = qs[:n]
    test = Test(
        program_id=program.id,
        course_id=course.id,
        title=f"Проверка: {course.title}",
        status="draft",
        generated_by=by,
        difficulty=difficulty,
        pass_score=max(0.3, min(1.0, pass_score)),
    )
    for q in qs:
        test.questions.append(question_row(q))
    db.add(test)
    db.commit()
    return test


def question_row(q: dict) -> TestQuestion:
    corr = sorted(set(q["correct"])) if isinstance(q["correct"], list) else [q["correct"]]
    return TestQuestion(
        text=q["text"],
        options=q["options"],
        correct=corr[0],
        correct_multi=corr,
        qtype=q.get("qtype", "single"),
        explanation=q.get("explanation", ""),
        source=q.get("source", ""),
    )


def correct_of(q: TestQuestion) -> list[int]:
    return list(q.correct_multi) if q.correct_multi else [q.correct]


def regenerate_question(db: Session, test: Test, q: TestQuestion) -> TestQuestion:
    """Новый вариант вопроса по тому же месту материала."""
    course = db.get(Course, test.course_id) if test.course_id else None
    content = (course.content or sections_text(course.sections or [])) if course else q.source
    chunk = (
        next((c for c in _chunks(course.sections or [], content) if q.source and q.source[:40] in c), None)
        if course
        else None
    )
    chunk = chunk or content[:2500]
    fresh = [
        x
        for x in ask_llm(chunk, course.title if course else test.title, 2, test.difficulty, {q.qtype})
        if similarity(x["text"], q.text) < 0.8
    ]
    if not fresh:
        fresh = [x for x in _rules_questions(chunk, 6, {q.qtype}) if similarity(x["text"], q.text) < 0.8]
    if not fresh:
        return q
    new = question_row(fresh[0])
    q.text, q.options, q.correct, q.correct_multi = new.text, new.options, new.correct, new.correct_multi
    q.qtype, q.explanation, q.source = new.qtype, new.explanation, new.source
    db.commit()
    return q


def grade(t: Test, answers: dict) -> tuple[float, dict]:
    """Проверка ответов: множественный выбор засчитывается только при точном совпадении."""
    qs = [q for q in t.questions if q.enabled]
    res = {}
    for q in qs:
        raw = answers.get(q.id, answers.get(str(q.id)))
        chosen = sorted(raw) if isinstance(raw, list) else ([] if raw is None else [int(raw)])
        corr = correct_of(q)
        res[str(q.id)] = {
            "chosen": chosen,
            "correct": corr,
            "ok": chosen == sorted(corr),
            "explanation": q.explanation,
            "source": q.source,
        }
    score = round(sum(1 for r in res.values() if r["ok"]) / len(qs), 2) if qs else 0
    return score, res


def test_out(t: Test, with_answers: bool) -> dict:
    """Тест для API; стороне — без правильных ответов и цитат."""
    qs = [q for q in t.questions if q.enabled or with_answers]
    return {
        "id": t.id,
        "title": t.title,
        "status": t.status,
        "course_id": t.course_id,
        "generated_by": t.generated_by,
        "pass_score": t.pass_score,
        "difficulty": t.difficulty,
        "questions": [
            {
                "id": q.id,
                "qtype": q.qtype,
                "text": q.text,
                "options": q.options,
                "enabled": q.enabled,
                **(
                    {"correct": correct_of(q), "explanation": q.explanation, "source": q.source}
                    if with_answers
                    else {}
                ),
            }
            for q in qs
        ],
    }


def course_out(
    c: Course,
    assigned: list[str] | None = None,
    progress: int | None = None,
    full: bool = False,
    done: list | None = None,
) -> dict:
    secs = c.sections or ([{"kind": "text", "title": "", "body": c.content}] if c.content else [])
    out = {
        "id": c.id,
        "kind": c.kind,
        "title": c.title,
        "description": c.description,
        "topic": c.topic,
        "tags": c.tags or [],
        "status": c.status,
        "duration": c.duration or f"{minutes(secs)} мин",
        "audience": c.audience,
        "file_name": c.file_name,
        "sections_count": len(secs),
        "assigned": assigned or [],
        "progress": progress,
    }
    if full:
        out["sections"] = secs
        out["done"] = done or []
    return out


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
