"""Segment rule-tree compiler.

A rule tree is {"op": "and"|"or", "rules": [rule | group, ...]} where a rule is
{"field": str, "operator": str, "value": any}. Fields and operators are whitelisted and
compiled to SQLAlchemy expressions over Contact JOIN Company. No user-supplied SQL ever
reaches the database.
"""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models import (
    CompanyCategory,
    CompanyTag,
    ConsentRecord,
    Contact,
    ContactTag,
    Suppression,
)
from app.models import Company as Co
from app.models.enums import CompanySize, CompanyStatus, SubscriptionStatus, VerificationStatus
from app.services.compliance import eligibility_clause

MAX_DEPTH = 5
MAX_RULES = 100

TEXT_OPS = {"eq", "neq", "in", "not_in", "contains", "not_contains", "starts_with", "is_empty", "is_not_empty"}
REF_OPS = {"eq", "neq", "in", "not_in", "is_empty", "is_not_empty"}
ENUM_OPS = {"eq", "neq", "in", "not_in"}
DATE_OPS = {"before", "after", "is_empty", "is_not_empty"}


class SegmentError(ValueError):
    pass


def _country():
    return sa.func.coalesce(Contact.country_code, Co.country_code)


def _city():
    return sa.func.coalesce(Contact.city, Co.city)


# field -> (kind, column-or-callable, label, enum class)
FIELDS: dict[str, tuple] = {
    "industry": ("ref", lambda: Co.industry_id, "Industry", None),
    "company": ("ref", lambda: Contact.company_id, "Company", None),
    "company_size": ("enum", lambda: Co.company_size, "Company Size", CompanySize),
    "company_status": ("enum", lambda: Co.status, "Company Status", CompanyStatus),
    "company_category": ("ref_m2m", "company_category", "Company Category", None),
    "company_tags": ("ref_m2m", "company_tags", "Company Tags", None),
    "country": ("text", _country, "Country", None),
    "city": ("text", _city, "City", None),
    "job_title": ("text", lambda: Contact.job_title, "Job Title", None),
    "department": ("text", lambda: Contact.department, "Department", None),
    "contact_category": ("ref", lambda: Contact.category_id, "Contact Category", None),
    "tags": ("ref_m2m", "contact_tags", "Contact Tags", None),
    "subscription_status": ("enum", lambda: Contact.subscription_status, "Subscription Status", SubscriptionStatus),
    "email_verification_status": ("enum", lambda: Contact.email_verification_status, "Email Verification",
                                  VerificationStatus),
    "email_domain": ("text", lambda: sa.func.split_part(sa.cast(Contact.email, sa.Text), "@", 2), "Email Domain",
                     None),
    "created_at": ("date", lambda: Contact.created_at, "Contact Created", None),
}
OPS_BY_KIND = {"text": TEXT_OPS, "ref": REF_OPS, "ref_m2m": {"in", "not_in", "eq", "neq", "is_empty",
                                                           "is_not_empty"},
               "enum": ENUM_OPS, "date": DATE_OPS}


def _as_list(v) -> list:
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _uuids(v) -> list[uuid.UUID]:
    try:
        return [uuid.UUID(str(x)) for x in _as_list(v)]
    except ValueError:
        raise SegmentError("Expected id value(s)") from None


def _m2m(kind: str, ids: list[uuid.UUID] | None):
    if kind == "contact_tags":
        q = sa.select(ContactTag.contact_id).where(ContactTag.contact_id == Contact.id)
        return q.where(ContactTag.tag_id.in_(ids)) if ids is not None else q
    if kind == "company_tags":
        q = sa.select(CompanyTag.company_id).where(CompanyTag.company_id == Contact.company_id)
        return q.where(CompanyTag.tag_id.in_(ids)) if ids is not None else q
    q = sa.select(CompanyCategory.company_id).where(CompanyCategory.company_id == Contact.company_id)
    return q.where(CompanyCategory.category_id.in_(ids)) if ids is not None else q


