"""Import jobs and audit logs."""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk, pg_enum, workspace_fk
from app.models.enums import ImportEntity, JobStatus


class ImportJob(UUIDPk, Timestamps, Base):
    __tablename__ = "import_jobs"

    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    entity: Mapped[ImportEntity] = mapped_column(pg_enum(ImportEntity, "import_entity"), nullable=False)
    file_key: Mapped[str] = mapped_column(sa.Text, nullable=False)
    original_filename: Mapped[str | None] = mapped_column(sa.String(255))
    column_mapping: Mapped[dict] = mapped_column(JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False)
    options: Mapped[dict] = mapped_column(JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        pg_enum(JobStatus, "job_status"), server_default="pending", nullable=False
    )
    total_rows: Mapped[int] = mapped_column(sa.Integer, server_default="0", nullable=False)
    inserted: Mapped[int] = mapped_column(sa.Integer, server_default="0", nullable=False)
    updated: Mapped[int] = mapped_column(sa.Integer, server_default="0", nullable=False)
    skipped: Mapped[int] = mapped_column(sa.Integer, server_default="0", nullable=False)
    errors: Mapped[list] = mapped_column(JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        sa.Index("ix_audit_logs_entity", "workspace_id", "entity_type", "entity_id"),
        sa.Index("ix_audit_logs_workspace_time", "workspace_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger, sa.Identity(always=True), primary_key=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(sa.String(64))
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
