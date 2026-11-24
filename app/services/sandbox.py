"""Песочницы демо: каждый браузер получает свою копию демо-организации.

Правки одного посетителя (дашборд, пары, анкеты, курсы) не видны следующему. Копии
собираются заранее в фоне (запас `demo_pool_size`), поэтому вход занимает доли секунды.
Песочница живёт `demo_sandbox_hours` часов с последнего входа, затем удаляется.
"""

import logging
import threading
import time
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.security import new_token
from app.core.settings import get_settings
from app.db.models import Organization, User
from app.db.session import SessionLocal

log = logging.getLogger(__name__)

SANDBOX_COOKIE = "pulse_sandbox"
DEMO_ROLES = {
    "hr": "hr@pulse.demo",
    "lead": "lead@pulse.demo",
    "mentor": "mentor@pulse.demo",
    "intern": "intern@pulse.demo",
}
DEMO_EMAILS = {email: role for role, email in DEMO_ROLES.items()}

_lock = threading.Lock()
_refill = threading.Event()


def enabled() -> bool:
    """Песочницы включены: демо-режим и флаг `demo_sandbox`."""
    s = get_settings()
    return s.demo_mode and s.demo_sandbox


def _users(token: str) -> list[tuple[str, str, str, str | None]]:
    from app.seed import DEMO_USERS

    return [(email.replace("@", f"+{token}@"), name, role, ext) for email, name, role, ext in DEMO_USERS]


def build(db: Session, use_llm: bool) -> Organization:
    """Собирает одну песочницу: организация, аккаунты, анкеты за 6 месяцев, курсы."""
    from app.seed import create_org, seed_demo_data, seed_learning

    token = new_token(12).replace("-", "").replace("_", "")[:16].lower()
    prog = create_org(db, users=_users(token), sandbox_token=token)
    seed_demo_data(db, prog, use_llm=use_llm)
    seed_learning(db, prog)
    return db.get(Organization, prog.organization_id)


def _live(db: Session, token: str | None) -> Organization | None:
    if not token:
        return None
    org = db.query(Organization).filter(Organization.sandbox_token == token).first()
    return org if org and org.sandbox_claimed_at else None


def claim(db: Session, token: str | None) -> Organization:
    """Песочница браузера: прежняя, если ещё жива, иначе готовая из запаса или новая."""
    now = datetime.utcnow()
    with _lock:
        org = _live(db, token)
        if org is None:
            org = (
                db.query(Organization)
                .filter(Organization.sandbox_token.is_not(None), Organization.sandbox_claimed_at.is_(None))
                .order_by(Organization.id)
                .first()
            )
            if org is None:
                org = build(db, use_llm=False)
            org.sandbox_claimed_at = now
        org.sandbox_seen_at = now
        db.commit()
    _refill.set()
    return org


def user_for(db: Session, org: Organization, role: str) -> User:
    """Демо-аккаунт нужной роли внутри песочницы."""
    return (
        db.query(User)
        .filter(User.organization_id == org.id, User.role == role, User.email.like(f"{role}+%"))
        .one()
    )


def cleanup(db: Session) -> int:
    """Удаляет песочницы, в которые не входили дольше срока."""
    edge = datetime.utcnow() - timedelta(hours=get_settings().demo_sandbox_hours)
    old = (
        db.query(Organization)
        .filter(Organization.sandbox_claimed_at.is_not(None), Organization.sandbox_seen_at < edge)
        .all()
    )
    for org in old:
        db.delete(org)
    db.commit()
    return len(old)


def refill(db: Session) -> None:
    """Достраивает запас готовых песочниц."""
    want = get_settings().demo_pool_size
    while True:
        ready = (
            db.query(Organization)
            .filter(Organization.sandbox_token.is_not(None), Organization.sandbox_claimed_at.is_(None))
            .count()
        )
        if ready >= want:
            return
        build(db, use_llm=get_settings().llm_enabled)


def _worker(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            with SessionLocal() as db:
                cleanup(db)
                refill(db)
        except Exception:  # noqa: BLE001 — фоновая задача не должна падать навсегда
            log.exception("песочницы демо: ошибка фоновой задачи")
            time.sleep(30)
        _refill.wait(600)
        _refill.clear()


def start_worker() -> threading.Event:
    """Фоновый поток: держит запас песочниц и удаляет старые."""
    stop = threading.Event()
    threading.Thread(target=_worker, args=(stop,), name="demo-sandbox", daemon=True).start()
    return stop
