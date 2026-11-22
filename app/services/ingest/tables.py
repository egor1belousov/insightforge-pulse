"""Чтение Excel/CSV и распознавание колонок."""

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from app.services.ingest.text import (
    ID_RE,
    INTERN_WORDS,
    MENTOR_WORDS,
    month_from_name,
    norm,
    question_code,
    verbal_scale_for,
)

ROLES = ("id", "link", "period", "score", "comment", "department", "email", "timestamp", "pair", "skip")
ROLE_NAMES = {
    "id": "ID участника",
    "link": "ID другой стороны",
    "pair": "ID пары",
    "period": "Месяц анкеты",
    "score": "Оценка",
    "comment": "Комментарий",
    "department": "Подразделение",
    "email": "Почта",
    "timestamp": "Отметка времени",
    "skip": "Не учитывать",
}

PERIOD_WORDS = ("месяц", "month", "период", "period", "дата", "date", "волна", "срез")
DEPT_WORDS = ("подраздел", "отдел", "department", "dept", "направлени", "филиал")
TS_WORDS = ("отметка времени", "timestamp", "время отправки", "submitted", "создан")
COMMENT_WORDS = ("коммент", "comment", "что мешает", "что получается", "отзыв", "пожелан", "примечан")
PAIR_WORDS = ("пара", "pair")
MONTH_N_RE = re.compile(
    r"(?:месяц|month|мес\.?)\s*(\d{1,2})|(\d{1,2})\s*(?:-?й)?\s*(?:месяц|мес)", re.IGNORECASE
)


@dataclass
class ColumnGuess:
    """Распознанная колонка."""

    name: str
    role: str
    conf: float
    question: str | None = None
    match_conf: float = 0.0
    scale_min: float | None = None
    scale_max: float | None = None
    labels: list[str] = field(default_factory=list)


@dataclass
class RawTable:
    """Таблица ответов из файла."""

    file: str
    sheet: str
    df: pd.DataFrame
    title: str = ""
    fmt: str = "wide"
    long_info: dict = field(default_factory=dict)


def _read_csv(path: Path) -> pd.DataFrame:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1251"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    try:
        sep = csv.Sniffer().sniff(text[:4000], delimiters=",;\t").delimiter
    except csv.Error:
        sep = ","
    return pd.read_csv(io.StringIO(text), sep=sep, header=None, dtype=object)


def _is_texty(v: object) -> bool:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return False
    if isinstance(v, (int, float, datetime, date, pd.Timestamp)):
        return False
    s = str(v).strip()
    if not s:
        return False
    try:
        float(s.replace(",", "."))
        return False
    except ValueError:
        return True


def _find_header(raw: pd.DataFrame) -> tuple[int, int, str]:
    """Возвращает (первая строка шапки, число строк шапки, заголовок над таблицей)."""
    width = raw.shape[1]
    title = ""
    best = None
    for i in range(min(len(raw), 15)):
        row = raw.iloc[i].tolist()
        filled = [
            v for v in row if not (v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "")
        ]
        if len(filled) <= 1 and width > 2:
            if filled and not title:
                title = str(filled[0])
            continue
        texty = sum(_is_texty(v) for v in filled)
        if texty >= max(2, 0.6 * len(filled)):
            best = i
            break
    if best is None:
        return 0, 1, title
    if best + 1 < len(raw):
        nxt = raw.iloc[best + 1].tolist()
        filled = [
            v for v in nxt if not (v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "")
        ]
        cur_filled = sum(
            1 for v in raw.iloc[best].tolist() if not (v is None or (isinstance(v, float) and pd.isna(v)))
        )
        if filled and sum(_is_texty(v) for v in filled) == len(filled) and len(filled) > cur_filled * 0.8:
            if best + 2 < len(raw) and not all(
                _is_texty(v)
                for v in raw.iloc[best + 2].tolist()
                if v is not None and not (isinstance(v, float) and pd.isna(v))
            ):
                return best, 2, title
    return best, 1, title


def _frame_from_raw(raw: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    raw = raw.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)
    if raw.empty:
        return raw, ""
    start, n, title = _find_header(raw)
    if n == 2:
        top = raw.iloc[start].ffill().tolist()
        bottom = raw.iloc[start + 1].tolist()
        headers = []
        for t, b in zip(top, bottom, strict=False):
            b_ok = b is not None and not (isinstance(b, float) and pd.isna(b)) and str(b).strip()
            headers.append(str(b).strip() if b_ok else str(t).strip())
        if title == "" and any(str(t) != "nan" for t in top):
            title = " ".join(dict.fromkeys(str(t) for t in top if str(t) != "nan"))
    else:
        headers = [
            str(h).strip() if h is not None and str(h) != "nan" else "" for h in raw.iloc[start].tolist()
        ]
    seen: dict[str, int] = {}
    uniq = []
    for i, h in enumerate(headers):
        h = h or f"Колонка {i + 1}"
        if h in seen:
            seen[h] += 1
            h = f"{h} ({seen[h]})"
        else:
            seen[h] = 0
        uniq.append(h)
    df = raw.iloc[start + n :].copy()
    df.columns = uniq
    df = df.dropna(how="all").reset_index(drop=True)
    return df, title


