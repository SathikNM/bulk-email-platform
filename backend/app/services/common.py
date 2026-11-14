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


# ---------------- phone numbers ----------------
# International calling codes for the countries contacts are most likely to come from.
CALLING_CODES = {
    "SA": "966", "AE": "971", "QA": "974", "KW": "965", "BH": "973", "OM": "968", "EG": "20", "JO": "962",
    "LB": "961", "IQ": "964", "MA": "212", "TN": "216", "DZ": "213", "GB": "44", "US": "1", "IN": "91",
    "PK": "92", "LK": "94", "BD": "880", "DE": "49", "FR": "33", "IT": "39", "ES": "34", "NL": "31",
    "TR": "90", "PH": "63", "YE": "967", "SD": "249", "SY": "963",
}
_SPLIT = {"966": (2, 3, 4), "971": (2, 3, 4), "965": (4, 4), "974": (4, 4), "973": (4, 4), "968": (4, 4)}


def normalize_phone(value: str | None, country_code: str | None = None, default_country: str = "SA") -> str | None:
    """Return the number in international form with its country code, e.g. '050 006 0878' -> '+966 50 006 0878'.

    Numbers already carrying a code (+44..., 0044..., 966...) keep it; local numbers get the code of the
    contact's country (default Saudi Arabia). Unparseable values are returned trimmed, unchanged.
    """
    if value is None:
        return None
    raw = str(value).strip()
    if not raw or raw in ("-", "–", "—"):
        return None
    if isinstance(value, float) and value.is_integer():
        raw = str(int(value))
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return raw[:40]
    if raw.startswith("+"):
        intl = digits
    elif digits.startswith("00"):
        intl = digits[2:]
    else:
        cc = CALLING_CODES.get((country_code or default_country or "SA").upper(), "966")
        if digits.startswith(cc) and len(digits) > len(cc) + 6:
            intl = digits
        else:
            intl = cc + digits.lstrip("0")
    code = next((c for c in sorted(_SPLIT, key=len, reverse=True) if intl.startswith(c)), None)
    if code:
        rest = intl[len(code):]
        parts, i = [], 0
        for n in _SPLIT[code]:
            if i < len(rest):
                parts.append(rest[i:i + n])
                i += n
        if i < len(rest):
            parts[-1] += rest[i:]
        return f"+{code} {' '.join(parts)}"[:40]
    code = next((c for c in sorted(set(CALLING_CODES.values()), key=len, reverse=True) if intl.startswith(c)), None)
    if code:
        return f"+{code} {intl[len(code):]}"[:40]
    return f"+{intl}"[:40]
