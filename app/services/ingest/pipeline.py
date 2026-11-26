"""Умная загрузка: распознавание файлов и сборка записей (docs/SPEC.md, раздел 5).

`analyze()` строит редактируемую схему «Мы поняли так» с уверенностью каждого решения.
`build_records()` применяет схему (с правками HR) к файлам и возвращает нормализованные анкеты.
"""

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from app.services.ingest.tables import (
    ColumnGuess,
    RawTable,
    _numeric,
    _vals,
    detect_long,
    guess_columns,
    period_values,
    pivot_long,
    read_tables,
)
from app.services.ingest.text import (
    INTERN_WORDS,
    MENTOR_WORDS,
    canon_id,
    guess_topic,
    id_number,
    id_prefix,
    is_inverse,
    norm,
    question_code,
    side_hint,
    similarity,
    verbal_scale_for,
)
from app.services.ingest.word import ParsedQuestionnaire, parse_docx

STRUCT_EXT = {".docx"}
TABLE_EXT = {".xlsx", ".xls", ".csv", ".xlsm"}
INTERN_PREFIXES = ("С", "СТ", "I", "IN", "T", "STU", "СТЖ")
MENTOR_PREFIXES = ("Н", "НС", "М", "MEN", "НАС", "K", "К")
ASK_BELOW = 0.6
PROGRAM_MONTHS = 6

# Подключаемые решатели для спорных случаев (LLM, этап 4). Возвращают (значение, уверенность) или None.
SideResolver = Callable[[dict], tuple[str, float] | None]
TopicResolver = Callable[[str, list[str]], tuple[str, float] | None]


@dataclass
class Resolvers:
    """Внешние помощники распознавания; без них работают правила."""

    side: SideResolver | None = None
    topic: TopicResolver | None = None


@dataclass
class Record:
    """Одна анкета после нормализации."""

    side: str
    ext_id: str
    period: int
    link: str | None = None
    department: str | None = None
    scores: dict[str, tuple[str, float | None]] = field(default_factory=dict)
    texts: dict[str, str] = field(default_factory=dict)
    complete: bool = True


def _other(side: str) -> str:
    return "mentor" if side == "intern" else "intern"


def _prefix_side(value: object) -> str | None:
    p = id_prefix(value)
    if not p:
        return None
    if p in ("С", "S", "СТ", "I", "IN", "T", "STU", "СТЖ", "INT"):
        return "intern"
    if p in ("Н", "M", "НС", "МЕН", "MEN", "K", "К", "МН", "НАС"):
        return "mentor"
    return None


def _questions_to_schema(qn: ParsedQuestionnaire | None, side: str) -> dict:
    letter = "I" if side == "intern" else "M"
    if qn is None:
        return {"title": "", "source": "import", "side_conf": 0.0, "questions": []}
    qs = []
    for i, q in enumerate(qn.questions, 1):
        qs.append(
            {
                "key": f"{letter}{i}",
                "text": q.text,
                "qtype": q.qtype,
                "min": q.scale_min,
                "max": q.scale_max,
                "labels": q.labels,
                "options": q.options,
                "code": q.code,
                "alias": q.alias,
                "inverse": q.inverse,
                "topic": None,
                "topic_conf": 0.0,
                "mirror": None,
                "mirror_conf": 0.0,
            }
        )
    return {"title": qn.title, "source": "word", "side_conf": qn.side_conf, "questions": qs}


def _load_tables(paths: list[Path], codes: set[str], texts: list[str]) -> list[RawTable]:
    tables: list[RawTable] = []
    for p in paths:
        if p.suffix.lower() not in TABLE_EXT:
            continue
        for t in read_tables(p):
            info = detect_long(t.df, codes, texts)
            if info:
                t.long_info = info
                t.fmt = "long"
                t.df = pivot_long(t.df, info)
            tables.append(t)
    return tables


