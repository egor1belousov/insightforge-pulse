"""Помощники распознавания на основе LLM (подключаются на этапе 4)."""

from app.services.ingest.pipeline import Resolvers


def ingest_resolvers() -> Resolvers:
    """Решатели для спорных случаев загрузки; без LLM — пустые (работают правила)."""
    return Resolvers()
