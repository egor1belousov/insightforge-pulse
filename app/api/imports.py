"""Загрузка файлов: распознавание, правки, подтверждение."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.deps import HR_ONLY, require_role
from app.db.models import ImportJob, Program, User
from app.db.session import get_db
from app.services import recalc
from app.services.ingest import jobs
from app.services.llm.resolvers import ingest_resolvers

router = APIRouter(prefix="/api/import", tags=["загрузка"])


def _program(db: Session, user: User) -> Program:
    prog = db.get(Program, user.program_id) if user.program_id else None
    if prog is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Программа не найдена.")
    return prog


def _job(db: Session, job_id: int, prog: Program) -> ImportJob:
    job = db.get(ImportJob, job_id)
    if job is None or job.program_id != prog.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Загрузка не найдена.")
    return job


def job_out(job: ImportJob) -> dict:
    return {"id": job.id, "status": job.status, "files": job.files, "schema": job.schema}


@router.post("/upload")
async def upload(
    files: list[UploadFile] = File(...),
    user: User = Depends(require_role(*HR_ONLY)),
    db: Session = Depends(get_db),
) -> dict:
    prog = _program(db, user)
    data = [(f.filename or "file", await f.read()) for f in files]
    try:
        job = jobs.create_job(db, prog, data, ingest_resolvers())
    except jobs.ImportError_ as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return job_out(job)


@router.get("/{job_id}/schema")
def get_schema(
    job_id: int, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    return job_out(_job(db, job_id, _program(db, user)))


@router.put("/{job_id}/schema")
def put_schema(
    job_id: int, schema: dict, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)
) -> dict:
    prog = _program(db, user)
    try:
        job = jobs.update_schema(db, _job(db, job_id, prog), schema)
    except jobs.ImportError_ as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return job_out(job)


@router.post("/{job_id}/confirm")
def confirm(job_id: int, user: User = Depends(require_role(*HR_ONLY)), db: Session = Depends(get_db)) -> dict:
    prog = _program(db, user)
    job = _job(db, job_id, prog)
    try:
        stats = jobs.confirm(db, job, prog)
    except (jobs.ImportError_, ValueError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    stats["recalc"] = recalc.after_import(db, prog)
    return stats