def _table_side(
    t: RawTable, cols: list[ColumnGuess], qsets: dict[str, list[str]]
) -> tuple[str, float, list[str]]:
    """Сторона таблицы по взвешенным признакам."""
    score = {"intern": 0.0, "mentor": 0.0}
    why: list[str] = []
    fi, fm = side_hint(f"{t.file} {t.sheet} {t.title}")
    if fi != fm:
        s = "intern" if fi else "mentor"
        score[s] += 0.4
        why.append("имя файла или листа")
    id_cols = [c for c in cols if c.role == "id"]
    # заголовок колонки ID: «ID стажёра» — своя сторона, если это первая колонка ID
    if id_cols:
        hi, hm = side_hint(id_cols[0].name)
        if hi != hm:
            s = "intern" if hi else "mentor"
            score[s] += 0.25
            why.append(f"колонка «{id_cols[0].name}»")
        elif len(id_cols) > 1:
            hi2, hm2 = side_hint(id_cols[1].name)
            if hi2 != hm2:
                s = "mentor" if hi2 else "intern"
                score[s] += 0.2
                why.append(f"колонка связи «{id_cols[1].name}»")
        ps = Counter(_prefix_side(v) for v in _vals(t.df[id_cols[0].name]))
        ps.pop(None, None)
        if ps:
            s, _ = ps.most_common(1)[0]
            score[s] += 0.3
            why.append("формат ID")
    heads = [c.name for c in cols if c.role in ("score", "comment")]
    if heads and qsets["intern"] and qsets["mentor"]:
        mi = sum(max((similarity(h, q) for q in qsets["intern"]), default=0) for h in heads) / len(heads)
        mm = sum(max((similarity(h, q) for q in qsets["mentor"]), default=0) for h in heads) / len(heads)
        if abs(mi - mm) > 0.03:
            s = "intern" if mi > mm else "mentor"
            score[s] += min(0.4, abs(mi - mm) * 3)
            why.append("заголовки совпадают с анкетой из Word")
    hq = sum(side_hint(h)[1] for h in heads)
    if hq >= 2:
        score["mentor"] += 0.1
    total = score["intern"] + score["mentor"]
    if total == 0:
        return "intern", 0.3, ["признаков нет"]
    side = max(score, key=lambda k: score[k])
    conf = min(
        0.99, 0.5 + (score[side] - score[_other(side)]) / max(total, 0.8) * 0.5 + min(0.2, score[side] / 4)
    )
    return side, round(conf, 2), why


def _own_and_link(cols: list[ColumnGuess], df: pd.DataFrame, side: str) -> None:
    ids = [c for c in cols if c.role in ("id", "link")]
    if len(ids) < 2:
        for c in ids:
            c.role = "id"
        return
    own_words = INTERN_WORDS if side == "intern" else MENTOR_WORDS
    other_words = MENTOR_WORDS if side == "intern" else INTERN_WORDS
    scored = []
    for c in ids:
        h = c.name.lower().replace("ё", "е")
        s = 0.0
        if any(w in h for w in own_words) or any(w in h for w in ("участник", "респондент", "код", "id")):
            s += 1
        if any(w in h for w in other_words):
            s -= 1.5
        ps = Counter(_prefix_side(v) for v in _vals(df[c.name]))
        ps.pop(None, None)
        if ps:
            s += 1 if ps.most_common(1)[0][0] == side else -1
        scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    scored[0][1].role = "id"
    scored[0][1].conf = 0.95 if scored[0][0] > scored[1][0] else 0.6
    for _, c in scored[1:]:
        c.role = "link"
        c.conf = 0.9 if scored[0][0] > scored[1][0] else 0.55


def _infer_scale(vals: list) -> tuple[float, float, list[str]]:
    nums = _numeric(vals)
    if nums is None:
        scale = verbal_scale_for([str(v) for v in vals]) or []
        return 0, max(1, len(scale) - 1), scale
    lo, hi = min(nums), max(nums)
    smin = 0 if lo == 0 else 1
    for top in (5, 7, 10, 100):
        if hi <= top:
            return smin, top, []
    return lo, hi, []


def _name_similarity(header: str, q: dict) -> float:
    """Похожесть заголовка колонки на вопрос: по формулировке и по названию показателя из Word."""
    s = similarity(header, q["text"])
    if q.get("alias"):
        s = max(s, 1.0 if norm(header) == norm(q["alias"]) else similarity(header, q["alias"]))
    return s


