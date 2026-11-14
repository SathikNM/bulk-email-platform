"""Celery tasks. Each task opens its own scoped session (RLS applies to workers too)."""
import logging
import uuid

from app.db.session import worker_session
from app.models import ImportJob
from app.models.enums import JobStatus
from app.services import imports
from app.workers.celery_app import celery

log = logging.getLogger(__name__)


@celery.task(name="bep.run_import")
def run_import(job_id: str, workspace_id: str) -> None:
    db = worker_session(uuid.UUID(workspace_id))
    try:
        job = db.get(ImportJob, uuid.UUID(job_id))
        if job is None or job.status != JobStatus.PENDING:
            return
        try:
            imports.run_job(db, job)
        except Exception as e:  # noqa: BLE001
            log.exception("Import %s failed", job_id)
            db.rollback()
            job = db.get(ImportJob, uuid.UUID(job_id))
            job.status = JobStatus.FAILED
            job.errors = [{"row": 0, "error": f"Import failed: {str(e)[:300]}"}]
            db.commit()
    finally:
        db.close()
