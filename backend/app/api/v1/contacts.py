"""Module 2: Contact database (multiple contacts per company), consent and unsubscribe."""
import hashlib
import uuid
from datetime import datetime, timezone
from ipaddress import ip_address

import sqlalchemy as sa
from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.core.deps import Admin, Analyst, Ctx, Marketer, Owner, Viewer
from app.core.errors import BadRequest, Conflict
from app.models import (
    Category,
    Company,
    ConsentRecord,
    Contact,
    ContactTag,
    Industry,
    Suppression,
    Tag,
)
from app.models.enums import LawfulBasis, MemberRole, SubscriptionStatus, SuppressionReason, VerificationStatus
from app.services.common import audit, get_or_404, is_role_account, normalize_phone, paginate, row_dict
from app.services.compliance import unsubscribe_contact
from app.services.exports import export_response
from app.services.jobs import enqueue_after_commit

router = APIRouter(prefix="/contacts", tags=["contacts"])


class ContactIn(BaseModel):
    company_id: uuid.UUID
    email: EmailStr
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    name_ar: str | None = Field(default=None, max_length=200)
    job_title: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    country_code: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    city: str | None = Field(default=None, max_length=120)
    category_id: uuid.UUID | None = None
    notes: str | None = None
    tag_ids: list[uuid.UUID] | None = None
    # Consent captured at creation. Without it the contact stays `pending`.
    consent_source: str | None = Field(default=None, max_length=200)
    consent_date: datetime | None = None
    lawful_basis: LawfulBasis = LawfulBasis.EXPLICIT_CONSENT

    @field_validator("country_code")
    @classmethod
    def _upper(cls, v):
        return v.upper() if v else v


class ContactUpdate(BaseModel):
    company_id: uuid.UUID | None = None
    email: EmailStr | None = None
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    name_ar: str | None = Field(default=None, max_length=200)
    job_title: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    country_code: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    city: str | None = Field(default=None, max_length=120)
    category_id: uuid.UUID | None = None
    notes: str | None = None
    tag_ids: list[uuid.UUID] | None = None
    email_verification_status: VerificationStatus | None = None

    @field_validator("country_code")
    @classmethod
    def _upper(cls, v):
        return v.upper() if v else v


class ConsentIn(BaseModel):
    lawful_basis: LawfulBasis
    source: str = Field(min_length=2, max_length=200)
    evidence: str | None = None
    ip_address: str | None = None
    granted_at: datetime | None = None

    @field_validator("ip_address")
    @classmethod
    def _ip(cls, v):
        if v:
            ip_address(v)
        return v


class UnsubscribeIn(BaseModel):
    reason: str | None = None


class BulkIn(BaseModel):
    contact_ids: list[uuid.UUID] = Field(min_length=1, max_length=5000)
    add_tag_ids: list[uuid.UUID] = []
    remove_tag_ids: list[uuid.UUID] = []
    category_id: uuid.UUID | None = None
    clear_category: bool = False
    department: str | None = None
    unsubscribe: bool = False
    delete: bool = False


class VerifyIn(BaseModel):
    contact_ids: list[uuid.UUID] | None = None  # None = all unverified in workspace


def _out(ctx: Ctx, c: Contact, detail: bool = False) -> dict:
    d = row_dict(c)
    comp = ctx.db.execute(sa.select(Company.name, Company.code, Industry.name, Company.name_ar)
                          .outerjoin(Industry, Industry.id == Company.industry_id)
                          .where(Company.id == c.company_id)).first()
    d["company_name"], d["company_code"], d["industry"], d["company_name_ar"] = comp if comp else (None,) * 4
    d["full_name"] = " ".join(x for x in (c.first_name, c.last_name) if x) or None
    d["category"] = ctx.db.scalar(sa.select(Category.name).where(Category.id == c.category_id)) \
        if c.category_id else None
    d["tags"] = [{"id": str(i), "name": n, "color": col} for i, n, col in ctx.db.execute(
        sa.select(Tag.id, Tag.name, Tag.color).join(ContactTag, ContactTag.tag_id == Tag.id)
        .where(ContactTag.contact_id == c.id).order_by(Tag.name))]
    d["is_role_account"] = is_role_account(c.email)
    if detail:
        d["consents"] = [row_dict(x) for x in ctx.db.scalars(
            sa.select(ConsentRecord).where(ConsentRecord.contact_id == c.id)
            .order_by(ConsentRecord.granted_at.desc()))]
        d["suppressed"] = ctx.db.scalar(sa.select(Suppression.reason).where(Suppression.email == c.email))
    return d


