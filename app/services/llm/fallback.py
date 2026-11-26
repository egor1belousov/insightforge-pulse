"""Запасные правила для задач LLM: работают, когда Ollama недоступна или ответ невалиден."""

import re

from app.services.ingest.text import TOPIC_KEYWORDS

ANXIETY_WORDS: dict[str, float] = {
    "боюсь": 0.5,
    "страшно": 0.5,
    "тревож": 0.5,
    "переживаю": 0.4,
    "волнуюсь": 0.4,
    "неуверен": 0.4,
    "не успева": 0.4,
    "устал": 0.4,
    "выгора": 0.5,
    "нет времени": 0.4,
    "не хватает": 0.3,
    "непонятн": 0.35,
    "не понимаю": 0.35,
    "будет ли": 0.3,
    "не знаю": 0.25,
    "сложно ": 0.3,
    "тяжело": 0.35,
    "не реагирует": 0.3,
    "игнорир": 0.3,
    "ошибк": 0.2,
    "горят": 0.3,
    "так и не было": 0.3,
    "не было": 0.2,
    "уйти": 0.4,
    "уволь": 0.5,
    "перегруж": 0.4,
    "одиноко": 0.4,
    "не помогает": 0.4,
    "стресс": 0.4,
    "неясн": 0.35,
    "переделыв": 0.3,
    "долго жд": 0.3,
    "задержива": 0.3,
    "слишком": 0.3,
    "выше комфортн": 0.3,
    "повторно уточн": 0.3,
    "снизил": 0.25,
    "нарушает": 0.3,
}
POSITIVE_WORDS: dict[str, float] = {
    "отлично": 0.5,
    "хорошо": 0.35,
    "нравит": 0.4,
    "спасибо": 0.3,
    "понятнее": 0.35,
    "понятно": 0.25,
    "растёт": 0.35,
    "растет": 0.35,
    "справляюсь": 0.3,
    "всегда на связи": 0.4,
    "лучше": 0.3,
    "интересно": 0.3,
    "можно давать": 0.3,
    "сам": 0.1,
    "легко": 0.3,
    "доволен": 0.4,
    "довольна": 0.4,
    "стабильно": 0.35,
    "качественно": 0.3,
    "инициатив": 0.3,
    "улучш": 0.3,
    "выросл": 0.3,
    "увереннее": 0.3,
}
NEGATIVE_WORDS: dict[str, float] = {
    "не ": 0.1,
    "нет ": 0.15,
    "плохо": 0.4,
    "ошибк": 0.3,
    "не реагирует": 0.4,
    "большая": 0.15,
    "торопится": 0.3,
    "пропускает": 0.3,
    "горят": 0.3,
    "боюсь": 0.3,
    "не успева": 0.3,
    "сложн": 0.25,
}
SHORT_FORMAL = 12
# «Сложностей нет», «Критичных сложностей не было», «Ничего не мешает» — спокойный ответ, а не тревога.
NO_PROBLEM_RE = re.compile(
    r"(?:(?:сложност|проблем|препятстви|трудност)\w*[^.!?]{0,40}?\b(?:нет|не было|не возникал\w*)\b"
    r"|\b(?:нет|без)\s+(?:\w+\s+){0,2}(?:сложност|проблем|препятстви)\w*"
    r"|ничего\s+(?:\w+\s+)?не\s+мешает)",
    re.IGNORECASE,
)


def _score(text: str, words: dict[str, float]) -> float:
    t = " " + text.lower().replace("ё", "е") + " "
    return sum(w for k, w in words.items() if k.replace("ё", "е") in t)


def _without_calm(text: str) -> str:
    """Убирает из текста фразы «сложностей нет»: в них нет тревоги, хотя есть слово «сложно»."""
    return NO_PROBLEM_RE.sub(" ", text)


def is_calm(text: str) -> bool:
    """Комментарий целиком сводится к «сложностей нет»."""
    return bool(NO_PROBLEM_RE.search(text)) and len(_without_calm(text).strip(" .,;—-")) < SHORT_FORMAL


def comment_topics(text: str) -> list[str]:
    """Темы комментария по словарю."""
    t = " " + text.lower().replace("ё", "е") + " "
    out = [k for k, words in TOPIC_KEYWORDS.items() if any(kw in t for kw in words)]
    if any(w in t for w in ("обучен", "курс", "оборудован")):
        out.append("tasks")
    return list(dict.fromkeys(out))


def pick_quote(text: str) -> str:
    """Короткая дословная цитата: самое тревожное предложение комментария."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n", text) if p.strip()]
    if not parts:
        return ""
    best = max(parts, key=lambda p: _score(_without_calm(p), ANXIETY_WORDS))
    return best[:200]


def analyze_comment(text: str, score: float | None) -> dict:
    """Разбор комментария правилами.

    Args:
        text: Текст комментария.
        score: Средняя оценка автора в этом месяце (0–1) или None.

    Returns:
        Темы, тон (−1…1), тревожность (0–1), противоречие с баллами (0–1), цитата.
    """
    rest = _without_calm(text)
    anxiety = min(1.0, _score(rest, ANXIETY_WORDS))
    pos, neg = _score(rest, POSITIVE_WORDS), _score(rest, NEGATIVE_WORDS) + anxiety * 0.5
    if is_calm(text):
        pos += 0.3
    tone = max(-1.0, min(1.0, pos - neg))
    if len(text.strip()) <= SHORT_FORMAL and anxiety == 0:
        tone = 0.0
    contradiction = 0.0
    if score is not None:
        contradiction = anxiety * max(0.0, min(1.0, (score - 0.4) / 0.35))
    return {
        "topics": comment_topics(text),
        "tone": round(tone, 2),
        "anxiety": round(anxiety, 2),
        "contradiction": round(contradiction, 2),
        "quote": pick_quote(text),
    }


def tone_label(tone: float) -> str:
    """Подпись тона для интерфейса."""
    return "позитив" if tone > 0.15 else "негатив" if tone < -0.15 else "нейтрально"