def _match_columns(cols: list[ColumnGuess], df: pd.DataFrame, qs: list[dict]) -> list[dict]:
    """Сопоставляет колонки оценок и комментариев вопросам анкеты. Дополняет анкету, если вопроса нет."""
    score_qs = [q for q in qs if q["qtype"] != "text"]
    text_qs = [q for q in qs if q["qtype"] == "text"]
    used: set[str] = set()
    cand = []
    for c in cols:
        if c.role != "score":
            continue
        code = question_code(c.name)
        for q in score_qs:
            if code and q.get("code") == code:
                cand.append((1.0, c.name, q["key"]))
            else:
                cand.append((_name_similarity(c.name, q), c.name, q["key"]))
    cand.sort(key=lambda x: -x[0])
    assigned: dict[str, tuple[str, float]] = {}
    for s, cname, qkey in cand:
        if cname in assigned or qkey in used or s < 0.55:
            continue
        assigned[cname] = (qkey, s)
        used.add(qkey)
    letter = qs[0]["key"][0] if qs else "X"
    for c in cols:
        if c.role == "score":
            vals = _vals(df[c.name])
            if c.name in assigned:
                c.question, c.match_conf = assigned[c.name][0], round(min(0.99, assigned[c.name][1]), 2)
                q = next(q for q in qs if q["key"] == c.question)
                if q["min"] is None or q["max"] is None:
                    q["min"], q["max"], labels = _infer_scale(vals)
                    q["labels"] = q["labels"] or labels
                elif not q["labels"]:
                    nums = _numeric(vals)
                    if nums is None:
                        q["labels"] = verbal_scale_for([str(v) for v in vals]) or []
            else:
                lo, hi, labels = _infer_scale(vals)
                key = f"{letter}{len(qs) + 1}"
                qs.append(
                    {
                        "key": key,
                        "text": c.name,
                        "qtype": "scale",
                        "min": lo,
                        "max": hi,
                        "labels": labels,
                        "options": [],
                        "code": question_code(c.name),
                        "inverse": is_inverse(c.name),
                        "topic": None,
                        "topic_conf": 0.0,
                        "mirror": None,
                        "mirror_conf": 0.0,
                    }
                )
                c.question, c.match_conf = key, 0.7 if not score_qs else 0.5
        elif c.role == "comment":
            if not text_qs:
                key = f"{letter}{len(qs) + 1}"
                q = {
                    "key": key,
                    "text": "Комментарий",
                    "qtype": "text",
                    "min": None,
                    "max": None,
                    "labels": [],
                    "options": [],
                    "code": None,
                    "inverse": False,
                    "topic": None,
                    "topic_conf": 0.0,
                    "mirror": None,
                    "mirror_conf": 0.0,
                }
                qs.append(q)
                text_qs.append(q)
            # свободный текстовый вопрос предпочтительнее занятого: два столбца комментариев не сливаются
            free = [q for q in text_qs if q["key"] not in used] or text_qs
            best = max(free, key=lambda q: _name_similarity(c.name, q))
            code = question_code(c.name)
            if code:
                best = next((q for q in text_qs if q.get("code") == code), best)
            c.question, c.match_conf = best["key"], 0.9
            if any(q.get("alias") for q in text_qs):
                used.add(best["key"])
    return qs


def _topics_and_mirrors(qsets: dict[str, list[dict]], resolvers: Resolvers) -> None:
    for side in ("intern", "mentor"):
        for q in qsets[side]:
            if q["qtype"] == "text":
                q["topic"], q["topic_conf"] = None, 1.0
                continue
            topic, conf = guess_topic(f"{q.get('alias') or ''} {q['text']}")
            if conf < 0.7 and resolvers.topic:
                res = resolvers.topic(q["text"], [])
                if res:
                    topic, conf = res
            q["topic"], q["topic_conf"] = topic, conf
    mq = [q for q in qsets["mentor"] if q["qtype"] != "text"]
    taken: set[str] = set()
    for qi in [q for q in qsets["intern"] if q["qtype"] != "text"]:
        options = [m for m in mq if m["key"] not in taken]
        if not options:
            break
        same = [m for m in options if m["topic"] == qi["topic"]]
        pool = same or options
        best = max(pool, key=lambda m: similarity(qi["text"], m["text"]))
        conf = min(qi["topic_conf"], best["topic_conf"]) if same else 0.4
        if same:
            qi["mirror"], best["mirror"] = best["key"], qi["key"]
            qi["mirror_conf"] = best["mirror_conf"] = round(conf, 2)
            taken.add(best["key"])


