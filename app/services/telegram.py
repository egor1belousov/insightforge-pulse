"""Telegram-бот: привязка участника по личной ссылке, напоминания и анкета прямо в чате.

Бот работает через long polling (getUpdates), поэтому ему не нужен входящий адрес.
Один поток на каждую организацию с подключённым ботом.
"""

import logging
import secrets
import threading

import httpx
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.models import AppSetting, Organization, Participant, Program
from app.db.session import SessionLocal
from app.services import integrations

log = logging.getLogger("pulse.telegram")
API = "https://api.telegram.org/bot{token}/{method}"

_threads: dict[str, threading.Event] = {}
_state: dict[tuple[int, int], dict] = {}  # (org, chat) → шаг анкеты в чате


def _get(db: Session, org: int, key: str) -> dict:
    row = db.query(AppSetting).filter(AppSetting.organization_id == org, AppSetting.key == key).first()
    return dict(row.value) if row and row.value else {}


def _set(db: Session, org: int, key: str, value: dict) -> None:
    row = db.query(AppSetting).filter(AppSetting.organization_id == org, AppSetting.key == key).first()
    if row is None:
        db.add(AppSetting(organization_id=org, key=key, value=value))
    else:
        row.value = value
    db.commit()


def call(token: str, method: str, **payload) -> dict:
    """Запрос к Bot API. Возвращает result или пустой словарь при ошибке."""
    try:
        r = httpx.post(API.format(token=token, method=method), json=payload, timeout=15)
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("Telegram %s: %s", method, e)
        return {}
    if not data.get("ok"):
        log.warning("Telegram %s: %s", method, data.get("description"))
        return {}
    return data.get("result") or {}


def link_for(db: Session, part: Participant) -> str | None:
    """Личная ссылка на бота для участника: t.me/<бот>?start=<код>."""
    org = db.get(Program, part.program_id).organization_id
    cfg = integrations.config(db, org, "telegram")
    if not cfg or not cfg.get("info"):
        return None
    codes = _get(db, org, "tg_codes")
    code = next((c for c, pid in codes.items() if pid == part.id), None)
    if code is None:
        code = secrets.token_urlsafe(9).replace("-", "a").replace("_", "b")
        codes[code] = part.id
        _set(db, org, "tg_codes", codes)
    return f"https://t.me/{cfg['info'].lstrip('@')}?start={code}"


def chats(db: Session, org: int) -> dict:
    """Привязанные чаты: id участника → id чата."""
    return _get(db, org, "tg_chats")


def chat_of(db: Session, org: int, part_id: int) -> int | None:
    return _get(db, org, "tg_chats").get(str(part_id))


def send_reminder(db: Session, program: Program, part: Participant, title: str, link: str) -> str:
    """Напоминание в чат участника. Возвращает «отправлено» или причину."""
    cfg = integrations.config(db, program.organization_id, "telegram")
    if not cfg:
        return "Telegram не подключён"
    chat = chat_of(db, program.organization_id, part.id)
    if not chat:
        return "участник не подключил бота"
    url = get_settings().public_url.rstrip("/") + link
    kb = [[{"text": "Ответить здесь, в чате", "callback_data": "survey"}]]
    if url.startswith("https://"):
        kb.append([{"text": "Открыть анкету на сайте", "url": url}])
    ok = call(
        cfg["token"],
        "sendMessage",
        chat_id=chat,
        text=f"🔔 {title}\nШесть вопросов, две минуты. Ответы видит только HR.",
        reply_markup={"inline_keyboard": kb},
    )
    if ok:
        integrations.log(db, program.organization_id, "telegram", f"Напоминание {part.external_id}")
    return "отправлено" if ok else "Telegram не ответил"


# ---------- анкета в чате ----------


def _questions(db: Session, part: Participant) -> list:
    from app.services.forms.submit import active_questionnaire

    qn = active_questionnaire(db, part.program_id, part.side)
    return list(qn.questions) if qn else []


