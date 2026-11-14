"""Compliance primitives shared by API, tracking endpoints and webhooks."""
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import ConsentRecord, Contact, Suppression
from app.models.enums import SubscriptionStatus, SuppressionReason, VerificationStatus

STATUS_FOR_REASON = {SuppressionReason.HARD_BOUNCE: SubscriptionStatus.BOUNCED,
                     SuppressionReason.COMPLAINT: SubscriptionStatus.COMPLAINED}


def unsubscribe_contact(db: Session, workspace_id: uuid.UUID, c: Contact, reason: SuppressionReason,
                        source: str, user_id=None) -> None:
    """Withdraw consent, mark the contact and add the address to the suppression list."""
    now = datetime.now(timezone.utc)
    c.subscription_status = STATUS_FOR_REASON.get(reason, SubscriptionStatus.UNSUBSCRIBED)
    if reason == SuppressionReason.HARD_BOUNCE:
        c.email_verification_status = VerificationStatus.INVALID
    db.execute(sa.update(ConsentRecord).where(ConsentRecord.contact_id == c.id,
                                              ConsentRecord.withdrawn_at.is_(None)).values(withdrawn_at=now))
    suppress_email(db, workspace_id, c.email, reason, source, user_id)


def suppress_email(db: Session, workspace_id: uuid.UUID, email: str, reason: SuppressionReason,
                   source: str, user_id=None) -> None:
    db.execute(pg_insert(Suppression).values(workspace_id=workspace_id, email=email, reason=reason,
                                             source=source[:200], created_by=user_id).on_conflict_do_nothing())


def eligibility_clause():
    """SQL condition a contact must satisfy to receive marketing email. Used everywhere a
    recipient list is built or re-checked; there is deliberately no way to bypass it."""
    return sa.and_(
        Contact.deleted_at.is_(None),
        Contact.subscription_status == SubscriptionStatus.SUBSCRIBED,
        Contact.email_verification_status != VerificationStatus.INVALID,
        ~sa.exists().where(Suppression.email == Contact.email,
                           Suppression.workspace_id == Contact.workspace_id),
        sa.exists().where(ConsentRecord.contact_id == Contact.id, ConsentRecord.withdrawn_at.is_(None)),
    )
