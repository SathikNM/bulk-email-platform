"""Bulk email engine: recipient snapshot, batch claiming, throttling, retries, idempotency.

Guarantees
- Each (campaign, contact) and (campaign, email) is inserted once (DB unique constraints).
- Rows are claimed with SELECT ... FOR UPDATE SKIP LOCKED and moved queued -> sending
  -> sent/failed; a row that has been `sent` is never sent again.
- Eligibility (subscription, suppression, consent, verification) is re-checked
  immediately before each send.
- A row left in `sending` by a crashed worker is marked failed ("outcome unknown")
  rather than retried, preferring a missed email over a duplicate.
"""
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.redis import get_redis
from app.core.security import sign_payload
from app.models import Campaign, CampaignRecipient, Company, Contact, EmailEvent, SendingAccount, Workspace
from app.models.enums import CampaignStatus as S
from app.models.enums import EventType
from app.models.enums import RecipientStatus as R
from app.providers import AccountError, OutgoingEmail, PermanentError, TransientError, build_provider
from app.providers.direct import HardBounce
from app.services import mailbox, rendering
from app.services.compliance import eligibility_clause

log = logging.getLogger(__name__)
PLACEHOLDER_RE = re.compile(r"\{\{__L:([A-Za-z0-9_\-]+)\}\}")


# ---------------- counters / throttling ----------------

def _day_key(account_id) -> str:
    return f"sent:{account_id}:{datetime.now(timezone.utc):%Y%m%d}"


def sent_today(account_id) -> int:
    return int(get_redis().get(_day_key(account_id)) or 0)


def reserve_daily(account: SendingAccount) -> bool:
    r = get_redis()
    key = _day_key(account.id)
    n = r.incr(key)
    if n == 1:
        r.expire(key, 2 * 86400)
    from app.api.v1.sending_accounts import effective_daily_limit
    if n > effective_daily_limit(account):
        r.decr(key)
        return False
    return True


def release_daily(account: SendingAccount) -> None:
    get_redis().decr(_day_key(account.id))


def throttle(account: SendingAccount) -> None:
    """Fixed one-second window limiter shared by all workers for this account."""
    r = get_redis()
    while True:
        sec = int(time.time())
        key = f"rate:{account.id}:{sec}"
        n = r.incr(key)
        if n == 1:
            r.expire(key, 3)
        if n <= account.max_per_second:
            return
        time.sleep(max(0.0, sec + 1 - time.time()) + 0.01)


# ---------------- tracking URLs ----------------

def _url(path: str) -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}{path}"


def unsubscribe_url(recipient_id) -> str:
    return _url(f"/u/{sign_payload({'r': str(recipient_id)}, 'unsub')}")


def open_pixel_url(recipient_id) -> str:
    return _url(f"/t/o/{sign_payload({'r': str(recipient_id)}, 'open')}.gif")


def click_url(recipient_id, link_token: str) -> str:
    return _url(f"/t/c/{sign_payload({'r': str(recipient_id), 'l': link_token}, 'click')}")


def personalise(c: Campaign, rec: CampaignRecipient, sender_address: str | None) -> tuple[str, str, str]:
    system = {"UnsubscribeUrl": unsubscribe_url(rec.id), "ViewInBrowserUrl": "", "SenderAddress": sender_address or "",
              "CurrentYear": str(datetime.now().year)}
    subject, html, text = rendering.render_for_recipient(c.html_snapshot or "", c.subject or "", c.text_snapshot,
                                                         rec.merge_data or {}, system)
    html = PLACEHOLDER_RE.sub(lambda m: click_url(rec.id, m.group(1)), html)
    text = PLACEHOLDER_RE.sub(lambda m: click_url(rec.id, m.group(1)), text)
    pixel = f'<img src="{open_pixel_url(rec.id)}" width="1" height="1" alt="" style="display:block;border:0" />'
    html = re.sub(r"</body\s*>", pixel + "</body>", html, count=1, flags=re.I) if re.search(r"</body", html, re.I) \
        else html + pixel
    return subject, html, text


# ---------------- snapshot ----------------

def snapshot_recipients(db: Session, c: Campaign) -> int:
    """Insert eligible audience into campaign_recipients (idempotent)."""
    from app.services.campaigns import build_audience
    stmt = build_audience(db, c, eligible_only=True)
    if stmt is None:
        return 0
    rows = db.execute(stmt.with_only_columns(Contact, Company.name).order_by(Contact.created_at)).all()
    inserted = 0
    for contact, company_name in rows:
        res = db.execute(pg_insert(CampaignRecipient.__table__).values(
            workspace_id=c.workspace_id, campaign_id=c.id, contact_id=contact.id, email=contact.email,
            merge_data=rendering.merge_data_for(contact, company_name)).on_conflict_do_nothing()
            .returning(CampaignRecipient.__table__.c.id))
        inserted += 1 if res.first() is not None else 0
    c.total_recipients = db.scalar(sa.select(sa.func.count()).select_from(CampaignRecipient)
                                   .where(CampaignRecipient.campaign_id == c.id))
    return inserted