def _signature(tables: list[RawTable]) -> str:
    parts = sorted("|".join([t.fmt] + sorted(norm(c) for c in t.df.columns)) for t in tables)
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:32]


def _table_sig(t: RawTable) -> str:
    return hashlib.sha256("|".join([t.fmt] + sorted(norm(c) for c in t.df.columns)).encode()).hexdigest()[:16]


def analyze(paths: list[Path], resolvers: Resolvers | None = None, profile: dict | None = None) -> dict:
    """Распознаёт набор файлов и возвращает схему «Мы поняли так».

    Args:
        paths: Файлы Excel/CSV с ответами и Word со структурой анкет.
        resolvers: Помощники для спорных решений (LLM); без них — только правила.
        profile: Сохранённая схема того же формата: применяется без вопросов.

    Returns:
        Схема с решениями, уверенностью, проблемами качества и вопросами к HR.
    """
    resolvers = resolvers or Resolvers()
    parsed: list[ParsedQuestionnaire] = []
    files = []
    for p in paths:
        ext = p.suffix.lower()
        if ext in STRUCT_EXT:
            qns = parse_docx(p)
            parsed.extend(qns)
            files.append(
                {
                    "name": p.name,
                    "kind": "structure",
                    "found": [f"{q.title} ({len(q.questions)} вопр.)" for q in qns],
                }
            )
        elif ext in TABLE_EXT:
            files.append({"name": p.name, "kind": "responses"})
        else:
            files.append({"name": p.name, "kind": "unknown"})
    by_side: dict[str, ParsedQuestionnaire | None] = {"intern": None, "mentor": None}
    for qn in sorted(parsed, key=lambda q: -q.side_conf):
        if qn.side and by_side[qn.side] is None:
            by_side[qn.side] = qn
    quest = {s: _questions_to_schema(by_side[s], s) for s in ("intern", "mentor")}
    codes = {q["code"] for s in quest.values() for q in s["questions"] if q["code"]}
    all_texts = [q["text"] for s in quest.values() for q in s["questions"]]
    tables = _load_tables(paths, codes, all_texts)
    for f in files:
        if f["kind"] == "responses":
            f["tables"] = sum(1 for t in tables if t.file == f["name"])
    texts = {s: [q["text"] for q in quest[s]["questions"]] for s in quest}

    tinfo = []
    for t in tables:
        cols = guess_columns(t.df)
        side, conf, why = _table_side(t, cols, texts)
        if conf < ASK_BELOW and resolvers.side:
            res = resolvers.side(
                {"file": t.file, "sheet": t.sheet, "headers": list(map(str, t.df.columns))[:30]}
            )
            if res:
                side, conf = res
                why = [*why, "LLM"]
        tinfo.append({"t": t, "cols": cols, "side": side, "conf": conf, "why": why})
    # две таблицы одной стороны — вероятно, вторая принадлежит другой стороне
    for side in ("intern", "mentor"):
        same = [x for x in tinfo if x["side"] == side]
        if len(same) > 1 and not any(x["side"] == _other(side) for x in tinfo):
            weakest = min(same, key=lambda x: x["conf"])
            weakest["side"] = _other(side)
            weakest["conf"] = 0.6
            weakest["why"].append("вторая таблица — другая сторона")

    schema_tables = []
    for i, x in enumerate(tinfo):
        t, cols, side = x["t"], x["cols"], x["side"]
        _own_and_link(cols, t.df, side)
        quest[side]["questions"] = _match_columns(cols, t.df, quest[side]["questions"])
        schema_tables.append(
            {
                "key": f"t{i}",
                "file": t.file,
                "sheet": t.sheet,
                "format": t.fmt,
                "long": t.long_info or None,
                "rows": len(t.df),
                "side": side,
                "side_conf": x["conf"],
                "side_why": x["why"],
                "sig": _table_sig(t),
                "columns": [
                    {
                        "name": c.name,
                        "role": c.role,
                        "conf": c.conf,
                        "question": c.question,
                        "match_conf": c.match_conf,
                    }
                    for c in cols
                ],
            }
        )
    _topics_and_mirrors({s: quest[s]["questions"] for s in quest}, resolvers)

    schema = {
        "signature": _signature(tables),
        "profile_applied": False,
        "files": files,
        "questionnaires": quest,
        "tables": schema_tables,
        "pairs": [],
        "issues": [],
        "fixes": {"id_map": {}},
    }
    if profile:
        _apply_profile(schema, profile)
    records = _collect(tables, schema)
    schema["issues"] = _quality(records, schema)  # сначала находим опечатки в ID
    schema["pairs"] = _infer_pairs(records, schema)
    schema["issues"] = _quality(records, schema)
    schema["asks"] = asks(schema)
    schema["summary"] = _summary(records, schema)
    return schema


