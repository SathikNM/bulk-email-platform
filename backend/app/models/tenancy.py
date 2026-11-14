"""Workspaces (tenants), users, memberships, refresh tokens."""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk, pg_enum
from app.models.enums import MemberRole


class Workspace(UUIDPk, Timestamps, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    slug: Mapped[str] = mapped_column(sa.String(80), nullable=False, unique=True)
    default_locale: Mapped[str] = mapped_column(sa.String(10), server_default="en", nullable=False)
    timezone: Mapped[str] = mapped_column(sa.String(64), server_default="Asia/Riyadh", nullable=False)
    legal_address: Mapped[str | None] = mapped_column(sa.Text)
    compliance_settings: Mapped[dict] = mapped_column(
        JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.true(), nullable=False)


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    full_name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.true(), nullable=False)
    is_superadmin: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.false(), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    totp_secret_enc: Mapped[bytes | None] = mapped_column(sa.LargeBinary)
    totp_enabled: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.false(), nullable=False)


class WorkspaceMember(Timestamps, Base):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True,
        index=True,
    )
    role: Mapped[MemberRole] = mapped_column(pg_enum(MemberRole, "member_role"), nullable=False)


class RefreshToken(UUIDPk, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(sa.String(128), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
