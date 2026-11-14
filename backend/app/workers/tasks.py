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


@celery.task(name="bep.verify_contacts")
def verify_contacts(workspace_id: str, contact_ids: list[str]) -> dict:
    from app.models import Contact
    from app.services.verification import verify

    db = worker_session(uuid.UUID(workspace_id))
    counts: dict[str, int] = {}
    try:
        for cid in contact_ids:
            c = db.get(Contact, uuid.UUID(cid))
            if c is None:
                continue
            status, _reason = verify(c.email)
            if status is not None:
                c.email_verification_status = status
                counts[status.value] = counts.get(status.value, 0) + 1
            else:
                counts["inconclusive"] = counts.get("inconclusive", 0) + 1
        db.commit()
        return counts
    finally:
        db.close()


# ---------------------------------------------------------------- bulk sending

def _enqueue_batches(campaign_id: str, workspace_id: str, n: int, countdown: int = 0) -> None:
    for _ in range(max(n, 0)):
        send_batch.apply_async((campaign_id, workspace_id), countdown=countdown)


@celery.task(name="bep.prepare_campaign")
def prepare_campaign(campaign_id: str, workspace_id: str) -> int:
    from app.services import sending

    db = worker_session(uuid.UUID(workspace_id))
    try:
        n = sending.prepare(db, uuid.UUID(campaign_id))
    except Exception as e:  # noqa: BLE001
        log.exception("prepare_campaign %s failed", campaign_id)
        db.rollback()
        from app.models import Campaign
        from app.models.enums import CampaignStatus
        c = db.get(Campaign, uuid.UUID(campaign_id))
        if c is not None:
            c.status, c.last_error = CampaignStatus.FAILED, f"Preparation failed: {e}"[:500]
            db.commit()
        return 0
    finally:
        db.close()
    _enqueue_batches(campaign_id, workspace_id, n)
    return n


@celery.task(name="bep.send_batch", bind=True, max_retries=None)
def send_batch(self, campaign_id: str, workspace_id: str) -> dict:
    from app.services import sending

    db = worker_session(uuid.UUID(workspace_id))
    try:
        out = sending.send_batch(db, uuid.UUID(campaign_id))
    finally:
        db.close()
    if not out["stop"] and out["retry_in"] and not celery.conf.task_always_eager:
        send_batch.apply_async((campaign_id, workspace_id), countdown=out["retry_in"])
    return out


@celery.task(name="bep.dispatch_due_campaigns")
def dispatch_due_campaigns() -> int:
    from datetime import datetime, timezone

    import sqlalchemy as sa

    from app.models import Campaign
    from app.models.enums import CampaignStatus

    db = worker_session(system=True)
    try:
        due = db.execute(sa.select(Campaign.id, Campaign.workspace_id).where(
            Campaign.status == CampaignStatus.SCHEDULED, Campaign.scheduled_at <= datetime.now(timezone.utc),
            Campaign.approved_at.isnot(None), Campaign.deleted_at.is_(None))).all()
    finally:
        db.close()
    for cid, ws in due:
        prepare_campaign.delay(str(cid), str(ws))
    return len(due)


@celery.task(name="bep.resume_stalled")
def resume_stalled() -> dict:
    """Recover after worker crashes: fail rows stuck in `sending`, re-enqueue campaigns with queued rows."""
    from datetime import datetime, timedelta, timezone

    import sqlalchemy as sa

    from app.models import Campaign, CampaignRecipient
    from app.models.enums import CampaignStatus, RecipientStatus
    from app.services import sending

    db = worker_session(system=True)
    try:
        stuck = sending.recover_stuck(db)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=2)
        rows = db.execute(sa.select(Campaign.id, Campaign.workspace_id, sa.func.count(CampaignRecipient.id))
                          .join(CampaignRecipient, CampaignRecipient.campaign_id == Campaign.id)
                          .where(Campaign.status == CampaignStatus.SENDING,
                                 CampaignRecipient.status == RecipientStatus.QUEUED,
                                 sa.or_(CampaignRecipient.next_attempt_at.is_(None),
                                        CampaignRecipient.next_attempt_at <= datetime.now(timezone.utc)),
                                 CampaignRecipient.updated_at < cutoff)
                          .group_by(Campaign.id)).all()
        db.commit()
    finally:
        db.close()
    for cid, ws, n in rows:
        _enqueue_batches(str(cid), str(ws), -(-n // 50))
    return {"stuck_failed": stuck, "campaigns_resumed": len(rows)}


# ---------------------------------------------------------------- analytics

@celery.task(name="bep.rollup_all_stats")
def rollup_all_stats() -> int:
    from app.services import analytics

    db = worker_session(system=True)
    try:
        ids = analytics.campaigns_with_recent_events(db)
        for cid in ids:
            analytics.rollup_campaign(db, cid)
        db.commit()
        return len(ids)
    finally:
        db.close()
