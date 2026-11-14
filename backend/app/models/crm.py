"""Companies, contacts, taxonomy, consent and suppressions."""
import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import CITEXT, INET, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDelete, Timestamps, UUIDPk, pg_enum, workspace_fk
from app.models.enums import (
    CategoryScope,
    CompanySize,
    CompanyStatus,
    LawfulBasis,
    SubscriptionStatus,
    SuppressionReason,
    VerificationStatus,
)

# Sequences company_code_seq / contact_code_seq are created in migration 0001.


class Industry(UUIDPk, Timestamps, Base):
    __tablename__ = "industries"
    __table_args__ = (
        sa.Index("uq_industries_workspace_name", "workspace_id", sa.text("lower(name)"), unique=True),
    )

    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("industries.id", ondelete="SET NULL")
    )


class Category(UUIDPk, Timestamps, Base):
    __tablename__ = "categories"
    __table_args__ = (
        sa.Index(
            "uq_categories_workspace_scope_name", "workspace_id", "scope", sa.text("lower(name)"),
            unique=True,
        ),
    )

    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    scope: Mapped[CategoryScope] = mapped_column(pg_enum(CategoryScope, "category_scope"), nullable=False)
    name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    color: Mapped[str | None] = mapped_column(sa.String(16))


class Tag(UUIDPk, Timestamps, Base):
    __tablename__ = "tags"
    __table_args__ = (
        sa.Index("uq_tags_workspace_name", "workspace_id", sa.text("lower(name)"), unique=True),
    )

    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    name: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    color: Mapped[str | None] = mapped_column(sa.String(16))


class Company(UUIDPk, Timestamps, SoftDelete, Base):
    __tablename__ = "companies"
    __table_args__ = (
        sa.Index(
            "uq_companies_workspace_domain", "workspace_id", "domain", unique=True,
            postgresql_where=sa.text("domain IS NOT NULL AND deleted_at IS NULL"),
        ),
        sa.Index("uq_companies_code", "code", unique=True),
        sa.Index(
            "ix_companies_segment_filters",
            "workspace_id", "industry_id", "country_code", "city", "company_size",
        ),
        sa.Index(
            "ix_companies_normalized_name_trgm", "normalized_name",
            postgresql_using="gin", postgresql_ops={"normalized_name": "gin_trgm_ops"},
        ),
        sa.Index("ix_companies_keyset", "workspace_id", "created_at", "id"),
        sa.CheckConstraint("annual_revenue IS NULL OR annual_revenue >= 0", name="revenue_non_negative"),
        sa.CheckConstraint("country_code IS NULL OR country_code ~ '^[A-Z]{2}$'", name="country_iso2"),
    )

    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    code: Mapped[str] = mapped_column(
        sa.String(20), nullable=False,
        server_default=sa.text("'COMP-' || lpad(nextval('company_code_seq')::text, 6, '0')"),
    )
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    name_ar: Mapped[str | None] = mapped_column(sa.String(255))  # Arabic company name
    # Lower-cased name without spaces/punctuation (keeps Arabic letters) for duplicate detection.
    normalized_name: Mapped[str] = mapped_column(
        sa.Text,
        sa.Computed("lower(regexp_replace(name, '[[:space:][:punct:]]+', '', 'g'))", persisted=True),
    )
    industry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("industries.id", ondelete="SET NULL")
    )
    business_type: Mapped[str | None] = mapped_column(sa.String(120))
    country_code: Mapped[str | None] = mapped_column(sa.String(2))
    city: Mapped[str | None] = mapped_column(sa.String(120))
    website: Mapped[str | None] = mapped_column(sa.String(255))
    domain: Mapped[str | None] = mapped_column(CITEXT)
    company_size: Mapped[CompanySize | None] = mapped_column(pg_enum(CompanySize, "company_size"))
    annual_revenue: Mapped[Decimal | None] = mapped_column(sa.Numeric(18, 2))
    status: Mapped[CompanyStatus] = mapped_column(
        pg_enum(CompanyStatus, "company_status"), server_default="active", nullable=False
    )
    data_source: Mapped[str | None] = mapped_column(sa.String(120))
    notes: Mapped[str | None] = mapped_column(sa.Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )


class CompanyCategory(Base):
    __tablename__ = "company_categories"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True,
        index=True,
    )


class CompanyTag(Base):
    __tablename__ = "company_tags"
    __table_args__ = (sa.Index("ix_company_tags_tag_company", "tag_id", "company_id"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )


class Contact(UUIDPk, Timestamps, SoftDelete, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        sa.Index(
            "uq_contacts_workspace_email", "workspace_id", "email", unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
        ),
        sa.Index("uq_contacts_code", "code", unique=True),
        sa.Index(
            "ix_contacts_eligibility",
            "workspace_id", "subscription_status", "email_verification_status",
        ),
        sa.Index("ix_contacts_workspace_company", "workspace_id", "company_id"),
        sa.Index("ix_contacts_keyset", "workspace_id", "created_at", "id"),
        *[
            sa.Index(
                f"ix_contacts_{col}_trgm", col,
                postgresql_using="gin", postgresql_ops={col: "gin_trgm_ops"},
            )
            for col in ("first_name", "last_name", "job_title", "email")
        ],
        sa.CheckConstraint("country_code IS NULL OR country_code ~ '^[A-Z]{2}$'", name="country_iso2"),
        sa.CheckConstraint("position('@' in email) > 1", name="email_has_at"),
    )

    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(
        sa.String(20), nullable=False,
        server_default=sa.text("'CONT-' || lpad(nextval('contact_code_seq')::text, 6, '0')"),
    )
    first_name: Mapped[str | None] = mapped_column(sa.String(120))
    last_name: Mapped[str | None] = mapped_column(sa.String(120))
    name_ar: Mapped[str | None] = mapped_column(sa.String(200))  # full name in Arabic
    job_title: Mapped[str | None] = mapped_column(sa.String(200))
    department: Mapped[str | None] = mapped_column(sa.String(120))
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    phone: Mapped[str | None] = mapped_column(sa.String(40))
    country_code: Mapped[str | None] = mapped_column(sa.String(2))
    city: Mapped[str | None] = mapped_column(sa.String(120))
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("categories.id", ondelete="SET NULL")
    )
    # Default 'pending': a publicly available address is never treated as consent.
    subscription_status: Mapped[SubscriptionStatus] = mapped_column(
        pg_enum(SubscriptionStatus, "subscription_status"), server_default="pending", nullable=False
    )
    consent_source: Mapped[str | None] = mapped_column(sa.String(200))
    consent_date: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    email_verification_status: Mapped[VerificationStatus] = mapped_column(
        pg_enum(VerificationStatus, "verification_status"), server_default="unverified",
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(sa.Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )


class ContactTag(Base):
    __tablename__ = "contact_tags"
    __table_args__ = (sa.Index("ix_contact_tags_tag_contact", "tag_id", "contact_id"),)

    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("contacts.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )


class ConsentRecord(UUIDPk, Base):
    __tablename__ = "consent_records"

    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False,
        index=True,
    )
    lawful_basis: Mapped[LawfulBasis] = mapped_column(pg_enum(LawfulBasis, "lawful_basis"), nullable=False)
    source: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    evidence: Mapped[str | None] = mapped_column(sa.Text)
    ip_address: Mapped[str | None] = mapped_column(INET)
    granted_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    withdrawn_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


class Suppression(UUIDPk, Base):
    __tablename__ = "suppressions"
    __table_args__ = (sa.UniqueConstraint("workspace_id", "email"),)

    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    reason: Mapped[SuppressionReason] = mapped_column(
        pg_enum(SuppressionReason, "suppression_reason"), nullable=False
    )
    source: Mapped[str | None] = mapped_column(sa.String(200))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
