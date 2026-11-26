"""Нормализация текста, словари сторон, тем и словесных шкал."""

import re

from rapidfuzz import fuzz

INTERN_WORDS = ("стаж", "intern", "trainee", "студент", "практикант")
MENTOR_WORDS = ("наставн", "mentor", "куратор", "руководител", "buddy")

TOPIC_KEYWORDS: dict[str, dict[str, float]] = {
    "tasks": {"понятн": 1, "понима": 1, "ожида": 2, "задач": 0.5, "ясн": 1, "критери": 1, "цел": 0.5},
    "auto": {"самостоят": 3, "без помощ": 3, "участок": 1, "независим": 2, "сам ": 1},
    "support": {
        "поддерж": 2,
        "внимани": 2,
        "наставничеств": 2,
        "времени на": 1,
        "команд": 1,
        "помощ": 0.5,
        "комфортно": 1,
        "взаимодейств": 3,
    },
    "load": {
        "нагруз": 3,
        "объем": 3,
        "успева": 2,
        "темп": 2,
        "перегруж": 3,
        "загруж": 2,
        "загруз": 2,
        "срок": 3,
        "организ": 1.5,
    },
    "feedback": {"обратн": 3, "отзыв": 2, "ревью": 2, "замечан": 2, "критик": 2},
    "growth": {
        "перспектив": 3,
        "штат": 3,
        "будущ": 2,
        "предложени": 2,
        "карьер": 3,
        "растет": 1,
        "развит": 1,
        "развива": 2,
        "навык": 2,
    },
    "engage": {"интерес": 3, "вовлеч": 3, "инициатив": 3, "мотивац": 2},
    "overall": {"в целом": 3, "удовлетвор": 3, "довол": 3, "качеств": 2},
}

VERBAL_SCALES: list[list[str]] = [
    ["совсем нет", "скорее нет", "отчасти", "скорее да", "полностью"],
    ["совсем нет", "скорее нет", "нейтрально", "скорее да", "полностью"],
    ["не согласен", "скорее не согласен", "нейтрально", "скорее согласен", "согласен"],
    ["полностью не согласен", "не согласен", "нейтрально", "согласен", "полностью согласен"],
    ["нет", "скорее нет", "не знаю", "скорее да", "да"],
    ["очень плохо", "плохо", "нормально", "хорошо", "отлично"],
    ["никогда", "редко", "иногда", "часто", "всегда"],
]

INVERSE_WORDS = ("перегруж", "устаю", "устал", "тревож", "стресс", "выгоран", "трудно", "сложно ли")

MONTHS: dict[str, int] = {
    "январ": 1,
    "феврал": 2,
    "март": 3,
    "апрел": 4,
    "ма": 5,
    "июн": 6,
    "июл": 7,
    "август": 8,
    "сентябр": 9,
    "октябр": 10,
    "ноябр": 11,
    "декабр": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

CONFUSABLE = str.maketrans({"О": "0", "O": "0", "о": "0", "o": "0", "З": "3", "l": "1", "I": "1", "|": "1"})
LAT_TO_CYR = str.maketrans({"C": "С", "H": "Н", "M": "М", "S": "С"})

ID_RE = re.compile(r"^\s*[A-Za-zА-Яа-яЁё]{1,4}\s*[-_ ]?\s*[0-9OoОо]{1,5}\s*$")
CODE_RE = re.compile(r"^\s*(?:q|в|вопрос|question)\s*[-_.]?\s*(\d{1,3})\s*[.):]?\s*", re.IGNORECASE)
NUM_PREFIX_RE = re.compile(r"^\s*\d{1,3}\s*[.)]\s*")


def norm(text: object) -> str:
    """Нижний регистр, ё→е, без пунктуации и номера в начале."""
    s = str(text or "").lower().replace("ё", "е")
    s = CODE_RE.sub("", s)
    s = NUM_PREFIX_RE.sub("", s)
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def question_code(text: object) -> str | None:
    """Код вопроса вида Q3 из начала строки или None."""
    m = CODE_RE.match(str(text or ""))
    return f"Q{int(m.group(1))}" if m else None


def similarity(a: object, b: object) -> float:
    """Похожесть двух формулировок 0–1."""
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    return max(fuzz.token_set_ratio(na, nb), fuzz.ratio(na, nb)) / 100.0


def side_hint(text: object) -> tuple[float, float]:
    """Признаки стороны в тексте: (вес стажёра, вес наставника)."""
    t = str(text or "").lower().replace("ё", "е")
    return float(any(w in t for w in INTERN_WORDS)), float(any(w in t for w in MENTOR_WORDS))


def guess_topic(text: str) -> tuple[str, float]:
    """Тема вопроса по взвешенному словарю ключевых слов: (код, уверенность)."""
    t = " " + str(text).lower().replace("ё", "е") + " "
    scores = {k: sum(w for kw, w in words.items() if kw in t) for k, words in TOPIC_KEYWORDS.items()}
    best = max(scores, key=lambda k: scores[k])
    ordered = sorted(scores.values(), reverse=True)
    if ordered[0] == 0:
        return "support", 0.3
    gap = ordered[0] - ordered[1]
    conf = 0.9 if gap >= 1.5 else 0.75 if gap > 0 else 0.5
    return best, conf


def is_inverse(text: str) -> bool:
    """Инверсный вопрос: высокий балл означает плохое состояние."""
    t = str(text).lower()
    return any(w in t for w in INVERSE_WORDS)


def verbal_scale_for(values: list[str]) -> list[str] | None:
    """Подбирает словесную шкалу, покрывающую все значения."""
    vals = {norm(v) for v in values if str(v).strip()}
    if not vals:
        return None
    best, best_cover = None, 0.0
    for scale in VERBAL_SCALES:
        ns = [norm(x) for x in scale]
        cover = sum(1 for v in vals if v in ns) / len(vals)
        if cover > best_cover:
            best, best_cover = scale, cover
    return best if best_cover >= 0.8 else None


def month_from_name(value: object) -> int | None:
    """Номер календарного месяца по названию («июнь», «Jun») или None."""
    t = str(value or "").strip().lower()
    if not t or not t[0].isalpha():
        return None
    for prefix, num in sorted(MONTHS.items(), key=lambda kv: -len(kv[0])):
        if t.startswith(prefix) and (prefix != "ма" or t.startswith(("май", "мая", "мае"))):
            return num
    return None


def canon_id(value: object) -> str:
    """Каноническая форма ID для сравнения: без пробелов, исправлены похожие символы."""
    s = re.sub(r"\s+", "", str(value or "")).upper().replace("_", "-")
    m = re.match(r"^([A-ZА-ЯЁ]+)-?(.+)$", s)
    if not m:
        return s
    return f"{m.group(1)}-{m.group(2).translate(CONFUSABLE)}"


def id_prefix(value: object) -> str:
    """Буквенный префикс ID."""
    m = re.match(r"^\s*([A-Za-zА-Яа-яЁё]+)", str(value or ""))
    return m.group(1).upper().translate(LAT_TO_CYR) if m else ""


def id_number(value: object) -> int | None:
    """Числовая часть ID."""
    m = re.search(r"(\d+)\s*$", canon_id(value))
    return int(m.group(1)) if m else None
