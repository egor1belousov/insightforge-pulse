"""Регистрация, вход, приглашения."""

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password, new_token, verify_password
from app.core.settings import get_settings
from app.db.models import Invite, Organization, Participant, Program, Topic, User

log = logging.getLogger("pulse.accounts")

DEFAULT_TOPICS: list[tuple[str, str]] = [
    ("tasks", "Понимание задач"),
    ("auto", "Самостоятельность"),
    ("support", "Поддержка"),
    ("load", "Нагрузка"),
    ("feedback", "Обратная связь"),
    ("growth", "Перспективы"),
]
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 10
MAX_TEXT = 200  # длина строковых столбцов имени, почты, организации и потока
MAX_PASSWORD = 128
EMAIL_TAKEN = "Эта почта уже зарегистрирована. Войдите или восстановите доступ у HR."


class AccountError(ValueError):
    """Ошибка с понятным пользователю текстом."""


@dataclass
class InviteInfo:
    """Сведения о приглашении для страницы принятия."""

    email: str
    role: str
    external_id: str | None
    organization: str


def _check_email(email: str) -> str:
    email = email.strip().lower()
    if len(email) > MAX_TEXT or not EMAIL_RE.match(email):
        raise AccountError("Введите рабочую почту, например hr@pulse.demo.")
    return email


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AccountError(f"Пароль должен быть не короче {MIN_PASSWORD} символов.")
    if len(password) > MAX_PASSWORD:
        raise AccountError(f"Пароль должен быть не длиннее {MAX_PASSWORD} символов.")


def _check_length(**fields: str) -> None:
    labels = {"name": "Имя", "organization": "Название организации", "program": "Название программы"}
    for key, value in fields.items():
        if len(value.strip()) > MAX_TEXT:
            raise AccountError(f"{labels[key]}: не больше {MAX_TEXT} символов.")


def _commit_user(db: Session) -> None:
    """Сохраняет нового пользователя; одновременная регистрация той же почты — понятная ошибка."""
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise AccountError(EMAIL_TAKEN) from e


def ensure_topics(db: Session, organization_id: int) -> None:
    """Создаёт темы по умолчанию для организации, если их ещё нет."""
    have = {t.code for t in db.query(Topic).filter(Topic.organization_id == organization_id)}
    for code, name in DEFAULT_TOPICS:
        if code not in have:
            db.add(Topic(organization_id=organization_id, code=code, name=name))


def default_questionnaires(db: Session, program: Program) -> None:
    """Стандартная анкета потока: шесть зеркальных вопросов стажёру и наставнику по темам и комментарий."""
    from app.seed import demo_schema
    from app.services.ingest.persist import save_questionnaires

    save_questionnaires(db, program, {"questionnaires": demo_schema()["questionnaires"], "pairs": []})


def register_hr(
    db: Session, *, name: str, email: str, password: str, organization: str, program: str
) -> User:
    """Регистрирует HR: создаёт организацию, программу и пользователя.

    Raises:
        AccountError: если данные некорректны или почта занята.
    """
    email = _check_email(email)
    _check_password(password)
    if not name.strip() or not organization.strip() or not program.strip():
        raise AccountError("Заполните имя, организацию и название программы.")
    _check_length(name=name, organization=organization, program=program)
    if db.query(User).filter(User.email == email).first():
        raise AccountError(EMAIL_TAKEN)
    org = Organization(name=organization.strip())
    db.add(org)
    db.flush()
    prog = Program(organization_id=org.id, name=program.strip(), start_date=date.today().replace(day=1))
    db.add(prog)
    db.flush()
    ensure_topics(db, org.id)
    default_questionnaires(db, prog)
    user = User(
        email=email,
        password_hash=hash_password(password),
        name=name.strip(),
        role="hr",
        organization_id=org.id,
        program_id=prog.id,
    )
    db.add(user)
    _commit_user(db)
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    """Проверяет почту и пароль.

    Raises:
        AccountError: если пара неверна.
    """
    user = db.query(User).filter(User.email == email.strip().lower()).first()
    if not user or not verify_password(password, user.password_hash):
        raise AccountError("Неверная почта или пароль.")
    return user


def create_invite(db: Session, *, by: User, email: str, role: str, external_id: str | None) -> Invite:
    """Создаёт одноразовое приглашение на 7 дней.

    Raises:
        AccountError: если роль или почта некорректны.
    """
    email = _check_email(email)
    if role not in ("hr", "lead", "mentor", "intern"):
        raise AccountError("Роль приглашения: HR, руководитель, наставник или стажёр.")
    if db.query(User).filter(User.email == email).first():
        raise AccountError("Пользователь с этой почтой уже есть.")
    ext = (external_id or "").strip()[:50] or None
    if role in ("hr", "lead"):
        ext = None
    inv = Invite(
        token=new_token(),
        email=email,
        role=role,
        external_id=ext,
        organization_id=by.organization_id,
        program_id=by.program_id,
        expires_at=datetime.now() + timedelta(days=get_settings().invite_days),
        created_by=by.id,
    )
    db.add(inv)
    db.commit()
    log.info("Приглашение для %s (%s): /invite/%s", email, role, inv.token)
    return inv


def _valid_invite(db: Session, token: str) -> Invite:
    inv = db.query(Invite).filter(Invite.token == token).first()
    if not inv:
        raise AccountError("Приглашение не найдено.")
    if inv.used_at is not None:
        raise AccountError("Приглашение уже использовано. Войдите с паролем.")
    if inv.expires_at < datetime.now():
        raise AccountError("Срок приглашения истёк. Попросите HR отправить новое.")
    return inv


def invite_info(db: Session, token: str) -> InviteInfo:
    """Возвращает сведения о действующем приглашении."""
    inv = _valid_invite(db, token)
    org = db.get(Organization, inv.organization_id)
    return InviteInfo(
        email=inv.email, role=inv.role, external_id=inv.external_id, organization=org.name if org else ""
    )


def accept_invite(db: Session, token: str, *, name: str, password: str) -> User:
    """Принимает приглашение: создаёт пользователя и привязывает его к участнику.

    Raises:
        AccountError: если приглашение недействительно или данные некорректны.
    """
    inv = _valid_invite(db, token)
    _check_password(password)
    if not name.strip():
        raise AccountError("Введите имя.")
    _check_length(name=name)
    if db.query(User).filter(User.email == inv.email).first():
        raise AccountError("Пользователь с этой почтой уже есть.")
    user = User(
        email=inv.email,
        password_hash=hash_password(password),
        name=name.strip(),
        role=inv.role,
        organization_id=inv.organization_id,
        program_id=inv.program_id,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise AccountError("Пользователь с этой почтой уже есть.") from e
    if inv.role in ("mentor", "intern") and inv.program_id:
        ext = inv.external_id or ("С-" if inv.role == "intern" else "Н-") + str(user.id + 100)
        part = (
            db.query(Participant)
            .filter(Participant.program_id == inv.program_id, Participant.external_id == ext)
            .first()
        )
        if part is None:
            part = Participant(program_id=inv.program_id, external_id=ext, side=inv.role)
            db.add(part)
        part.user_id = user.id
    inv.used_at = datetime.now()
    _commit_user(db)
    return user
