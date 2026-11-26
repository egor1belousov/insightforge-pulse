import time

import pytest
from fastapi.testclient import TestClient

from app.core.settings import get_settings
from app.db.models import Participant, Question, Questionnaire, Response
from app.db.session import SessionLocal
from app.main import app
from app.seed import seed_accounts, seed_demo_data
from app.services.events import bus as bus_mod
from tests.conftest import csrf_headers


@pytest.fixture
def demo():
    with SessionLocal() as db:
        prog = seed_accounts(db)
        seed_demo_data(db, prog)
    events: list = []
    orig = bus_mod.bus.publish
    bus_mod.bus.publish = lambda pid, ev, data: events.append((ev, data))
    yield events
    bus_mod.bus.publish = orig


def login(email: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"email": email, "password": get_settings().demo_password})
    assert r.status_code == 200, r.text
    return c


def mentor_answers(c: TestClient, value: str = "3") -> dict:
    me = c.get("/api/me").json()
    return {q["id"]: value for q in me["questionnaire"]["questions"] if q["qtype"] != "text"}


def test_mentor_submits_and_dashboard_gets_before_after_fast(demo) -> None:
    c = login("mentor@pulse.demo")
    me = c.get("/api/me").json()
    assert me["participant"]["external_id"] == "Н-006" and me["submitted"] is False and me["period"] == 6
    t0 = time.monotonic()
    r = c.post(
        "/api/responses",
        json={"answers": mentor_answers(c), "comment": "Нет времени, объекты горят"},
        headers=csrf_headers(c),
    )
    elapsed = time.monotonic() - t0
    assert r.status_code == 200, r.text
    assert elapsed < 5
    ev = [d for e, d in demo if e == "pair_updated"][-1]
    assert ev["pair"] == "П-06" and ev["who"] == "Н-006" and ev["period"] == 6
    assert ev["before"]["index"] is None and ev["after"]["index"] is not None  # тестовая пара: первая анкета
    assert "→" in ev["message"]
    assert "missing" not in ev["after"]["signals"]
    hr = login("hr@pulse.demo")
    n = hr.get("/api/notifications").json()
    assert n["unread"] >= 1 and "Н-006" in n["items"][0]["title"]


def test_incomplete_answers_rejected(demo) -> None:
    c = login("intern@pulse.demo")
    ans = mentor_answers(c)
    ans.pop(next(iter(ans)))
    r = c.post("/api/responses", json={"answers": ans}, headers=csrf_headers(c))
    assert r.status_code == 400 and "Ответьте на все вопросы" in r.json()["detail"]


def test_sides_see_only_their_own(demo) -> None:
    c = login("intern@pulse.demo")
    me = c.get("/api/me").json()
    assert set(me) >= {"participant", "questionnaire", "bars", "talk"}
    text = str(me)
    assert "Н-006" not in text.replace(me.get("other") or "", "") or me["other"] == "Н-006"
    assert "Нет времени" not in text and "свои объекты" not in text  # комментариев наставника нет
    assert c.get("/api/pairs").status_code == 403
    assert c.get("/api/events").status_code == 403


def test_survey_link_without_login(demo) -> None:
    hr = login("hr@pulse.demo")
    links = {x["external_id"]: x["link"] for x in hr.get("/api/survey-links").json()}
    token = links["СТ-001"].rsplit("/", 1)[1]
    anon = TestClient(app)
    form = anon.get(f"/api/survey/{token}").json()
    answers = {q["id"]: "4" for q in form["questionnaire"]["questions"] if q["qtype"] != "text"}
    r = anon.post(f"/api/survey/{token}", json={"answers": answers, "comment": ""})
    assert r.status_code == 200
    assert any(d["who"] == "СТ-001" for e, d in demo if e == "pair_updated")
    assert anon.get("/api/survey/bad-token").status_code == 404


def test_demo_button_and_yandex_webhook(demo, monkeypatch) -> None:
    hr = login("hr@pulse.demo")
    r = hr.post("/api/demo/test-response", headers=csrf_headers(hr))
    assert r.status_code == 200 and r.json()["who"] == "Н-006"
    monkeypatch.setenv("YANDEX_WEBHOOK_SECRET", "s3cret")
    get_settings.cache_clear()
    with SessionLocal() as db:
        qn = (
            db.query(Questionnaire)
            .filter(Questionnaire.side == "intern", Questionnaire.active.is_(True))
            .one()
        )
        qs = db.query(Question).filter(Question.questionnaire_id == qn.id, Question.qtype != "text").all()
        fields = (
            {"Ваш ID": "СТ-003"} | {q.text: "5" for q in qs} | {"Комментарий": "Стало спокойнее, спасибо"}
        )
        assert db.query(Participant).filter(Participant.external_id == "СТ-003").count() == 1
    anon = TestClient(app)
    assert anon.post("/api/forms/yandex/webhook?token=bad", json=fields).status_code == 403
    r = anon.post("/api/forms/yandex/webhook?token=s3cret", json=fields)
    assert r.status_code == 200 and r.json()["ok"], r.text
    with SessionLocal() as db:  # доставка прошла в фоне после ответа
        part = db.query(Participant).filter(Participant.external_id == "СТ-003").one()
        assert (
            db.query(Response).filter(Response.participant_id == part.id, Response.source == "yandex").count()
            == 1
        )
    get_settings.cache_clear()


def test_mgts_form_fields_bind_to_intern_and_period(demo) -> None:
    """Ответ формы с полями как в анкете МГТС: ID, подразделение, период, показатели, два открытых вопроса."""
    from app.services.forms.external import ingest_external

    with SessionLocal() as db:
        from app.db.models import Answer, Program

        prog = db.query(Program).first()
        fields = {
            "ID наставника": "Н-005",
            "ID стажера": "СТ-005",
            "Подразделение / направление стажировки": "IT",
            "Контрольный период": "Месяц 6",
            "Понимание задач и ожиданий": "2",
            "Качество выполнения задач": "3",
            "Самостоятельность": "2",
            "Соблюдение сроков и организация работы": "2",
            "Вовлеченность и инициативность": "4",
            "Взаимодействие с наставником и командой": "3",
            "Комментарий о работе за период": "Сорвал два срока подряд, перестал задавать вопросы.",
            "Сложности / ситуации для внимания": "Нужна встреча с HR.",
        }
        ev = ingest_external(db, prog, fields, "yandex")
        assert ev["who"] == "Н-005" and ev["pair"] == "П-05" and ev["period"] == 6
        assert "low" in ev["after"]["signals"] and ev["after"]["index"] < ev["before"]["index"]
        part = db.query(Participant).filter(Participant.external_id == "Н-005").one()
        resp = db.query(Response).filter(Response.participant_id == part.id, Response.period == 6).one()
        texts = [
            a.text for a in db.query(Answer).filter(Answer.response_id == resp.id, Answer.text.isnot(None))
        ]
        assert len(texts) == 2 and resp.source == "yandex"
