"""Asynchronous bounce handling for direct delivery.

Every campaign email is sent with a VERP envelope sender, bounces+<recipient-id>.<signature>@<bounce-domain>,
so a delivery-status notification (DSN) that arrives later identifies the exact campaign recipient
without parsing the returned message. The signature stops anyone from forging bounces that would
suppress arbitrary contacts.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import uuid
from datetime import datetime, timezone
from email import message_from_bytes
from email import policy as email_policy
from email.message import Message

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.config import settings

log = logging.getLogger(__name__)

LOCAL_PREFIX = "bounces"
_VERP = re.compile(r"^bounces\+([0-9a-f]{32})\.([0-9a-z]{10})$")
# Permanent statuses that mean "this address will never work" (RFC 3463).
HARD = re.compile(r"^5\.(1\.\d+|2\.1|4\.4)$")


def _sig(rid_hex: str) -> str:
    d = hmac.new(f"{settings.SECRET_KEY}:verp".encode(), rid_hex.encode(), hashlib.sha256).hexdigest()
    return d[:10]


def verp_address(recipient_id: str | uuid.UUID, domain: str) -> str:
    rid = uuid.UUID(str(recipient_id)).hex
    return f"{LOCAL_PREFIX}+{rid}.{_sig(rid)}@{domain}"


def parse_verp(address: str) -> uuid.UUID | None:
    local = address.rsplit("@", 1)[0].lower()
    m = _VERP.match(local)
    if not m or not hmac.compare_digest(m.group(2), _sig(m.group(1))):
        return None
    return uuid.UUID(m.group(1))


def parse_dsn(raw: bytes) -> list[dict]:
    """Return [{status, recipient, action, diagnostic}] from a DSN (multipart/report) or a plain bounce."""
    msg: Message = message_from_bytes(raw, policy=email_policy.default)
    out: list[dict] = []
    for part in msg.walk():
        if part.get_content_type() != "message/delivery-status":
            continue
        payload = part.get_payload()
        blocks = payload if isinstance(payload, list) else [message_from_bytes(part.as_bytes())]
        for block in blocks:
            status = str(block.get("Status", "")).strip()
            if not status:
                continue
            rcpt = str(block.get("Final-Recipient") or block.get("Original-Recipient") or "")
            out.append({"status": status.split()[0], "recipient": rcpt.split(";")[-1].strip().lower(),
                        "action": str(block.get("Action", "")).strip().lower(),
                        "diagnostic": str(block.get("Diagnostic-Code", "")).strip()[:500]})
    if not out:  # non-standard bounce: look for an enhanced status code in the text
        text = raw.decode(errors="replace")
        m = re.search(r"\b([45]\.\d{1,3}\.\d{1,3})\b", text)
        if m and re.search(r"(?i)(undeliver|delivery (status|failure)|returned mail|failure notice)", text):
            out.append({"status": m.group(1), "recipient": "", "action": "failed", "diagnostic": text[:500]})
    return out


def is_auto_reply(raw: bytes) -> bool:
    msg = message_from_bytes(raw, policy=email_policy.default)
    return (str(msg.get("Auto-Submitted", "no")).lower() not in ("", "no") and
            msg.get_content_type() != "multipart/report") or bool(msg.get("X-Autoreply"))


def process(db: Session, rcpt_address: str, raw: bytes) -> str:
    """Apply one inbound bounce. Returns a short outcome string (for logs and tests)."""
    from app.models import CampaignRecipient, Contact, EmailEvent
    from app.models.enums import EventType, RecipientStatus, SuppressionReason
    from app.services.compliance import unsubscribe_contact

    rid = parse_verp(rcpt_address)
    if rid is None:
        return "ignored: unsigned address"
    rec = db.get(CampaignRecipient, rid)
    if rec is None:
        return "ignored: unknown recipient"
    reports = [r for r in parse_dsn(raw) if r["action"] in ("failed", "")]
    if not reports:
        return "ignored: auto-reply" if is_auto_reply(raw) else "ignored: not a failure report"
    r = reports[0]
    hard = bool(HARD.match(r["status"]))
    et = EventType.BOUNCE_HARD if hard else EventType.BOUNCE_SOFT
    db.add(EmailEvent(workspace_id=rec.workspace_id, campaign_id=rec.campaign_id, recipient_id=rec.id,
                      event_type=et, occurred_at=datetime.now(timezone.utc), raw={"dsn": r}))
    if hard:
        rec.status = RecipientStatus.BOUNCED
        rec.last_error = f"Bounced {r['status']}: {r['diagnostic']}"[:500]
        contact = db.get(Contact, rec.contact_id)
        if contact:
            unsubscribe_contact(db, rec.workspace_id, contact, SuppressionReason.HARD_BOUNCE,
                                f"direct: {r['status']} bounce")
    return et.value


def bounce_domains(db: Session) -> set[str]:
    """Domains the receiver accepts mail for: the bounce subdomains of direct-delivery accounts."""
    from app.core.security import decrypt_json
    from app.models import SendingAccount
    from app.models.enums import Provider
    out: set[str] = set()
    for a in db.scalars(sa.select(SendingAccount).where(SendingAccount.provider == Provider.DIRECT)):
        d = (decrypt_json(a.encrypted_credentials).get("return_path_domain") or "").strip().lower()
        if d:
            out.add(d)
    return out
