"""Module 1: Company database."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import sqlalchemy as sa
from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field, HttpUrl, field_validator
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.core.deps import Admin, Analyst, Ctx, Marketer, Viewer
from app.core.errors import BadRequest, Conflict
from app.models import (
    Campaign,
    CampaignRecipient,
    Category,
    Company,
    CompanyCategory,
    CompanyTag,
    Contact,
    Industry,
    Tag,
)
from app.models.enums import CompanySize, CompanyStatus
from app.services.common import audit, domain_from_website, get_or_404, paginate, row_dict
from app.services.exports import export_response

router = APIRouter(prefix="/companies", tags=["companies"])


class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    name_ar: str | None = Field(default=None, max_length=255)
    industry_id: uuid.UUID | None = None
    business_type: str | None = Field(default=None, max_length=120)
    country_code: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    city: str | None = Field(default=None, max_length=120)
    website: str | None = Field(default=None, max_length=255)
    company_size: CompanySize | None = None
    annual_revenue: Decimal | None = Field(default=None, ge=0)
    status: CompanyStatus = CompanyStatus.ACTIVE
    data_source: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    tag_ids: list[uuid.UUID] | None = None
    category_ids: list[uuid.UUID] | None = None

    @field_validator("country_code")
    @classmethod
    def _upper(cls, v):
        return v.upper() if v else v

    @field_validator("website")
    @classmethod
    def _website(cls, v):
        if not v:
            return None
        url = v if "://" in v else f"https://{v}"
        HttpUrl(url)
        return url


class CompanyUpdate(CompanyIn):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    status: CompanyStatus | None = None


class MergeIn(BaseModel):
    primary_id: uuid.UUID
    duplicate_ids: list[uuid.UUID] = Field(min_length=1)


class TagAssignIn(BaseModel):
    tag_ids: list[uuid.UUID]


def _out(ctx: Ctx, c: Company, detail: bool = False) -> dict:
    d = row_dict(c, exclude={"normalized_name"})
    d["industry"] = ctx.db.scalar(sa.select(Industry.name).where(Industry.id == c.industry_id)) \
        if c.industry_id else None
    d["tags"] = [{"id": str(i), "name": n, "color": col} for i, n, col in ctx.db.execute(
        sa.select(Tag.id, Tag.name, Tag.color).join(CompanyTag, CompanyTag.tag_id == Tag.id)
        .where(CompanyTag.company_id == c.id).order_by(Tag.name))]
    d["categories"] = [{"id": str(i), "name": n} for i, n in ctx.db.execute(
        sa.select(Category.id, Category.name).join(CompanyCategory, CompanyCategory.category_id == Category.id)
        .where(CompanyCategory.company_id == c.id).order_by(Category.name))]
    d["contact_count"] = ctx.db.scalar(sa.select(sa.func.count()).select_from(Contact).where(
        Contact.company_id == c.id, Contact.deleted_at.is_(None)))
    if detail:
        contacts = ctx.db.scalars(sa.select(Contact).where(Contact.company_id == c.id,
                                                           Contact.deleted_at.is_(None))
                                  .order_by(Contact.last_name, Contact.first_name).limit(200)).all()
        d["contacts"] = [{k: v for k, v in row_dict(x).items() if k in {
            "id", "code", "first_name", "last_name", "job_title", "department", "email", "phone",
            "subscription_status", "email_verification_status"}} for x in contacts]
        d["campaigns"] = [{"id": str(i), "name": n, "status": s.value, "sent": sent} for i, n, s, sent in
                          ctx.db.execute(
            sa.select(Campaign.id, Campaign.name, Campaign.status, sa.func.count(CampaignRecipient.id))
            .join(CampaignRecipient, CampaignRecipient.campaign_id == Campaign.id)
            .join(Contact, Contact.id == CampaignRecipient.contact_id)
            .where(Contact.company_id == c.id)
            .group_by(Campaign.id).order_by(Campaign.created_at.desc()).limit(20))]
    return d


def _filtered(q, industry_id, country_code, city, company_size, status, tag_id, category_id):
    stmt = sa.select(Company).where(Company.deleted_at.is_(None))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(sa.or_(Company.name.ilike(like), Company.domain.ilike(like),
                                 Company.code.ilike(like), Company.city.ilike(like), Company.name_ar.ilike(like)))
    if industry_id:
        stmt = stmt.where(Company.industry_id.in_(industry_id))
    if country_code:
        stmt = stmt.where(Company.country_code.in_([c.upper() for c in country_code]))
    if city:
        stmt = stmt.where(sa.func.lower(Company.city).in_([c.lower() for c in city]))
    if company_size:
        stmt = stmt.where(Company.company_size.in_(company_size))
    if status:
        stmt = stmt.where(Company.status.in_(status))
    if tag_id:
        stmt = stmt.where(Company.id.in_(sa.select(CompanyTag.company_id).where(CompanyTag.tag_id.in_(tag_id))))
    if category_id:
        stmt = stmt.where(Company.id.in_(sa.select(CompanyCategory.company_id)
                                         .where(CompanyCategory.category_id.in_(category_id))))
    return stmt


SORTS = {"name": Company.name, "created_at": Company.created_at, "updated_at": Company.updated_at,
         "country": Company.country_code, "city": Company.city}


def _sorted(stmt, sort: str):
    desc = sort.startswith("-")
    col = SORTS.get(sort.lstrip("-"), Company.created_at)
    return stmt.order_by(col.desc() if desc else col.asc(), Company.id)


@router.get("")
def list_companies(ctx: Ctx = Viewer, q: str | None = None, page: int = 1, page_size: int = 25,
                   sort: str = "-created_at",
                   industry_id: list[uuid.UUID] | None = Query(None),
                   country_code: list[str] | None = Query(None), city: list[str] | None = Query(None),
                   company_size: list[CompanySize] | None = Query(None),
                   status: list[CompanyStatus] | None = Query(None),
                   tag_id: list[uuid.UUID] | None = Query(None),
                   category_id: list[uuid.UUID] | None = Query(None)):
    stmt = _sorted(_filtered(q, industry_id, country_code, city, company_size, status, tag_id,
                             category_id), sort)
    return paginate(ctx.db, stmt, page, page_size, lambda c: _out(ctx, c))


@router.get("/export")
def export_companies(ctx: Ctx = Analyst, format: str = Query("csv", pattern="^(csv|xlsx)$"),
                     q: str | None = None,
                     industry_id: list[uuid.UUID] | None = Query(None),
                     country_code: list[str] | None = Query(None), city: list[str] | None = Query(None),
                     company_size: list[CompanySize] | None = Query(None),
                     status: list[CompanyStatus] | None = Query(None),
                     tag_id: list[uuid.UUID] | None = Query(None),
                     category_id: list[uuid.UUID] | None = Query(None)):
    stmt = _sorted(_filtered(q, industry_id, country_code, city, company_size, status, tag_id,
                             category_id), "name").limit(100_000)
    rows = []
    for c in ctx.db.scalars(stmt):
        d = _out(ctx, c)
        d["tags"] = [t["name"] for t in d["tags"]]
        d["categories"] = [t["name"] for t in d["categories"]]
        rows.append(d)
    audit(ctx, "export", "company", after={"rows": len(rows), "format": format})
    cols = [("code", "Company ID"), ("name", "Company Name"), ("name_ar", "Company Name (Arabic)"),
            ("industry", "Industry"),
            ("business_type", "Business Type"), ("country_code", "Country"), ("city", "City"),
            ("website", "Website"), ("company_size", "Company Size"), ("annual_revenue", "Annual Revenue"),
            ("categories", "Categories"), ("tags", "Tags"), ("status", "Status"),
            ("data_source", "Data Source"), ("contact_count", "Contacts"), ("notes", "Notes"),
            ("created_at", "Created"), ("updated_at", "Updated")]
    return export_response(rows, cols, format, "companies")


@router.get("/duplicates")
def find_duplicates(ctx: Ctx = Marketer, threshold: float = Query(0.6, ge=0.3, le=1.0)):
    ctx.db.execute(sa.text("SELECT set_config('pg_trgm.similarity_threshold', :t, true)"),
                   {"t": str(threshold)})
    rows = ctx.db.execute(sa.text("""
        SELECT a.id AS a_id, a.name AS a_name, a.domain AS a_domain,
               b.id AS b_id, b.name AS b_name, b.domain AS b_domain,
               similarity(a.normalized_name, b.normalized_name) AS score,
               (a.domain IS NOT NULL AND a.domain = b.domain) AS same_domain
        FROM companies a JOIN companies b ON a.id < b.id
        WHERE a.deleted_at IS NULL AND b.deleted_at IS NULL
          AND (a.normalized_name % b.normalized_name OR (a.domain IS NOT NULL AND a.domain = b.domain))
        ORDER BY same_domain DESC, score DESC LIMIT 200
    """)).mappings().all()
    return [{"a": {"id": str(r["a_id"]), "name": r["a_name"], "domain": r["a_domain"]},
             "b": {"id": str(r["b_id"]), "name": r["b_name"], "domain": r["b_domain"]},
             "score": round(float(r["score"]), 3), "same_domain": r["same_domain"]} for r in rows]


@router.get("/check-duplicate")
def check_duplicate(ctx: Ctx = Viewer, name: str = "", website: str | None = None,
                    exclude_id: uuid.UUID | None = None):
    domain = domain_from_website(website)
    stmt = sa.select(Company.id, Company.name, Company.domain,
                     sa.func.similarity(Company.normalized_name, sa.func.lower(
                         sa.func.regexp_replace(name, "[[:space:][:punct:]]+", "", "g"))).label("score")
                     ).where(Company.deleted_at.is_(None))
    if exclude_id:
        stmt = stmt.where(Company.id != exclude_id)
    order = [(Company.domain == domain).desc()] if domain else []
    rows = ctx.db.execute(stmt.order_by(*order, sa.desc("score")).limit(5)).all()
    return [{"id": str(i), "name": n, "domain": d, "score": round(float(s or 0), 3),
             "same_domain": bool(domain and d == domain)}
            for i, n, d, s in rows if (domain and d == domain) or (s or 0) >= 0.5]


@router.post("", status_code=201)
def create_company(body: CompanyIn, ctx: Ctx = Marketer):
    data = body.model_dump(exclude={"tag_ids", "category_ids"})
    data["domain"] = domain_from_website(body.website)
    c = Company(workspace_id=ctx.workspace_id, created_by=ctx.user.id, **data)
    try:
        with ctx.db.begin_nested():
            ctx.db.add(c)
            ctx.db.flush()
    except IntegrityError:
        raise Conflict("A company with this website domain already exists", field="website") from None
    _set_links(ctx, c.id, body.tag_ids, body.category_ids)
    audit(ctx, "create", "company", c.id, after=row_dict(c))
    return _out(ctx, c, detail=True)


@router.get("/{company_id}")
def get_company(company_id: uuid.UUID, ctx: Ctx = Viewer):
    return _out(ctx, get_or_404(ctx.db, Company, company_id, "Company"), detail=True)


@router.patch("/{company_id}")
def update_company(company_id: uuid.UUID, body: CompanyUpdate, ctx: Ctx = Marketer):
    c = get_or_404(ctx.db, Company, company_id, "Company")
    before = row_dict(c)
    data = body.model_dump(exclude_unset=True, exclude={"tag_ids", "category_ids"})
    if "website" in data:
        data["domain"] = domain_from_website(data["website"])
    for k, v in data.items():
        setattr(c, k, v)
    try:
        with ctx.db.begin_nested():
            ctx.db.flush()
    except IntegrityError:
        raise Conflict("A company with this website domain already exists", field="website") from None
    _set_links(ctx, c.id, body.tag_ids, body.category_ids)
    audit(ctx, "update", "company", c.id, before, row_dict(c))
    return _out(ctx, c, detail=True)


@router.delete("/{company_id}", status_code=204)
def delete_company(company_id: uuid.UUID, ctx: Ctx = Admin, cascade_archive: bool = False):
    c = get_or_404(ctx.db, Company, company_id, "Company")
    n = ctx.db.scalar(sa.select(sa.func.count()).select_from(Contact).where(
        Contact.company_id == c.id, Contact.deleted_at.is_(None)))
    if n and not cascade_archive:
        raise Conflict(f"Company has {n} active contact(s). Pass cascade_archive=true to archive them too.",
                       contact_count=n)
    now = datetime.now(timezone.utc)
    if n:
        ctx.db.execute(sa.update(Contact).where(Contact.company_id == c.id, Contact.deleted_at.is_(None))
                       .values(deleted_at=now))
    c.deleted_at = now
    audit(ctx, "delete", "company", c.id, before=row_dict(c), after={"archived_contacts": n})
    return Response(status_code=204)


@router.post("/{company_id}/tags")
def add_tags(company_id: uuid.UUID, body: TagAssignIn, ctx: Ctx = Marketer):
    get_or_404(ctx.db, Company, company_id, "Company")
    for t in body.tag_ids:
        get_or_404(ctx.db, Tag, t, "Tag")
        ctx.db.execute(pg_insert(CompanyTag).values(company_id=company_id, tag_id=t).on_conflict_do_nothing())
    return _out(ctx, ctx.db.get(Company, company_id))


@router.delete("/{company_id}/tags/{tag_id}", status_code=204)
def remove_tag(company_id: uuid.UUID, tag_id: uuid.UUID, ctx: Ctx = Marketer):
    get_or_404(ctx.db, Company, company_id, "Company")
    ctx.db.execute(sa.delete(CompanyTag).where(CompanyTag.company_id == company_id, CompanyTag.tag_id == tag_id))
    return Response(status_code=204)


@router.put("/{company_id}/categories")
def set_categories(company_id: uuid.UUID, body: dict, ctx: Ctx = Marketer):
    get_or_404(ctx.db, Company, company_id, "Company")
    _set_links(ctx, company_id, None, [uuid.UUID(str(x)) for x in body.get("category_ids", [])])
    return _out(ctx, ctx.db.get(Company, company_id))


@router.post("/merge")
def merge_companies(body: MergeIn, ctx: Ctx = Admin):
    if body.primary_id in body.duplicate_ids:
        raise BadRequest("primary_id cannot also be a duplicate")
    primary = get_or_404(ctx.db, Company, body.primary_id, "Company")
    moved = 0
    now = datetime.now(timezone.utc)
    for dup_id in body.duplicate_ids:
        dup = get_or_404(ctx.db, Company, dup_id, "Company")
        moved += ctx.db.execute(sa.update(Contact).where(Contact.company_id == dup.id)
                                .values(company_id=primary.id)).rowcount
        for (tid,) in ctx.db.execute(sa.select(CompanyTag.tag_id).where(CompanyTag.company_id == dup.id)):
            ctx.db.execute(pg_insert(CompanyTag).values(company_id=primary.id, tag_id=tid)
                           .on_conflict_do_nothing())
        for (cid,) in ctx.db.execute(sa.select(CompanyCategory.category_id)
                                     .where(CompanyCategory.company_id == dup.id)):
            ctx.db.execute(pg_insert(CompanyCategory).values(company_id=primary.id, category_id=cid)
                           .on_conflict_do_nothing())
        for f in ("industry_id", "business_type", "country_code", "city", "company_size",
                  "annual_revenue", "data_source"):
            if getattr(primary, f) is None and getattr(dup, f) is not None:
                setattr(primary, f, getattr(dup, f))
        if primary.website is None and dup.website:
            primary.website = dup.website
            dup_domain, dup.domain = dup.domain, None
            ctx.db.flush()
            primary.domain = dup_domain
        if dup.notes:
            primary.notes = ((primary.notes or "") + f"\n[Merged from {dup.name}] {dup.notes}").strip()
        dup.deleted_at = now
        dup.domain = None
        ctx.db.flush()
    audit(ctx, "merge", "company", primary.id, after={"merged": [str(d) for d in body.duplicate_ids],
                                                      "contacts_moved": moved})
    return {**_out(ctx, primary, detail=True), "contacts_moved": moved}


def _set_links(ctx: Ctx, company_id: uuid.UUID, tag_ids, category_ids) -> None:
    if tag_ids is not None:
        ctx.db.execute(sa.delete(CompanyTag).where(CompanyTag.company_id == company_id))
        for t in set(tag_ids):
            get_or_404(ctx.db, Tag, t, "Tag")
            ctx.db.add(CompanyTag(company_id=company_id, tag_id=t))
    if category_ids is not None:
        ctx.db.execute(sa.delete(CompanyCategory).where(CompanyCategory.company_id == company_id))
        for cid in set(category_ids):
            get_or_404(ctx.db, Category, cid, "Category")
            ctx.db.add(CompanyCategory(company_id=company_id, category_id=cid))
    ctx.db.flush()
