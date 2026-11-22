"""Задания загрузки: хранение файлов, анализ, подтверждение."""

import re
import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.models import ImportJob, MappingProfile, Program
from app.services.ingest import pipeline
from app.services.ingest.persist import persist

ALLOWED = pipeline.STRUCT_EXT | pipeline.TABLE_EXT


class ImportError_(ValueError):
    """Ошибка загрузки с понятным текстом."""


def job_dir(job_id: int) -> Path:
    """Папка с файлами задания."""
    return Path(get_settings().upload_dir) / f"job_{job_id}"


def job_files(job: ImportJob) -> list[Path]:
    """Файлы задания в порядке загрузки."""
    d = job_dir(job.id)
    return [d / f["stored"] for f in job.files]


def _safe_name(name: str) -> str:
    base = Path(name).name
    return re.sub(r"[^\w.\-() ]", "_", base)[:150] or "file"


def create_job(
    db: Session,
    program: Program,
    uploads: list[tuple[str, bytes]],
    resolvers: pipeline.Resolvers | None = None,
) -> ImportJob:
    """Сохраняет файлы, распознаёт их и создаёт задание со схемой.

    Raises:
        ImportError_: если файлов нет или формат не поддерживается.
    """
    if not uploads:
        raise ImportError_("Добавьте файлы: Excel или CSV с ответами и Word со структурой анкет.")
    limit = get_settings().max_upload_mb * 1024 * 1024
    for name, data in uploads:
        if Path(name).suffix.lower() not in ALLOWED:
            raise ImportError_(f"Файл «{name}» не поддерживается. Нужны .xlsx, .xls, .csv или .docx.")
        if len(data) > limit:
            raise ImportError_(f"Файл «{name}» больше {get_settings().max_upload_mb} МБ.")
    job = ImportJob(program_id=program.id, files=[], status="draft")
    db.add(job)
    db.flush()
    d = job_dir(job.id)
    d.mkdir(parents=True, exist_ok=True)
    files = []
    for name, data in uploads:
        stored = _safe_name(name)
        (d / stored).write_bytes(data)
        files.append({"name": name, "stored": stored, "size": len(data)})
    job.files = files
    paths = job_files(job)
    try:
        schema = pipeline.analyze(paths, resolvers)
        profile = (
            db.query(MappingProfile)
            .filter(
                MappingProfile.organization_id == program.organization_id,
                MappingProfile.signature == schema["signature"],
            )
            .order_by(MappingProfile.id.desc())
            .first()
        )
        if profile:
            schema = pipeline.analyze(paths, resolvers, profile=profile.schema)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        shutil.rmtree(d, ignore_errors=True)
        raise ImportError_(f"Не удалось разобрать файлы: {e}") from e
    if not schema["tables"]:
        db.rollback()
        shutil.rmtree(d, ignore_errors=True)
        raise ImportError_("В файлах не найдено таблиц с ответами: нужна колонка с ID участников.")
    job.schema = schema
    job.quality = schema["issues"]
    db.commit()
    return job


def update_schema(db: Session, job: ImportJob, schema: dict) -> ImportJob:
    """Принимает правки HR и пересчитывает зависимые решения."""
    if job.status != "draft":
        raise ImportError_("Загрузка уже подтверждена.")
    try:
        job.schema = pipeline.refresh(job_files(job), schema)
    except (ValueError, KeyError) as e:
        raise ImportError_(f"Не удалось применить правки: {e}") from e
    job.quality = job.schema["issues"]
    db.commit()
    return job


def confirm(db: Session, job: ImportJob, program: Program) -> dict:
    """Записывает данные в БД и сохраняет профиль сопоставления."""
    if job.status != "draft":
        raise ImportError_("Загрузка уже подтверждена.")
    records = pipeline.build_records(job_files(job), job.schema)
    stats = persist(db, program, job.schema, records)
    db.add(
        MappingProfile(
            organization_id=program.organization_id,
            signature=job.schema["signature"],
            schema=pipeline.profile_from_schema(job.schema),
        )
    )
    job.status = "confirmed"
    db.commit()
    return stats
