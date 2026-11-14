"""Module 3: audience segments (save, edit, duplicate, live counts, preview)."""
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from app.core.deps import Ctx, Marketer, Viewer
from app.core.errors import BadRequest, Conflict
from app.models import Campaign, Category, Company, Contact, Industry, Segment, Tag
from app.models.enums import CategoryScope, CompanySize, CompanyStatus, SubscriptionStatus, VerificationStatus
from app.services import segments as seg
from app.services.common import audit, get_or_404, paginate, row_dict
from app.services.compliance import eligibility_clause

router = APIRouter(prefix="/segments", tags=["segments"])


class RulesIn(BaseModel):
    rules: dict = Field(default_factory=lambda: {"op": "and", "rules": []})


class SegmentIn(RulesIn):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None


class SegmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    rules: dict | None = None


def _check(rules: dict):
    try:
        seg.compile_rules(rules)
    except seg.SegmentError as e:
        raise BadRequest(str(e)) from None


def _counts(ctx: Ctx, rules: dict) -> dict:
    try:
        return seg.counts(ctx.db, rules)
    except seg.SegmentError as e:
        raise BadRequest(str(e)) from None


def _refresh(ctx: Ctx, s: Segment) -> dict:
    c = _counts(ctx, s.rules)
    s.cached_count, s.cached_eligible_count = c["total"], c["eligible"]
    s.count_refreshed_at = datetime.now(timezone.utc)
    return c


def _contact_row(c: Contact, company: str, eligible: bool, co_city: str | None = None,
                 co_country: str | None = None) -> dict:
    return {"id": str(c.id), "code": c.code, "first_name": c.first_name, "last_name": c.last_name,
            "email": c.email, "job_title": c.job_title, "department": c.department, "company_name": company,
            "country_code": c.country_code or co_country, "city": c.city or co_city, "subscription_status": c.subscription_status.value,
            "email_verification_status": c.email_verification_status.value, "eligible": eligible}


def _preview(ctx: Ctx, rules: dict, page: int, page_size: int, eligible_only: bool) -> dict:
    try:
        stmt = seg.base_query().where(seg.compile_rules(rules))
    except seg.SegmentError as e:
        raise BadRequest(str(e)) from None
    if eligible_only:
        stmt = stmt.where(eligibility_clause())
    stmt = stmt.add_columns(Company.name, eligibility_clause().label("eligible"), Company.city, Company.country_code) \
        .order_by(Company.name, Contact.last_name, Contact.id)
    page, page_size = max(page, 1), min(max(page_size, 1), 200)
    total = ctx.db.scalar(sa.select(sa.func.count()).select_from(stmt.order_by(None).subquery()))
    rows = ctx.db.execute(stmt.limit(page_size).offset((page - 1) * page_size)).all()
    return {"items": [_contact_row(c, n, bool(e), cc, ct) for c, n, e, cc, ct in rows], "total": total, "page": page,
            "page_size": page_size}


@router.get("/fields")
def fields(ctx: Ctx = Viewer):
    """Field catalogue for the segment builder with operators and value options."""
    opts = {
        "industry": [{"value": str(i), "label": n} for i, n in ctx.db.execute(
            sa.select(Industry.id, Industry.name).order_by(Industry.name))],
        "contact_category": [{"value": str(i), "label": n} for i, n in ctx.db.execute(
            sa.select(Category.id, Category.name).where(Category.scope == CategoryScope.CONTACT).order_by(Category.name))],
        "company_category": [{"value": str(i), "label": n} for i, n in ctx.db.execute(
            sa.select(Category.id, Category.name).where(Category.scope == CategoryScope.COMPANY).order_by(Category.name))],
        "tags": [{"value": str(i), "label": n} for i, n in ctx.db.execute(sa.select(Tag.id, Tag.name).order_by(Tag.name))],
        "company_size": [{"value": s.value, "label": s.value} for s in CompanySize],
        "company_status": [{"value": s.value, "label": s.value.title()} for s in CompanyStatus],
        "subscription_status": [{"value": s.value, "label": s.value.title()} for s in SubscriptionStatus],
        "email_verification_status": [{"value": s.value, "label": s.value.title()} for s in VerificationStatus],
        "country": [{"value": v, "label": v} for (v,) in ctx.db.execute(sa.text(
            "SELECT DISTINCT coalesce(ct.country_code, co.country_code) v FROM contacts ct "
            "JOIN companies co ON co.id = ct.company_id WHERE coalesce(ct.country_code, co.country_code) "
            "IS NOT NULL ORDER BY 1"))],
        "city": [{"value": v, "label": v} for (v,) in ctx.db.execute(sa.text(
            "SELECT DISTINCT coalesce(ct.city, co.city) v FROM contacts ct JOIN companies co ON "
            "co.id = ct.company_id WHERE coalesce(ct.city, co.city) IS NOT NULL ORDER BY 1 LIMIT 500"))],
        "department": [{"value": v, "label": v} for (v,) in ctx.db.execute(
            sa.select(Contact.department).where(Contact.department.isnot(None)).distinct().order_by(Contact.department))],
    }
    opts["company_tags"] = opts["tags"]
    out = []
    for key, (kind, _, label, _) in seg.FIELDS.items():
        out.append({"field": key, "label": label, "kind": kind, "operators": sorted(seg.OPS_BY_KIND[kind]),
                    "options": opts.get(key), "async_options": key == "company"})
    return out


