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


def test_sandboxes_share_demo_bot_and_route_by_link(demo, monkeypatch) -> None:  # noqa: F811
    from app.services import sandbox

    monkeypatch.setattr(telegram, "call", lambda token, method, **p: {"message_id": 1})
    with SessionLocal() as db:
        tmpl = integrations.demo_template(db)
        integrations._put(
            db, tmpl, "int_telegram", {"connected": True, "token": "T", "info": "@pulse_bot", "secret": "s"}
        )
        a, b = sandbox.build(db, use_llm=False), sandbox.build(db, use_llm=False)
        assert integrations.config(db, a.id, "telegram")["source"] == "demo"
        assert set(telegram.orgs_for(db, "T")) >= {tmpl, a.id, b.id}
        pa = (
            db.query(Participant)
            .join(Program)
            .filter(Program.organization_id == a.id, Participant.external_id == "С-104")
            .one()
        )
        pb = (
            db.query(Participant)
            .join(Program)
            .filter(Program.organization_id == b.id, Participant.external_id == "С-104")
            .one()
        )
        la, lb = telegram.link_for(db, pa), telegram.link_for(db, pb)
        for link, org, part in ((la, a.id, pa), (lb, b.id, pb)):
            upd = {"message": {"chat": {"id": 5}, "text": "/start " + link.split("=")[1]}}
            assert telegram.route(db, "T", upd) == org
            telegram.handle(db, org, "T", upd)
            assert telegram.chat_of(db, org, part.id) == 5
        # чат перепривязан ко второй песочнице, из первой убран
        assert telegram.chat_of(db, a.id, pa.id) is None
        assert telegram.route(db, "T", {"message": {"chat": {"id": 5}, "text": "привет"}}) == b.id


def test_yandex_answers_page_maps_columns_to_values() -> None:
    from app.services.forms.connectors import parse_yandex_page

    page = {
        "columns": [
            {"id": 1, "text": "Ваш ID"},
            {"id": 2, "text": "Насколько понятны задачи?"},
            {"id": 3, "text": "Что мешает?"},
        ],
        "answers": [
            {
                "id": 77,
                "data": [
                    {"value": "С-104"},
                    {"value": 7},
                    {"value": [{"label": "нагрузка"}, {"label": "сроки"}]},
                ],
            }
        ],
        "next": {"next_url": None},
    }
    assert parse_yandex_page(page) == [
        ("77", {"Ваш ID": "С-104", "Насколько понятны задачи?": 7, "Что мешает?": "нагрузка, сроки"})
    ]


def test_yandex_form_id_from_link(demo, monkeypatch) -> None:  # noqa: F811
    hr = login("hr@pulse.demo")
    monkeypatch.setattr(integrations, "check", lambda kind, cfg: "форма …a9cc, вопросов: 7")
    r = hr.post(
        "/api/integrations/yandex",
        json={
            "token": "y0_x",
            "form_id": "https://forms.yandex.ru/u/6800cd9202848f10b272a9cc/",
            "org_id": "",
        },
        headers=csrf_headers(hr),
    ).json()
    assert r["connected"] and r["fields"][1]["value"] == "6800cd9202848f10b272a9cc"
    bad = hr.post(
        "/api/integrations/yandex", json={"token": "y0_x", "form_id": "abc"}, headers=csrf_headers(hr)
    )
    assert bad.status_code == 400 and "24 символа" in bad.json()["detail"]


def test_mail_body_plain_and_json() -> None:
    from app.services.forms.connectors import parse_mail_body

    plain = "Ваш ID:\nС-104\nНасколько понятны задачи, которые вы получаете?: 7\nКомментарий: что получается и что мешает?\nНе хватает времени"
    f = parse_mail_body(plain)
    assert f["Ваш ID"] == "С-104" and f["Насколько понятны задачи, которые вы получаете?"] == "7"
    assert f["Комментарий"].startswith("что получается") or "Не хватает времени" in " ".join(f.values())
    js = 'Ответ формы {"Ваш ID": "С-104", "Комфортен ли для вас объём задач?": "5"}'
    assert parse_mail_body(js) == {"Ваш ID": "С-104", "Комфортен ли для вас объём задач?": "5"}


