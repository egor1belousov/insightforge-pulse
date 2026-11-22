"""Зависимости FastAPI: текущий пользователь, проверка ролей и CSRF."""

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.security import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE, read_session_token
from app.db.models import Participant, User
from app.db.session import get_db

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def current_user_optional(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Пользователь из cookie сессии или None."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    user_id = read_session_token(token)
    if user_id is None:
        return None
    return db.get(User, user_id)


def check_csrf(request: Request) -> None:
    """Проверка CSRF для изменяющих запросов: заголовок или поле формы совпадает с cookie."""
    if request.method in SAFE_METHODS:
        return
    cookie = request.cookies.get(CSRF_COOKIE)
    sent = request.headers.get(CSRF_HEADER)
    if not cookie or not sent or cookie != sent:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Сессия устарела. Обновите страницу и повторите.")


def current_user(request: Request, user: User | None = Depends(current_user_optional)) -> User:
    """Текущий пользователь; без входа — 401."""
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нужно войти в систему.")
    check_csrf(request)
    return user


def require_role(*roles: str) -> Callable[..., User]:
    """Зависимость: пропускает только пользователей с указанными ролями.

    Args:
        *roles: Разрешённые роли (hr, lead, mentor, intern).

    Returns:
        Функция-зависимость, возвращающая пользователя.
    """

    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "У вашей роли нет доступа к этому разделу.")
        return user

    return dep


def own_participant(db: Session, user: User) -> Participant | None:
    """Участник (сторона пары), привязанный к пользователю."""
    return db.query(Participant).filter(Participant.user_id == user.id).first()


STAFF = ("hr", "lead")
HR_ONLY = ("hr",)
SIDE_ROLES = ("mentor", "intern")
