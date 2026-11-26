"""Серверные страницы интерфейса (Jinja2). Данные страницы получают из API."""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.deps import current_user_optional, own_participant
from app.core.settings import get_settings
from app.db.models import Program, User
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
# иконки нижней панели вкладок на телефоне (SVG-контур 24×24)
TAB_ICONS = {
    "dash": '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/>'
    '<rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
    "pairs": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0113 0"/><circle cx="17" cy="9" r="2.8"/>'
    '<path d="M15.5 14.5a5.5 5.5 0 016 5.5"/>',
    "prog": '<path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5"/>',
    "forms": '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h4"/>',
    "learn": '<path d="M4 5a2 2 0 012-2h13v16H6a2 2 0 00-2 2V5z"/><path d="M4 19a2 2 0 012-2h13"/>',
    "me": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0116 0"/>',
}
DEMO_ACCOUNTS = [
    {"email": "hr@pulse.demo", "label": "HR-партнёр", "scope": "Все пары, действия, анкеты, обучение"},
    {"email": "lead@pulse.demo", "label": "Руководитель программы", "scope": "Все пары, без назначений"},
    {
        "email": "mentor@pulse.demo",
        "label": "Наставник Н-006",
        "scope": "Только своя пара, без ответов стажёра",
    },
    {
        "email": "intern@pulse.demo",
        "label": "Стажёр СТ-006",
        "scope": "Только своя стажировка, без ответов наставника",
    },
]
ASSET_V = "24"


def home_for(user: User) -> str:
    """Стартовая страница роли."""
    return "/dashboard" if user.role in ("hr", "lead") else "/me"


def render(request: Request, name: str, status_code: int = 200, **ctx) -> HTMLResponse:
    """Рендер шаблона с общим контекстом: версия статики, nonce для встроенных скриптов, адрес сайта."""
    base = {
        "asset_v": ASSET_V,
        "csp_nonce": getattr(request.state, "csp_nonce", ""),
        "public_url": get_settings().public_url.rstrip("/"),
    }
    return templates.TemplateResponse(request, name, {**base, **ctx}, status_code=status_code)


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
        "program_name": (db.get(Program, user.program_id).name if user.program_id else "")
        if user.role in ("hr", "lead")
        else "",
        "demo": is_demo_user(db, user),
    }
    short = {"Моя стажировка": "Стажировка", "Моя пара": "Пара"}
    nav = [
        {
            "key": k,
            "label": label,
            "short": short.get(label, label),
            "url": url,
            "badge": None,
            "icon": TAB_ICONS[k],
        }
        for k, label, url in NAV[user.role]
    ]
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


def is_demo_user(db: Session, user: User) -> bool:
    """Пользователь из демо: песочница или основная демо-организация."""
    from app.db.models import Organization
    from app.services import integrations

    org = db.get(Organization, user.organization_id)
    return bool(org and (org.sandbox_token or org.id == integrations.demo_template(db)))


@router.get("/")
def landing(
    request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user_optional)
) -> Response:
    # рабочий аккаунт не должен незаметно смениться демо-аккаунтом
    real = user is not None and not is_demo_user(db, user)
    return render(
        request,
        "landing.html",
        roles=LANDING_ROLES,
        demo=get_settings().demo_mode,
        real_user={"name": user.name, "home": home_for(user)} if real else None,
    )


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
