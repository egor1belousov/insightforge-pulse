"""Коннекторы Яндекс Форм и Google Forms: опрос новых ответов каждые 15 секунд.

Без токенов в .env выключены (см. docs/FORMS.md).
"""

import asyncio
import json
import logging
from typing import Any

import httpx

from app.core.settings import get_settings
from app.db.models import AppSetting, Program
from app.db.session import SessionLocal
from app.services.forms.external import ingest_external
from app.services.forms.submit import SubmitError

log = logging.getLogger("pulse.connectors")


def yandex_enabled() -> bool:
    s = get_settings()
    return bool(s.yandex_forms_token and s.yandex_form_id)


def google_enabled() -> bool:
    s = get_settings()
    return bool(s.google_forms_credentials and s.google_form_id)


def status() -> dict:
    """Состояние коннекторов для интерфейса."""
    return {
        "yandex": {
            "enabled": yandex_enabled(),
            "form_id": get_settings().yandex_form_id or None,
            "webhook": "/api/forms/yandex/webhook",
        },
        "google": {"enabled": google_enabled(), "form_id": get_settings().google_form_id or None},
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


def poll_yandex(program_id: int) -> int:
    """Забирает новые ответы Яндекс Формы. Возвращает число обработанных."""
    s = get_settings()
    url = f"{s.yandex_forms_api}/surveys/{s.yandex_form_id}/answers"
    r = httpx.get(url, headers={"Authorization": f"OAuth {s.yandex_forms_token}"}, timeout=15)
    r.raise_for_status()
    payload = r.json()
    items = payload.get("answers") or payload.get("items") or (payload if isinstance(payload, list) else [])
    return _process(program_id, "yandex", [parse_yandex_answer(i) for i in items])


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


def poll_google(program_id: int) -> int:
    """Забирает новые ответы Google Forms (forms.responses.list)."""
    s = get_settings()
    creds = json.loads(s.google_forms_credentials)
    token = _google_token(creds)
    h = {"Authorization": f"Bearer {token}"}
    base = f"https://forms.googleapis.com/v1/forms/{s.google_form_id}"
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
    return _process(program_id, "google", parsed)


def _process(program_id: int, source: str, items: list[tuple[str, dict]]) -> int:
    key = f"seen_{source}"
    done = 0
    with SessionLocal() as db:
        program = db.get(Program, program_id)
        seen = _seen(db, program, key)
        for aid, fields in items:
            if aid in seen:
                continue
            try:
                ingest_external(db, program, fields, source)
                done += 1
            except SubmitError as e:
                log.warning("%s: ответ %s не принят: %s", source, aid, e)
            seen.add(aid)
        _mark(db, program, key, seen)
    return done


async def poller(program_id: int) -> None:
    """Фоновый опрос включённых коннекторов."""
    interval = get_settings().forms_poll_seconds
    while True:
        for enabled, fn in ((yandex_enabled, poll_yandex), (google_enabled, poll_google)):
            if not enabled():
                continue
            try:
                await asyncio.to_thread(fn, program_id)
            except Exception as e:  # noqa: BLE001
                log.warning("Коннектор %s: %s", fn.__name__, e)
        await asyncio.sleep(interval)