@router.post("/count")
def count_unsaved(body: RulesIn, ctx: Ctx = Viewer):
    return _counts(ctx, body.rules)


@router.post("/preview")
def preview_unsaved(body: RulesIn, ctx: Ctx = Viewer, page: int = 1, page_size: int = 25,
                    eligible_only: bool = False):
    return _preview(ctx, body.rules, page, page_size, eligible_only)


@router.get("")
def list_segments(ctx: Ctx = Viewer, q: str | None = None, page: int = 1, page_size: int = 50):
    stmt = sa.select(Segment).order_by(Segment.updated_at.desc())
    if q:
        stmt = stmt.where(Segment.name.ilike(f"%{q}%"))
    used = dict(ctx.db.execute(sa.select(Campaign.segment_id, sa.func.count()).where(Campaign.deleted_at.is_(None))
                               .group_by(Campaign.segment_id)).all())
    return paginate(ctx.db, stmt, page, page_size, lambda s: {**row_dict(s), "campaign_count": used.get(s.id, 0)})


@router.post("", status_code=201)
def create_segment(body: SegmentIn, ctx: Ctx = Marketer):
    _check(body.rules)
    s = Segment(workspace_id=ctx.workspace_id, created_by=ctx.user.id, **body.model_dump())
    try:
        with ctx.db.begin_nested():
            ctx.db.add(s)
            ctx.db.flush()
    except IntegrityError:
        raise Conflict("A segment with this name already exists") from None
    counts = _refresh(ctx, s)
    audit(ctx, "create", "segment", s.id, after=row_dict(s))
    return {**row_dict(s), "counts": counts}


@router.get("/{segment_id}")
def get_segment(segment_id: uuid.UUID, ctx: Ctx = Viewer):
    s = get_or_404(ctx.db, Segment, segment_id, "Segment")
    return {**row_dict(s), "counts": _refresh(ctx, s)}


@router.patch("/{segment_id}")
def update_segment(segment_id: uuid.UUID, body: SegmentUpdate, ctx: Ctx = Marketer):
    s = get_or_404(ctx.db, Segment, segment_id, "Segment")
    before = row_dict(s)
    data = body.model_dump(exclude_unset=True)
    if "rules" in data:
        _check(data["rules"])
    for k, v in data.items():
        setattr(s, k, v)
    try:
        with ctx.db.begin_nested():
            ctx.db.flush()
    except IntegrityError:
        raise Conflict("A segment with this name already exists") from None
    counts = _refresh(ctx, s)
    audit(ctx, "update", "segment", s.id, before, row_dict(s))
    return {**row_dict(s), "counts": counts}


@router.delete("/{segment_id}", status_code=204)
def delete_segment(segment_id: uuid.UUID, ctx: Ctx = Marketer):
    s = get_or_404(ctx.db, Segment, segment_id, "Segment")
    active = ctx.db.scalar(sa.select(sa.func.count()).select_from(Campaign).where(
        Campaign.segment_id == s.id, Campaign.status.in_(["scheduled", "processing", "sending", "paused"])))
    if active:
        raise Conflict("Segment is used by a scheduled or running campaign")
    ctx.db.delete(s)
    audit(ctx, "delete", "segment", segment_id, before=row_dict(s))
    return Response(status_code=204)


@router.post("/{segment_id}/duplicate", status_code=201)
def duplicate_segment(segment_id: uuid.UUID, ctx: Ctx = Marketer):
    s = get_or_404(ctx.db, Segment, segment_id, "Segment")
    base = f"{s.name} (copy)"
    name, n = base, 2
    while ctx.db.scalar(sa.select(Segment.id).where(sa.func.lower(Segment.name) == name.lower())):
        name, n = f"{base} {n}", n + 1
    new = Segment(workspace_id=ctx.workspace_id, name=name[:200], description=s.description, rules=s.rules,
                  created_by=ctx.user.id)
    ctx.db.add(new)
    ctx.db.flush()
    counts = _refresh(ctx, new)
    audit(ctx, "duplicate", "segment", new.id, after={"from": str(s.id)})
    return {**row_dict(new), "counts": counts}


@router.get("/{segment_id}/contacts")
def segment_contacts(segment_id: uuid.UUID, ctx: Ctx = Viewer, page: int = 1, page_size: int = 25,
                     eligible_only: bool = False):
    s = get_or_404(ctx.db, Segment, segment_id, "Segment")
    return _preview(ctx, s.rules, page, page_size, eligible_only)
