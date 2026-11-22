"""Помощники распознавания загрузки на основе LLM."""

from app.services.ingest.pipeline import Resolvers
from app.services.llm import tasks
from app.services.llm.client import enabled


def _side(info: dict) -> tuple[str, float] | None:
    res = tasks.classify_table(info["file"], info["sheet"], info["headers"])
    return (res["side"], res["confidence"]) if not res["fallback"] else None


def _topic(text: str, others: list[str]) -> tuple[str, float] | None:
    res = tasks.map_question_topic(text, "intern", others)
    return (res["topic"], res["confidence"]) if not res["fallback"] else None


def ingest_resolvers() -> Resolvers:
    """Решатели для спорных случаев загрузки; без LLM — пустые (работают правила)."""
    if not enabled():
        return Resolvers()
    return Resolvers(side=_side, topic=_topic)
