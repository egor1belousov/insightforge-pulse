"""Разбор комментариев: LLM с запасным вариантом на правилах."""

from app.services.llm import tasks


def contradiction(anxiety: float, score: float | None) -> float:
    """Противоречие комментария баллам: тревожный текст при высокой оценке."""
    return tasks._contradiction(anxiety, score)


def analyze(text: str, score: float | None, side: str = "intern") -> dict:
    """Разбирает комментарий: темы, тон, тревожность, противоречие, цитата."""
    return tasks.analyze_comment(text, score, side)