def read_tables(path: Path) -> list[RawTable]:
    """Читает все листы файла с ответами; пропускает листы без данных.

    Args:
        path: .xlsx, .xls или .csv.

    Returns:
        Таблицы с найденной шапкой.
    """
    suffix = path.suffix.lower()
    sheets: dict[str, pd.DataFrame]
    if suffix == ".csv":
        sheets = {"csv": _read_csv(path)}
    else:
        engine = "xlrd" if suffix == ".xls" else "openpyxl"
        sheets = pd.read_excel(path, sheet_name=None, header=None, engine=engine)
    out = []
    for name, raw in sheets.items():
        df, title = _frame_from_raw(raw)
        if len(df) < 3 or df.shape[1] < 3:
            continue
        if not any(_id_like_share(df[c]) > 0.8 for c in df.columns):
            continue
        out.append(RawTable(file=path.name, sheet=str(name), df=df, title=title))
    return out


def _vals(s: pd.Series) -> list:
    return [
        v
        for v in s.tolist()
        if not (v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "")
    ]


def _id_like_share(s: pd.Series) -> float:
    vals = _vals(s)
    if not vals:
        return 0.0
    return sum(bool(ID_RE.match(str(v))) for v in vals) / len(vals)


def _numeric(vals: list) -> list[float] | None:
    out = []
    for v in vals:
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            out.append(float(v))
            continue
        try:
            out.append(float(str(v).replace(",", ".")))
        except ValueError:
            return None
    return out


def _period_kind(name: str, vals: list) -> tuple[str | None, float]:
    """Тип колонки периода: date / number / month_name / month_text."""
    h = name.lower()
    head = any(w in h for w in PERIOD_WORDS)
    if not vals:
        return None, 0.0
    if all(isinstance(v, (datetime, date, pd.Timestamp)) for v in vals):
        return "date", 0.97
    if all(month_from_name(v) for v in vals):
        return "month_name", 0.95
    if all(MONTH_N_RE.search(str(v)) for v in vals):
        return "month_text", 0.95
    nums = _numeric(vals)
    if nums is not None and all(float(x).is_integer() for x in nums) and min(nums) >= 1 and max(nums) <= 24:
        if head:
            return "number", 0.97
    if head:
        try:
            parsed = pd.to_datetime(pd.Series([str(v) for v in vals]), errors="coerce", dayfirst=True)
            if parsed.notna().mean() > 0.9:
                return "date", 0.9
        except (ValueError, TypeError):
            pass
    return None, 0.0


def detect_long(df: pd.DataFrame, codes: set[str], texts: list[str]) -> dict | None:
    """Длинный формат: колонка с кодами/формулировками вопросов и колонка значений."""
    n = len(df)
    for qcol in df.columns:
        vals = [str(v) for v in _vals(df[qcol])]
        uniq = set(vals)
        if not (3 <= len(uniq) <= 60) or len(vals) < n * 0.9 or n / max(1, len(uniq)) < 4:
            continue
        code_hits = sum(1 for u in uniq if question_code(u) or u.upper() in codes)
        from app.services.ingest.text import similarity

        text_hits = sum(1 for u in uniq if texts and max(similarity(u, t) for t in texts) > 0.8)
        if max(code_hits, text_hits) < 0.7 * len(uniq):
            continue
        rest = [c for c in df.columns if c != qcol]
        value_col = None
        for c in rest:
            cv = _vals(df[c])
            if len(cv) < n * 0.9 or _id_like_share(df[c]) > 0.5 or _period_kind(c, cv)[0]:
                continue
            value_col = c
            break
        if value_col is None:
            continue
        return {"question_col": qcol, "value_col": value_col}
    return None


def pivot_long(df: pd.DataFrame, info: dict) -> pd.DataFrame:
    """Переводит длинный формат в широкий: строка = анкета."""
    keys = [c for c in df.columns if c not in (info["question_col"], info["value_col"])]
    tmp = df.copy()
    for k in keys:
        tmp[k] = tmp[k].fillna("")
    wide = tmp.pivot_table(
        index=keys, columns=info["question_col"], values=info["value_col"], aggfunc="last"
    ).reset_index()
    wide.columns = [str(c) for c in wide.columns]
    for k in keys:
        wide[k] = wide[k].replace("", None)
    return wide


