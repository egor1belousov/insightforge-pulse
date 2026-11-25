"""Исправления по итогам тестирования стенда: граничные данные, отдача страниц, заголовки."""

import pytest

from app.db.models import Organization, User
from app.db.session import SessionLocal
from app.services import accounts

REG = {
    "name": "Анна",
    "email": "hr@pulse.demo",
    "password": "очень-надёжный-пароль",
    "organization": "МГТС",
    "program": "П",
}


@pytest.mark.parametrize("field", ["name", "organization", "program"])
def test_long_registration_fields_are_rejected(client, field):
    r = client.post("/api/auth/register", json={**REG, field: "Я" * 300})
    assert r.status_code == 400
    assert "не больше 200 символов" in r.json()["detail"]


def test_long_email_and_password_are_rejected(client):
    assert (
        client.post("/api/auth/register", json={**REG, "email": "a" * 250 + "@pulse.demo"}).status_code == 400
    )
    assert client.post("/api/auth/register", json={**REG, "password": "x" * 500}).status_code == 400


def test_concurrent_duplicate_email_is_a_clear_error():
    db = SessionLocal()
    try:
        org = Organization(name="О")
        db.add(org)
        db.flush()
        db.add(User(email="twin@pulse.demo", password_hash="x", name="Т", role="hr", organization_id=org.id))
        db.commit()
        db.add(User(email="twin@pulse.demo", password_hash="x", name="Т", role="hr", organization_id=org.id))
        with pytest.raises(accounts.AccountError, match="уже зарегистрирована"):
            accounts._commit_user(db)
    finally:
        db.close()


def test_unknown_page_is_html_404(client):
    r = client.get("/qa_missing_page")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("text/html")
    assert "На главную" in r.text
    api = client.get("/api/qa_missing")
    assert api.status_code == 404 and api.json() == {"detail": "Not Found"}


def test_head_for_pages(client):
    r = client.head("/")
    assert r.status_code == 200 and r.content == b""
    assert client.head("/login").status_code == 200


def test_security_headers_and_nonce(client):
    r = client.get("/login")
    csp = r.headers["content-security-policy"]
    nonce = csp.split("'nonce-")[1].split("'")[0]
    assert "frame-ancestors 'none'" in csp
    assert f'<script nonce="{nonce}">' in r.text
    assert r.headers["x-frame-options"] == "DENY"
    assert client.get("/login").headers["content-security-policy"] != csp  # nonce одноразовый


def test_static_cache(client):
    assert "immutable" in client.get("/static/css/app.css?v=1").headers["cache-control"]
    assert client.get("/static/icons/favicon.svg").headers["cache-control"] == "public, max-age=86400"


def test_seo_files_and_meta(client):
    assert "Sitemap:" in client.get("/robots.txt").text
    assert "<loc>" in client.get("/sitemap.xml").text
    assert client.get("/favicon.ico").headers["content-type"].startswith("image/svg")
    page = client.get("/").text
    for tag in ('name="description"', 'property="og:title"', 'property="og:image"', 'rel="canonical"'):
        assert tag in page


def test_events_stream_checks_login_without_holding_session(client):
    assert client.get("/api/events").status_code == 401
