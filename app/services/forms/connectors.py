"""Коннекторы Яндекс Форм и Google Forms: опрос новых ответов и разбор вебхука.

Подключаются на экране «Настройки» (или токенами в .env, см. docs/FORMS.md).
"""

import asyncio
import json
import logging
import re
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


def _yandex_value(v: Any) -> Any:
    if isinstance(v, list):
        return ", ".join(
            str(x.get("label") or x.get("text") or x) if isinstance(x, dict) else str(x) for x in v
        )
    if isinstance(v, dict):
        return v.get("label") or v.get("text") or v.get("value")
    return v


def parse_yandex_page(payload: dict) -> list[tuple[str, dict]]:
    """Страница ответов API: подписи вопросов в columns, значения в answers[].data по позициям."""
    cols = [c.get("text") or c.get("slug") or str(c.get("id")) for c in payload.get("columns") or []]
    out = []
    for a in payload.get("answers") or []:
        data = a.get("data")
        if isinstance(data, dict):  # формат raw: {код вопроса: {value}}
            fields = {k: _yandex_value(v.get("value") if isinstance(v, dict) else v) for k, v in data.items()}
        else:
            fields = {
                (cols[i] if i < len(cols) else f"вопрос {i + 1}"): _yandex_value((d or {}).get("value"))
                for i, d in enumerate(data or [])
            }
        out.append((str(a.get("id")), fields))
    return out


def fetch_yandex(cfg: dict, pages: int = 20) -> list[tuple[str, dict]]:
    """Ответы Яндекс Формы по API, с переходом по страницам next.next_url."""
    s = get_settings()
    url = f"{s.yandex_forms_api}/surveys/{cfg['form_id']}/answers?page_size=100"
    out: list[tuple[str, dict]] = []
    for _ in range(pages):
        r = httpx.get(url, headers=integrations.yandex_headers(cfg), timeout=15)
        r.raise_for_status()
        payload = r.json()
        out += parse_yandex_page(payload)
        nxt = (payload.get("next") or {}).get("next_url")
        if not nxt:
            break
        url = nxt if nxt.startswith("http") else s.yandex_forms_api.rstrip("/") + nxt.removeprefix("/v1")
    return out


MAIL_SUBJECT = "пульс"


def parse_mail_body(text: str) -> dict:
    """Тело письма формы → {подпись вопроса: ответ}: JSON или строки «Вопрос: ответ»."""
    start = text.find("{")
    if start != -1:
        try:
            data = json.loads(text[start : text.rfind("}") + 1])
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            _, fields = parse_yandex_answer(data)
            flat = {k: v for k, v in fields.items() if not isinstance(v, (dict, list))}
            if flat:
                return flat
    fields: dict[str, Any] = {}
    last = None
    text = re.split(r"Это письмо содержит ответы|Яндекс не несёт ответственности", text)[0]
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.lower() in ("нет ответа", "—", "-"):
            continue
        # пояснение к вопросу в кавычках, за ним ответ: «"Где 1 — …, а 10 — …": 9» — ответ относится к вопросу выше
        desc = re.match(r'^["«].+["»]\s*:\s*(.*)$', line)
        if desc and last is not None and not fields[last]:
            fields[last] = desc.group(1).strip()
            continue
        if ":" in line:
            # «Вопрос?: ответ» — делим по вопросительному знаку, иначе по первому двоеточию
            cut = line.find("?:")
            k, v = (line[: cut + 1], line[cut + 2 :]) if cut != -1 else line.split(":", 1)
            if k.strip() and len(k) < 160:
                last = k.strip()
                fields[last] = v.strip()
                continue
        if last is not None and not fields[last]:
            fields[last] = line  # ответ на следующей строке
        elif last is not None:
            fields[last] += " " + line
    return fields


def _mail_text(msg) -> str:
    import html as html_lib
    import re as re_

    parts = msg.walk() if msg.is_multipart() else [msg]
    plain, rich = "", ""
    for part in parts:
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        payload = part.get_payload(decode=True) or b""
        text = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
        if ctype == "text/plain":
            plain += text
        else:
            text = re_.sub(r"<br\s*/?>|</p>|</div>|</tr>", "\n", text, flags=re_.I)
            rich += html_lib.unescape(re_.sub(r"<[^>]+>", "", text))
    return plain or rich


def fetch_mail(cfg: dict, limit: int = 50) -> list[tuple[str, dict]]:
    """Письма формы из ящика: тема содержит «Пульс». Ключ — Message-ID."""
    import email
    import imaplib
    from email.header import decode_header, make_header

    m = imaplib.IMAP4_SSL("imap.yandex.ru", 993, timeout=15)
    m.login(cfg["email"], cfg["password"])
    m.select("INBOX")
    _, ids = m.search(None, "ALL")
    out = []
    for num in (ids[0].split() if ids and ids[0] else [])[-limit:]:
        _, data = m.fetch(num, "(BODY.PEEK[])")
        msg = email.message_from_bytes(data[0][1])
        subject = str(make_header(decode_header(msg.get("Subject", ""))))
        if MAIL_SUBJECT not in subject.lower():
            continue
        mid = msg.get("Message-ID") or f"{cfg['email']}:{num.decode()}"
        out.append((mid, parse_mail_body(_mail_text(msg))))
    m.logout()
    return out


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


def poll(db, program_id: int | None, kind: str, cfg: dict, org: int | None = None) -> int:
    """Забирает новые ответы формы организации. Возвращает число принятых."""
    program = db.get(Program, program_id) if program_id else None
    org = org or (program.organization_id if program else None)
    items = {"yandex": fetch_yandex, "google": fetch_google, "yandex_mail": fetch_mail}[kind](cfg)
    key = f"seen_{kind}"
    seen = _seen(db, program, key)
    done = 0
    for aid, fields in items:
        if aid in seen:
            continue
        try:
            ingest_any(db, integrations.active_demo_org(db, org) if org else org, fields, kind)
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
                for kind in ("yandex", "google", "yandex_mail"):
                    # песочницы демо берут форму основной организации — опрашиваем её один раз
                    cfg = integrations.own(db, org.id, kind) or (
                        {} if org.sandbox_token else integrations.config(db, org.id, kind)
                    )
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
