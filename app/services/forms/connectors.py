"""Коннекторы Яндекс Форм и Google Forms: опрос новых ответов и разбор вебхука.

Подключаются на экране «Настройки» (или токенами в .env, см. docs/FORMS.md).
"""

import asyncio
import json
import logging
from typing import Any

import httpx

from app.core.settings import get_settings
from app.db.models import AppSetting, Organization, Program
from app.db.session import SessionLocal
from app.services import integrations
from app.services.forms.external import ingest_external
from app.services.forms.submit import SubmitError

log = logging.getLogger("pulse.connectors")


def status(db, org: int) -> dict:
    """Состояние коннекторов форм организации для интерфейса."""
    y, g = integrations.config(db, org, "yandex"), integrations.config(db, org, "google")
    return {
        "yandex": {"enabled": bool(y), "form_id": y.get("form_id"), "webhook": "/api/forms/yandex/webhook"},
        "google": {"enabled": bool(g), "form_id": g.get("form_id")},
        "poll_seconds": get_settings().forms_poll_seconds,
    }


def _seen(db, program: Program, key: str) -> set[str]:
    row = (
        db.query(AppSetting)
        .filter(AppSetting.organization_id == program.organization_id, AppSetting.key == key)
        .first()
    )
    return set(row.value or []) if row else set()


def _mark(db, program: Program, key: str, ids: set[str]) -> None:
    row = (
        db.query(AppSetting)
        .filter(AppSetting.organization_id == program.organization_id, AppSetting.key == key)
        .first()
    )
    if row is None:
        row = AppSetting(organization_id=program.organization_id, key=key, value=[])
        db.add(row)
    row.value = sorted(ids)[-5000:]
    db.commit()


def parse_yandex_answer(item: dict) -> tuple[str, dict[str, Any]]:
    """Ответ Яндекс Формы → (id, {подпись поля: значение}). Поддерживает формат API и вебхука."""
    aid = str(item.get("id") or item.get("answer_id") or json.dumps(item, sort_keys=True)[:64])
    fields: dict[str, Any] = {}
    data = item.get("data") or item.get("answers") or item.get("fields") or item
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, dict):
                label = (
                    v.get("question", {}).get("label")
                    if isinstance(v.get("question"), dict)
                    else v.get("label") or k
                )
                val = v.get("value")
                if isinstance(val, list):
                    val = ", ".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in val)
                fields[str(label or k)] = val
            else:
                fields[str(k)] = v
    elif isinstance(data, list):
        for d in data:
            label = d.get("label") or (d.get("question") or {}).get("label") or d.get("key") or d.get("id")
            val = d.get("value")
            if isinstance(val, list):
                val = ", ".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in val)
            fields[str(label)] = val
    return aid, fields


def fetch_yandex(cfg: dict) -> list[tuple[str, dict]]:
    """Ответы Яндекс Формы по API."""
    s = get_settings()
    url = f"{s.yandex_forms_api}/surveys/{cfg['form_id']}/answers"
    r = httpx.get(url, headers={"Authorization": f"OAuth {cfg['token']}"}, timeout=15)
    r.raise_for_status()
    payload = r.json()
    items = payload.get("answers") or payload.get("items") or (payload if isinstance(payload, list) else [])
    return [parse_yandex_answer(i) for i in items]


def _google_token(creds: dict) -> str:
    r = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "refresh_token": creds["refresh_token"],
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def fetch_google(cfg: dict) -> list[tuple[str, dict]]:
    """Ответы Google Forms (forms.responses.list)."""
    creds = json.loads(cfg["credentials"])
    token = _google_token(creds)
    h = {"Authorization": f"Bearer {token}"}
    base = f"https://forms.googleapis.com/v1/forms/{cfg['form_id']}"
    form = httpx.get(base, headers=h, timeout=15).json()
    titles = {}
    for it in form.get("items", []):
        qid = ((it.get("questionItem") or {}).get("question") or {}).get("questionId")
        if qid:
            titles[qid] = it.get("title", qid)
    resp = httpx.get(f"{base}/responses", headers=h, timeout=15).json()
    parsed = []
    for rr in resp.get("responses", []):
        fields = {}
        for qid, ans in (rr.get("answers") or {}).items():
            vals = [a.get("value") for a in (ans.get("textAnswers") or {}).get("answers", [])]
            fields[titles.get(qid, qid)] = ", ".join(v for v in vals if v)
        if rr.get("respondentEmail"):
            fields["email"] = rr["respondentEmail"]
        parsed.append((rr.get("responseId", ""), fields))
    return parsed


def ingest_any(db, org: int, fields: dict, source: str) -> dict:
    """Ответ внешней формы: ищем участника во всех потоках организации.

    Raises:
        SubmitError: если участник не найден ни в одном потоке.
    """
    last: SubmitError | None = None
    for program in db.query(Program).filter(Program.organization_id == org).order_by(Program.id.desc()):
        try:
            return ingest_external(db, program, fields, source)
        except SubmitError as e:
            last = e
    raise last or SubmitError("В организации нет потоков.")


def poll(db, program_id: int | None, kind: str, cfg: dict) -> int:
    """Забирает новые ответы формы организации. Возвращает число принятых."""
    program = db.get(Program, program_id) if program_id else None
    org = program.organization_id if program else None
    items = fetch_yandex(cfg) if kind == "yandex" else fetch_google(cfg)
    key = f"seen_{kind}"
    seen = _seen(db, program, key)
    done = 0
    for aid, fields in items:
        if aid in seen:
            continue
        try:
            ingest_any(db, org, fields, kind)
            done += 1
        except SubmitError as e:
            log.warning("%s: ответ %s не принят: %s", kind, aid, e)
        seen.add(aid)
    _mark(db, program, key, seen)
    return done


async def poller() -> None:
    """Фоновый опрос подключённых форм всех организаций."""
    while True:
        with SessionLocal() as db:
            jobs = []
            for org in db.query(Organization):
                prog = (
                    db.query(Program).filter(Program.organization_id == org.id).order_by(Program.id).first()
                )
                for kind in ("yandex", "google"):
                    cfg = integrations.config(db, org.id, kind)
                    if cfg and prog:
                        jobs.append((prog.id, kind, cfg))
        for pid, kind, cfg in jobs:
            try:
                await asyncio.to_thread(_poll_job, pid, kind, cfg)
            except Exception as e:  # noqa: BLE001
                log.warning("Коннектор %s: %s", kind, e)
        await asyncio.sleep(get_settings().forms_poll_seconds)


def _poll_job(pid: int, kind: str, cfg: dict) -> int:
    with SessionLocal() as db:
        return poll(db, pid, kind, cfg)
