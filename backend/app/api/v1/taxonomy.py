"""Industries, categories and tags (Module 3 taxonomy)."""
import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from app.core.deps import Ctx, Marketer, Viewer
from app.core.errors import Conflict
from app.models import Category, Company, CompanyCategory, CompanyTag, Contact, ContactTag, Industry, Tag
from app.models.enums import CategoryScope
from app.services.common import audit, get_or_404, row_dict

router = APIRouter(tags=["taxonomy"])


class NameIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    color: str | None = Field(default=None, max_length=16)


class IndustryIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: uuid.UUID | None = None


class CategoryIn(NameIn):
    scope: CategoryScope


def _save(ctx: Ctx, obj, label: str):
    try:
        with ctx.db.begin_nested():
            ctx.db.add(obj)
            ctx.db.flush()
    except IntegrityError:
        raise Conflict(f"A {label} with this name already exists") from None
    return obj


# ---- industries ----
@router.get("/industries")
def list_industries(ctx: Ctx = Viewer):
    counts = (sa.select(Company.industry_id, sa.func.count().label("n"))
              .where(Company.deleted_at.is_(None)).group_by(Company.industry_id).subquery())
    rows = ctx.db.execute(sa.select(Industry, sa.func.coalesce(counts.c.n, 0))
                          .outerjoin(counts, counts.c.industry_id == Industry.id)
                          .order_by(Industry.name)).all()
    return [{**row_dict(i), "company_count": n} for i, n in rows]


@router.post("/industries", status_code=201)
def create_industry(body: IndustryIn, ctx: Ctx = Marketer):
    obj = _save(ctx, Industry(workspace_id=ctx.workspace_id, **body.model_dump()), "industry")
    audit(ctx, "create", "industry", obj.id, after=row_dict(obj))
    return row_dict(obj)


@router.patch("/industries/{item_id}")
def update_industry(item_id: uuid.UUID, body: IndustryIn, ctx: Ctx = Marketer):
    obj = get_or_404(ctx.db, Industry, item_id, "Industry")
    for k, v in body.model_dump().items():
        setattr(obj, k, v)
    _save(ctx, obj, "industry")
    return row_dict(obj)


@router.delete("/industries/{item_id}", status_code=204)
def delete_industry(item_id: uuid.UUID, ctx: Ctx = Marketer):
    obj = get_or_404(ctx.db, Industry, item_id, "Industry")
    ctx.db.delete(obj)
    audit(ctx, "delete", "industry", item_id, before=row_dict(obj))
    return Response(status_code=204)


# ---- categories ----
@router.get("/categories")
def list_categories(ctx: Ctx = Viewer, scope: CategoryScope | None = Query(default=None)):
    stmt = sa.select(Category).order_by(Category.scope, Category.name)
    if scope:
        stmt = stmt.where(Category.scope == scope)
    cats = ctx.db.scalars(stmt).all()
    comp = dict(ctx.db.execute(sa.select(CompanyCategory.category_id, sa.func.count())
                               .group_by(CompanyCategory.category_id)).all())
    cont = dict(ctx.db.execute(sa.select(Contact.category_id, sa.func.count())
                               .where(Contact.deleted_at.is_(None))
                               .group_by(Contact.category_id)).all())
    return [{**row_dict(c), "usage_count": comp.get(c.id, 0) + cont.get(c.id, 0)} for c in cats]


@router.post("/categories", status_code=201)
def create_category(body: CategoryIn, ctx: Ctx = Marketer):
    obj = _save(ctx, Category(workspace_id=ctx.workspace_id, **body.model_dump()), "category")
    audit(ctx, "create", "category", obj.id, after=row_dict(obj))
    return row_dict(obj)


@router.patch("/categories/{item_id}")
def update_category(item_id: uuid.UUID, body: NameIn, ctx: Ctx = Marketer):
    obj = get_or_404(ctx.db, Category, item_id, "Category")
    for k, v in body.model_dump().items():
        setattr(obj, k, v)
    _save(ctx, obj, "category")
    return row_dict(obj)


@router.delete("/categories/{item_id}", status_code=204)
def delete_category(item_id: uuid.UUID, ctx: Ctx = Marketer):
    obj = get_or_404(ctx.db, Category, item_id, "Category")
    ctx.db.delete(obj)
    audit(ctx, "delete", "category", item_id, before=row_dict(obj))
    return Response(status_code=204)


# ---- tags ----
@router.get("/tags")
def list_tags(ctx: Ctx = Viewer):
    tags = ctx.db.scalars(sa.select(Tag).order_by(Tag.name)).all()
    comp = dict(ctx.db.execute(sa.select(CompanyTag.tag_id, sa.func.count())
                               .group_by(CompanyTag.tag_id)).all())
    cont = dict(ctx.db.execute(sa.select(ContactTag.tag_id, sa.func.count())
                               .group_by(ContactTag.tag_id)).all())
    return [{**row_dict(t), "company_count": comp.get(t.id, 0), "contact_count": cont.get(t.id, 0)}
            for t in tags]


@router.post("/tags", status_code=201)
def create_tag(body: NameIn, ctx: Ctx = Marketer):
    obj = _save(ctx, Tag(workspace_id=ctx.workspace_id, **body.model_dump()), "tag")
    audit(ctx, "create", "tag", obj.id, after=row_dict(obj))
    return row_dict(obj)


@router.patch("/tags/{item_id}")
def update_tag(item_id: uuid.UUID, body: NameIn, ctx: Ctx = Marketer):
    obj = get_or_404(ctx.db, Tag, item_id, "Tag")
    for k, v in body.model_dump().items():
        setattr(obj, k, v)
    _save(ctx, obj, "tag")
    return row_dict(obj)


@router.delete("/tags/{item_id}", status_code=204)
def delete_tag(item_id: uuid.UUID, ctx: Ctx = Marketer):
    obj = get_or_404(ctx.db, Tag, item_id, "Tag")
    ctx.db.delete(obj)
    audit(ctx, "delete", "tag", item_id, before=row_dict(obj))
    return Response(status_code=204)