def _apply_profile(schema: dict, profile: dict) -> None:
    by_sig = {t["sig"]: t for t in profile.get("tables", [])}
    for t in schema["tables"]:
        saved = by_sig.get(t["sig"])
        if not saved:
            continue
        t["side"], t["side_conf"] = saved["side"], 1.0
        cols = {c["name"]: c for c in saved["columns"]}
        for c in t["columns"]:
            if c["name"] in cols:
                c.update({k: cols[c["name"]][k] for k in ("role", "question")})
                c["conf"] = c["match_conf"] = 1.0
    if profile.get("questionnaires"):
        schema["questionnaires"] = profile["questionnaires"]
        for s in schema["questionnaires"].values():
            for q in s["questions"]:
                q["topic_conf"] = 1.0
                if q.get("mirror"):
                    q["mirror_conf"] = 1.0
    schema["profile_applied"] = True


def asks(schema: dict) -> list[dict]:
    """Решения с низкой уверенностью, по которым нужен ответ HR."""
    out = []
    for t in schema["tables"]:
        if t["side_conf"] < ASK_BELOW:
            out.append(
                {"where": f"{t['file']} · {t['sheet']}", "what": "сторона таблицы", "conf": t["side_conf"]}
            )
        for c in t["columns"]:
            if c["role"] != "skip" and c["conf"] < ASK_BELOW:
                out.append(
                    {"where": f"{t['file']} · {c['name']}", "what": "назначение колонки", "conf": c["conf"]}
                )
            if c["role"] == "score" and c["match_conf"] < ASK_BELOW:
                out.append(
                    {"where": f"{t['file']} · {c['name']}", "what": "вопрос анкеты", "conf": c["match_conf"]}
                )
    for p in schema["pairs"]:
        if p["conf"] < ASK_BELOW:
            out.append({"where": f"{p['intern']} ↔ {p['mentor']}", "what": "пара", "conf": p["conf"]})
    for s in schema["questionnaires"].values():
        for q in s["questions"]:
            if q["qtype"] != "text" and q["topic_conf"] < ASK_BELOW:
                out.append({"where": q["text"][:60], "what": "тема вопроса", "conf": q["topic_conf"]})
    return out


def _norm_value(raw: object, q: dict) -> float | None:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)) or str(raw).strip() == "":
        return None
    if q.get("labels") and len(q["labels"]) > 2:
        labels = [norm(x) for x in q["labels"]]
        v = norm(raw)
        if v in labels:
            x = labels.index(v) / (len(labels) - 1)
            return round(1 - x if q.get("inverse") else x, 4)
    try:
        num = float(str(raw).replace(",", "."))
    except ValueError:
        return None
    lo, hi = q.get("min"), q.get("max")
    if lo is None or hi is None or hi == lo:
        return None
    x = max(0.0, min(1.0, (num - lo) / (hi - lo)))
    return round(1 - x if q.get("inverse") else x, 4)


