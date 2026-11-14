"""Shared helpers: audit logging, pagination, normalisation."""
import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from urllib.parse import urlparse

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models import AuditLog


def _jsonable(v: Any) -> Any:
    if isinstance(v, (uuid.UUID, Decimal)):
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, bytes):
        return "<bytes>"
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


def row_dict(obj, exclude: set[str] | None = None) -> dict:
    exclude = (exclude or set()) | {"encrypted_credentials", "password_hash"}
    return {c.key: _jsonable(getattr(obj, c.key)) for c in sa.inspect(obj).mapper.column_attrs
            if c.key not in exclude}


def audit(ctx, action: str, entity_type: str, entity_id=None, before=None, after=None) -> None:
    ctx.db.add(AuditLog(
        workspace_id=ctx.workspace_id, user_id=ctx.user.id, action=action,
        entity_type=entity_type, entity_id=str(entity_id) if entity_id else None,
        before=_jsonable(before) if before is not None else None,
        after=_jsonable(after) if after is not None else None,
        ip=ctx.ip, user_agent=ctx.user_agent,
    ))


class Page(BaseModel):
    items: list
    total: int
    page: int
    page_size: int


def paginate(db: Session, stmt: sa.Select, page: int, page_size: int, mapper=None) -> dict:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)
    total = db.scalar(sa.select(sa.func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.execute(stmt.limit(page_size).offset((page - 1) * page_size)).scalars().all()
    return {"items": [mapper(r) if mapper else r for r in rows], "total": total or 0,
            "page": page, "page_size": page_size}


def domain_from_website(website: str | None) -> str | None:
    if not website:
        return None
    w = website.strip()
    if not re.match(r"^[a-z]+://", w, re.I):
        w = "http://" + w
    host = (urlparse(w).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    return host or None


def normalise_country(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip()
    if len(v) == 2:
        return v.upper()
    return COUNTRY_NAMES.get(v.lower())


COUNTRY_NAMES = {
    "saudi arabia": "SA", "ksa": "SA", "kingdom of saudi arabia": "SA", "united arab emirates": "AE",
    "uae": "AE", "qatar": "QA", "kuwait": "KW", "bahrain": "BH", "oman": "OM", "egypt": "EG",
    "jordan": "JO", "lebanon": "LB", "iraq": "IQ", "morocco": "MA", "tunisia": "TN", "algeria": "DZ",
    "united kingdom": "GB", "uk": "GB", "united states": "US", "usa": "US", "india": "IN",
    "pakistan": "PK", "sri lanka": "LK", "bangladesh": "BD", "germany": "DE", "france": "FR",
    "italy": "IT", "spain": "ES", "netherlands": "NL", "turkey": "TR", "türkiye": "TR",
    "singapore": "SG", "malaysia": "MY", "indonesia": "ID", "china": "CN", "japan": "JP",
    "canada": "CA", "australia": "AU", "south africa": "ZA", "nigeria": "NG", "kenya": "KE",
    "ireland": "IE", "switzerland": "CH", "sweden": "SE", "norway": "NO", "denmark": "DK",
    "philippines": "PH", "brazil": "BR", "mexico": "MX",
}

ROLE_LOCAL_PARTS = {"info", "admin", "support", "sales", "contact", "hello", "office", "noreply",
                    "no-reply", "webmaster", "postmaster", "abuse", "hr", "careers", "jobs",
                    "billing", "accounts", "enquiries", "inquiries", "marketing"}


def is_role_account(email: str) -> bool:
    return email.split("@", 1)[0].lower() in ROLE_LOCAL_PARTS


def get_or_404(db: Session, model, obj_id, label: str | None = None):
    """Fetch by primary key (RLS already limits rows to the current workspace)."""
    from app.core.errors import NotFound

    obj = db.get(model, obj_id)
    if obj is None or getattr(obj, "deleted_at", None) is not None:
        raise NotFound(label or model.__name__)
    return obj