def _filtered(q, company_id, department, job_title, subscription_status, verification, category_id,
              tag_id, country_code, industry_id):
    stmt = sa.select(Contact).join(Company, Company.id == Contact.company_id).where(Contact.deleted_at.is_(None))
    if q:
        like = f"%{q.strip()}%"
        full = sa.func.concat_ws(" ", Contact.first_name, Contact.last_name)
        stmt = stmt.where(sa.or_(full.ilike(like), Contact.email.ilike(like), Contact.job_title.ilike(like),
                                 Company.name.ilike(like), Contact.code.ilike(like), Contact.name_ar.ilike(like),
                                 Company.name_ar.ilike(like)))
    if company_id:
        stmt = stmt.where(Contact.company_id.in_(company_id))
    if department:
        stmt = stmt.where(sa.func.lower(Contact.department).in_([d.lower() for d in department]))
    if job_title:
        stmt = stmt.where(sa.or_(*[Contact.job_title.ilike(f"%{t}%") for t in job_title]))
    if subscription_status:
        stmt = stmt.where(Contact.subscription_status.in_(subscription_status))
    if verification:
        stmt = stmt.where(Contact.email_verification_status.in_(verification))
    if category_id:
        stmt = stmt.where(Contact.category_id.in_(category_id))
    if tag_id:
        stmt = stmt.where(Contact.id.in_(sa.select(ContactTag.contact_id).where(ContactTag.tag_id.in_(tag_id))))
    if country_code:
        stmt = stmt.where(Contact.country_code.in_([c.upper() for c in country_code]))
    if industry_id:
        stmt = stmt.where(Company.industry_id.in_(industry_id))
    return stmt


SORTS = {"name": Contact.last_name, "email": Contact.email, "company": Company.name,
         "created_at": Contact.created_at, "job_title": Contact.job_title}


def _sorted(stmt, sort):
    desc = sort.startswith("-")
    col = SORTS.get(sort.lstrip("-"), Contact.created_at)
    return stmt.order_by(col.desc() if desc else col.asc(), Contact.id)


@router.get("")
def list_contacts(ctx: Ctx = Viewer, q: str | None = None, page: int = 1, page_size: int = 25,
                  sort: str = "-created_at",
                  company_id: list[uuid.UUID] | None = Query(None), department: list[str] | None = Query(None),
                  job_title: list[str] | None = Query(None),
                  subscription_status: list[SubscriptionStatus] | None = Query(None),
                  verification: list[VerificationStatus] | None = Query(None),
                  category_id: list[uuid.UUID] | None = Query(None), tag_id: list[uuid.UUID] | None = Query(None),
                  country_code: list[str] | None = Query(None), industry_id: list[uuid.UUID] | None = Query(None)):
    stmt = _sorted(_filtered(q, company_id, department, job_title, subscription_status, verification,
                             category_id, tag_id, country_code, industry_id), sort)
    return paginate(ctx.db, stmt, page, page_size, lambda c: _out(ctx, c))


@router.get("/export")
def export_contacts(ctx: Ctx = Analyst, format: str = Query("csv", pattern="^(csv|xlsx)$"),
                    q: str | None = None, company_id: list[uuid.UUID] | None = Query(None),
                    department: list[str] | None = Query(None), job_title: list[str] | None = Query(None),
                    subscription_status: list[SubscriptionStatus] | None = Query(None),
                    verification: list[VerificationStatus] | None = Query(None),
                    category_id: list[uuid.UUID] | None = Query(None), tag_id: list[uuid.UUID] | None = Query(None),
                    country_code: list[str] | None = Query(None),
                    industry_id: list[uuid.UUID] | None = Query(None)):
    stmt = _sorted(_filtered(q, company_id, department, job_title, subscription_status, verification,
                             category_id, tag_id, country_code, industry_id), "company").limit(200_000)
    rows = []
    for c in ctx.db.scalars(stmt):
        d = _out(ctx, c)
        d["tags"] = [t["name"] for t in d["tags"]]
        rows.append(d)
    audit(ctx, "export", "contact", after={"rows": len(rows), "format": format})
    cols = [("code", "Contact ID"), ("company_code", "Company ID"), ("company_name", "Company"),
            ("company_name_ar", "Company (Arabic)"), ("first_name", "First Name"), ("last_name", "Last Name"),
            ("name_ar", "Name (Arabic)"), ("job_title", "Job Title"),
            ("department", "Department"), ("email", "Business Email"), ("phone", "Phone"),
            ("country_code", "Country"), ("city", "City"), ("category", "Contact Category"),
            ("subscription_status", "Subscription Status"), ("consent_source", "Consent Source"),
            ("consent_date", "Consent Date"), ("email_verification_status", "Email Verification"),
            ("tags", "Tags"), ("notes", "Notes")]
    return export_response(rows, cols, format, "contacts")


