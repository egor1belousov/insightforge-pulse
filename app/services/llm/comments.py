"""Разбор комментариев: LLM с запасным вариантом на правилах."""

from app.services.llm import fallback, tasks


def contradiction(anxiety: float, score: float | None) -> float:
    """Противоречие комментария баллам: тревожный текст при высокой оценке."""
    return tasks._contradiction(anxiety, score)


def analyze(text: str, score: float | None, side: str = "intern") -> dict:
    """Разбирает комментарий: темы, тон, тревожность, противоречие, цитата."""
    return tasks.analyze_comment(text, score, side)


def analyze_rules(text: str, score: float | None) -> dict:
    """Быстрый разбор правилами (для мгновенного пересчёта; LLM дообновит в фоне)."""
    res = fallback.analyze_comment(text, score)
    return res | {"contradiction": contradiction(res["anxiety"], score), "model": "rules", "fallback": True}
