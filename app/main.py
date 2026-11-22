"""Точка входа приложения «Пульс адаптации»."""

from fastapi import FastAPI
from sqlalchemy import text

from app.core.settings import get_settings
from app.db.session import engine

settings = get_settings()

app = FastAPI(
    title="Пульс адаптации",
    version="0.1.0",
    docs_url="/docs" if settings.is_dev else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.is_dev else None,
)


@app.get("/health", tags=["служебное"])
def health() -> dict[str, str]:
    """Проверка, что приложение и база отвечают."""
    db_status = "ok"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_status = "недоступна"
    return {"status": "ok", "db": db_status}
