"""Разбор структуры анкет из Word (абзацы и таблицы)."""

import re
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.services.ingest.text import is_inverse, question_code, side_hint, verbal_scale_for

SCALE_RE = re.compile(r"(?:шкал\w*|scale|от|from)?\s*(\d{1,2})\s*(?:[-–—]|до|to)\s*(\d{1,2})", re.IGNORECASE)
EDGE_RE = re.compile(r"(\d{1,2})\s*[-–—=:]\s*([а-яёa-z][а-яёa-z ]{2,30})", re.IGNORECASE)
TEXT_WORDS = ("свободн", "текст", "коммент", "открыт", "своими словами")
CHOICE_SPLIT = re.compile(r"\s*[/;|]\s*")


@dataclass
class ParsedQuestion:
    """Вопрос анкеты из Word."""

    text: str
    qtype: str = "scale"
    scale_min: float | None = None
    scale_max: float | None = None
    labels: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)
    code: str | None = None
    section: str = ""
    inverse: bool = False


@dataclass
class ParsedQuestionnaire:
    """Анкета: сторона, заголовок, вопросы."""

    side: str | None
    title: str
    questions: list[ParsedQuestion] = field(default_factory=list)
    side_conf: float = 0.0


def _blocks(doc) -> list[Paragraph | Table]:
    body = doc.element.body
    out: list[Paragraph | Table] = []
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            out.append(Paragraph(child, doc))
        elif tag == "tbl":
            out.append(Table(child, doc))
    return out


def _is_heading(p: Paragraph) -> bool:
    style = (p.style.name or "").lower() if p.style is not None else ""
    text = p.text.strip()
    if not text or len(text) > 120:
        return False
    if style.startswith(("heading", "title", "заголовок")):
        return True
    bold = all(r.bold for r in p.runs if r.text.strip()) and any(r.text.strip() for r in p.runs)
    return bold and "анкет" in text.lower()


def _apply_answer_spec(q: ParsedQuestion, spec: str) -> None:
    low = spec.lower()
    if any(w in low for w in TEXT_WORDS):
        q.qtype = "text"
        return
    parts = [x for x in CHOICE_SPLIT.split(spec) if x.strip()]
    if len(parts) >= 3:
        scale = verbal_scale_for(parts)
        if scale:
            q.qtype, q.labels, q.scale_min, q.scale_max = "scale", scale, 0, len(scale) - 1
        else:
            q.qtype, q.options = "choice", [p.strip() for p in parts]
        return
    m = SCALE_RE.search(spec)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo < hi <= 100:
            q.scale_min, q.scale_max, q.qtype = lo, hi, "scale"
    edges = EDGE_RE.findall(spec)
    if len(edges) >= 2:
        q.labels = [edges[0][1].strip(" ,."), edges[-1][1].strip(" ,.")]


def _new_question(text: str, section: str) -> ParsedQuestion:
    code = question_code(text)
    clean = re.sub(r"^\s*(?:q\s*\d+|\d{1,3})\s*[.):]\s*", "", text.strip(), flags=re.IGNORECASE)
    q = ParsedQuestion(text=clean, code=code, section=section, inverse=is_inverse(clean))
    if any(w in clean.lower() for w in ("коммент", "что мешает", "что получается", "своими словами")):
        q.qtype = "text"
    return q


def _looks_like_question(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    numbered = bool(re.match(r"^\s*(?:q\s*\d+|\d{1,3})\s*[.):]\s+\S", t, re.IGNORECASE))
    return t.endswith("?") or numbered


def parse_docx(path: Path) -> list[ParsedQuestionnaire]:
    """Находит в документе анкеты и их вопросы.

    Args:
        path: Путь к .docx.

    Returns:
        Список анкет; сторона определяется по заголовку или имени файла.
    """
    doc = Document(str(path))
    result: list[ParsedQuestionnaire] = []
    cur: ParsedQuestionnaire | None = None
    section = ""
    last_q: ParsedQuestion | None = None

    def ensure() -> ParsedQuestionnaire:
        nonlocal cur
        if cur is None:
            cur = ParsedQuestionnaire(side=None, title=path.stem)
            result.append(cur)
        return cur

    for block in _blocks(doc):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if not text:
                continue
            if _is_heading(block) and not _looks_like_question(text):
                hi, hm = side_hint(text)
                if "анкет" in text.lower() or hi or hm:
                    cur = ParsedQuestionnaire(side=None, title=text)
                    result.append(cur)
                    section, last_q = "", None
                else:
                    section = text
                continue
            if _looks_like_question(text):
                last_q = _new_question(text, section)
                ensure().questions.append(last_q)
            elif last_q is not None and (
                SCALE_RE.search(text) or any(w in text.lower() for w in TEXT_WORDS) or "/" in text
            ):
                _apply_answer_spec(last_q, text)
        else:
            rows = [[c.text.strip() for c in r.cells] for r in block.rows]
            if not rows:
                continue
            header = [h.lower() for h in rows[0]]
            q_col = next((i for i, h in enumerate(header) if "вопрос" in h or "question" in h), None)
            spec_col = next(
                (i for i, h in enumerate(header) if "тип" in h or "ответ" in h or "шкал" in h or "type" in h),
                None,
            )
            code_col = next(
                (i for i, h in enumerate(header) if h in ("№", "#", "n", "код", "code", "no")), None
            )
            body = rows[1:] if q_col is not None else rows
            if q_col is None:
                q_col = max(range(len(rows[0])), key=lambda i: sum(len(r[i]) for r in rows if i < len(r)))
            for r in body:
                if q_col >= len(r) or not r[q_col]:
                    continue
                prefix = r[code_col] if code_col is not None and code_col < len(r) else ""
                text = r[q_col]
                q = _new_question(text, section)
                if prefix and question_code(prefix):
                    q.code = question_code(prefix)
                if spec_col is not None and spec_col < len(r):
                    _apply_answer_spec(q, r[spec_col])
                ensure().questions.append(q)

    for qn in result:
        hi, hm = side_hint(qn.title)
        if hi != hm:
            qn.side, qn.side_conf = ("intern" if hi else "mentor"), 0.95
        else:
            fi, fm = side_hint(path.stem)
            if fi != fm:
                qn.side, qn.side_conf = ("intern" if fi else "mentor"), 0.85
            else:
                qi = sum(side_hint(q.text)[1] for q in qn.questions)
                qn.side, qn.side_conf = ("mentor", 0.6) if qi >= 2 else ("intern", 0.5)
        for q in qn.questions:
            if q.qtype == "scale" and q.scale_min is None:
                q.scale_min, q.scale_max = None, None
    return [qn for qn in result if qn.questions]
