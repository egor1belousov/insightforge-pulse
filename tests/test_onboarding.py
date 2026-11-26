from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import csrf_headers


def test_invited_mentor_visible_to_hr_with_answers(client) -> None:
    hr = TestClient(app)
    hr.post(
        "/api/auth/register",
        json={
            "name": "Ира",
            "email": "ira@example.com",
            "password": "Passw0rd!42",
            "organization": "Тест",
            "program": "Поток 1",
        },
    )
    inv = hr.post(
        "/api/auth/invites", json={"email": "m@example.com", "role": "mentor"}, headers=csrf_headers(hr)
    ).json()
    m = TestClient(app)
    m.post(
        "/api/auth/invites/" + inv["link"].split("/")[-1] + "/accept",
        json={"name": "Миша", "password": "Passw0rd!42"},
    )
    assert hr.get("/api/programs").json()[0]["people"] == 1
    rows = hr.get("/api/forms/mailing").json()["rows"]
    assert [(r["external_id"], r["pair"], r["status"]) for r in rows] == [
        ("Н-102", "без пары", "не заполнено")
    ]
    # HR видит себя рабочим пользователем: на главной — «В кабинет», метки демо нет
    page = hr.get("/").text
    assert "В кабинет" in page and "data-demo-switch" in page
    assert "demo-chip" not in hr.get("/dashboard").text


def test_demo_user_sees_demo_badge(client) -> None:
    from app.core.settings import get_settings
    from app.db.session import SessionLocal
    from app.seed import seed_accounts

    with SessionLocal() as db:
        seed_accounts(db)
    c = TestClient(app)
    c.post("/api/auth/login", json={"email": "hr@pulse.demo", "password": get_settings().demo_password})
    page = c.get("/dashboard").text
    assert "demo-chip" in page and "Выйти из демо" in page
    assert "В кабинет" not in c.get("/").text


def test_new_company_gets_standard_questionnaire(client) -> None:
    hr = TestClient(app)
    hr.post(
        "/api/auth/register",
        json={
            "name": "Ира",
            "email": "q@example.com",
            "password": "Passw0rd!42",
            "organization": "Т",
            "program": "П",
        },
    )
    qs = hr.get("/api/questionnaires").json()
    assert all(qs[side]["questions"] for side in ("intern", "mentor"))
    inv = hr.post(
        "/api/auth/invites", json={"email": "i@example.com", "role": "intern"}, headers=csrf_headers(hr)
    ).json()
    i = TestClient(app)
    i.post(
        "/api/auth/invites/" + inv["link"].split("/")[-1] + "/accept",
        json={"name": "Оля", "password": "Passw0rd!42"},
    )
    me = i.get("/api/me").json()
    qs = [q for q in me["questionnaire"]["questions"] if q["qtype"] != "text"]
    assert len(qs) == 7  # стандартная анкета — пульс-опрос стажёра МГТС
    r = i.post(
        "/api/responses", json={"answers": {q["id"]: "4" for q in qs}, "comment": ""}, headers=csrf_headers(i)
    )
    assert r.status_code == 200, r.text
    rows = hr.get("/api/forms/mailing").json()["rows"]
    assert rows[0]["status"] == "заполнено" and rows[0]["response_id"]
