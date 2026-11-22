"""Точка входа приложения «Пульс адаптации»."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import auth, imports, llm, programs
from app.core.settings import get_settings
from app.db.session import engine
from app.web import pages

settings = get_settings()

app = FastAPI(
    title="Пульс адаптации",
    version="0.1.0",
    docs_url="/docs" if settings.is_dev else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.is_dev else None,
)
app.include_router(auth.router)
app.include_router(programs.router)
app.include_router(imports.router)
app.include_router(llm.router)
app.include_router(pages.router)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "web" / "static"), name="static")


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
