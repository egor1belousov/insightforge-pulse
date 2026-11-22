"""Пересчёт аналитики после изменения данных и рассылка событий."""

from sqlalchemy.orm import Session

from app.db.models import Program
from app.services.events.bus import bus


def after_import(db: Session, program: Program) -> dict:
    """Вызывается после подтверждённой загрузки."""
    bus.publish(program.id, "data_imported", {"program_id": program.id})
    return {"published": True}
