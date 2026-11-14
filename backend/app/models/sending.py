"""Sending accounts, campaigns, recipients, tracking and events."""
import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import CITEXT, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDelete, Timestamps, UUIDPk, pg_enum, workspace_fk
from app.models.enums import CampaignStatus, EventType, IdentityStatus, Provider, RecipientStatus


class SendingAccount(UUIDPk, Timestamps, Base):
    __tablename__ = "sending_accounts"
    __table_args__ = (
        sa.UniqueConstraint("workspace_id", "from_email"),
        sa.CheckConstraint("max_per_second > 0 AND max_per_day > 0", name="positive_limits"),
    )

    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    provider: Mapped[Provider] = mapped_column(pg_enum(Provider, "provider"), nullable=False)
    from_email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    from_name: Mapped[str | None] = mapped_column(sa.String(200))
    reply_to: Mapped[str | None] = mapped_column(CITEXT)
    domain: Mapped[str] = mapped_column(CITEXT, nullable=False)
    # Fernet/KMS-encrypted JSON blob. Never returned by the API.
    encrypted_credentials: Mapped[bytes | None] = mapped_column(sa.LargeBinary)
    region: Mapped[str | None] = mapped_column(sa.String(40))
    configuration_set: Mapped[str | None] = mapped_column(sa.String(120))
    max_per_second: Mapped[int] = mapped_column(sa.Integer, server_default="1", nullable=False)
    max_per_day: Mapped[int] = mapped_column(sa.Integer, server_default="200", nullable=False)
    verification_status: Mapped[IdentityStatus] = mapped_column(
        pg_enum(IdentityStatus, "identity_status"), server_default="pending", nullable=False
    )
    dns_records: Mapped[dict | None] = mapped_column(JSONB)
    is_default: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.false(), nullable=False)


class Campaign(UUIDPk, Timestamps, SoftDelete, Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        sa.CheckConstraint(
            "status <> 'scheduled' OR scheduled_at IS NOT NULL", name="scheduled_needs_time"
        ),
        sa.CheckConstraint(
            "status IN ('draft','cancelled') OR approved_at IS NOT NULL", name="sending_needs_approval"
        ),
        sa.Index("ix_campaigns_workspace_status", "workspace_id", "status"),
        sa.Index(
            "ix_campaigns_due", "scheduled_at", postgresql_where=sa.text("status = 'scheduled'")
        ),
    )

    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    segment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("segments.id", ondelete="SET NULL")
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("email_templates.id", ondelete="SET NULL")
    )
    sending_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("sending_accounts.id", ondelete="RESTRICT")
    )
    subject: Mapped[str | None] = mapped_column(sa.String(300))
    preheader: Mapped[str | None] = mapped_column(sa.String(300))
    html_snapshot: Mapped[str | None] = mapped_column(sa.Text)
    text_snapshot: Mapped[str | None] = mapped_column(sa.Text)
    manual_contact_ids: Mapped[list] = mapped_column(
        JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False
    )
    status: Mapped[CampaignStatus] = mapped_column(
        pg_enum(CampaignStatus, "campaign_status"), server_default="draft", nullable=False
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    duplicated_from: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="SET NULL")
    )
    total_recipients: Mapped[int] = mapped_column(sa.Integer, server_default="0", nullable=False)
    last_error: Mapped[str | None] = mapped_column(sa.Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )


class CampaignRecipient(UUIDPk, Timestamps, Base):
    """Frozen recipient snapshot. The unique constraints are the duplicate-send guard."""

    __tablename__ = "campaign_recipients"
    __table_args__ = (
        sa.UniqueConstraint("campaign_id", "contact_id"),
        sa.UniqueConstraint("campaign_id", "email"),
        sa.Index("ix_campaign_recipients_campaign_status", "campaign_id", "status"),
        sa.Index("uq_campaign_recipients_provider_message_id", "provider_message_id", unique=True,
                 postgresql_where=sa.text("provider_message_id IS NOT NULL")),
        sa.Index("ix_campaign_recipients_contact", "contact_id"),
    )

    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("contacts.id", ondelete="RESTRICT"), nullable=False
    )
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    merge_data: Mapped[dict] = mapped_column(JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False)
    status: Mapped[RecipientStatus] = mapped_column(
        pg_enum(RecipientStatus, "recipient_status"), server_default="queued", nullable=False
    )
    provider_message_id: Mapped[str | None] = mapped_column(sa.String(255))
    attempts: Mapped[int] = mapped_column(sa.SmallInteger, server_default="0", nullable=False)
    last_error: Mapped[str | None] = mapped_column(sa.Text)
    sent_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    first_opened_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    first_clicked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class TrackedLink(UUIDPk, Base):
    __tablename__ = "tracked_links"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False,
        index=True,
    )
    original_url: Mapped[str] = mapped_column(sa.Text, nullable=False)
    token: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


class EmailEvent(Base):
    __tablename__ = "email_events"
    __table_args__ = (
        sa.Index("ix_email_events_campaign_type_time", "campaign_id", "event_type", "occurred_at"),
        sa.Index("ix_email_events_recipient", "recipient_id"),
        sa.Index("ix_email_events_occurred_brin", "workspace_id", "occurred_at", postgresql_using="brin"),
        sa.Index("uq_email_events_provider_event_id", "provider_event_id", unique=True,
                 postgresql_where=sa.text("provider_event_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger, sa.Identity(always=True), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="CASCADE")
    )
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("campaign_recipients.id", ondelete="CASCADE")
    )
    event_type: Mapped[EventType] = mapped_column(pg_enum(EventType, "event_type"), nullable=False)
    provider_event_id: Mapped[str | None] = mapped_column(sa.String(255))
    url: Mapped[str | None] = mapped_column(sa.Text)
    user_agent: Mapped[str | None] = mapped_column(sa.Text)
    ip: Mapped[str | None] = mapped_column(INET)
    is_machine: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.false(), nullable=False)
    raw: Mapped[dict | None] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


class CampaignDailyStat(Base):
    __tablename__ = "campaign_daily_stats"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(sa.Date, primary_key=True)
    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    sent: Mapped[int] = mapped_column(sa.Integer, server_default="0", nullable=False)
    delivered: Mapped[int] = mapped_column(sa.Integer, server_default="0", nullable=False)
    bounced: Mapped[int] = mapped_column(sa.Integer, server_default="0", nullable=False)
    opened: Mapped[int] = mapped_column(sa.Integer, server_default="0", nullable=False)
    unique_opened: Mapped[int] = mapped_column(sa.Integer, server_default="0", nullable=False)
    clicked: Mapped[int] = mapped_column(sa.Integer, server_default="0", nullable=False)
    unique_clicked: Mapped[int] = mapped_column(sa.Integer, server_default="0", nullable=False)
    unsubscribed: Mapped[int] = mapped_column(sa.Integer, server_default="0", nullable=False)
    complained: Mapped[int] = mapped_column(sa.Integer, server_default="0", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
