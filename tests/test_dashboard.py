from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import csrf_headers
from tests.test_live_chain import demo, login  # noqa: F401


def test_dashboard_story_and_roles(demo) -> None:  # noqa: F811
    hr = login("hr@pulse.demo")
    d = hr.get("/api/dashboard").json()
    assert d["headline"] == "Сигналов нет — пары в норме"
    assert [h["pair"] for h in d["history"]][:3] == ["П-05", "П-03", "П-04"]
    assert "внимание требовалось 4 парам из 6" in d["sub"]
    assert d["forms"]["pending"] == ["СТ-006", "Н-006"]
    assert all(p["i"] is not None and p["m"] is not None for p in d["pairs"] if p["code"] != "П-06")
    past = hr.get("/api/dashboard?period=2").json()
    assert past["period"] == 2 and {a["pair"] for a in past["alerts"]} == {"П-01", "П-03", "П-05"}
    assert past["zones"] == {"red": 2, "amber": 1, "green": 2}
    assert past["alerts"][0]["zone"] == "red"
    one = hr.get("/api/dashboard?dept=HR-блок").json()
    assert [p["code"] for p in one["pairs"]] == ["П-04"]
    lead = login("lead@pulse.demo")
    assert lead.get("/api/dashboard").json()["tasks"] == []
    assert login("intern@pulse.demo").get("/api/dashboard").status_code == 403
    assert TestClient(app).get("/dashboard", follow_redirects=False).status_code == 303


def test_layout_is_saved_per_user(demo) -> None:  # noqa: F811
    hr = login("hr@pulse.demo")
    r = hr.put(
        "/api/dashboard/layout", json={"hidden": {"feed": True}, "preset": "custom"}, headers=csrf_headers(hr)
    )
    assert r.status_code == 200
    assert hr.get("/api/dashboard/layout").json()["hidden"] == {"feed": True}
    assert login("lead@pulse.demo").get("/api/dashboard/layout").json()["hidden"] == {}


def test_pair_card_and_action_lifecycle(demo) -> None:  # noqa: F811
    hr = login("hr@pulse.demo")
    pid = next(p["id"] for p in hr.get("/api/dashboard").json()["pairs"] if p["code"] == "П-05")
    c = hr.get(f"/api/pairs/{pid}/diagnosis").json()
    assert [t["zone"] for t in c["timeline"]] == ["red", "red", "red", "green", "green", "green"]
    assert "2 из 5" in c["timeline"][0]["signals"][0]["description"]
    assert c["summary"].startswith("Сейчас сигналов нет") and "июнь–август" in c["summary"]
    assert [d["name"] for d in c["decomp"]] == [
        "Уровень",
        "Тренд",
        "Запаздывание",
        "Слова ≠ цифры",
    ]
    assert c["contrib"]
    cal = hr.get(f"/api/pairs/{pid}/diagnosis?scale=cal&topic=tasks").json()
    assert cal["chart"]["intern"][0][1] != c["chart"]["intern"][0][1]
    h = csrf_headers(hr)
    aid = hr.post(
        f"/api/pairs/{pid}/actions", json={"kind": "meeting", "title": "Встреча втроём"}, headers=h
    ).json()["id"]
    assert hr.post(f"/api/actions/{aid}/agenda", headers=h).json()["items"]
    out = hr.post(
        f"/api/actions/{aid}/outcomes",
        json={"text": "Стажёр будет сдавать работу после самопроверки с 16 ноября."},
        headers=h,
    ).json()
    assert out["agreements"][0]["who"].startswith("Стажёр")
    hr.put(f"/api/actions/{aid}/outcomes", json={"text": "x", "agreements": out["agreements"]}, headers=h)
    a = hr.get(f"/api/pairs/{pid}/diagnosis").json()["actions"][0]
    assert a["status"] == "done" and a["agreements"] and a["effect"]["text"]
    assert (
        hr.post(f"/api/pairs/{pid}/notes", json={"text": "Звонил наставнику"}, headers=h).status_code == 200
    )
    lead = login("lead@pulse.demo")
    assert lead.get(f"/api/pairs/{pid}/diagnosis").json()["notes"] == []
    assert (
        lead.post(f"/api/pairs/{pid}/notes", json={"text": "x"}, headers=csrf_headers(lead)).status_code
        == 403
    )
    p4 = next(p["id"] for p in hr.get("/api/dashboard?period=4").json()["pairs"] if p["code"] == "П-04")
    c4 = hr.get(f"/api/pairs/{p4}/diagnosis").json()
    assert c4["recommended"] or c4["timeline"][3]["zone"] == "red"
    sid = next(s.id for s in _signals_of(p4))
    assert hr.post(f"/api/signals/{sid}/verdict", json={"verdict": "confirmed"}, headers=h).status_code == 200


def _signals_of(pair_id: int) -> list:
    from app.db.models import Signal
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        return db.query(Signal).filter(Signal.pair_id == pair_id).all()


def test_public_pages_render() -> None:
    c = TestClient(app)
    for url in ("/", "/login", "/register", "/invite/xyz"):
        assert c.get(url).status_code == 200, url
