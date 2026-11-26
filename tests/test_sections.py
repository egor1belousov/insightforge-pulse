import io

from openpyxl import load_workbook

from tests.conftest import csrf_headers
from tests.test_live_chain import demo, login  # noqa: F401


def test_report_pdf_and_xlsx(demo) -> None:  # noqa: F811
    hr = login("hr@pulse.demo")
    r = hr.get("/api/reports?fmt=pdf&period=all")
    assert r.status_code == 200 and r.content[:4] == b"%PDF" and len(r.content) > 3000
    x = hr.get("/api/reports?fmt=xlsx&period=last&parts=pairs,signals")
    wb = load_workbook(io.BytesIO(x.content))
    assert wb.sheetnames == ["Сигналы", "Пары"]
    assert wb["Пары"].max_row == 6
    assert hr.get("/api/reports?parts=").status_code == 400
    assert login("lead@pulse.demo").get("/api/reports?fmt=pdf").status_code == 200
    assert login("intern@pulse.demo").get("/api/reports").status_code == 403


def test_settings_change_recomputes(demo) -> None:  # noqa: F811
    hr = login("hr@pulse.demo")
    s = hr.get("/api/settings").json()
    assert s["analytics"]["level_threshold"] == 0.25 and "health" in s["preview"]
    before = len(hr.get("/api/signals?period=2").json())
    s2 = hr.put(
        "/api/settings",
        json={"analytics": {"growth_slope": 0.5, "low_critical": 0.0, "gap_threshold": 0.9}},
        headers=csrf_headers(hr),
    ).json()
    assert s2["analytics"]["growth_slope"] == 0.5
    assert len(hr.get("/api/signals?period=2").json()) < before
    hr.post("/api/settings/reset", headers=csrf_headers(hr))
    assert len(hr.get("/api/signals?period=2").json()) == before
    r = hr.put(
        "/api/settings", json={"rules": {"health": {"on": True, "value": 95}}}, headers=csrf_headers(hr)
    ).json()
    assert set(r["preview"]["health"]) == {"П-05"}


def test_builder_adds_mirrored_questions(demo) -> None:  # noqa: F811
    hr = login("hr@pulse.demo")
    h = csrf_headers(hr)
    sug = hr.post(
        "/api/questions/suggest",
        json={"text": "Понятны ли вам критерии итоговой аттестации?", "side": "intern"},
        headers=h,
    ).json()
    assert sug["topic"] in ("tasks", "growth") and sug["mirror_text"]
    r = hr.post(
        "/api/questions",
        json={
            "side": "intern",
            "text": "Понятны ли вам критерии итоговой аттестации?",
            "topic": "tasks",
            "mirror_text": "Объяснили ли вы стажёру критерии аттестации?",
        },
        headers=h,
    )
    assert r.status_code == 200 and r.json()["versions"] == {"intern": 2, "mentor": 2}
    q = hr.get("/api/questionnaires").json()
    new_i = next(x for x in q["intern"]["questions"] if "аттестации" in x["text"])
    new_m = next(x for x in q["mentor"]["questions"] if "аттестации" in x["text"])
    assert new_i["mirror"] == new_m["id"]
    me = login("intern@pulse.demo").get("/api/me").json()
    assert any("аттестации" in x["text"] for x in me["questionnaire"]["questions"])


def test_mailing_remind_and_outcomes(demo) -> None:  # noqa: F811
    hr = login("hr@pulse.demo")
    h = csrf_headers(hr)
    m = hr.get("/api/forms/mailing").json()
    assert m["got"] == 10 and m["total"] == 12
    assert "Н-006" in hr.post("/api/forms/remind", json={"ids": ["Н-006"]}, headers=h).json()["message"]
    assert (
        next(r for r in hr.get("/api/forms/mailing").json()["rows"] if r["external_id"] == "Н-006")["status"]
        == "напомнили"
    )
    mentor = login("mentor@pulse.demo")
    assert "анкету" in mentor.get("/api/notifications").json()["items"][0]["title"]
    o = hr.get("/api/program/overview").json()
    assert o["unpaired"] == []
    pid = o["outcomes"][0]["pair_id"]
    assert hr.post(f"/api/pairs/{pid}/outcome", json={"outcome": "stay"}, headers=h).status_code == 200


def test_hr_sees_filled_answers_read_only(demo) -> None:  # noqa: F811
    hr = login("hr@pulse.demo")
    rows = hr.get("/api/forms/mailing").json()["rows"]
    filled = next(r for r in rows if r["response_id"])
    assert next(r for r in rows if r["status"] != "заполнено")["response_id"] is None
    v = hr.get(f"/api/forms/responses/{filled['response_id']}").json()
    assert v["external_id"] == filled["external_id"] and len(v["answers"]) >= 5
    assert any(a["value"] for a in v["answers"]) and v["answers"][0]["max"] == 5
    assert login("lead@pulse.demo").get(f"/api/forms/responses/{filled['response_id']}").status_code == 403
    assert hr.get("/api/forms/responses/999999").status_code == 404