@router.get("/duplicates")
def duplicates(ctx: Ctx = Marketer):
    """Near-duplicate people: same name at the same company with different emails,
    or the same mailbox across case/dots variants (gmail-style)."""
    rows = ctx.db.execute(sa.text("""
        SELECT a.id a_id, a.email a_email, b.id b_id, b.email b_email,
               concat_ws(' ', a.first_name, a.last_name) AS name, c.name AS company,
               'same name at same company' AS reason
        FROM contacts a JOIN contacts b ON a.id < b.id AND a.company_id = b.company_id
        JOIN companies c ON c.id = a.company_id
        WHERE a.deleted_at IS NULL AND b.deleted_at IS NULL
          AND lower(coalesce(a.first_name,'')) = lower(coalesce(b.first_name,''))
          AND lower(coalesce(a.last_name,'')) = lower(coalesce(b.last_name,''))
          AND coalesce(a.first_name, a.last_name) IS NOT NULL
        UNION ALL
        SELECT a.id, a.email, b.id, b.email, concat_ws(' ', a.first_name, a.last_name), c.name,
               'same mailbox (dots/+tag variant)'
        FROM contacts a JOIN contacts b ON a.id < b.id
        JOIN companies c ON c.id = a.company_id
        WHERE a.deleted_at IS NULL AND b.deleted_at IS NULL
          AND split_part(a.email::text, '@', 2) = split_part(b.email::text, '@', 2)
          AND replace(split_part(split_part(a.email::text,'@',1),'+',1),'.','')
            = replace(split_part(split_part(b.email::text,'@',1),'+',1),'.','')
        LIMIT 500
    """)).mappings().all()
    return [{"a": {"id": str(r["a_id"]), "email": r["a_email"]}, "b": {"id": str(r["b_id"]), "email": r["b_email"]},
             "name": r["name"], "company": r["company"], "reason": r["reason"]} for r in rows]


@router.get("/check-email")
def check_email(email: str, ctx: Ctx = Viewer):
    c = ctx.db.scalar(sa.select(Contact).where(Contact.email == email.strip(), Contact.deleted_at.is_(None)))
    sup = ctx.db.scalar(sa.select(Suppression.reason).where(Suppression.email == email.strip()))
    return {"exists": c is not None, "contact_id": str(c.id) if c else None,
            "suppressed": sup.value if sup else None, "role_account": is_role_account(email)}


@router.get("/facets")
def facets(ctx: Ctx = Viewer):
    """Distinct values for filter dropdowns."""
    def distinct(col):
        return [v for (v,) in ctx.db.execute(sa.select(col).where(Contact.deleted_at.is_(None), col.isnot(None))
                                             .distinct().order_by(col).limit(500))]
    return {"departments": distinct(Contact.department), "job_titles": distinct(Contact.job_title),
            "countries": distinct(Contact.country_code), "cities": distinct(Contact.city)}


def _apply_consent(ctx: Ctx, c: Contact, body) -> None:
    if not (body.consent_source and body.consent_date):
        return
    c.consent_source, c.consent_date = body.consent_source, body.consent_date
    ctx.db.add(ConsentRecord(workspace_id=ctx.workspace_id, contact_id=c.id, lawful_basis=body.lawful_basis,
                             source=body.consent_source, granted_at=body.consent_date, recorded_by=ctx.user.id))
    if c.subscription_status == SubscriptionStatus.PENDING:
        c.subscription_status = SubscriptionStatus.SUBSCRIBED


