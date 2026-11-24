"""Интеграции организации: Яндекс Формы, Google Forms, рабочая почта, Telegram-бот.

Настройки хранятся в таблице настроек организации и задаются на экране «Настройки».
Значения из .env — запасной вариант для организации, где интеграция не настроена.
Секреты наружу не отдаются: в интерфейсе видны только последние символы.
"""

import json
import re
import secrets
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage

import httpx
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.models import AppSetting

OPTIONAL = {"org_id"}
FORM_ID_RE = re.compile(r"[a-fA-F\d]{24}")

KINDS: dict[str, dict] = {
    "yandex": {
        "title": "Яндекс Формы",
        "desc": "Ответы анкеты приходят сами: опрос по API каждые 15 секунд и вебхук",
        "fields": [
            (
                "token",
                "OAuth-токен",
                True,
                "oauth.yandex.ru → приложение с доступом «Просмотр настроек форм (forms:read)»",
            ),
            ("form_id", "ID формы", False, "24 символа из адреса формы, можно вставить ссылку целиком"),
            (
                "org_id",
                "ID организации",
                False,
                "Форма организации: Yandex Cloud — ID вида bpf… (консоль → Организация), Яндекс 360 — число из tracker.yandex.ru/admin/orgs",
            ),
        ],
    },
    "google": {
        "title": "Google Forms",
        "desc": "Альтернатива Яндекс Формам: опрос ответов по API",
        "fields": [
            (
                "credentials",
                "OAuth-доступ (JSON)",
                True,
                "client_id, client_secret, refresh_token из Google Cloud",
            ),
            ("form_id", "ID формы", False, "Из адреса формы: docs.google.com/forms/d/<ID>/edit"),
        ],
    },
    "smtp": {
        "title": "Рабочая почта",
        "desc": "Приглашения и напоминания письмом со ссылкой на анкету",
        "fields": [
            ("host", "SMTP-сервер", False, "Например, smtp.yandex.ru"),
            ("port", "Порт", False, "587 (STARTTLS) или 465 (SSL)"),
            ("user", "Логин", False, "Адрес отправителя"),
            ("password", "Пароль приложения", True, "Пароль приложения почтового сервиса"),
        ],
    },
    "telegram": {
        "title": "Telegram-бот",
        "desc": "Напоминания и ответы на анкету прямо в чате",
        "fields": [("token", "Токен бота", True, "Выдаёт @BotFather командой /newbot")],
    },
}


def _row(db: Session, org: int, key: str) -> AppSetting | None:
    return db.query(AppSetting).filter(AppSetting.organization_id == org, AppSetting.key == key).first()


def _put(db: Session, org: int, key: str, value) -> None:
    row = _row(db, org, key)
    if row is None:
        db.add(AppSetting(organization_id=org, key=key, value=value))
    else:
        row.value = value
    db.commit()


def _env(kind: str) -> dict:
    s = get_settings()
    return {
        "yandex": {
            "token": s.yandex_forms_token,
            "form_id": s.yandex_form_id,
            "secret": s.yandex_webhook_secret,
        },
        "google": {"credentials": s.google_forms_credentials, "form_id": s.google_form_id},
        "smtp": {
            "host": s.smtp_host,
            "port": str(s.smtp_port),
            "user": s.smtp_user,
            "password": s.smtp_password,
        },
        "telegram": {"token": ""},
    }[kind]


def demo_template(db: Session) -> int | None:
    """Основная демо-организация (не песочница) — от неё песочницы берут интеграции."""
    from app.db.models import Organization, User

    row = (
        db.query(User.organization_id)
        .join(Organization, Organization.id == User.organization_id)
        .filter(User.email == "hr@pulse.demo", Organization.sandbox_token.is_(None))
        .first()
    )
    return row[0] if row else None


def is_sandbox(db: Session, org: int) -> bool:
    from app.db.models import Organization

    o = db.get(Organization, org)
    return bool(o and o.sandbox_token)


def own(db: Session, org: int, kind: str) -> dict:
    """Интеграция, подключённая именно в этой организации."""
    row = _row(db, org, f"int_{kind}")
    return row.value if row and row.value and row.value.get("connected") else {}


def config(db: Session, org: int, kind: str) -> dict:
    """Рабочая конфигурация: своя, у песочницы демо — от основной демо-организации, иначе из .env."""
    cfg = own(db, org, kind)
    if cfg:
        return cfg
    if is_sandbox(db, org):
        tmpl = demo_template(db)
        if tmpl and tmpl != org:
            shared = own(db, tmpl, kind)
            if shared:
                return shared | {"source": "demo"}
    env = _env(kind)
    required = [f for f, _, _, _ in KINDS[kind]["fields"] if f != "port"]
    if all(env.get(f) for f in required):
        return env | {"connected": True, "source": "env"}
    return {}