def test_mail_answers_reach_participant(demo, monkeypatch) -> None:  # noqa: F811
    from app.services.forms import connectors

    qs = [
        "Насколько понятны задачи, которые вы получаете?",
        "Можете ли вы выполнять задачи без помощи наставника?",
        "Хватает ли вам времени и внимания наставника?",
        "Комфортен ли для вас объём задач?",
        "Получаете ли вы обратную связь по своей работе?",
        "Насколько вам понятны ваши перспективы после стажировки?",
    ]
    body = (
        "Ваш ID: С-104\n"
        + "\n".join(f"{q}: 4" for q in qs)
        + "\nКомментарий: что получается и что мешает?: Нагрузка большая"
    )
    monkeypatch.setattr(
        connectors, "fetch_mail", lambda cfg, limit=50: [("<m1@ya>", connectors.parse_mail_body(body))]
    )
    with SessionLocal() as db:
        prog = db.query(Program).first()
        cfg = {"email": "x@yandex.ru", "password": "p", "connected": True}
        assert connectors.poll(db, prog.id, "yandex_mail", cfg) == 1
        assert connectors.poll(db, prog.id, "yandex_mail", cfg) == 0  # письмо не загружается дважды
        part = db.query(Participant).filter(Participant.external_id == "С-104").one()
        assert (
            db.query(Response)
            .filter(Response.participant_id == part.id, Response.source == "yandex_mail")
            .count()
            == 1
        )


def test_mail_with_question_descriptions_and_footer() -> None:
    from app.services.forms.connectors import parse_mail_body

    body = (
        "Пульс: ответ\nВаш ID: С-104\nНасколько понятны задачи, которые вы получаете?:\n"
        '"Где 1 - совсем непонятны, а 10  - все задачи понятны.": 9\n'
        "Комментарий: что получается и что мешает?:\nНет ответа\n"
        "Это письмо содержит ответы на опрос, созданный пользователем Yandex Forms."
    )
    f = parse_mail_body(body)
    assert f["Насколько понятны задачи, которые вы получаете?"] == "9"
    assert f["Комментарий: что получается и что мешает?"] == ""
    assert not any("Где 1" in k for k in f)


def test_form_answer_reaches_every_live_demo_copy(demo) -> None:  # noqa: F811
    from datetime import datetime

    from app.db.models import Organization
    from app.services import sandbox
    from app.services.forms import connectors

    qs = [
        "Насколько понятны задачи, которые вы получаете?",
        "Можете ли вы выполнять задачи без помощи наставника?",
        "Хватает ли вам времени и внимания наставника?",
        "Комфортен ли для вас объём задач?",
        "Получаете ли вы обратную связь по своей работе?",
        "Насколько вам понятны ваши перспективы после стажировки?",
    ]
    fields = {"Ваш ID": "С-104"} | {q: "5" for q in qs}
    with SessionLocal() as db:
        tmpl = integrations.demo_template(db)
        copies = [sandbox.build(db, use_llm=False) for _ in range(2)]
        for o in copies:
            o.sandbox_claimed_at = o.sandbox_seen_at = datetime.utcnow()
        db.commit()
        targets = integrations.demo_targets(db, tmpl)
        assert targets[0] == tmpl and {o.id for o in copies} <= set(targets)
        ev = connectors.deliver(db, tmpl, fields, "yandex")
        assert ev["delivered"] == 3
        for org in [tmpl] + [o.id for o in copies]:
            n = (
                db.query(Response)
                .join(Participant)
                .join(Program)
                .filter(
                    Program.organization_id == org,
                    Participant.external_id == "С-104",
                    Response.source == "yandex",
                )
                .count()
            )
            assert n == 1
        assert db.get(Organization, copies[0].id).sandbox_token


def test_yandex_webhook_only_mode(demo) -> None:  # noqa: F811
    hr = login("hr@pulse.demo")
    r = hr.post(
        "/api/integrations/yandex", json={"token": "", "form_id": "", "org_id": ""}, headers=csrf_headers(hr)
    ).json()
    assert r["connected"] and "вебхук" in r["info"] and "token=" in r["webhook"]
    secret = r["webhook"].split("token=")[1]
    body = "Ваш ID: С-104" + chr(10) + "Комфортен ли для вас объём задач?: 6"
    resp = hr.post(
        f"/api/forms/yandex/webhook?token={secret}",
        content=body.encode(),
        headers={"content-type": "text/plain"},
    )
    assert resp.status_code == 400 and "Ответьте на все вопросы" in resp.json()["detail"]
    assert hr.post("/api/forms/yandex/webhook?token=wrong", json={}).status_code == 403