def _collect(tables: list[RawTable], schema: dict) -> list[Record]:
    """Собирает записи по схеме без исправлений качества."""
    records: list[Record] = []
    for t, st in zip(tables, schema["tables"], strict=True):
        side = st["side"]
        qs = {q["key"]: q for q in schema["questionnaires"][side]["questions"]}
        roles = {c["name"]: c for c in st["columns"]}
        id_col = next((c["name"] for c in st["columns"] if c["role"] == "id"), None)
        if id_col is None:
            continue
        link_col = next((c["name"] for c in st["columns"] if c["role"] == "link"), None)
        per_col = next((c["name"] for c in st["columns"] if c["role"] == "period"), None)
        dep_col = next((c["name"] for c in st["columns"] if c["role"] == "department"), None)
        periods = period_values(t.df[per_col]) if per_col else [1] * len(t.df)
        for idx, (_, row) in enumerate(t.df.iterrows()):
            ext = row[id_col]
            if ext is None or (isinstance(ext, float) and pd.isna(ext)):
                continue
            rec = Record(side=side, ext_id=str(ext).strip(), period=periods[idx] or 0)
            if link_col and not pd.isna(row[link_col]):
                rec.link = str(row[link_col]).strip()
            if dep_col and not pd.isna(row[dep_col]):
                rec.department = str(row[dep_col]).strip()
            for name, c in roles.items():
                if c["role"] == "score" and c["question"] in qs:
                    raw = row[name]
                    val = _norm_value(raw, qs[c["question"]])
                    rec.scores[c["question"]] = (None if val is None else str(raw), val)
                elif c["role"] == "comment" and c["question"]:
                    raw = row[name]
                    if raw is not None and not (isinstance(raw, float) and pd.isna(raw)) and str(raw).strip():
                        prev = rec.texts.get(c["question"], "")
                        rec.texts[c["question"]] = (prev + "\n" if prev else "") + str(raw).strip()
            records.append(rec)
    return records


def _infer_pairs(records: list[Record], schema: dict) -> list[dict]:
    links: dict[tuple[str, str], Counter] = defaultdict(Counter)
    ids = {"intern": set(), "mentor": set()}
    for r in records:
        cid = schema["fixes"]["id_map"].get(r.ext_id, r.ext_id)
        ids[r.side].add(cid)
        if r.link:
            lid = schema["fixes"]["id_map"].get(r.link, r.link)
            key = (cid, lid) if r.side == "intern" else (lid, cid)
            links[key][r.side] += 1
    pairs: dict[str, dict] = {}
    best_for_intern: dict[str, tuple[str, int]] = {}
    for (i, m), cnt in links.items():
        n = sum(cnt.values())
        if i not in best_for_intern or n > best_for_intern[i][1]:
            best_for_intern[i] = (m, n)
    for i, (m, _) in best_for_intern.items():
        if i in ids["intern"] or m in ids["mentor"]:
            pairs[i] = {"intern": i, "mentor": m, "conf": 0.99, "how": "колонка связи"}
    free_i = sorted(i for i in ids["intern"] if i not in pairs)
    taken_m = {p["mentor"] for p in pairs.values()}
    free_m = sorted(m for m in ids["mentor"] if m not in taken_m)
    for i in free_i:
        if i in pairs:
            continue
        ni = id_number(i)
        best = None
        for m in free_m:
            nm = id_number(m)
            if ni is None or nm is None:
                continue
            if nm - ni in (100, -100) or nm % 100 == ni % 100:
                best = m
                break
        if best:
            pairs[i] = {"intern": i, "mentor": best, "conf": 0.8, "how": "совпадение номеров ID"}
            free_m.remove(best)
    return sorted(pairs.values(), key=lambda p: p["intern"])