def _rule(r: dict):
    field, op, value = r.get("field"), r.get("operator"), r.get("value")
    if field not in FIELDS:
        raise SegmentError(f"Unknown field '{field}'")
    kind, col, _, enum_cls = FIELDS[field]
    if op not in OPS_BY_KIND[kind]:
        raise SegmentError(f"Operator '{op}' is not valid for field '{field}'")

    if kind == "ref_m2m":
        if op in ("is_empty", "is_not_empty"):
            ex = sa.exists(_m2m(col, None))
            return ~ex if op == "is_empty" else ex
        ids = _uuids(value)
        if not ids:
            raise SegmentError(f"'{field}' needs at least one value")
        ex = sa.exists(_m2m(col, ids))
        return ex if op in ("in", "eq") else ~ex

    c = col()
    if op == "is_empty":
        return sa.or_(c.is_(None), sa.cast(c, sa.Text) == "") if kind == "text" else c.is_(None)
    if op == "is_not_empty":
        return sa.and_(c.isnot(None), sa.cast(c, sa.Text) != "") if kind == "text" else c.isnot(None)

    if kind == "date":
        try:
            d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            raise SegmentError(f"Invalid date '{value}'") from None
        return c < d if op == "before" else c >= d

    if kind == "enum":
        vals = _as_list(value)
        try:
            vals = [enum_cls(v) for v in vals]
        except ValueError:
            raise SegmentError(f"Invalid value for '{field}'") from None
        if not vals:
            raise SegmentError(f"'{field}' needs a value")
        return c.in_(vals) if op in ("eq", "in") else sa.or_(c.is_(None), c.notin_(vals))

    if kind == "ref":
        ids = _uuids(value)
        if not ids:
            raise SegmentError(f"'{field}' needs a value")
        return c.in_(ids) if op in ("eq", "in") else sa.or_(c.is_(None), c.notin_(ids))

    # text (case-insensitive)
    vals = [str(v).strip() for v in _as_list(value) if str(v).strip()]
    if not vals:
        raise SegmentError(f"'{field}' needs a value")
    lc = sa.func.lower(sa.cast(c, sa.Text))
    if op in ("eq", "in"):
        return lc.in_([v.lower() for v in vals])
    if op in ("neq", "not_in"):
        return sa.or_(c.is_(None), lc.notin_([v.lower() for v in vals]))
    if op == "contains":
        return sa.or_(*[sa.cast(c, sa.Text).ilike(f"%{_esc(v)}%", escape="\\") for v in vals])
    if op == "not_contains":
        return sa.or_(c.is_(None), sa.and_(*[~sa.cast(c, sa.Text).ilike(f"%{_esc(v)}%", escape="\\")
                                             for v in vals]))
    return sa.or_(*[sa.cast(c, sa.Text).ilike(f"{_esc(v)}%", escape="\\") for v in vals])  # starts_with


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def compile_rules(tree: dict | None):
    """Return a SQL boolean expression for the tree (true() for an empty tree)."""
    counter = {"n": 0}

    def walk(node, depth):
        if depth > MAX_DEPTH:
            raise SegmentError(f"Groups can be nested at most {MAX_DEPTH} levels deep")
        if not isinstance(node, dict):
            raise SegmentError("Invalid rule")
        if "rules" in node:
            op = (node.get("op") or "and").lower()
            if op not in ("and", "or"):
                raise SegmentError("Group operator must be 'and' or 'or'")
            parts = [walk(ch, depth + 1) for ch in node.get("rules") or []]
            if not parts:
                return sa.true()
            return sa.and_(*parts) if op == "and" else sa.or_(*parts)
        counter["n"] += 1
        if counter["n"] > MAX_RULES:
            raise SegmentError(f"A segment can have at most {MAX_RULES} conditions")
        return _rule(node)

    if not tree:
        return sa.true()
    return walk(tree, 0)


def base_query():
    return (sa.select(Contact).join(Co, Co.id == Contact.company_id)
            .where(Contact.deleted_at.is_(None), Co.deleted_at.is_(None)))


def matching_ids_query(tree: dict | None, eligible_only: bool = False):
    stmt = base_query().where(compile_rules(tree))
    if eligible_only:
        stmt = stmt.where(eligibility_clause())
    return stmt.with_only_columns(Contact.id)


def counts(db: Session, tree: dict | None) -> dict:
    cond = compile_rules(tree)
    suppressed = sa.exists().where(Suppression.email == Contact.email,
                                   Suppression.workspace_id == Contact.workspace_id)
    has_consent = sa.exists().where(ConsentRecord.contact_id == Contact.id, ConsentRecord.withdrawn_at.is_(None))
    stmt = (sa.select(
        sa.func.count().label("total"),
        sa.func.count().filter(eligibility_clause()).label("eligible"),
        sa.func.count().filter(suppressed).label("suppressed"),
        sa.func.count().filter(Contact.subscription_status != SubscriptionStatus.SUBSCRIBED).label("not_subscribed"),
        sa.func.count().filter(Contact.email_verification_status == VerificationStatus.INVALID).label("invalid_email"),
        sa.func.count().filter(~has_consent).label("no_consent"),
    ).select_from(Contact).join(Co, Co.id == Contact.company_id)
        .where(Contact.deleted_at.is_(None), Co.deleted_at.is_(None), cond))
    r = db.execute(stmt).one()
    status_rows = db.execute(sa.select(Contact.subscription_status, sa.func.count())
                             .select_from(Contact).join(Co, Co.id == Contact.company_id)
                             .where(Contact.deleted_at.is_(None), Co.deleted_at.is_(None), cond)
                             .group_by(Contact.subscription_status)).all()
    return {"total": r.total, "eligible": r.eligible,
            "excluded": {"suppressed": r.suppressed, "not_subscribed": r.not_subscribed,
                         "invalid_email": r.invalid_email, "no_active_consent": r.no_consent},
            "by_subscription_status": {s.value: n for s, n in status_rows}}
