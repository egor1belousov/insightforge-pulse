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
from app.services.sandbox import public_email

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
ASSET_V = "7"


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
        "email": public_email(user.email),
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


@router.get("/demo/{role}")
def demo_enter(role: str, request: Request, db: Session = Depends(get_db)) -> Response:
    """Вход в демо одной кнопкой: роль в песочнице этого браузера, даже если уже вошли под другой."""
    from app.api.auth import demo_session
    from app.services import sandbox

    if not get_settings().demo_mode or role not in sandbox.DEMO_ROLES:
        return RedirectResponse("/login", status_code=303)
    if not sandbox.enabled():
        return RedirectResponse(f"/login?as={role}", status_code=303)
    resp = RedirectResponse("/", status_code=303)
    user = demo_session(request, resp, db, role)
    resp.headers["location"] = home_for(user)
    return resp


@router.get("/import")
def import_page(
    request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user_optional)
) -> Response:
    return app_page(request, db, user, "app/import.html", "forms", ("hr",))


@router.get("/survey/{token}")
def survey_page(request: Request, token: str) -> Response:
    return render(request, "survey.html", token=token)


@router.get("/dashboard")
def dashboard_page(
    request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user_optional)
) -> Response:
    return app_page(
        request, db, user, "app/dashboard.html", "dash", ("hr", "lead"), demo=get_settings().demo_mode
    )


@router.get("/pairs")
def pairs_page(
    request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user_optional)
) -> Response:
    return app_page(request, db, user, "app/pairs.html", "pairs", ("hr", "lead"))


LANDING_ROLES = [
    {
        "key": "hr",
        "tag": "ВИДИТ ВСЁ",
        "label": "HR-партнёр",
        "short": "HR",
        "desc": "Программа и пары, дашборд с конструктором, анкеты и рассылки, курсы и тесты, настройки.",
    },
    {
        "key": "lead",
        "tag": "ВИДИТ ВСЁ, НЕ НАЗНАЧАЕТ",
        "label": "Руководитель программы",
        "short": "руководитель",
        "desc": "Картина программы, пары, отчёт, справочник по методике, ИИ-ассистент.",
    },
    {
        "key": "mentor",
        "tag": "ТОЛЬКО СВОЯ ПАРА",
        "label": "Наставник",
        "short": "наставник",
        "desc": "Своя анкета, свои оценки, темы для разговора, прямой запрос к HR, памятки.",
    },
    {
        "key": "intern",
        "tag": "ТОЛЬКО СВОЯ СТАЖИРОВКА",
        "label": "Стажёр",
        "short": "стажёр",
        "desc": "Своя анкета, прогресс, курсы и тесты, прямой запрос к HR, ассистент.",
    },
]


@router.get("/")
def landing(request: Request) -> Response:
    return render(request, "landing.html", roles=LANDING_ROLES, demo=get_settings().demo_mode)


@router.get("/register")
def register_page(request: Request, user: User | None = Depends(current_user_optional)) -> Response:
    if user is not None:
        return RedirectResponse(home_for(user), status_code=303)
    return render(request, "auth/register.html")


@router.get("/invite/{token}")
def invite_page(request: Request, token: str) -> Response:
    return render(request, "auth/invite.html", token=token)


def _section(path: str, template: str, active: str, roles: tuple[str, ...], title: str):
    def page(
        request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user_optional)
    ) -> Response:
        return app_page(
            request, db, user, template, active, roles, page_title=title, demo=get_settings().demo_mode
        )

    router.add_api_route(path, page, methods=["GET"], include_in_schema=False)


_section("/program", "app/program.html", "prog", ("hr",), "Программа")
_section("/forms", "app/forms.html", "forms", ("hr",), "Анкеты")
_section("/me", "app/me.html", "me", ("mentor", "intern"), "Моя стажировка")
_section("/settings", "app/settings.html", "settings", ("hr",), "Настройки")
_section("/learn", "app/learn.html", "learn", ("hr", "lead", "mentor", "intern"), "Обучение")
