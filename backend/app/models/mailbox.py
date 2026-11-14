"""Mailbox: every email the platform sends, and every reply it receives, grouped into threads."""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPk


class MailMessage(UUIDPk, Base):
    __tablename__ = "mail_messages"
    __table_args__ = (
        sa.Index("ix_mail_messages_workspace_id", "workspace_id"),
        sa.Index("ix_mail_messages_folder", "workspace_id", "direction", "created_at"),
        sa.Index("ix_mail_messages_thread", "thread_id", "created_at"),
        sa.Index("ix_mail_messages_contact", "contact_id"),
        sa.Index("ix_mail_messages_unread", "workspace_id", postgresql_where=sa.text("direction = 'in' AND NOT is_read")),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    direction: Mapped[str] = mapped_column(sa.String(3), nullable=False)          # out | in
    kind: Mapped[str] = mapped_column(sa.String(20), nullable=False)              # test | campaign | reply | inbound | auto_reply
    status: Mapped[str] = mapped_column(sa.String(20), nullable=False)            # queued | sent | failed | received
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("sending_accounts.id", ondelete="SET NULL"))
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="SET NULL"))
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("campaign_recipients.id", ondelete="SET NULL"))
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("contacts.id", ondelete="SET NULL"))
    from_addr: Mapped[str] = mapped_column(sa.String(320), nullable=False)
    from_name: Mapped[str | None] = mapped_column(sa.String(200))
    to_addr: Mapped[str] = mapped_column(sa.String(320), nullable=False)
    subject: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default="")
    body_text: Mapped[str | None] = mapped_column(sa.Text)
    body_html: Mapped[str | None] = mapped_column(sa.Text)
    message_id_hdr: Mapped[str | None] = mapped_column(sa.String(500))
    in_reply_to: Mapped[str | None] = mapped_column(sa.String(500))
    error: Mapped[str | None] = mapped_column(sa.Text)
    is_read: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.true(), nullable=False)
    sent_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)
