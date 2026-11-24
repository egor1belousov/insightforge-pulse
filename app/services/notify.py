"""Доставка напоминаний по каналам и автонапоминания по расписанию.

Каждый канал отправляет честно: если почта или Telegram не подключены, сообщение
по ним не уходит, а в ответе сказано почему.
"""

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.security import make_survey_token
from app.db.models import AppSetting, Notification, Participant, Program, User
from app.services import integrations

CHANNELS = {"email": True, "tg": True, "site": True}
CHANNEL_RU = {"email": "почта", "tg": "Telegram", "site": "сайт"}
REMINDERS = {
    "on": True,
    "first_days": 2,
    "second_days": 4,
    "max": 2,
    "escalate_days": 6,
    "quiet_from": 20,
    "quiet_to": 9,
    "channels": {"email": True, "tg": True, "site": True},
}


def setting(db: Session, org: int, key: str, default):
    row = db.query(AppSetting).filter(AppSetting.organization_id == org, AppSetting.key == key).first()
    if row is None:
        return default
    if isinstance(default, dict) and isinstance(row.value, dict):
        return default | row.value
    return row.value


def save(db: Session, org: int, key: str, value) -> None:
    row = db.query(AppSetting).filter(AppSetting.organization_id == org, AppSetting.key == key).first()
    if row is None:
        db.add(AppSetting(organization_id=org, key=key, value=value))
    else:
        row.value = value
    db.commit()


def period_start(program: Program, period: int) -> date:
    """Первый день месяца анкеты: от даты старта программы."""
    start = program.start_date or date.today().replace(day=1)
    m = start.month - 1 + period - 1
    return date(start.year + m // 12, m % 12 + 1, 1)


def deliver(
    db: Session, program: Program, part: Participant, title: str, text: str, channels: dict[str, bool]
) -> dict[str, str]:
    """Отправляет напоминание участнику по включённым каналам.

    Returns:
        Канал → «отправлено» или причина, почему не отправлено.
    """
    out: dict[str, str] = {}
    link = f"/survey/{make_survey_token(part.id)}"
    user = db.get(User, part.user_id) if part.user_id else None
    if channels.get("site"):
        if user:
            db.add(Notification(user_id=user.id, title=title, sub=text, link="/me", level="warn"))
            out["site"] = "отправлено"
        else:
            out["site"] = "нет аккаунта на сайте"
    if channels.get("email"):
        out["email"] = integrations.send_email(
            db, program.organization_id, user.email if user else None, title, text, link
        )
    if channels.get("tg"):
        from app.services import telegram

        out["tg"] = telegram.send_reminder(db, program, part, title, link)
    db.commit()
    return out


def summary(results: dict[str, dict[str, str]]) -> str:
    """Короткий итог рассылки: что ушло и что нет."""
    sent: dict[str, int] = {}
    skipped: dict[str, set[str]] = {}
    for res in results.values():
        for ch, st in res.items():
            if st == "отправлено":
                sent[ch] = sent.get(ch, 0) + 1
            else:
                skipped.setdefault(ch, set()).add(st)
    parts = [f"{CHANNEL_RU[c]} — {n}" for c, n in sent.items()]
    text = "Отправлено: " + (", ".join(parts) if parts else "никому")
    if skipped:
        text += ". Не ушло: " + "; ".join(
            f"{CHANNEL_RU[c]} ({', '.join(sorted(r))})" for c, r in skipped.items()
        )
    return text + "."


def due(db: Session, program: Program, period: int, pending: list[Participant], today: date) -> list[dict]:
    """Кому автонапоминание положено сейчас: по дням с начала месяца и числу уже отправленных."""
    cfg = setting(db, program.organization_id, "reminders", REMINDERS)
    if not cfg["on"]:
        return []
    log = setting(db, program.organization_id, f"autoremind_{period}", {})
    days = (today - period_start(program, period)).days
    steps = [cfg["first_days"], cfg["second_days"]][: max(0, int(cfg["max"]))]
    out = []
    for p in pending:
        n = len(log.get(p.external_id, []))
        if n < len(steps) and days >= steps[n]:
            out.append({"participant": p, "number": n + 1})
    return out


def quiet(cfg: dict, now: datetime) -> bool:
    """Тихие часы: напоминания не уходят ночью."""
    a, b = int(cfg["quiet_from"]), int(cfg["quiet_to"])
    h = now.hour
    return (h >= a or h < b) if a > b else a <= h < b


def run_auto(db: Session, program: Program, period: int, pending: list[Participant], now: datetime) -> dict:
    """Отправляет положенные автонапоминания и эскалирует HR после срока."""
    cfg = setting(db, program.organization_id, "reminders", REMINDERS)
    if quiet(cfg, now):
        return {
            "sent": [],
            "message": f"Сейчас тихие часы ({cfg['quiet_from']}:00–{cfg['quiet_to']}:00), напоминания не отправляются.",
        }
    log = setting(db, program.organization_id, f"autoremind_{period}", {})
    sent, results = [], {}
    for d in due(db, program, period, pending, now.date()):
        p = d["participant"]
        results[p.external_id] = deliver(
            db,
            program,
            p,
            "Напоминание: анкета за месяц ждёт вас",
            f"{d['number']}-е напоминание · 2 минуты",
            cfg["channels"],
        )
        log.setdefault(p.external_id, []).append(now.isoformat(timespec="minutes"))
        sent.append(p.external_id)
    days = (now.date() - period_start(program, period)).days
    esc_key = f"escalated_{period}"
    escalated = set(setting(db, program.organization_id, esc_key, []))
    late = [p.external_id for p in pending if days >= cfg["escalate_days"] and p.external_id not in escalated]
    if late:
        for hr in db.query(User).filter(User.organization_id == program.organization_id, User.role == "hr"):
            db.add(
                Notification(
                    user_id=hr.id,
                    title="Анкету не заполнили после напоминаний",
                    sub=", ".join(late) + " — стоит связаться лично",
                    link="/forms",
                    level="warn",
                )
            )
        save(db, program.organization_id, esc_key, sorted(escalated | set(late)))
    save(db, program.organization_id, f"autoremind_{period}", log)
    msg = summary(results) if sent else "Сейчас никому не положено напоминание."
    if late:
        msg += f" HR получил уведомление: {', '.join(late)}."
    return {"sent": sent, "escalated": late, "message": msg}


def next_step(
    db: Session, program: Program, period: int, pending: list[Participant], today: date
) -> list[str]:
    """План автонапоминаний для экрана: кому и когда уйдёт следующее."""
    cfg = setting(db, program.organization_id, "reminders", REMINDERS)
    if not cfg["on"]:
        return []
    log = setting(db, program.organization_id, f"autoremind_{period}", {})
    start = period_start(program, period)
    steps = [cfg["first_days"], cfg["second_days"]][: max(0, int(cfg["max"]))]
    out = []
    for p in pending:
        n = len(log.get(p.external_id, []))
        if n < len(steps):
            when = start + timedelta(days=steps[n])
            out.append(
                f"{p.external_id}: {n + 1}-е — {'сейчас' if when <= today else when.strftime('%d.%m')}"
            )
        else:
            out.append(f"{p.external_id}: напоминания исчерпаны")
    return out
