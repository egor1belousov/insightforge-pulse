from app.db.models import Question, Questionnaire, User
from app.db.session import SessionLocal
from tests.conftest import csrf_headers
from tests.test_live_chain import demo, login  # noqa: F401


def test_streams_belong_to_company(demo) -> None:  # noqa: F811
    hr = login("hr@pulse.demo")
    h = csrf_headers(hr)
    first = hr.get("/api/programs").json()
    assert len(first) == 1 and first[0]["current"] and first[0]["pairs"] == 6
    assert hr.post("/api/programs", json={"name": " "}, headers=h).status_code == 400
    new = hr.post(
        "/api/programs",
        json={"name": "Весна 2027", "start": "2027-03-01", "months": 4, "copy_questionnaires": True},
        headers=h,
    ).json()
    lst = hr.get("/api/programs").json()
    assert lst[0]["name"] == "Весна 2027" and lst[0]["current"] and lst[0]["status"] == "скоро"
    with SessionLocal() as db:
        qns = db.query(Questionnaire).filter(Questionnaire.program_id == new["id"]).all()
        assert {q.side for q in qns} == {"intern", "mentor"}
        qs = db.query(Question).filter(Question.questionnaire_id.in_([q.id for q in qns])).all()
        assert qs and all(q.mirror_question_id in {x.id for x in qs} for q in qs if q.mirror_question_id)
    # руководитель видит новый поток и может в него переключиться
    lead = login("lead@pulse.demo")
    assert [p["name"] for p in lead.get("/api/programs").json()][0] == "Весна 2027"
    assert lead.post(f"/api/programs/{new['id']}/switch", headers=csrf_headers(lead)).status_code == 200
    assert lead.get("/api/pairs").json() == []
    assert hr.post(f"/api/programs/{first[0]['id']}/switch", headers=h).status_code == 200
    assert len(hr.get("/api/pairs").json()) == 6
    assert hr.post("/api/programs/99999/switch", headers=h).status_code == 404
    assert login("mentor@pulse.demo").post(f"/api/programs/{new['id']}/switch").status_code in (403, 401)


def test_removing_employee_keeps_company_data(demo) -> None:  # noqa: F811
    hr = login("hr@pulse.demo")
    h = csrf_headers(hr)
    users = hr.get("/api/settings").json()["users"]
    me = next(u for u in users if u["me"])
    lead = next(u for u in users if u["role"] == "lead")
    assert hr.delete(f"/api/users/{me['id']}", headers=h).status_code == 400
    assert hr.delete(f"/api/users/{lead['id']}", headers=h).json()["ok"]
    with SessionLocal() as db:
        assert db.query(User).filter(User.email == "lead@pulse.demo").first() is None
    assert len(hr.get("/api/pairs").json()) == 6