def guess_columns(df: pd.DataFrame) -> list[ColumnGuess]:
    """Определяет роль каждой колонки по заголовку и содержимому."""
    guesses: list[ColumnGuess] = []
    n = len(df)
    for col in df.columns:
        h = str(col).lower().replace("ё", "е")
        vals = _vals(df[col])
        if not vals:
            guesses.append(ColumnGuess(col, "skip", 0.9))
            continue
        idshare = _id_like_share(df[col])
        uniq = len({str(v).strip() for v in vals})
        if any(w in h for w in TS_WORDS):
            guesses.append(ColumnGuess(col, "timestamp", 0.95))
            continue
        if sum("@" in str(v) for v in vals) > 0.8 * len(vals):
            guesses.append(ColumnGuess(col, "email", 0.97))
            continue
        if idshare > 0.8 and uniq <= max(60, n // 2):
            if any(w in h for w in PAIR_WORDS) and not any(w in h for w in INTERN_WORDS + MENTOR_WORDS):
                ids = {str(v).strip() for v in vals}
                prefixes = {re.match(r"\D+", s).group(0) if re.match(r"\D+", s) else "" for s in ids}
                if len(prefixes) == 1 and next(iter(prefixes)).upper().startswith(("П", "P")):
                    guesses.append(ColumnGuess(col, "pair", 0.9))
                    continue
            guesses.append(ColumnGuess(col, "id", 0.9))
            continue
        kind, conf = _period_kind(str(col), vals)
        if kind:
            guesses.append(ColumnGuess(col, "period", conf))
            continue
        if any(w in h for w in DEPT_WORDS):
            guesses.append(ColumnGuess(col, "department", 0.95))
            continue
        nums = _numeric(vals)
        if nums is not None:
            lo, hi = min(nums), max(nums)
            if lo >= 0 and hi <= 100 and len(set(nums)) <= 11:
                guesses.append(ColumnGuess(col, "score", 0.9))
            else:
                guesses.append(ColumnGuess(col, "skip", 0.6))
            continue
        scale = verbal_scale_for([str(v) for v in vals])
        if scale:
            guesses.append(
                ColumnGuess(col, "score", 0.9, labels=scale, scale_min=0, scale_max=len(scale) - 1)
            )
            continue
        avg_len = sum(len(str(v)) for v in vals) / len(vals)
        if any(w in h for w in COMMENT_WORDS) or avg_len > 15:
            guesses.append(ColumnGuess(col, "comment", 0.9 if any(w in h for w in COMMENT_WORDS) else 0.75))
            continue
        if uniq <= max(10, n // 3):
            guesses.append(ColumnGuess(col, "department", 0.6))
            continue
        guesses.append(ColumnGuess(col, "comment", 0.6))
    return guesses


def period_values(series: pd.Series, kind_hint: str | None = None) -> list[int | None]:
    """Номера месяцев программы (1, 2, …) для колонки периода."""
    vals = series.tolist()
    nonnull = [v for v in vals if not (v is None or (isinstance(v, float) and pd.isna(v)))]
    kind, _ = _period_kind(str(series.name), nonnull)
    kind = kind or kind_hint
    out: list[int | None] = []
    if kind == "date":
        dts = pd.to_datetime(
            pd.Series([str(v) if not isinstance(v, (datetime, date, pd.Timestamp)) else v for v in vals]),
            errors="coerce",
            dayfirst=True,
        )
        keys = [d.year * 12 + d.month if not pd.isna(d) else None for d in dts]
        base = min(k for k in keys if k is not None)
        return [k - base + 1 if k is not None else None for k in keys]
    if kind == "month_name":
        nums = [month_from_name(v) for v in vals]
        valid = [x for x in nums if x]
        base = min(valid)
        span = max(valid) - base
        if span > 6:  # переход через новый год: сентябрь…февраль
            nums = [x + 12 if x and x < 7 else x for x in nums]
            base = min(x for x in nums if x)
        return [x - base + 1 if x else None for x in nums]
    for v in vals:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            out.append(None)
            continue
        m = MONTH_N_RE.search(str(v))
        if m:
            out.append(int(m.group(1) or m.group(2)))
            continue
        try:
            out.append(int(float(str(v).replace(",", "."))))
        except ValueError:
            out.append(None)
    return out


def header_norm(name: str) -> str:
    """Заголовок для сопоставления: без служебных хвостов."""
    return norm(name)