def connected(db: Session, org: int, kind: str) -> bool:
    return bool(config(db, org, kind))


def log(db: Session, org: int, kind: str, text: str, ok: bool = True) -> None:
    """Запись в журнал интеграции (последние 20 событий)."""
    row = _row(db, org, f"intlog_{kind}")
    items = list(row.value) if row and row.value else []
    items.insert(0, {"at": datetime.now().isoformat(timespec="seconds"), "text": text, "ok": ok})
    _put(db, org, f"intlog_{kind}", items[:20])


def _mask(v: str) -> str:
    v = str(v or "")
    return "" if not v else ("•" * 6 + v[-4:] if len(v) > 6 else "•" * len(v))


def public(db: Session, org: int, base_url: str = "") -> dict:
    """Состояние всех интеграций для экрана: без секретов."""
    out = {}
    for kind, meta in KINDS.items():
        cfg = config(db, org, kind)
        logrow = _row(db, org, f"intlog_{kind}")
        item = {
            "kind": kind,
            "title": meta["title"],
            "desc": meta["desc"],
            "connected": bool(cfg),
            "source": cfg.get("source", "settings") if cfg else None,
            "info": cfg.get("info") if cfg else None,
            "fields": [
                {
                    "key": f,
                    "label": label,
                    "secret": sec,
                    "help": help_,
                    "value": _mask(cfg.get(f)) if sec else cfg.get(f, ""),
                }
                for f, label, sec, help_ in meta["fields"]
            ],
            "log": (logrow.value if logrow and logrow.value else [])[:8],
        }
        if kind == "yandex" and cfg:
            item["webhook"] = f"{base_url}/api/forms/yandex/webhook?token={cfg.get('secret', '')}"
        out[kind] = item
    return out


class CheckError(Exception):
    """Проверка подключения не прошла — текст для HR."""


