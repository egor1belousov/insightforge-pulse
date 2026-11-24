"""Интеграции: подключение из интерфейса, проверка, журнал; ссылки на Telegram-бота."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.deps import HR_ONLY, current_user, require_role
from app.db.models import Participant, Program, User
from app.db.session import get_db
from app.services import integrations, telegram
from app.services.forms import connectors

router = APIRouter(prefix="/api", tags=["интеграции"])


def _org(user: User) -> int:
    return user.organization_id


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@router.get("/integrations")
def list_integrations(
    request: Request, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    return integrations.public(db, _org(user), _base(request))


@router.post("/integrations/{kind}")
def connect(
    kind: str,
    data: dict,
    request: Request,
    user: User = Depends(require_role(*HR_ONLY)),
    db: Session = Depends(get_db),
) -> dict:
    if kind not in integrations.KINDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Нет такой интеграции.")
    try:
        integrations.connect(db, _org(user), kind, data)
    except integrations.CheckError as e:
        integrations.log(db, _org(user), kind, str(e), ok=False)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return integrations.public(db, _org(user), _base(request))[kind]


@router.delete("/integrations/{kind}")
def disconnect(
    kind: str, request: Request, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    if kind not in integrations.KINDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Нет такой интеграции.")
    integrations.disconnect(db, _org(user), kind)
    return integrations.public(db, _org(user), _base(request))[kind]


@router.post("/integrations/{kind}/sync")
def sync(kind: str, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)) -> dict:
    """Забрать ответы формы прямо сейчас, не дожидаясь опроса."""
    if kind not in ("yandex", "google", "yandex_mail"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Синхронизация есть только у форм.")
    cfg = integrations.config(db, _org(user), kind)
    if not cfg:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Сначала подключите форму.")
    try:
        owner = integrations.config_owner(db, _org(user), kind)
        prog = db.query(Program).filter(Program.organization_id == owner).order_by(Program.id).first()
        n = connectors.poll(db, prog.id if prog else user.program_id, kind, cfg, org=owner)
    except Exception as e:  # noqa: BLE001 — ошибку внешнего сервиса показываем HR
        integrations.log(db, _org(user), kind, f"Ошибка загрузки: {str(e)[:140]}", ok=False)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Форма не ответила: {str(e)[:140]}") from e
    integrations.log(db, _org(user), kind, f"Загружено новых ответов: {n}")
    return {"ok": True, "new": n, "message": f"Новых ответов: {n}"}


@router.get("/telegram/link")
def my_link(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Личная ссылка на бота для стажёра или наставника."""
    part = db.query(Participant).filter(Participant.user_id == user.id).first()
    if part is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ссылка есть только у стажёров и наставников.")
    org = db.get(Program, part.program_id).organization_id
    return {"link": telegram.link_for(db, part), "linked": telegram.chat_of(db, org, part.id) is not None}


@router.get("/participants/{pid}/telegram")
def participant_link(
    pid: int, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    part = db.get(Participant, pid)
    if part is None or db.get(Program, part.program_id).organization_id != user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Участник не найден.")
    return {
        "link": telegram.link_for(db, part),
        "linked": telegram.chat_of(db, user.organization_id, part.id) is not None,
    }
