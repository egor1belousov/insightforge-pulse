"""Серверные страницы интерфейса (Jinja2). Данные страницы получают из API."""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.deps import current_user_optional, own_participant
from app.core.settings import get_settings
from app.db.models import User
from app.db.session import get_db

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))
router = APIRouter(include_in_schema=False)

ROLE_LABEL = {"hr": "HR-партнёр", "lead": "Руководитель программы", "mentor": "Наставник", "intern": "Стажёр"}
ROLE_SCOPE = {
    "hr": "Все пары, действия, анкеты, обучение",
    "lead": "Все пары, без назначений",
    "mentor": "Только своя пара, без ответов стажёра",
    "intern": "Только своя стажировка, без ответов наставника",
}
NAV = {
    "hr": [
        ("dash", "Дашборд", "/dashboard"),
        ("pairs", "Пары", "/pairs"),
        ("prog", "Программа", "/program"),
        ("forms", "Анкеты", "/forms"),
        ("learn", "Обучение", "/learn"),
    ],
    "lead": [("dash", "Дашборд", "/dashboard"), ("pairs", "Пары", "/pairs"), ("learn", "Обучение", "/learn")],
    "mentor": [("me", "Моя пара", "/me"), ("learn", "Обучение", "/learn")],
    "intern": [("me", "Моя стажировка", "/me"), ("learn", "Обучение", "/learn")],
}
DEMO_ACCOUNTS = [
    {"email": "hr@pulse.demo", "label": "HR-партнёр", "scope": "Все пары, действия, анкеты, обучение"},
    {"email": "lead@pulse.demo", "label": "Руководитель программы", "scope": "Все пары, без назначений"},
    {
        "email": "mentor@pulse.demo",
        "label": "Наставник Н-204",
        "scope": "Только своя пара, без ответов стажёра",
    },
    {
        "email": "intern@pulse.demo",
        "label": "Стажёр С-104",
        "scope": "Только своя стажировка, без ответов наставника",
    },
]
ASSET_V = "1"


def home_for(user: User) -> str:
    """Стартовая страница роли."""
    return "/dashboard" if user.role in ("hr", "lead") else "/me"


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    """Рендер шаблона с общим контекстом."""
    return templates.TemplateResponse(request, name, {"asset_v": ASSET_V, **ctx})


def app_page(
    request: Request,
    db: Session,
    user: User | None,
    template: str,
    active: str,
    roles: tuple[str, ...],
    **ctx,
) -> Response:
    """Страница приложения: проверка входа и роли, верхняя панель."""
    if user is None:
        return RedirectResponse(f"/login?next={request.url.path}", status_code=303)
    if user.role not in roles:
        return RedirectResponse(home_for(user), status_code=303)
    part = own_participant(db, user)
    words = user.name.split()
    initials = (
        "".join(w[0] for w in words[:2]).upper()
        if user.role in ("hr", "lead")
        else ("Н" if user.role == "mentor" else "С")
    )
    me = {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "program_id": user.program_id,
        "role_label": ROLE_LABEL[user.role],
        "scope": ROLE_SCOPE[user.role],
        "initials": initials,
        "short": part.external_id if part else ("HR" if user.role == "hr" else "Руководитель"),
        "external_id": part.external_id if part else None,
    }
    nav = [{"key": k, "label": label, "url": url, "badge": None} for k, label, url in NAV[user.role]]
    return render(request, template, me=me, nav=nav, active=active, home_url=home_for(user), **ctx)


@router.get("/login")
def login_page(request: Request, user: User | None = Depends(current_user_optional)) -> Response:
    if user is not None:
        return RedirectResponse(home_for(user), status_code=303)
    s = get_settings()
    return render(
        request,
        "auth/login.html",
        demo=s.demo_mode,
        demo_accounts=DEMO_ACCOUNTS,
        demo_password=s.demo_password if s.demo_mode else "",
    )


@router.get("/import")
def import_page(
    request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user_optional)
) -> Response:
    return app_page(request, db, user, "app/import.html", "forms", ("hr",))