def _quality(records: list[Record], schema: dict) -> list[dict]:
    issues: list[dict] = []
    counts: dict[str, Counter] = {"intern": Counter(), "mentor": Counter()}
    for r in records:
        counts[r.side][r.ext_id] += 1
    id_map: dict[str, str] = {}
    for cnt in counts.values():
        typical = max(cnt.values()) if cnt else 0
        for ext, n in cnt.items():
            if n > max(2, typical // 3):
                continue
            canon = canon_id(ext)
            target = next((o for o in cnt if o != ext and canon_id(o) == canon and cnt[o] > n), None)
            if target is None:
                frequent = [o for o in cnt if cnt[o] > n and o != ext]
                if frequent:
                    cand = max(frequent, key=lambda o: similarity(o, ext))
                    if similarity(cand, ext) >= 0.8 and id_prefix(cand) == id_prefix(ext):
                        target = cand
            if target:
                id_map[ext] = target
                why = (
                    "похожие символы (буква вместо цифры)"
                    if canon_id(ext) == canon_id(target)
                    else "похожий ID"
                )
                issues.append(
                    {
                        "key": f"id:{ext}",
                        "type": "id_typo",
                        "title": f"Неизвестный ID: «{ext}»",
                        "text": f"Встречается {n} раз, {why}. Похоже на {target}.",
                        "fix_label": f"Исправить на {target}",
                        "apply": True,
                        "data": {"from": ext, "to": target},
                    }
                )
    schema["fixes"]["id_map"] = id_map
    seen: Counter = Counter()
    for r in records:
        seen[(r.side, id_map.get(r.ext_id, r.ext_id), r.period)] += 1
    dups = [k for k, v in seen.items() if v > 1]
    if dups:
        names = ", ".join(f"{k[1]} (месяц {k[2]})" for k in dups[:5])
        issues.append(
            {
                "key": "dup",
                "type": "duplicate",
                "title": f"Дубли: {len(dups)}",
                "text": f"Анкета отправлена повторно: {names}.",
                "fix_label": "Оставить последнюю отправку",
                "apply": True,
                "data": {"items": [list(k) for k in dups]},
            }
        )
    miss = []
    for r in records:
        empty = [k for k, (_, v) in r.scores.items() if v is None]
        if empty and len(empty) < len(r.scores):
            miss.append((r.ext_id, r.period, empty))
    if miss:
        total = sum(len(x[2]) for x in miss)
        names = "; ".join(f"{e}, месяц {p}: {len(q)} вопр." for e, p, q in miss[:5])
        issues.append(
            {
                "key": "miss",
                "type": "missing",
                "title": f"Пропуски: {total} ответ(а)",
                "text": f"{names}. Пропуски не считаются проблемой пары.",
                "fix_label": "Не учитывать в расчёте",
                "apply": True,
                "data": {"items": [[e, p, q] for e, p, q in miss]},
            }
        )
    ranges = {}
    for side, s in schema["questionnaires"].items():
        rs = {
            (q["min"], q["max"], len(q.get("labels") or [])) for q in s["questions"] if q["qtype"] != "text"
        }
        ranges[side] = rs
    if ranges.get("intern") and ranges.get("mentor") and ranges["intern"] != ranges["mentor"]:

        def fmt(rs: set) -> str:
            return ", ".join(
                f"{a:g}–{b:g}" if not n or n <= 2 else "словесная" for a, b, n in rs if a is not None
            )

        issues.append(
            {
                "key": "scale",
                "type": "scales",
                "title": "Разные шкалы",
                "text": f"Стажёры: {fmt(ranges['intern'])}; наставники: {fmt(ranges['mentor'])}.",
                "fix_label": "Привести к 0–1",
                "apply": True,
                "data": {},
            }
        )
    bad_periods = sorted({(r.ext_id, r.period) for r in records if r.period < 1 or r.period > 24})
    if bad_periods:
        issues.append(
            {
                "key": "period",
                "type": "period",
                "title": f"Месяц вне диапазона: {len(bad_periods)}",
                "text": ", ".join(f"{e}: {p}" for e, p in bad_periods[:5]),
                "fix_label": "Не учитывать эти анкеты",
                "apply": True,
                "data": {"items": [list(x) for x in bad_periods]},
            }
        )
    paired = {p["intern"] for p in schema.get("pairs", [])} | {p["mentor"] for p in schema.get("pairs", [])}
    lonely = sorted({id_map.get(r.ext_id, r.ext_id) for r in records} - paired)
    if lonely:
        issues.append(
            {
                "key": "lonely",
                "type": "unpaired",
                "title": f"Без второй стороны: {len(lonely)}",
                "text": ", ".join(lonely[:8]) + ". Свяжите пару вручную ниже.",
                "fix_label": "Загрузить без пары",
                "apply": True,
                "data": {"items": lonely},
            }
        )
    return issues


def _summary(records: list[Record], schema: dict) -> dict:
    final = finalize(records, schema)
    return {
        "responses": {s: sum(1 for r in final if r.side == s) for s in ("intern", "mentor")},
        "participants": {s: len({r.ext_id for r in final if r.side == s}) for s in ("intern", "mentor")},
        "periods": sorted({r.period for r in final}),
        "pairs": len(schema["pairs"]),
    }


def finalize(records: list[Record], schema: dict) -> list[Record]:
    """Применяет исправления качества, отмеченные в схеме."""
    applied = {i["type"]: i for i in schema.get("issues", []) if i.get("apply")}
    id_map = {
        i["data"]["from"]: i["data"]["to"]
        for i in schema.get("issues", [])
        if i["type"] == "id_typo" and i.get("apply")
    }
    id_map.update(schema.get("fixes", {}).get("manual_ids", {}))
    out: dict[tuple, Record] = {}
    order: list[tuple] = []
    for r in records:
        r2 = Record(**{**r.__dict__})
        r2.ext_id = id_map.get(r.ext_id, r.ext_id)
        if r2.link:
            r2.link = id_map.get(r2.link, r2.link)
        if "period" in applied and (r2.period < 1 or r2.period > 24):
            continue
        if any(v is None for _, v in r2.scores.values()):
            r2.complete = False
        key = (r2.side, r2.ext_id, r2.period)
        if key in out and "duplicate" not in applied:
            continue
        if key not in out:
            order.append(key)
        out[key] = r2
    return [out[k] for k in order]


def build_records(paths: list[Path], schema: dict) -> list[Record]:
    """Читает файлы заново и применяет к ним схему (с правками HR).

    Args:
        paths: Те же файлы, что при анализе.
        schema: Схема после подтверждения.

    Returns:
        Нормализованные анкеты.
    """
    codes = {q["code"] for s in schema["questionnaires"].values() for q in s["questions"] if q.get("code")}
    texts = [q["text"] for s in schema["questionnaires"].values() for q in s["questions"]]
    tables = _load_tables(paths, codes, texts)
    if len(tables) != len(schema["tables"]):
        raise ValueError("Файлы изменились после анализа. Загрузите их заново.")
    return finalize(_collect(tables, schema), schema)


def refresh(paths: list[Path], schema: dict) -> dict:
    """Пересчитывает пары, проблемы качества и вопросы после правок HR на экране.

    Ручные пары и отметки «исправить» сохраняются.
    """
    codes = {q["code"] for s in schema["questionnaires"].values() for q in s["questions"] if q.get("code")}
    texts = [q["text"] for s in schema["questionnaires"].values() for q in s["questions"]]
    tables = _load_tables(paths, codes, texts)
    for t, st in zip(tables, schema["tables"], strict=True):
        side = st["side"]
        qs = schema["questionnaires"][side]["questions"]
        known = {q["key"] for q in qs}
        for c in st["columns"]:
            if c["role"] in ("score", "comment") and c.get("question") not in known:
                guess = ColumnGuess(c["name"], c["role"], c["conf"])
                schema["questionnaires"][side]["questions"] = _match_columns([guess], t.df, qs)
                c["question"], c["match_conf"] = guess.question, guess.match_conf
    applied = {i["key"]: i.get("apply", True) for i in schema.get("issues", [])}
    manual = [p for p in schema.get("pairs", []) if p.get("manual")]
    records = _collect(tables, schema)
    schema["issues"] = _quality(records, schema)
    inferred = {p["intern"]: p for p in _infer_pairs(records, schema)}
    for m in manual:
        inferred = {k: v for k, v in inferred.items() if v["mentor"] != m["mentor"]}
        inferred[m["intern"]] = m
    schema["pairs"] = sorted(inferred.values(), key=lambda p: p["intern"])
    schema["issues"] = _quality(records, schema)
    for i in schema["issues"]:
        if i["key"] in applied:
            i["apply"] = applied[i["key"]]
    schema["asks"] = asks(schema)
    schema["summary"] = _summary(records, schema)
    return schema


def profile_from_schema(schema: dict) -> dict:
    """Часть схемы, которая сохраняется как профиль сопоставления."""
    return {
        "tables": [{"sig": t["sig"], "side": t["side"], "columns": t["columns"]} for t in schema["tables"]],
        "questionnaires": schema["questionnaires"],
    }
