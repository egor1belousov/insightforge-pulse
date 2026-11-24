"""Точка входа приложения «Пульс адаптации»."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import auth, dashboard, extra, forms, imports, integrations, learn, llm, programs
from app.core.settings import get_settings
from app.db.session import engine
from app.web import pages

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Запускает опрос форм, Telegram-бота, автонапоминания и запас песочниц демо."""
    from app.services import sandbox
    from app.services.forms import connectors

    stop = sandbox.start_worker() if sandbox.enabled() and settings.demo_pool_size > 0 else None
    from app.services import reminders, telegram

    stops = [telegram.start()] if settings.telegram_bot else []
    stops.append(reminders.start())

    task = asyncio.create_task(connectors.poller())
    stop = sandbox.start_worker() if sandbox.enabled() and settings.demo_pool_size > 0 else None
    from app.services import reminders, telegram

    stops = [telegram.start()] if settings.telegram_bot else []
    stops.append(reminders.start())
    yield
    if task:
        task.cancel()
    if stop:
        stop.set()
    for ev in stops:
        ev.set()


app = FastAPI(
    lifespan=lifespan,
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
app.include_router(forms.router)
app.include_router(dashboard.router)
app.include_router(extra.router)
app.include_router(learn.router)
app.include_router(integrations.router)
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
