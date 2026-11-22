import pytest

from app.db.session import SessionLocal
from app.seed import seed_accounts, seed_demo_data, seed_learning
from tests.conftest import csrf_headers
from tests.test_live_chain import login


@pytest.fixture
def full():
    with SessionLocal() as db:
        prog = seed_accounts(db)
        seed_demo_data(db, prog)
        seed_learning(db, prog)


def test_roles_see_their_learning(full) -> None:
    hr = login("hr@pulse.demo").get("/api/learn").json()
    assert len(hr["courses"]) == 5 and hr["guide"] and hr["tests"][0]["questions"][0]["correct"] is not None
    intern = login("intern@pulse.demo").get("/api/learn").json()
    assert [c["title"] for c in intern["courses"]] == ["Оборудование ШПД"]
    assert "correct" not in intern["tests"][0]["questions"][0]
    assert intern["guide"] == []
    mentor = login("mentor@pulse.demo").get("/api/learn").json()
    assert [c["kind"] for c in mentor["courses"]] == ["Памятка"]


def test_intern_takes_test_and_progress(full) -> None:
    c = login("intern@pulse.demo")
    t = c.get("/api/learn").json()["tests"][0]
    ans = {q["id"]: 0 for q in t["questions"]}
    r = c.post(f"/api/tests/{t['id']}/answer", json={"answers": ans}, headers=csrf_headers(c)).json()
    assert r["score"] == pytest.approx(1 / 3, abs=0.01)
    cid = c.get("/api/learn").json()["courses"][0]["id"]
    assert (
        c.post(f"/api/courses/{cid}/progress", json={"progress": 100}, headers=csrf_headers(c)).json()[
            "progress"
        ]
        == 100
    )


def test_hr_creates_course_generates_and_publishes_test(full) -> None:
    hr = login("hr@pulse.demo")
    h = csrf_headers(hr)
    text = (
        "Перед началом работ на высоте проверяют страховочную привязь и каску. Лестницу устанавливают под углом семьдесят пять градусов. "
        "Работы в грозу запрещены и переносятся на другой день. Инструмент поднимают только в сумке, а не в руках."
    )
    c = hr.post(
        "/api/courses",
        data={"title": "Техника безопасности", "kind": "Курс", "topic": "tasks", "text": text},
        headers=h,
    ).json()
    pairs = hr.get("/api/dashboard").json()["pairs"]
    assert (
        hr.post(
            f"/api/courses/{c['id']}/assign", json={"pair_ids": [pairs[0]["id"]], "side": "intern"}, headers=h
        ).json()["assigned"]
        == 1
    )
    t = hr.post("/api/tests/generate", json={"course_id": c["id"], "n": 3}, headers=h).json()
    assert t["status"] == "draft" and t["questions"] and t["generated_by"] == "rules"
    q = t["questions"][0]
    assert q["options"][q["correct"]] in text
    hr.put(f"/api/tests/{t['id']}/questions/{q['id']}", json={"enabled": False}, headers=h)
    assert hr.post(f"/api/tests/{t['id']}/publish", headers=h).json()["assigned"] == 1
    assert login("lead@pulse.demo").post(
        "/api/tests/generate", json={"course_id": c["id"]}, headers=h
    ).status_code in (403, 401)


def test_assistant_respects_roles(full) -> None:
    hr = login("hr@pulse.demo")
    r = hr.post("/api/assistant", json={"message": "Что делать с П-02?"}, headers=csrf_headers(hr)).json()
    assert "П-02" in r["answer"] and r["refs"]
    first = hr.post(
        "/api/assistant", json={"message": "Кому помочь первым?"}, headers=csrf_headers(hr)
    ).json()
    assert "П-03" in first["answer"]
    intern = login("intern@pulse.demo")
    r = intern.post(
        "/api/assistant", json={"message": "Что думает обо мне наставник?"}, headers=csrf_headers(intern)
    ).json()
    assert "не показываю" in r["answer"]
    r = intern.post(
        "/api/assistant", json={"message": "Какие оценки ставит мне наставник?"}, headers=csrf_headers(intern)
    ).json()
    assert "не показываю" in r["answer"]
    r = intern.post(
        "/api/assistant", json={"message": "Когда можно взять отпуск?"}, headers=csrf_headers(intern)
    ).json()
    assert "2 недели" in r["answer"] and "регламент" in r["refs"][0]
    r = intern.post(
        "/api/assistant", json={"message": "Что с парой П-02?"}, headers=csrf_headers(intern)
    ).json()
    assert "С-102" not in r["answer"] and "Н-202" not in r["answer"]
