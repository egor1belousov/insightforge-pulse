from datetime import date, datetime

from app.db.models import Participant, Program, Response
from app.db.session import SessionLocal
from app.services import integrations, notify, reminders, telegram
from tests.conftest import csrf_headers
from tests.test_live_chain import demo, login  # noqa: F401


def test_connect_checks_masks_and_disconnects(demo, monkeypatch) -> None:  # noqa: F811
    hr = login("hr@pulse.demo")
    h = csrf_headers(hr)
    monkeypatch.setattr(
        integrations,
        "check",
        lambda kind, cfg: (_ for _ in ()).throw(integrations.CheckError("Telegram не принял токен")),
    )
    r = hr.post("/api/integrations/telegram", json={"token": "bad"}, headers=h)
    assert r.status_code == 400 and "не принял" in r.json()["detail"]
    monkeypatch.setattr(integrations, "check", lambda kind, cfg: "@pulse_test_bot")
    r = hr.post("/api/integrations/telegram", json={"token": "123456:SECRET-TOKEN"}, headers=h).json()
    assert r["connected"] and r["info"] == "@pulse_test_bot"
    assert "SECRET" not in str(r) and r["fields"][0]["value"].endswith("OKEN")
    assert any("Подключено" in e["text"] for e in r["log"])
    # пустой секрет при повторном сохранении — прежний токен остаётся
    r = hr.post("/api/integrations/telegram", json={"token": ""}, headers=h).json()
    assert r["connected"]
    assert hr.delete("/api/integrations/telegram", headers=h).json()["connected"] is False
    assert login("lead@pulse.demo").get("/api/integrations").status_code == 403


def test_remind_reports_what_really_went(demo) -> None:  # noqa: F811
    hr = login("hr@pulse.demo")
    r = hr.post("/api/forms/remind", json={"ids": ["Н-204"]}, headers=csrf_headers(hr)).json()
    assert r["results"]["Н-204"]["site"] == "отправлено"
    assert r["results"]["Н-204"]["email"] == "демо-адрес, письмо не отправляется"
    assert r["results"]["Н-204"]["tg"] == "Telegram не подключён"
    assert "сайт — 1" in r["message"] and "Не ушло" in r["message"]


def test_auto_reminders_schedule_quiet_hours_and_escalation(demo) -> None:  # noqa: F811
    hr = login("hr@pulse.demo")
    h = csrf_headers(hr)
    m = hr.get("/api/forms/mailing").json()
    assert m["reminders"]["on"] and m["plan"]
    cfg = hr.put(
        "/api/forms/reminders", json=m["reminders"] | {"first_days": 30, "second_days": 1}, headers=h
    ).json()
    assert cfg["first_days"] == 27 and cfg["second_days"] == 28
    with SessionLocal() as db:
        prog = db.query(Program).first()
        period = max(r.period for r in db.query(Response))
        start = notify.period_start(prog, period)
        pend = reminders.pending(db, prog, period)
        assert [p.external_id for p in pend] == ["Н-204"]
        notify.save(db, prog.organization_id, "reminders", notify.REMINDERS)
        assert notify.due(db, prog, period, pend, start) == []
        night = datetime.combine(date(start.year, start.month, 3), datetime.min.time()).replace(hour=23)
        assert "тихие часы" in reminders.run_program(db, prog, night)["message"]
        day = night.replace(day=3, hour=11)
        r = reminders.run_program(db, prog, day)
        assert r["sent"] == ["Н-204"] and not r["escalated"]
        assert reminders.run_program(db, prog, day)["sent"] == []
        late = day.replace(day=9)
        r = reminders.run_program(db, prog, late)
        assert r["sent"] == ["Н-204"] and r["escalated"] == ["Н-204"]


def test_telegram_links_and_survey_in_chat(demo, monkeypatch) -> None:  # noqa: F811
    sent: list[dict] = []
    monkeypatch.setattr(
        telegram, "call", lambda token, method, **p: sent.append({"m": method, **p}) or {"message_id": 1}
    )
    with SessionLocal() as db:
        part = db.query(Participant).filter(Participant.external_id == "Н-204").one()
        org = db.get(Program, part.program_id).organization_id
        integrations._put(
            db, org, "int_telegram", {"connected": True, "token": "t", "info": "@pulse_bot", "secret": "s"}
        )
        link = telegram.link_for(db, part)
        assert link.startswith("https://t.me/pulse_bot?start=")
        code = link.split("=")[1]
        assert (
            telegram.send_reminder(db, db.get(Program, part.program_id), part, "x", "/me")
            == "участник не подключил бота"
        )
        telegram.handle(db, org, "t", {"message": {"chat": {"id": 77}, "text": "/start " + code}})
        assert telegram.chat_of(db, org, part.id) == 77
        assert telegram.send_reminder(db, db.get(Program, part.program_id), part, "x", "/me") == "отправлено"
        telegram.handle(
            db, org, "t", {"callback_query": {"id": "1", "data": "survey", "message": {"chat": {"id": 77}}}}
        )
        for _ in range(6):
            q = next(m for m in reversed(sent) if m["m"] == "sendMessage")
            data = q["reply_markup"]["inline_keyboard"][0][2]["callback_data"]
            telegram.handle(
                db, org, "t", {"callback_query": {"id": "2", "data": data, "message": {"chat": {"id": 77}}}}
            )
        telegram.handle(
            db, org, "t", {"message": {"chat": {"id": 77}, "text": "Не хватает времени на стажёра"}}
        )
        assert "Спасибо" in sent[-1]["text"]
        r = db.query(Response).filter(Response.participant_id == part.id, Response.source == "telegram").one()
        assert any(a.text for a in r.answers)
