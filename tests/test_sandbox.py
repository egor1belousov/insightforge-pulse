from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.settings import get_settings
from app.db.models import Organization, User
from app.db.session import SessionLocal
from app.main import app
from app.seed import seed_accounts
from app.services import sandbox


@pytest.fixture
def sandboxes(monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_sandbox", True)
    with SessionLocal() as db:
        seed_accounts(db)


def demo_login(c: TestClient, email: str) -> dict:
    r = c.post("/api/auth/login", json={"email": email, "password": get_settings().demo_password})
    assert r.status_code == 200, r.text
    return r.json()


def org_of(user_id: int) -> int:
    with SessionLocal() as db:
        return db.get(User, user_id).organization_id


def test_each_browser_gets_own_sandbox(sandboxes) -> None:
    a, b = TestClient(app), TestClient(app)
    ua = demo_login(a, "hr@pulse.demo")
    ub = demo_login(b, "hr@pulse.demo")
    assert ua["role"] == ub["role"] == "hr"
    assert org_of(ua["id"]) != org_of(ub["id"])
    with SessionLocal() as db:
        tmpl = db.query(User).filter(User.email == "hr@pulse.demo").one().organization_id
    assert tmpl not in (org_of(ua["id"]), org_of(ub["id"]))
    # смена роли в том же браузере — та же песочница
    ui = demo_login(a, "intern@pulse.demo")
    assert ui["role"] == "intern" and org_of(ui["id"]) == org_of(ua["id"])


def test_sandbox_has_full_demo_data(sandboxes) -> None:
    c = TestClient(app)
    demo_login(c, "hr@pulse.demo")
    pairs = c.get("/api/pairs").json()
    assert len(pairs) >= 5


def test_role_button_switches_account_when_logged_in(sandboxes) -> None:
    c = TestClient(app)
    demo_login(c, "hr@pulse.demo")
    r = c.get("/demo/intern", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/me"
    assert c.get("/api/auth/me").json()["role"] == "intern"
    r = c.get("/demo/hr", follow_redirects=False)
    assert r.headers["location"] == "/dashboard"
    assert c.get("/api/auth/me").json()["role"] == "hr"


def test_pool_is_used_and_old_sandboxes_removed(sandboxes) -> None:
    with SessionLocal() as db:
        ready = sandbox.build(db, use_llm=False)
        ready_id = ready.id
    c = TestClient(app)
    u = demo_login(c, "lead@pulse.demo")
    assert org_of(u["id"]) == ready_id
    with SessionLocal() as db:
        org = db.get(Organization, ready_id)
        org.sandbox_seen_at = datetime.utcnow() - timedelta(hours=get_settings().demo_sandbox_hours + 1)
        db.commit()
        assert sandbox.cleanup(db) == 1
        assert db.get(Organization, ready_id) is None
    assert c.get("/api/auth/me").status_code == 401
