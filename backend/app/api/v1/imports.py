"""CSV/XLSX imports for companies, contacts and suppressions (async via Celery)."""
import csv
import io
import json
import uuid

import sqlalchemy as sa
from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response

from app.core.config import settings
from app.core.deps import Ctx, Marketer
from app.core.errors import BadRequest
from app.models import ImportJob
from app.models.enums import ImportEntity, MemberRole
from app.services import imports, storage
from app.services.common import audit, get_or_404, paginate, row_dict
from app.services.jobs import enqueue_after_commit

router = APIRouter(prefix="/imports", tags=["imports"])


async def _read(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise BadRequest(f"File exceeds {settings.MAX_UPLOAD_MB} MB")
    if not (file.filename or "").lower().endswith((".csv", ".txt", ".xlsx", ".xlsm")):
        raise BadRequest("Upload a .csv or .xlsx file")
    return data


@router.post("/preview")
async def preview(entity: ImportEntity = Form(...), file: UploadFile = File(...), ctx: Ctx = Marketer):
    data = await _read(file)
    try:
        return imports.preview(data, file.filename or "upload.csv", entity)
    except ValueError as e:
        raise BadRequest(str(e)) from None


@router.post("", status_code=202)
async def start_import(entity: ImportEntity = Form(...), file: UploadFile = File(...),
                       column_mapping: str = Form(...), options: str = Form("{}"),
                       ctx: Ctx = Marketer):
    if entity == ImportEntity.SUPPRESSION and not ctx.at_least(MemberRole.ADMIN):
        raise BadRequest("Suppression imports require admin role")
    data = await _read(file)
    try:
        mapping = json.loads(column_mapping)
        opts = json.loads(options or "{}")
    except json.JSONDecodeError:
        raise BadRequest("column_mapping and options must be JSON objects") from None
    if not isinstance(mapping, dict):
        raise BadRequest("column_mapping must map file headers to field names")
    allowed = set(imports.FIELDS[entity])
    bad = [v for v in mapping.values() if v and v not in allowed]
    if bad:
        raise BadRequest(f"Unknown target field(s): {', '.join(bad)}")
    key = storage.new_key(ctx.workspace_id, "imports", file.filename or "upload.csv")
    storage.put(key, data)
    job = ImportJob(workspace_id=ctx.workspace_id, entity=entity, file_key=key,
                    original_filename=file.filename, column_mapping=mapping, options=opts,
                    created_by=ctx.user.id)
    ctx.db.add(job)
    ctx.db.flush()
    audit(ctx, "import_started", entity.value, job.id, after={"file": file.filename})
    from app.workers.tasks import run_import
    enqueue_after_commit(ctx.db, run_import, str(job.id), str(ctx.workspace_id))
    return row_dict(job)


@router.get("")
def list_jobs(ctx: Ctx = Marketer, page: int = 1, page_size: int = 20, entity: ImportEntity | None = None):
    stmt = sa.select(ImportJob).order_by(ImportJob.created_at.desc())
    if entity:
        stmt = stmt.where(ImportJob.entity == entity)
    return paginate(ctx.db, stmt, page, page_size, lambda j: {**row_dict(j), "errors": len(j.errors or [])})


@router.get("/{job_id}")
def get_job(job_id: uuid.UUID, ctx: Ctx = Marketer):
    return row_dict(get_or_404(ctx.db, ImportJob, job_id, "Import job"))


@router.get("/{job_id}/errors.csv")
def job_errors(job_id: uuid.UUID, ctx: Ctx = Marketer):
    job = get_or_404(ctx.db, ImportJob, job_id, "Import job")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["row", "error"])
    for e in job.errors or []:
        w.writerow([e.get("row"), e.get("error")])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="import-{job_id}-errors.csv"'})


@router.get("/templates/{entity}.csv")
def template(entity: ImportEntity, ctx: Ctx = Marketer):
    _ = uuid  # keep import used
    return Response("﻿" + ",".join(imports.FIELDS[entity]) + "\n", media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{entity.value}-template.csv"'})