def batches_needed(db: Session, campaign_id) -> int:
    n = db.scalar(sa.select(sa.func.count()).select_from(CampaignRecipient).where(
        CampaignRecipient.campaign_id == campaign_id, CampaignRecipient.status == R.QUEUED))
    return -(-n // settings.SEND_BATCH_SIZE)


def prepare(db: Session, campaign_id: uuid.UUID) -> int:
    """scheduled -> processing -> sending. Returns number of batches to enqueue."""
    from app.services.campaigns import transition
    c = db.scalar(sa.select(Campaign).where(Campaign.id == campaign_id).with_for_update())
    if c is None or c.status not in (S.SCHEDULED, S.PROCESSING):
        return 0
    if c.status == S.SCHEDULED:
        transition(c, S.PROCESSING)
        db.commit()
        c = db.get(Campaign, campaign_id)
    snapshot_recipients(db, c)
    if c.total_recipients == 0:
        c.status, c.completed_at = S.COMPLETED, datetime.now(timezone.utc)
        c.last_error = "No eligible recipients at send time"
        db.commit()
        return 0
    transition(c, S.SENDING)
    c.started_at = c.started_at or datetime.now(timezone.utc)
    db.commit()
    return batches_needed(db, campaign_id)


# ---------------- sending ----------------

def _event(db, rec: CampaignRecipient, et: EventType, **kw) -> None:
    db.add(EmailEvent(workspace_id=rec.workspace_id, campaign_id=rec.campaign_id, recipient_id=rec.id,
                      event_type=et, occurred_at=datetime.now(timezone.utc), **kw))


def _maybe_complete(db: Session, c: Campaign) -> None:
    pending = db.scalar(sa.select(sa.func.count()).select_from(CampaignRecipient).where(
        CampaignRecipient.campaign_id == c.id,
        CampaignRecipient.status.in_([R.QUEUED, R.SENDING])))
    if pending == 0 and c.status == S.SENDING:
        c.status, c.completed_at = S.COMPLETED, datetime.now(timezone.utc)
        from app.services.analytics import rollup_campaign
        rollup_campaign(db, c.id)


def send_batch(db: Session, campaign_id: uuid.UUID) -> dict:
    """Claim and send up to SEND_BATCH_SIZE queued recipients. Returns outcome counts and
    `retry_in` (seconds) when some rows need a later attempt."""
    out = {"sent": 0, "failed": 0, "skipped": 0, "requeued": 0, "retry_in": None, "stop": False}
    c = db.get(Campaign, campaign_id)
    if c is None or c.status != S.SENDING:
        out["stop"] = True
        return out
    account = db.get(SendingAccount, c.sending_account_id)
    sender_address = db.scalar(sa.select(Workspace.legal_address).where(Workspace.id == c.workspace_id))
    now = datetime.now(timezone.utc)
    claimed = db.scalars(sa.select(CampaignRecipient).where(
        CampaignRecipient.campaign_id == campaign_id, CampaignRecipient.status == R.QUEUED,
        sa.or_(CampaignRecipient.next_attempt_at.is_(None), CampaignRecipient.next_attempt_at <= now))
        .order_by(CampaignRecipient.created_at).limit(settings.SEND_BATCH_SIZE)
        .with_for_update(skip_locked=True)).all()
    if not claimed:
        _maybe_complete(db, c)
        db.commit()
        return out
    for rec in claimed:
        rec.status = R.SENDING
        rec.attempts += 1
    db.commit()

    provider = build_provider(account)
    try:
        for idx, rec in enumerate(claimed):
            if db.scalar(sa.select(Campaign.status).where(Campaign.id == campaign_id)) != S.SENDING:
                for r2 in claimed[idx:]:
                    if r2.status == R.SENDING:
                        r2.status, r2.attempts = R.QUEUED, r2.attempts - 1
                db.commit()
                out["stop"] = True
                return out
            # Re-check eligibility right before sending (never bypass suppression/unsubscribe).
            still_ok = db.scalar(sa.select(sa.func.count()).select_from(Contact).where(
                Contact.id == rec.contact_id, eligibility_clause()))
            if not still_ok:
                rec.status, rec.last_error = R.SKIPPED_SUPPRESSED, "No longer eligible at send time"
                out["skipped"] += 1
                db.commit()
                continue
            if not reserve_daily(account):
                rec.status, rec.attempts = R.QUEUED, rec.attempts - 1
                for r2 in claimed[idx + 1:]:
                    r2.status, r2.attempts = R.QUEUED, r2.attempts - 1
                tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=0, minute=5, second=0)
                out["retry_in"] = int((tomorrow - datetime.now(timezone.utc)).total_seconds())
                out["requeued"] += len(claimed) - idx
                db.commit()
                return out
            throttle(account)
            subject, html, text = personalise(c, rec, sender_address)
            unsub = unsubscribe_url(rec.id)
            sent_row = mailbox.start_outbound(db, c.workspace_id, account, rec.email, subject, kind="campaign",
                                              text=text, campaign_id=c.id, recipient_id=rec.id,
                                              contact_id=rec.contact_id)
            msg = OutgoingEmail(
                from_email=account.from_email, from_name=account.from_name,
                reply_to=mailbox.reply_to_header(account, sent_row), to=rec.email,
                subject=subject, html=html, text=text,
                headers={"Message-ID": sent_row.message_id_hdr,
                         "List-Unsubscribe": f"<{unsub}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                         "X-BEP-Campaign": str(c.id), "X-BEP-Recipient": str(rec.id),
                         "Feedback-ID": f"{c.id.hex[:12]}:{c.workspace_id.hex[:12]}:bep"},
                tags={"campaign": c.id.hex, "recipient": rec.id.hex})
            try:
                mid = provider.send(msg)
            except TransientError as e:
                release_daily(account)
                db.delete(sent_row)  # a retry records its own Sent entry
                if rec.attempts >= settings.SEND_MAX_ATTEMPTS:
                    rec.status, rec.last_error = R.FAILED, f"Gave up after {rec.attempts} attempts: {e}"[:500]
                    out["failed"] += 1
                else:
                    delay = min(3600, 30 * 2 ** (rec.attempts - 1))
                    rec.status, rec.last_error = R.QUEUED, str(e)[:500]
                    rec.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
                    out["requeued"] += 1
                    out["retry_in"] = min(out["retry_in"] or delay, delay)
                db.commit()
                continue
            except HardBounce as e:
                mailbox.finish_outbound(sent_row, False, str(e))
                rec.status, rec.last_error = R.BOUNCED, str(e)[:500]
                _event(db, rec, EventType.BOUNCE_HARD, raw={"error": str(e)[:500]})
                contact = db.get(Contact, rec.contact_id)
                if contact:
                    from app.services.compliance import unsubscribe_contact
                    from app.models.enums import SuppressionReason
                    unsubscribe_contact(db, rec.workspace_id, contact, SuppressionReason.HARD_BOUNCE,
                                        "direct: address does not exist")
                out["failed"] += 1
                db.commit()
                continue
            except PermanentError as e:
                release_daily(account)
                mailbox.finish_outbound(sent_row, False, str(e))
                rec.status, rec.last_error = R.FAILED, str(e)[:500]
                _event(db, rec, EventType.REJECT, raw={"error": str(e)[:500]})
                out["failed"] += 1
                db.commit()
                continue
            except AccountError as e:
                release_daily(account)
                db.delete(sent_row)
                rec.status, rec.attempts = R.QUEUED, rec.attempts - 1
                for r2 in claimed[idx + 1:]:
                    r2.status, r2.attempts = R.QUEUED, r2.attempts - 1
                c.status, c.last_error = S.PAUSED, f"Paused: sending account problem: {e}"[:500]
                db.commit()
                out["stop"] = True
                return out
            mailbox.finish_outbound(sent_row, True)
            rec.status, rec.provider_message_id, rec.sent_at = R.SENT, mid, datetime.now(timezone.utc)
            rec.next_attempt_at = None
            rec.last_error = None
            _event(db, rec, EventType.SEND, raw={"message_id": mid})
            out["sent"] += 1
            db.commit()
    finally:
        provider.close()
    c = db.get(Campaign, campaign_id)
    _maybe_complete(db, c)
    db.commit()
    return out


def recover_stuck(db: Session, older_than_minutes: int = 15) -> int:
    """Rows left in `sending` by a crashed worker: mark failed (outcome unknown) to avoid duplicates."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
    res = db.execute(sa.update(CampaignRecipient).where(CampaignRecipient.status == R.SENDING,
                                                        CampaignRecipient.updated_at < cutoff)
                     .values(status=R.FAILED, last_error="Worker interrupted; delivery outcome unknown (not retried "
                                                         "to avoid a duplicate send)"))
    return res.rowcount