def _ask(token: str, chat: int, st: dict, db: Session) -> None:
    part = db.get(Participant, st["pid"])
    qs = _questions(db, part)
    if st["i"] >= len(qs):
        _finish(token, chat, st, db, part)
        return
    q = qs[st["i"]]
    n = f"{st['i'] + 1}/{len(qs)}"
    if q.qtype == "text":
        call(
            token,
            "sendMessage",
            chat_id=chat,
            text=f"{n}. {q.text}\nНапишите ответом или нажмите «Пропустить».",
            reply_markup={"inline_keyboard": [[{"text": "Пропустить", "callback_data": "skip"}]]},
        )
        st["wait_text"] = q.id
        return
    lo, hi = int(q.scale_min or 1), int(q.scale_max or 10)
    vals = list(range(lo, hi + 1))
    rows = [vals[i : i + 5] for i in range(0, len(vals), 5)]
    kb = [[{"text": str(v), "callback_data": f"a:{q.id}:{v}"} for v in row] for row in rows]
    call(
        token,
        "sendMessage",
        chat_id=chat,
        text=f"{n}. {q.text}\n{lo} — совсем нет, {hi} — полностью да",
        reply_markup={"inline_keyboard": kb},
    )


def _finish(token: str, chat: int, st: dict, db: Session, part: Participant) -> None:
    from app.services.forms.submit import SubmitError, submit_response

    prog = db.get(Program, part.program_id)
    try:
        submit_response(db, prog, part, st["answers"], st.get("comment", ""), source="telegram")
    except SubmitError as e:
        call(token, "sendMessage", chat_id=chat, text=f"Не получилось сохранить: {e}")
        return
    finally:
        _state.pop((prog.organization_id, chat), None)
    integrations.log(db, prog.organization_id, "telegram", f"Анкета {part.external_id} заполнена в чате")
    call(token, "sendMessage", chat_id=chat, text="Спасибо! Ответы сохранены. Их видит только HR.")


def orgs_for(db: Session, token: str) -> list[int]:
    """Организации, которые используют этот бот (у демо — основная и все песочницы)."""
    return [
        o.id
        for o in db.query(Organization.id)
        if integrations.config(db, o.id, "telegram").get("token") == token
    ]


def route(db: Session, token: str, upd: dict) -> int | None:
    """Организация для обновления: по коду из /start или по привязанному чату."""
    msg, cb = upd.get("message"), upd.get("callback_query")
    chat = (msg or (cb or {}).get("message") or {}).get("chat", {}).get("id")
    orgs = orgs_for(db, token)
    text = (msg or {}).get("text") or ""
    if text.startswith("/start"):
        code = (text.split(maxsplit=1) + [""])[1].strip()
        for o in orgs:
            if code and code in _get(db, o, "tg_codes"):
                for other in orgs:  # чат привязан только к одной организации
                    if other != o:
                        ch = _get(db, other, "tg_chats")
                        if chat in ch.values():
                            _set(db, other, "tg_chats", {p: c for p, c in ch.items() if c != chat})
                return o
    for o in orgs:
        if chat in _get(db, o, "tg_chats").values():
            return o
    return orgs[0] if orgs else None


