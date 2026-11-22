from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import csrf_headers

PWD = "очень-надёжный-пароль"


def register(c: TestClient, email: str = "hr@pulse.demo") -> dict:
    r = c.post(
        "/api/auth/register",
        json={
            "name": "Анна",
            "email": email,
            "password": PWD,
            "organization": "МГТС",
            "program": "Стажировка 2026",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def invite(c: TestClient, email: str, role: str, ext: str | None = None) -> str:
    r = c.post(
        "/api/auth/invites", json={"email": email, "role": role, "external_id": ext}, headers=csrf_headers(c)
    )
    assert r.status_code == 200, r.text
    return r.json()["link"].rsplit("/", 1)[1]


def accept(token: str, name: str = "Иван") -> TestClient:
    c = TestClient(app)
    r = c.post(f"/api/auth/invites/{token}/accept", json={"name": name, "password": PWD})
    assert r.status_code == 200, r.text
    return c


def make_all_roles() -> dict[str, TestClient]:
    hr = TestClient(app)
    register(hr)
    lead = accept(invite(hr, "lead@pulse.demo", "lead"))
    mentor = accept(invite(hr, "mentor@pulse.demo", "mentor", "Н-204"))
    intern = accept(invite(hr, "intern@pulse.demo", "intern", "С-104"))
    return {"hr": hr, "lead": lead, "mentor": mentor, "intern": intern}


def test_register_creates_hr_program_and_session(client: TestClient) -> None:
    me = register(client)
    assert me["role"] == "hr" and me["program_id"]
    assert client.get("/api/auth/me").json()["email"] == "hr@pulse.demo"


def test_register_rejects_short_password(client: TestClient) -> None:
    r = client.post(
        "/api/auth/register",
        json={"name": "А", "email": "a@pulse.demo", "password": "123", "organization": "О", "program": "П"},
    )
    assert r.status_code == 400
    assert "не короче" in r.json()["detail"]


def test_invite_flow_binds_participant_and_is_one_time(client: TestClient) -> None:
    register(client)
    token = invite(client, "intern@pulse.demo", "intern", "С-104")
    info = client.get(f"/api/auth/invites/{token}").json()
    assert info["role"] == "intern" and info["external_id"] == "С-104"
    c = accept(token)
    assert c.get("/api/auth/me").json()["external_id"] == "С-104"
    again = TestClient(app).post(f"/api/auth/invites/{token}/accept", json={"name": "X", "password": PWD})
    assert again.status_code == 400


def test_login_and_rate_limit(client: TestClient) -> None:
    register(client)
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"email": "hr@pulse.demo", "password": PWD}).status_code == 200
    for _ in range(4):
        c.post("/api/auth/login", json={"email": "hr@pulse.demo", "password": "wrong-password"})
    assert c.post("/api/auth/login", json={"email": "hr@pulse.demo", "password": PWD}).status_code == 429


def test_csrf_required_for_changes(client: TestClient) -> None:
    register(client)
    r = client.post("/api/auth/invites", json={"email": "x@pulse.demo", "role": "intern"})
    assert r.status_code == 403


def test_unauthenticated_is_401() -> None:
    assert TestClient(app).get("/api/pairs").status_code == 401


ENDPOINTS = [
    ("get", "/api/pairs", {"hr": 200, "lead": 200, "mentor": 403, "intern": 403}),
    ("get", "/api/participants", {"hr": 200, "lead": 200, "mentor": 403, "intern": 403}),
    ("get", "/api/auth/invites", {"hr": 200, "lead": 403, "mentor": 403, "intern": 403}),
    ("post", "/api/programs", {"hr": 200, "lead": 403, "mentor": 403, "intern": 403}),
    ("post", "/api/participants", {"hr": 200, "lead": 403, "mentor": 403, "intern": 403}),
]


def test_role_matrix() -> None:
    clients = make_all_roles()
    for role, c in clients.items():
        for method, url, expected in ENDPOINTS:
            body = (
                {"name": f"Поток {role}"}
                if url == "/api/programs"
                else {"external_id": f"С-9{role[:1]}", "side": "intern"}
            )
            r = (
                getattr(c, method)(url, json=body, headers=csrf_headers(c))
                if method == "post"
                else c.get(url)
            )
            assert r.status_code == expected[role], (role, url, r.status_code, r.text)
