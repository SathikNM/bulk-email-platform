"""Engagement + provider event processing (opens, clicks, unsubscribes, bounces, complaints, deliveries)."""
import base64
import re
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from urllib.parse import urlparse

import httpx
import sqlalchemy as sa
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import CampaignRecipient, Contact, EmailEvent
from app.models.enums import EventType, RecipientStatus, SuppressionReason
from app.services.compliance import unsubscribe_contact

MACHINE_UA = re.compile(r"bot|crawler|spider|preview|scanner|barracuda|proofpoint|mimecast|"
                        r"microsoft office protection|safelinks|python-requests|curl|wget|go-http-client", re.I)


def is_machine(ua: str | None, sent_at: datetime | None, window_s: int = 10) -> bool:
    if not ua or MACHINE_UA.search(ua):
        return True
    return bool(sent_at and datetime.now(timezone.utc) - sent_at < timedelta(seconds=window_s))


def record_open(db: Session, rec: CampaignRecipient, ua: str | None, ip: str | None) -> None:
    machine = is_machine(ua, rec.sent_at)
    db.add(EmailEvent(workspace_id=rec.workspace_id, campaign_id=rec.campaign_id, recipient_id=rec.id,
                      event_type=EventType.OPEN, user_agent=(ua or "")[:500], ip=ip, is_machine=machine,
                      occurred_at=datetime.now(timezone.utc)))
    if not machine and rec.first_opened_at is None:
        rec.first_opened_at = datetime.now(timezone.utc)


def record_click(db: Session, rec: CampaignRecipient, url: str, ua: str | None, ip: str | None) -> None:
    machine = is_machine(ua, rec.sent_at, window_s=5)
    now = datetime.now(timezone.utc)
    db.add(EmailEvent(workspace_id=rec.workspace_id, campaign_id=rec.campaign_id, recipient_id=rec.id,
                      event_type=EventType.CLICK, url=url, user_agent=(ua or "")[:500], ip=ip, is_machine=machine,
                      occurred_at=now))
    if not machine:
        rec.first_clicked_at = rec.first_clicked_at or now
        rec.first_opened_at = rec.first_opened_at or now  # a click implies an open


def record_unsubscribe(db: Session, rec: CampaignRecipient, source: str) -> None:
    c = db.get(Contact, rec.contact_id)
    already = db.scalar(sa.select(EmailEvent.id).where(EmailEvent.recipient_id == rec.id,
                                                       EmailEvent.event_type == EventType.UNSUBSCRIBE))
    if c is not None:
        unsubscribe_contact(db, rec.workspace_id, c, SuppressionReason.UNSUBSCRIBE, source)
    if not already:
        db.add(EmailEvent(workspace_id=rec.workspace_id, campaign_id=rec.campaign_id, recipient_id=rec.id,
                          event_type=EventType.UNSUBSCRIBE, occurred_at=datetime.now(timezone.utc),
                          raw={"source": source}))


# ---------------- SES via SNS ----------------

CERT_HOST = re.compile(r"^sns\.[a-z0-9\-]+\.amazonaws\.com(\.cn)?$")
SNS_FIELDS = {
    "Notification": ["Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type"],
    "SubscriptionConfirmation": ["Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type"],
    "UnsubscribeConfirmation": ["Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type"],
}


class SNSVerificationError(Exception):
    pass


def valid_sns_url(url: str) -> bool:
    p = urlparse(url or "")
    return p.scheme == "https" and bool(CERT_HOST.match(p.hostname or ""))


@lru_cache(maxsize=16)
def fetch_cert(url: str) -> bytes:
    r = httpx.get(url, timeout=10)
    r.raise_for_status()
    return r.content


def verify_sns(msg: dict) -> None:
    t = msg.get("Type")
    if t not in SNS_FIELDS:
        raise SNSVerificationError("Unknown SNS message type")
    cert_url = msg.get("SigningCertURL") or msg.get("SigningCertUrl") or ""
    if not valid_sns_url(cert_url):
        raise SNSVerificationError("Untrusted signing certificate URL")
    canonical = "".join(f"{k}\n{msg[k]}\n" for k in SNS_FIELDS[t] if k in msg and msg[k] is not None)
    cert = x509.load_pem_x509_certificate(fetch_cert(cert_url))
    algo = hashes.SHA256() if str(msg.get("SignatureVersion")) == "2" else hashes.SHA1()  # noqa: S303 - AWS SNS v1
    try:
        cert.public_key().verify(base64.b64decode(msg.get("Signature", "")), canonical.encode(), padding.PKCS1v15(),
                                 algo)
    except (InvalidSignature, ValueError) as e:
        raise SNSVerificationError("Invalid SNS signature") from e


def handle_ses_event(db: Session, sns_message_id: str, event: dict) -> str:
    """Apply one SES event. Idempotent on the SNS MessageId."""
    etype = event.get("eventType") or event.get("notificationType")
    mail = event.get("mail", {})
    mid = mail.get("messageId")
    rec = db.scalar(sa.select(CampaignRecipient).where(CampaignRecipient.provider_message_id == mid)) if mid else None
    if rec is None:
        return "ignored: unknown message"
    now = datetime.now(timezone.utc)
    mapping = {"Delivery": EventType.DELIVERY, "Complaint": EventType.COMPLAINT, "Reject": EventType.REJECT}
    if etype == "Bounce":
        btype = event.get("bounce", {}).get("bounceType")
        et = EventType.BOUNCE_HARD if btype == "Permanent" else EventType.BOUNCE_SOFT
    elif etype in mapping:
        et = mapping[etype]
    else:
        return f"ignored: {etype}"
    res = db.execute(pg_insert(EmailEvent.__table__).values(
        workspace_id=rec.workspace_id, campaign_id=rec.campaign_id, recipient_id=rec.id, event_type=et,
        provider_event_id=sns_message_id, raw=event, occurred_at=now)
        .on_conflict_do_nothing(index_elements=["provider_event_id"],
                                index_where=sa.text("provider_event_id IS NOT NULL"))
        .returning(EmailEvent.__table__.c.id))
    if res.first() is None:
        return "duplicate"
    contact = db.get(Contact, rec.contact_id)
    if et == EventType.DELIVERY:
        if rec.status == RecipientStatus.SENT:
            rec.status = RecipientStatus.DELIVERED
        rec.delivered_at = rec.delivered_at or now
    elif et == EventType.BOUNCE_HARD:
        rec.status = RecipientStatus.BOUNCED
        if contact:
            unsubscribe_contact(db, rec.workspace_id, contact, SuppressionReason.HARD_BOUNCE, "ses: permanent bounce")
    elif et == EventType.COMPLAINT:
        rec.status = RecipientStatus.COMPLAINED
        if contact:
            unsubscribe_contact(db, rec.workspace_id, contact, SuppressionReason.COMPLAINT, "ses: complaint")
    elif et == EventType.REJECT:
        rec.status = RecipientStatus.FAILED
    return et.value


def recipient_from_token(db: Session, payload: dict | None) -> CampaignRecipient | None:
    if not payload:
        return None
    try:
        return db.get(CampaignRecipient, uuid.UUID(payload["r"]))
    except (KeyError, ValueError):
        return None
