"""Разбор комментариев: LLM с запасным вариантом на правилах."""

from app.services.llm import fallback


def contradiction(anxiety: float, score: float | None) -> float:
    """Противоречие комментария баллам: тревожный текст при высокой оценке."""
    if score is None:
        return 0.0
    return round(anxiety * max(0.0, min(1.0, (score - 0.4) / 0.35)), 2)


def analyze(text: str, score: float | None) -> dict:
    """Разбирает комментарий: темы, тон, тревожность, противоречие, цитата."""
    res = fallback.analyze_comment(text, score)
    res["contradiction"] = contradiction(res["anxiety"], score)
    return res | {"model": "rules", "fallback": True}
