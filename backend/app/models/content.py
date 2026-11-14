"""Segments, email templates and reusable blocks."""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDelete, Timestamps, UUIDPk, pg_enum, workspace_fk
from app.models.enums import BlockType, EditorType, TextDirection


class Segment(UUIDPk, Timestamps, Base):
    __tablename__ = "segments"
    __table_args__ = (
        sa.Index("uq_segments_workspace_name", "workspace_id", sa.text("lower(name)"), unique=True),
    )

    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text)
    rules: Mapped[dict] = mapped_column(JSONB, nullable=False)
    cached_count: Mapped[int | None] = mapped_column(sa.Integer)
    cached_eligible_count: Mapped[int | None] = mapped_column(sa.Integer)
    count_refreshed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )


class EmailTemplate(UUIDPk, Timestamps, SoftDelete, Base):
    __tablename__ = "email_templates"

    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    subject: Mapped[str | None] = mapped_column(sa.String(300))
    preheader: Mapped[str | None] = mapped_column(sa.String(300))
    editor_type: Mapped[EditorType] = mapped_column(pg_enum(EditorType, "editor_type"), nullable=False)
    design_json: Mapped[dict | None] = mapped_column(JSONB)
    html: Mapped[str | None] = mapped_column(sa.Text)
    text_body: Mapped[str | None] = mapped_column(sa.Text)
    direction: Mapped[TextDirection] = mapped_column(
        pg_enum(TextDirection, "text_direction"), server_default="ltr", nullable=False
    )
    locale: Mapped[str] = mapped_column(sa.String(10), server_default="en", nullable=False)
    is_draft: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.true(), nullable=False)
    duplicated_from: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("email_templates.id", ondelete="SET NULL")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )


class EmailBlock(UUIDPk, Timestamps, Base):
    __tablename__ = "email_blocks"
    __table_args__ = (sa.Index("ix_email_blocks_template_position", "template_id", "position"),)

    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    # NULL template_id = a reusable library block.
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("email_templates.id", ondelete="CASCADE")
    )
    name: Mapped[str | None] = mapped_column(sa.String(200))
    block_type: Mapped[BlockType] = mapped_column(pg_enum(BlockType, "block_type"), nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    position: Mapped[int] = mapped_column(sa.Integer, server_default="0", nullable=False)
    is_reusable: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.false(), nullable=False)
