"""Пароли, сессии, CSRF и ограничение попыток входа."""

import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.settings import get_settings

SESSION_COOKIE = "pulse_session"
CSRF_COOKIE = "pulse_csrf"
CSRF_HEADER = "x-csrf-token"

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Возвращает argon2-хеш пароля."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Проверяет пароль по хешу."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def make_session_token(user_id: int) -> str:
    """Создаёт подписанный JWT сессии."""
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(hours=settings.session_hours)}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def read_session_token(token: str) -> int | None:
    """Возвращает ID пользователя из токена или None, если токен недействителен."""
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def new_token(nbytes: int = 24) -> str:
    """Случайный токен для приглашений и CSRF."""
    return secrets.token_urlsafe(nbytes)


class LoginRateLimiter:
    """Не больше N попыток входа в минуту на одну почту."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        """Регистрирует попытку и сообщает, разрешена ли она."""
        now = time.monotonic()
        q = self._hits[key.lower()]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    def reset(self) -> None:
        """Очищает счётчики (для тестов)."""
        self._hits.clear()


login_limiter = LoginRateLimiter()


def make_survey_token(participant_id: int, days: int = 45) -> str:
    """Ссылка на анкету без входа: подписанный токен участника."""
    now = datetime.now(UTC)
    payload = {"pid": participant_id, "kind": "survey", "iat": now, "exp": now + timedelta(days=days)}
    return jwt.encode(payload, get_settings().secret_key, algorithm="HS256")


def read_survey_token(token: str) -> int | None:
    """ID участника из токена анкеты или None."""
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
        return int(payload["pid"]) if payload.get("kind") == "survey" else None
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
