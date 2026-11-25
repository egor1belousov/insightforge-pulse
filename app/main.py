"""Точка входа приложения «Пульс адаптации»."""

import asyncio
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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
STATIC = Path(__file__).parent / "web" / "static"
CSP = (
    "default-src 'self'; script-src 'self' 'nonce-{nonce}'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; worker-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)


class WebHeaders:
    """Заголовки безопасности и кеша, HEAD для страниц.

    Страницам — CSP с одноразовым nonce для встроенных скриптов шаблонов; всем ответам — запрет
    встраивания во фрейм; статике с версией в адресе — долгий кеш. HEAD к страницам отвечает как GET без тела.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        nonce = secrets.token_urlsafe(16)
        scope.setdefault("state", {})["csp_nonce"] = nonce
        path, query = scope["path"], scope.get("query_string", b"")
        head = scope["method"] == "HEAD" and not path.startswith("/api/")
        if head:
            scope = {**scope, "method": "GET"}

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                h = MutableHeaders(scope=message)
                if h.get("content-type", "").startswith("text/html"):
                    h["Content-Security-Policy"] = CSP.format(nonce=nonce)
                h["X-Frame-Options"] = "DENY"
                if path.startswith("/static/"):
                    h["Cache-Control"] = (
                        "public, max-age=31536000, immutable" if b"v=" in query else "public, max-age=86400"
                    )
            elif head and message["type"] == "http.response.body":
                message = {**message, "body": b""}
            await send(message)

        await self.app(scope, receive, send_with_headers)


app.add_middleware(WebHeaders)


@app.exception_handler(StarletteHTTPException)
async def not_found_page(request: Request, exc: StarletteHTTPException):
    """Несуществующая страница — HTML со ссылкой на главную; для API — прежний JSON."""
    if exc.status_code == 404 and not request.url.path.startswith(("/api/", "/static/")):
        return pages.render(request, "404.html", status_code=404)
    return await http_exception_handler(request, exc)


@app.exception_handler(DataError)
async def too_long(_: Request, __: DataError) -> JSONResponse:
    """Значение не помещается в столбец базы — понятный отказ вместо 500."""
    return JSONResponse(
        {"detail": "Слишком длинное или неверное значение. Сократите текст и повторите."}, 400
    )


@app.exception_handler(IntegrityError)
async def conflict(_: Request, __: IntegrityError) -> JSONResponse:
    """Повторная или одновременная отправка тех же данных."""
    return JSONResponse({"detail": "Такая запись уже есть. Обновите страницу."}, 409)


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
app.mount("/static", StaticFiles(directory=STATIC), name="static")

ROBOTS = (
    "User-agent: *\nAllow: /$\nAllow: /login\nAllow: /register\nDisallow: /\nSitemap: {url}/sitemap.xml\n"
)


@app.get("/robots.txt", include_in_schema=False)
def robots() -> PlainTextResponse:
    return PlainTextResponse(ROBOTS.format(url=settings.public_url.rstrip("/")))


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap() -> PlainTextResponse:
    url = settings.public_url.rstrip("/")
    items = "".join(f"<url><loc>{url}{p}</loc></url>" for p in ("/", "/login", "/register"))
    body = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</urlset>'
    return PlainTextResponse(body, media_type="application/xml")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(STATIC / "icons" / "favicon.svg", media_type="image/svg+xml")


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
