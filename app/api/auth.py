"""Регистрация, вход, приглашения."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import HR_ONLY, current_user, require_role
from app.core.security import CSRF_COOKIE, SESSION_COOKIE, login_limiter, make_session_token, new_token
from app.core.settings import get_settings
from app.db.models import Invite, Participant, User
from app.db.session import get_db
from app.services import accounts, sandbox

router = APIRouter(prefix="/api/auth", tags=["вход"])


class RegisterIn(BaseModel):
    name: str
    email: str
    password: str
    organization: str
    program: str


class LoginIn(BaseModel):
    email: str
    password: str


class InviteIn(BaseModel):
    email: str
    role: str
    external_id: str | None = None


class AcceptIn(BaseModel):
    name: str
    password: str


def start_session(resp: Response, user: User) -> None:
    """Ставит cookie сессии и CSRF."""
    secure = not get_settings().is_dev
    hours = get_settings().session_hours * 3600
    resp.set_cookie(
        SESSION_COOKIE,
        make_session_token(user.id),
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=hours,
    )
    resp.set_cookie(CSRF_COOKIE, new_token(16), httponly=False, samesite="lax", secure=secure, max_age=hours)


def demo_session(request: Request, resp: Response, db: Session, role: str) -> User:
    """Вход в демо: аккаунт роли в песочнице этого браузера."""
    org = sandbox.claim(db, request.cookies.get(sandbox.SANDBOX_COOKIE))
    user = sandbox.user_for(db, org, role)
    start_session(resp, user)
    resp.set_cookie(
        sandbox.SANDBOX_COOKIE,
        org.sandbox_token or "",
        httponly=True,
        samesite="lax",
        secure=not get_settings().is_dev,
        max_age=get_settings().demo_sandbox_hours * 3600,
    )
    return user


def user_out(db: Session, user: User) -> dict:
    """Публичные сведения о пользователе."""
    part = db.query(Participant).filter(Participant.user_id == user.id).first()
    return {
        "id": user.id,
        "email": sandbox.public_email(user.email),
        "name": user.name,
        "role": user.role,
        "program_id": user.program_id,
        "external_id": part.external_id if part else None,
    }


def _bad(e: accounts.AccountError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.post("/register")
def register(data: RegisterIn, resp: Response, db: Session = Depends(get_db)) -> dict:
    try:
        user = accounts.register_hr(db, **data.model_dump())
    except accounts.AccountError as e:
        raise _bad(e) from e
    start_session(resp, user)
    return user_out(db, user)


@router.post("/login")
def login(data: LoginIn, request: Request, resp: Response, db: Session = Depends(get_db)) -> dict:
    if not login_limiter.allow(data.email, get_settings().login_attempts_per_minute):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много попыток. Подождите минуту.")
    try:
        user = accounts.authenticate(db, data.email, data.password)
    except accounts.AccountError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e)) from e
    if sandbox.enabled() and user.email in sandbox.DEMO_EMAILS:
        user = demo_session(request, resp, db, user.role)
    else:
        start_session(resp, user)
    return user_out(db, user)


@router.post("/logout")
def logout(resp: Response) -> dict:
    resp.delete_cookie(SESSION_COOKIE)
    resp.delete_cookie(CSRF_COOKIE)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return user_out(db, user)


@router.post("/invites")
def create_invite(
    data: InviteIn, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    try:
        inv = accounts.create_invite(
            db, by=user, email=data.email, role=data.role, external_id=data.external_id
        )
    except accounts.AccountError as e:
        raise _bad(e) from e
    return {
        "id": inv.id,
        "email": inv.email,
        "role": inv.role,
        "external_id": inv.external_id,
        "link": f"/invite/{inv.token}",
    }


@router.get("/invites")
def list_invites(user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(Invite).filter(Invite.organization_id == user.organization_id).order_by(Invite.id.desc())
    return [
        {
            "id": i.id,
            "email": i.email,
            "role": i.role,
            "external_id": i.external_id,
            "used": i.used_at is not None,
            "expires_at": i.expires_at.isoformat(),
            "link": f"/invite/{i.token}",
        }
        for i in rows
    ]


@router.get("/invites/{token}")
def invite_info(token: str, db: Session = Depends(get_db)) -> dict:
    try:
        info = accounts.invite_info(db, token)
    except accounts.AccountError as e:
        raise _bad(e) from e
    return info.__dict__


@router.post("/invites/{token}/accept")
def accept_invite(token: str, data: AcceptIn, resp: Response, db: Session = Depends(get_db)) -> dict:
    try:
        user = accounts.accept_invite(db, token, name=data.name, password=data.password)
    except accounts.AccountError as e:
        raise _bad(e) from e
    start_session(resp, user)
    return user_out(db, user)
