import json

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
    assert q["source"] in text and all(0 <= k < len(q["options"]) for k in q["correct"])
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


def test_constructor_sections_tags_and_reader_progress(full) -> None:
    hr = login("hr@pulse.demo")
    h = csrf_headers(hr)
    sections = [
        {
            "kind": "text",
            "title": "Перед выездом",
            "body": "Проверьте комплект инструмента и заряд рефлектометра.",
        },
        {"kind": "check", "title": "Чек-лист", "body": "Каска\nПерчатки\nСхема разводки"},
        {"kind": "tip", "title": "", "body": "Нет схемы — работу не начинайте, позвоните наставнику."},
    ]
    c = hr.post(
        "/api/courses",
        data={
            "title": "Выезд на объект",
            "kind": "Чек-лист",
            "topic": "",
            "audience": "all",
            "tags": "Оборудование, Охрана труда",
            "sections": json.dumps(sections),
        },
        headers=h,
    ).json()
    assert c["tags"] == ["Оборудование", "Охрана труда"] and c["topic"] is None and len(c["sections"]) == 3
    c = hr.put(
        f"/api/courses/{c['id']}", json=c | {"tags": ["Оборудование"], "status": "draft"}, headers=h
    ).json()
    assert c["status"] == "draft" and c["tags"] == ["Оборудование"]
    assert hr.put(f"/api/courses/{c['id']}", json=c | {"sections": []}, headers=h).status_code == 400
    pairs = hr.get("/api/dashboard").json()["pairs"]
    pid = next(p["id"] for p in pairs if p["code"] == "П-04")
    hr.post(f"/api/courses/{c['id']}/assign", json={"pair_ids": [pid]}, headers=h)
    for who in ("intern@pulse.demo", "mentor@pulse.demo"):
        side = login(who)
        assert any(x["id"] == c["id"] for x in side.get("/api/learn").json()["courses"])
    intern = login("intern@pulse.demo")
    r = intern.post(
        f"/api/courses/{c['id']}/progress", json={"section": 1}, headers=csrf_headers(intern)
    ).json()
    assert r["progress"] == 33 and r["done"] == [1]
    assert intern.get(f"/api/courses/{c['id']}").json()["done"] == [1]


def test_split_sections_from_plain_text() -> None:
    from app.services.learning import split_sections

    secs = split_sections(
        "Подготовка\nСнимите покрытие. Очистите волокно.\nИнструмент\n- Скалыватель\n- Рефлектометр"
    )
    assert [s["title"] for s in secs if s["title"]] == ["Подготовка", "Инструмент"]
    assert next(s for s in secs if s["kind"] == "list")["body"] == "Скалыватель\nРефлектометр"


def test_question_types_editing_and_retake(full) -> None:
    hr = login("hr@pulse.demo")
    h = csrf_headers(hr)
    t = next(x for x in hr.get("/api/learn").json()["tests"])
    t = hr.post(
        f"/api/tests/{t['id']}/questions",
        json={
            "qtype": "multi",
            "text": "Что проверяют перед выездом?",
            "options": ["Инструмент", "Схему", "Погоду", "Обед"],
            "correct": [0, 1],
        },
        headers=h,
    ).json()
    multi = t["questions"][-1]
    assert multi["qtype"] == "multi" and multi["correct"] == [0, 1]
    t = hr.put(
        f"/api/tests/{t['id']}/questions/{multi['id']}",
        json={"qtype": "truefalse", "text": "Без схемы работу начинают", "correct": [1]},
        headers=h,
    ).json()
    tf = t["questions"][-1]
    assert tf["options"] == ["Верно", "Неверно"] and tf["correct"] == [1]
    assert (
        hr.put(f"/api/tests/{t['id']}/questions/{tf['id']}", json={"correct": [9]}, headers=h).status_code
        == 400
    )
    hr.put(f"/api/tests/{t['id']}", json={"pass_score": 0.75}, headers=h)
    intern = login("intern@pulse.demo")
    it = intern.get("/api/learn").json()["tests"][0]
    assert "correct" not in it["questions"][0] and it["pass_score"] == 0.75
    wrong = {q["id"]: 0 for q in it["questions"]}
    r = intern.post(
        f"/api/tests/{it['id']}/answer", json={"answers": wrong}, headers=csrf_headers(intern)
    ).json()
    assert not r["passed"] and r["attempts"] == 1
    right = {q["id"]: (1 if q["qtype"] == "truefalse" else 0) for q in it["questions"]}
    right.update({int(k): v["correct"] for k, v in r["result"].items()})
    r = intern.post(
        f"/api/tests/{it['id']}/answer", json={"answers": right}, headers=csrf_headers(intern)
    ).json()
    assert r["passed"] and r["score"] == 1 and r["attempts"] == 2