@router.post("", status_code=201)
def create_contact(body: ContactIn, ctx: Ctx = Marketer):
    get_or_404(ctx.db, Company, body.company_id, "Company")
    if body.category_id:
        get_or_404(ctx.db, Category, body.category_id, "Category")
    data = body.model_dump(exclude={"tag_ids", "consent_source", "consent_date", "lawful_basis"})
    data["phone"] = normalize_phone(data.get("phone"), data.get("country_code"))
    c = Contact(workspace_id=ctx.workspace_id, created_by=ctx.user.id, **data)
    try:
        with ctx.db.begin_nested():
            ctx.db.add(c)
            ctx.db.flush()
    except IntegrityError:
        raise Conflict("A contact with this email already exists", field="email") from None
    if ctx.db.scalar(sa.select(Suppression.id).where(Suppression.email == c.email)):
        c.subscription_status = SubscriptionStatus.UNSUBSCRIBED
    else:
        _apply_consent(ctx, c, body)
    _set_tags(ctx, c.id, body.tag_ids)
    audit(ctx, "create", "contact", c.id, after=row_dict(c))
    return _out(ctx, c, detail=True)


@router.get("/{contact_id}")
def get_contact(contact_id: uuid.UUID, ctx: Ctx = Viewer):
    return _out(ctx, get_or_404(ctx.db, Contact, contact_id, "Contact"), detail=True)


@router.patch("/{contact_id}")
def update_contact(contact_id: uuid.UUID, body: ContactUpdate, ctx: Ctx = Marketer):
    c = get_or_404(ctx.db, Contact, contact_id, "Contact")
    before = row_dict(c)
    data = body.model_dump(exclude_unset=True, exclude={"tag_ids"})
    if data.get("phone"):
        data["phone"] = normalize_phone(data["phone"], data.get("country_code") or c.country_code)
    if "company_id" in data:
        get_or_404(ctx.db, Company, data["company_id"], "Company")
    for k, v in data.items():
        setattr(c, k, v)
    try:
        with ctx.db.begin_nested():
            ctx.db.flush()
    except IntegrityError:
        raise Conflict("A contact with this email already exists", field="email") from None
    _set_tags(ctx, c.id, body.tag_ids)
    audit(ctx, "update", "contact", c.id, before, row_dict(c))
    return _out(ctx, c, detail=True)


@router.delete("/{contact_id}", status_code=204)
def delete_contact(contact_id: uuid.UUID, ctx: Ctx = Admin):
    c = get_or_404(ctx.db, Contact, contact_id, "Contact")
    c.deleted_at = datetime.now(timezone.utc)
    audit(ctx, "delete", "contact", c.id, before=row_dict(c))
    return Response(status_code=204)


@router.get("/{contact_id}/consents")
def list_consents(contact_id: uuid.UUID, ctx: Ctx = Viewer):
    get_or_404(ctx.db, Contact, contact_id, "Contact")
    return [row_dict(x) for x in ctx.db.scalars(sa.select(ConsentRecord).where(
        ConsentRecord.contact_id == contact_id).order_by(ConsentRecord.granted_at.desc()))]


@router.post("/{contact_id}/consents", status_code=201)
def add_consent(contact_id: uuid.UUID, body: ConsentIn, ctx: Ctx = Marketer):
    c = get_or_404(ctx.db, Contact, contact_id, "Contact")
    if ctx.db.scalar(sa.select(Suppression.id).where(Suppression.email == c.email)):
        raise Conflict("This address is on the suppression list. An admin must remove the suppression first.")
    granted = body.granted_at or datetime.now(timezone.utc)
    rec = ConsentRecord(workspace_id=ctx.workspace_id, contact_id=c.id, lawful_basis=body.lawful_basis,
                        source=body.source, evidence=body.evidence, ip_address=body.ip_address,
                        granted_at=granted, recorded_by=ctx.user.id)
    ctx.db.add(rec)
    c.consent_source, c.consent_date = body.source, granted
    if c.subscription_status in (SubscriptionStatus.PENDING, SubscriptionStatus.UNSUBSCRIBED):
        c.subscription_status = SubscriptionStatus.SUBSCRIBED
    ctx.db.flush()
    audit(ctx, "consent_granted", "contact", c.id, after=row_dict(rec))
    return row_dict(rec)