def handle(db: Session, org: int, token: str, upd: dict) -> None:
    """Одно обновление от Telegram."""
    msg, cb = upd.get("message"), upd.get("callback_query")
    chat = (msg or (cb or {}).get("message") or {}).get("chat", {}).get("id")
    if not chat:
        return
    chats = _get(db, org, "tg_chats")
    pid = next((int(p) for p, c in chats.items() if c == chat), None)
    if msg and (msg.get("text") or "").startswith("/start"):
        code = (msg["text"].split(maxsplit=1) + [""])[1].strip()
        target = _get(db, org, "tg_codes").get(code)
        if target:
            chats = {p: c for p, c in chats.items() if c != chat} | {str(target): chat}
            _set(db, org, "tg_chats", chats)
            part = db.get(Participant, target)
            integrations.log(db, org, "telegram", f"Подключился {part.external_id}")
            call(
                token,
                "sendMessage",
                chat_id=chat,
                text=f"Готово: вы подключены как {part.external_id}. Раз в месяц пришлю короткую анкету — можно отвечать прямо здесь.",
                reply_markup={
                    "inline_keyboard": [[{"text": "Заполнить анкету сейчас", "callback_data": "survey"}]]
                },
            )
        elif pid is None:
            call(
                token,
                "sendMessage",
                chat_id=chat,
                text="Откройте личную ссылку на бота из «Пульса адаптации» — так я пойму, кто вы.",
            )
        return
    if pid is None:
        call(
            token,
            "sendMessage",
            chat_id=chat,
            text="Сначала откройте личную ссылку на бота из «Пульса адаптации».",
        )
        return
    key = (org, chat)
    if cb:
        call(token, "answerCallbackQuery", callback_query_id=cb["id"])
        data = cb.get("data", "")
        if data == "survey":
            _state[key] = {"pid": pid, "i": 0, "answers": {}}
            _ask(token, chat, _state[key], db)
        elif data.startswith("a:") and key in _state:
            _, qid, v = data.split(":")
            st = _state[key]
            st["answers"][int(qid)] = v
            st["i"] += 1
            _ask(token, chat, st, db)
        elif data == "skip" and key in _state:
            st = _state[key]
            st.pop("wait_text", None)
            st["i"] += 1
            _ask(token, chat, st, db)
        return
    st = _state.get(key)
    if st and st.get("wait_text") and msg.get("text"):
        st["comment"] = (st.get("comment", "") + "\n" + msg["text"]).strip()
        st.pop("wait_text")
        st["i"] += 1
        _ask(token, chat, st, db)
    elif (msg.get("text") or "").lower() in ("/anketa", "анкета"):
        _state[key] = {"pid": pid, "i": 0, "answers": {}}
        _ask(token, chat, _state[key], db)
    else:
        call(
            token,
            "sendMessage",
            chat_id=chat,
            text="Я присылаю анкету раз в месяц. Заполнить сейчас — команда /anketa.",
        )


def _poll(token: str, stop: threading.Event) -> None:
    offset = 0
    while not stop.is_set():
        try:
            r = httpx.get(
                API.format(token=token, method="getUpdates"),
                params={"timeout": 25, "offset": offset},
                timeout=35,
            )
            ups = r.json().get("result", []) if r.status_code == 200 else []
        except (httpx.HTTPError, ValueError) as e:
            log.warning("Telegram getUpdates: %s", e)
            stop.wait(10)
            continue
        for u in ups:
            offset = u["update_id"] + 1
            try:
                with SessionLocal() as db:
                    org = route(db, token, u)
                    if org is not None:
                        handle(db, org, token, u)
            except Exception:  # noqa: BLE001 — одно сообщение не должно ронять бота
                log.exception("Telegram: ошибка обработки")


def supervise(stop: threading.Event) -> None:
    """Один поток на каждый подключённый бот; останавливает отключённые."""
    while not stop.is_set():
        try:
            with SessionLocal() as db:
                want = {
                    integrations.own(db, o.id, "telegram").get("token") for o in db.query(Organization.id)
                } - {None, ""}
            for tok, ev in list(_threads.items()):
                if tok not in want:
                    ev.set()
                    _threads.pop(tok)
            for tok in want - set(_threads):
                ev = threading.Event()
                threading.Thread(target=_poll, args=(tok, ev), daemon=True, name="tg-bot").start()
                _threads[tok] = ev
        except Exception:  # noqa: BLE001
            log.exception("Telegram: ошибка супервизора")
        stop.wait(20)
    for ev in _threads.values():
        ev.set()


def start() -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=supervise, args=(stop,), daemon=True, name="tg-supervisor").start()
    return stop