def check(kind: str, cfg: dict) -> str:
    """Настоящая проверка подключения. Возвращает описание, что подключено.

    Raises:
        CheckError: понятная причина, почему не подключилось.
    """
    try:
        if kind == "telegram":
            r = httpx.get(f"https://api.telegram.org/bot{cfg['token']}/getMe", timeout=10)
            data = r.json()
            if not data.get("ok"):
                raise CheckError("Telegram не принял токен: " + str(data.get("description", r.status_code)))
            return "@" + data["result"]["username"]
        if kind == "yandex":
            s = get_settings()
            r = httpx.get(
                f"{s.yandex_forms_api}/surveys/{cfg['form_id']}/answers",
                params={"page_size": 1},
                headers=yandex_headers(cfg),
                timeout=10,
            )
            if r.status_code == 401:
                raise CheckError(
                    "Яндекс не принял токен. Получите новый на oauth.yandex.ru и вставьте целиком."
                )
            if r.status_code == 403:
                raise CheckError(
                    "Нет доступа к ответам формы. Токен должен быть выдан владельцу формы; "
                    "для формы организации укажите ID организации."
                )
            if r.status_code == 404:
                raise CheckError("Форма с таким ID не найдена у этого аккаунта.")
            r.raise_for_status()
            cols = r.json().get("columns") or []
            return f"форма …{cfg['form_id'][-6:]}, вопросов: {len(cols)}"
        if kind == "google":
            from app.services.forms.connectors import _google_token

            try:
                creds = json.loads(cfg["credentials"])
            except json.JSONDecodeError as e:
                raise CheckError(
                    "Доступ Google должен быть JSON с client_id, client_secret, refresh_token."
                ) from e
            token = _google_token(creds)
            r = httpx.get(
                f"https://forms.googleapis.com/v1/forms/{cfg['form_id']}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if r.status_code == 404:
                raise CheckError("Форма с таким ID не найдена.")
            r.raise_for_status()
            return (r.json().get("info", {}).get("title") or cfg["form_id"])[:80]
        if kind == "smtp":
            with _smtp(cfg) as srv:
                srv.noop()
            return cfg["user"]
    except CheckError:
        raise
    except (httpx.HTTPError, smtplib.SMTPException, OSError, KeyError, ValueError) as e:
        raise CheckError(f"Не удалось подключиться: {str(e)[:160]}") from e
    raise CheckError("Неизвестная интеграция.")


def connect(db: Session, org: int, kind: str, data: dict) -> dict:
    """Проверяет и сохраняет интеграцию. Пустое секретное поле — оставить прежнее значение.

    Raises:
        CheckError: если проверка не прошла; настройки при этом не меняются.
    """
    old = (_row(db, org, f"int_{kind}").value or {}) if _row(db, org, f"int_{kind}") else {}
    cfg = {}
    for f, label, sec, _ in KINDS[kind]["fields"]:
        v = str(data.get(f) or "").strip()
        if sec and (not v or v.startswith("•")):
            v = old.get(f, "")
        if not v and f == "port":
            v = "587"
        if f == "form_id" and kind == "yandex":
            m = FORM_ID_RE.search(v)
            if not m:
                raise CheckError("ID формы — 24 символа из адреса формы (буквы a–f и цифры).")
            v = m.group(0)
        if not v and f in OPTIONAL:
            cfg[f] = ""
            continue
        if not v:
            raise CheckError(f"Заполните поле «{label}».")
        cfg[f] = v
    info = check(kind, cfg)
    cfg |= {"connected": True, "info": info, "secret": old.get("secret") or secrets.token_urlsafe(18)}
    _put(db, org, f"int_{kind}", cfg)
    log(db, org, kind, f"Подключено: {info}")
    return cfg


def disconnect(db: Session, org: int, kind: str) -> None:
    _put(db, org, f"int_{kind}", {"connected": False})
    log(db, org, kind, "Отключено")


def yandex_headers(cfg: dict) -> dict:
    """Заголовки API Яндекс Форм: OAuth и, для формы организации, X-Org-Id."""
    h = {"Authorization": f"OAuth {cfg['token']}"}
    org = str(cfg.get("org_id") or "").strip()
    if org:
        # организация Yandex Cloud (Identity Hub) — идентификатор вида bpf…, Яндекс 360 — числовой
        h["X-Org-Id" if org.isdigit() else "X-Cloud-Org-Id"] = org
    return h


def _smtp(cfg: dict) -> smtplib.SMTP:
    port = int(cfg.get("port") or 587)
    ctx = ssl.create_default_context()
    if port == 465:
        srv: smtplib.SMTP = smtplib.SMTP_SSL(cfg["host"], port, timeout=10, context=ctx)
    else:
        srv = smtplib.SMTP(cfg["host"], port, timeout=10)
        srv.starttls(context=ctx)
    srv.login(cfg["user"], cfg["password"])
    return srv


def send_email(db: Session, org: int, to: str | None, title: str, text: str, link: str) -> str:
    """Письмо со ссылкой на анкету. Возвращает «отправлено» или причину."""
    if not to:
        return "нет почты участника"
    if to.endswith("@pulse.demo"):
        return "демо-адрес, письмо не отправляется"
    cfg = config(db, org, "smtp")
    if not cfg:
        return "почта не подключена"
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = title, cfg["user"], to
    base = get_settings().public_url.rstrip("/")
    msg.set_content(f"{text}\n\nЗаполнить анкету: {base}{link}\n\nОтветы видит только HR.")
    try:
        with _smtp(cfg) as srv:
            srv.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        log(db, org, "smtp", f"Письмо {to} не ушло: {str(e)[:120]}", ok=False)
        return "ошибка почтового сервера"
    log(db, org, "smtp", f"Письмо {to}: {title}")
    return "отправлено"


def active_demo_org(db: Session, org: int) -> int:
    """Куда класть ответ внешней формы основной демо-организации: в песочницу, где сейчас идёт показ."""
    from datetime import datetime, timedelta

    from app.db.models import Organization

    if org != demo_template(db):
        return org
    recent = (
        db.query(Organization)
        .filter(
            Organization.sandbox_claimed_at.is_not(None),
            Organization.sandbox_seen_at
            >= datetime.utcnow() - timedelta(hours=get_settings().demo_sandbox_hours),
        )
        .order_by(Organization.sandbox_seen_at.desc())
        .first()
    )
    return recent.id if recent else org


def org_by_secret(db: Session, kind: str, secret: str) -> int | None:
    """Организация по секрету вебхука."""
    if not secret:
        return None
    for row in db.query(AppSetting).filter(AppSetting.key == f"int_{kind}"):
        if (
            row.value
            and row.value.get("connected")
            and secrets.compare_digest(str(row.value.get("secret", "")), secret)
        ):
            return row.organization_id
    return None