@router.post("/{contact_id}/unsubscribe")
def unsubscribe(contact_id: uuid.UUID, body: UnsubscribeIn, ctx: Ctx = Marketer):
    c = get_or_404(ctx.db, Contact, contact_id, "Contact")
    unsubscribe_contact(ctx.db, ctx.workspace_id, c, SuppressionReason.MANUAL,
                        f"manual: {body.reason or 'by user'}"[:200], ctx.user.id)
    audit(ctx, "unsubscribe", "contact", c.id, after={"reason": body.reason})
    return _out(ctx, c, detail=True)


@router.post("/{contact_id}/erase", status_code=204)
def erase(contact_id: uuid.UUID, ctx: Ctx = Owner):
    """Right to erasure: anonymise personal data, keep a suppression so they are never re-mailed."""
    c = get_or_404(ctx.db, Contact, contact_id, "Contact")
    unsubscribe_contact(ctx.db, ctx.workspace_id, c, SuppressionReason.MANUAL, "erasure request", ctx.user.id)
    original = c.email
    anon = f"erased-{c.id.hex[:12]}@erased.invalid"
    for f in ("first_name", "last_name", "name_ar", "job_title", "department", "phone", "city", "notes",
              "consent_source"):
        setattr(c, f, None)
    c.email = anon
    c.deleted_at = datetime.now(timezone.utc)
    ctx.db.execute(sa.delete(ContactTag).where(ContactTag.contact_id == c.id))
    ctx.db.execute(sa.update(ConsentRecord).where(ConsentRecord.contact_id == c.id)
                   .values(evidence=None, ip_address=None))
    audit(ctx, "erase", "contact", c.id, after={"email_hash": hashlib.sha256(
        original.lower().encode()).hexdigest()})
    return Response(status_code=204)


@router.post("/bulk")
def bulk(body: BulkIn, ctx: Ctx = Marketer):
    if body.delete and not ctx.at_least(MemberRole.ADMIN):
        raise BadRequest("Bulk delete requires admin role")
    contacts = ctx.db.scalars(sa.select(Contact).where(Contact.id.in_(body.contact_ids),
                                                       Contact.deleted_at.is_(None))).all()
    now = datetime.now(timezone.utc)
    for c in contacts:
        for t in body.add_tag_ids:
            ctx.db.execute(pg_insert(ContactTag).values(contact_id=c.id, tag_id=t).on_conflict_do_nothing())
        if body.remove_tag_ids:
            ctx.db.execute(sa.delete(ContactTag).where(ContactTag.contact_id == c.id,
                                                       ContactTag.tag_id.in_(body.remove_tag_ids)))
        if body.category_id or body.clear_category:
            c.category_id = None if body.clear_category else body.category_id
        if body.department is not None:
            c.department = body.department or None
        if body.unsubscribe:
            unsubscribe_contact(ctx.db, ctx.workspace_id, c, SuppressionReason.MANUAL, "bulk", ctx.user.id)
        if body.delete:
            c.deleted_at = now
    audit(ctx, "bulk_update", "contact", after={**body.model_dump(mode="json"), "affected": len(contacts)})
    return {"affected": len(contacts)}


@router.post("/verify", status_code=202)
def verify_emails(body: VerifyIn, ctx: Ctx = Marketer):
    stmt = sa.select(Contact.id).where(Contact.deleted_at.is_(None))
    stmt = stmt.where(Contact.id.in_(body.contact_ids)) if body.contact_ids else \
        stmt.where(Contact.email_verification_status == VerificationStatus.UNVERIFIED)
    ids = [str(i) for i in ctx.db.scalars(stmt.limit(50_000))]
    from app.workers.tasks import verify_contacts
    for i in range(0, len(ids), 200):
        enqueue_after_commit(ctx.db, verify_contacts, str(ctx.workspace_id), ids[i:i + 200])
    return {"queued": len(ids)}


def _set_tags(ctx: Ctx, contact_id, tag_ids) -> None:
    if tag_ids is None:
        return
    ctx.db.execute(sa.delete(ContactTag).where(ContactTag.contact_id == contact_id))
    for t in set(tag_ids):
        get_or_404(ctx.db, Tag, t, "Tag")
        ctx.db.add(ContactTag(contact_id=contact_id, tag_id=t))
    ctx.db.flush()
