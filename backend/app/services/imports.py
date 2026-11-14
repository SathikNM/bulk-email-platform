"""CSV/XLSX import for companies, contacts and suppressions.

Rows are validated individually; bad rows are recorded in import_jobs.errors with their
row number and never abort the whole file. Contacts default to `pending` unless the
file maps a consent source AND consent date (public addresses are not consent).
"""
import csv
import io
import re
import uuid
from collections.abc import Iterator
from datetime import date, datetime, timezone

import sqlalchemy as sa
from email_validator import EmailNotValidError, validate_email
from openpyxl import load_workbook
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import (
    Category,
    Company,
    CompanyTag,
    ConsentRecord,
    Contact,
    ContactTag,
    ImportJob,
    Industry,
    Suppression,
    Tag,
)
from app.models.enums import (
    CategoryScope,
    CompanySize,
    CompanyStatus,
    ImportEntity,
    JobStatus,
    LawfulBasis,
    SubscriptionStatus,
    SuppressionReason,
)
from app.services import storage
from app.services.common import domain_from_website, is_role_account, normalise_country

BATCH = 500
MAX_ERRORS = 1000

FIELDS: dict[ImportEntity, list[str]] = {
    ImportEntity.COMPANY: ["name", "industry", "business_type", "country", "city", "website",
                           "company_size", "annual_revenue", "category", "status", "data_source",
                           "notes", "tags"],
    ImportEntity.CONTACT: ["email", "first_name", "last_name", "full_name", "job_title", "department",
                           "phone", "country", "city", "company_name", "company_website", "category",
                           "consent_source", "consent_date", "subscription_status", "notes", "tags"],
    ImportEntity.SUPPRESSION: ["email", "reason"],
}
REQUIRED = {ImportEntity.COMPANY: ["name"], ImportEntity.CONTACT: ["email"],
            ImportEntity.SUPPRESSION: ["email"]}

ALIASES = {
    "name": ["company name", "company", "organisation", "organization", "account name"],
    "company_name": ["company", "company name", "organisation", "organization", "account"],
    "company_website": ["company website", "company domain", "domain"],
    "website": ["url", "web", "web site", "domain"],
    "email": ["email address", "e-mail", "business email", "work email", "mail"],
    "first_name": ["first", "firstname", "given name"],
    "last_name": ["last", "lastname", "surname", "family name"],
    "full_name": ["name", "contact name", "full name"],
    "job_title": ["title", "position", "designation", "role", "job"],
    "department": ["dept", "function", "division"],
    "phone": ["mobile", "telephone", "tel", "phone number", "contact number"],
    "country": ["country name", "nation"],
    "city": ["town", "location"],
    "company_size": ["size", "employees", "headcount", "no of employees"],
    "annual_revenue": ["revenue", "turnover"],
    "industry": ["sector", "vertical"],
    "consent_source": ["consent", "source of consent", "opt-in source"],
    "consent_date": ["opt-in date", "consent given", "opt in date"],
    "tags": ["tag", "labels"],
    "data_source": ["source", "lead source"],
    "reason": ["suppression reason"],
}


def _norm(h: str) -> str:
    return re.sub(r"[\s_\-]+", " ", (h or "").strip().lower())


def suggest_mapping(headers: list[str], entity: ImportEntity) -> dict[str, str | None]:
    fields = FIELDS[entity]
    out: dict[str, str | None] = {}
    used: set[str] = set()
    for h in headers:
        n = _norm(h)
        match = next((f for f in fields if f not in used and _norm(f) == n), None)
        if match is None:
            match = next((f for f in fields if f not in used and n in ALIASES.get(f, [])), None)
        if match:
            used.add(match)
        out[h] = match
    return out


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1256", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def read_rows(data: bytes, filename: str) -> tuple[list[str], Iterator[dict]]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        headers = [str(h).strip() if h is not None else f"column_{i + 1}"
                   for i, h in enumerate(next(it, []) or [])]

        def gen():
            for row in it:
                if row is None or all(v is None or str(v).strip() == "" for v in row):
                    continue
                yield {headers[i]: v for i, v in enumerate(row) if i < len(headers)}
        return headers, gen()
    if filename.lower().endswith((".csv", ".txt")):
        text = _decode(data)
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        headers = [h.strip() for h in (reader.fieldnames or [])]
        reader.fieldnames = headers

        def gen():
            for row in reader:
                if all((v or "").strip() == "" for v in row.values() if isinstance(v, str)):
                    continue
                yield row
        return headers, gen()
    raise ValueError("Unsupported file type. Upload .csv or .xlsx")


def preview(data: bytes, filename: str, entity: ImportEntity, limit: int = 20) -> dict:
    headers, rows = read_rows(data, filename)
    sample = []
    total = 0
    for r in rows:
        total += 1
        if len(sample) < limit:
            sample.append({k: _cell(v) for k, v in r.items()})
    return {"headers": headers, "rows": sample, "total_rows": total,
            "suggested_mapping": suggest_mapping(headers, entity), "fields": FIELDS[entity],
            "required": REQUIRED[entity]}


def _cell(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    s = str(v).strip()
    return s or None


def _parse_date(v) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day, tzinfo=timezone.utc)
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%m/%d/%Y",
                "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date '{s}' (use YYYY-MM-DD)")


SIZE_VALUES = {s.value for s in CompanySize}


def _parse_size(v: str | None) -> CompanySize | None:
    if not v:
        return None
    v = v.replace(" ", "")
    if v in SIZE_VALUES:
        return CompanySize(v)
    if v.isdigit():
        n = int(v)
        for lo, hi, s in ((1, 10, "1-10"), (11, 50, "11-50"), (51, 200, "51-200"),
                          (201, 500, "201-500"), (501, 1000, "501-1000"), (1001, 5000, "1001-5000")):
            if lo <= n <= hi:
                return CompanySize(s)
        return CompanySize.S5000_PLUS
    raise ValueError(f"Invalid company size '{v}'")


def clean_email(v: str | None) -> str:
    if not v:
        raise ValueError("Email is required")
    try:
        return validate_email(str(v).strip(), check_deliverability=False).normalized
    except EmailNotValidError as e:
        raise ValueError(f"Invalid email: {e}") from None


class _Lookup:
    """Per-job caches for taxonomy/company resolution (create missing on demand)."""

    def __init__(self, db: Session, ws: uuid.UUID, create_missing: bool):
        self.db, self.ws, self.create = db, ws, create_missing
        self.industries = {n.lower(): i for i, n in db.execute(sa.select(Industry.id, Industry.name))}
        self.tags = {n.lower(): i for i, n in db.execute(sa.select(Tag.id, Tag.name))}
        self.cats = {(s, n.lower()): i for i, s, n in
                     db.execute(sa.select(Category.id, Category.scope, Category.name))}

    def industry(self, name: str | None):
        if not name:
            return None
        key = name.strip().lower()
        if key not in self.industries:
            if not self.create:
                raise ValueError(f"Unknown industry '{name}'")
            obj = Industry(workspace_id=self.ws, name=name.strip()[:120])
            self.db.add(obj)
            self.db.flush()
            self.industries[key] = obj.id
        return self.industries[key]

    def category(self, scope: CategoryScope, name: str | None):
        if not name:
            return None
        key = (scope, name.strip().lower())
        if key not in self.cats:
            if not self.create:
                raise ValueError(f"Unknown category '{name}'")
            obj = Category(workspace_id=self.ws, scope=scope, name=name.strip()[:120])
            self.db.add(obj)
            self.db.flush()
            self.cats[key] = obj.id
        return self.cats[key]

    def tag_ids(self, raw: str | None) -> list:
        ids = []
        for name in [t.strip() for t in re.split(r"[,;|]", raw or "") if t.strip()]:
            key = name.lower()
            if key not in self.tags:
                obj = Tag(workspace_id=self.ws, name=name[:80])
                self.db.add(obj)
                self.db.flush()
                self.tags[key] = obj.id
            ids.append(self.tags[key])
        return ids


def _map(row: dict, mapping: dict[str, str | None]) -> dict:
    out: dict = {}
    for header, field in mapping.items():
        if field and header in row:
            out[field] = row[header]
    return out


def _upsert_company(db: Session, lk: _Lookup, r: dict, update_existing: bool,
                    created_by=None) -> tuple[Company, str]:
    name = _cell(r.get("name") or r.get("company_name"))
    if not name:
        raise ValueError("Company name is required")
    website = _cell(r.get("website") or r.get("company_website"))
    domain = domain_from_website(website)
    existing = None
    if domain:
        existing = db.scalar(sa.select(Company).where(Company.domain == domain,
                                                      Company.deleted_at.is_(None)))
    if existing is None:
        existing = db.scalar(sa.select(Company).where(
            Company.normalized_name == sa.func.lower(sa.func.regexp_replace(
                name, "[[:space:][:punct:]]+", "", "g")), Company.deleted_at.is_(None)).limit(1))
    values = {"name": name[:255]}
    if website:
        values["website"], values["domain"] = website[:255], domain
    if "industry" in r and _cell(r["industry"]):
        values["industry_id"] = lk.industry(_cell(r["industry"]))
    for f in ("business_type", "city", "data_source", "notes"):
        if _cell(r.get(f)):
            values[f] = _cell(r[f])
    if _cell(r.get("country")):
        cc = normalise_country(_cell(r["country"]))
        if not cc:
            raise ValueError(f"Unknown country '{r['country']}' (use ISO-2 code, e.g. SA)")
        values["country_code"] = cc
    if _cell(r.get("company_size")):
        values["company_size"] = _parse_size(_cell(r["company_size"]))
    if _cell(r.get("annual_revenue")):
        try:
            values["annual_revenue"] = float(str(r["annual_revenue"]).replace(",", ""))
        except ValueError:
            raise ValueError(f"Invalid annual revenue '{r['annual_revenue']}'") from None
    if _cell(r.get("status")):
        try:
            values["status"] = CompanyStatus(_cell(r["status"]).lower())
        except ValueError:
            raise ValueError(f"Invalid status '{r['status']}'") from None
    if existing is not None:
        if not update_existing:
            return existing, "skipped"
        for k, v in values.items():
            setattr(existing, k, v)
        company, action = existing, "updated"
    else:
        company = Company(workspace_id=lk.ws, created_by=created_by, **values)
        db.add(company)
        db.flush()
        action = "inserted"
    cat = lk.category(CategoryScope.COMPANY, _cell(r.get("category")))
    if cat:
        db.execute(sa.text("INSERT INTO company_categories (company_id, category_id) VALUES (:a, :b) "
                           "ON CONFLICT DO NOTHING"), {"a": company.id, "b": cat})
    for tid in lk.tag_ids(_cell(r.get("tags"))):
        db.execute(pg_insert(CompanyTag).values(company_id=company.id, tag_id=tid)
                   .on_conflict_do_nothing())
    return company, action


def _upsert_contact(db: Session, lk: _Lookup, r: dict, opts: dict, suppressed: set[str],
                    created_by=None) -> str:
    email = clean_email(_cell(r.get("email")))
    company_name = _cell(r.get("company_name"))
    company_site = _cell(r.get("company_website"))
    if not company_name and not company_site:
        domain = email.split("@", 1)[1]
        company = db.scalar(sa.select(Company).where(Company.domain == domain,
                                                     Company.deleted_at.is_(None)))
        if company is None:
            if opts.get("default_company_id"):
                company = db.get(Company, uuid.UUID(str(opts["default_company_id"])))
            if company is None:
                raise ValueError("Company name (or company website) is required")
    else:
        company, _ = _upsert_company(db, lk, {"name": company_name or company_site,
                                              "website": company_site}, update_existing=False,
                                     created_by=created_by)
    first, last = _cell(r.get("first_name")), _cell(r.get("last_name"))
    if not first and not last and _cell(r.get("full_name")):
        parts = _cell(r["full_name"]).split(" ", 1)
        first, last = parts[0], (parts[1] if len(parts) > 1 else None)
    values = {"company_id": company.id}
    for f, v in (("first_name", first), ("last_name", last)):
        if v:
            values[f] = v[:120]
    for f in ("job_title", "department", "phone", "city", "notes"):
        if _cell(r.get(f)):
            values[f] = _cell(r[f])
    if _cell(r.get("country")):
        cc = normalise_country(_cell(r["country"]))
        if not cc:
            raise ValueError(f"Unknown country '{r['country']}'")
        values["country_code"] = cc
    cat = lk.category(CategoryScope.CONTACT, _cell(r.get("category")))
    if cat:
        values["category_id"] = cat

    consent_source = _cell(r.get("consent_source"))
    consent_date = _parse_date(r.get("consent_date"))
    has_consent = bool(consent_source and consent_date)
    if has_consent:
        values["consent_source"], values["consent_date"] = consent_source[:200], consent_date

    existing = db.scalar(sa.select(Contact).where(Contact.email == email, Contact.deleted_at.is_(None)))
    if existing is not None:
        if not opts.get("update_existing", True):
            return "skipped"
        for k, v in values.items():
            setattr(existing, k, v)
        contact, action = existing, "updated"
    else:
        contact = Contact(workspace_id=lk.ws, email=email, created_by=created_by, **values)
        db.add(contact)
        db.flush()
        action = "inserted"

    if email.lower() in suppressed:
        contact.subscription_status = SubscriptionStatus.UNSUBSCRIBED
    elif has_consent and opts.get("subscribe_with_consent", True):
        if contact.subscription_status in (SubscriptionStatus.PENDING, SubscriptionStatus.SUBSCRIBED):
            contact.subscription_status = SubscriptionStatus.SUBSCRIBED
            db.add(ConsentRecord(workspace_id=lk.ws, contact_id=contact.id,
                                 lawful_basis=LawfulBasis(opts.get("lawful_basis", "explicit_consent")),
                                 source=consent_source[:200], granted_at=consent_date,
                                 evidence=f"Imported from file (job {opts.get('job_id')})",
                                 recorded_by=created_by))
    for tid in lk.tag_ids(_cell(r.get("tags"))):
        db.execute(pg_insert(ContactTag).values(contact_id=contact.id, tag_id=tid)
                   .on_conflict_do_nothing())
    if is_role_account(email):
        return action + ":role"
    return action


def _upsert_suppression(db: Session, ws: uuid.UUID, r: dict, created_by=None) -> str:
    email = clean_email(_cell(r.get("email")))
    reason_raw = (_cell(r.get("reason")) or "manual").lower().replace(" ", "_")
    try:
        reason = SuppressionReason(reason_raw)
    except ValueError:
        reason = SuppressionReason.MANUAL
    res = db.execute(pg_insert(Suppression).values(
        workspace_id=ws, email=email, reason=reason, source="import", created_by=created_by)
        .on_conflict_do_nothing())
    db.execute(sa.update(Contact).where(Contact.email == email).values(
        subscription_status=SubscriptionStatus.UNSUBSCRIBED))
    return "inserted" if res.rowcount else "skipped"


def run_job(db: Session, job: ImportJob) -> None:
    """Execute an import job inside a workspace-scoped session. Commits per batch."""
    job.status = JobStatus.RUNNING
    db.commit()
    data = storage.get(job.file_key)
    _, rows = read_rows(data, job.original_filename or job.file_key)
    mapping = job.column_mapping or {}
    opts = {**(job.options or {}), "job_id": str(job.id)}
    missing = [f for f in REQUIRED[job.entity] if f not in mapping.values()
               and not (f == "name" and "company_name" in mapping.values())]
    if missing:
        job.status = JobStatus.FAILED
        job.errors = [{"row": 0, "error": f"Required column(s) not mapped: {', '.join(missing)}"}]
        db.commit()
        return
    lk = _Lookup(db, job.workspace_id, opts.get("create_missing_taxonomy", True))
    suppressed = {e.lower() for e in db.scalars(sa.select(Suppression.email))}
    errors: list = []
    counts = {"inserted": 0, "updated": 0, "skipped": 0}
    total = role_accounts = 0
    seen: set[str] = set()
    for i, raw in enumerate(rows, start=2):  # row 1 = header
        total += 1
        r = _map(raw, mapping)
        try:
            with db.begin_nested():
                if job.entity == ImportEntity.CONTACT:
                    key = str(r.get("email") or "").strip().lower()
                    if key and key in seen:
                        raise ValueError("Duplicate email within this file")
                    seen.add(key)
                    action = _upsert_contact(db, lk, r, opts, suppressed, job.created_by)
                elif job.entity == ImportEntity.COMPANY:
                    _, action = _upsert_company(db, lk, r, opts.get("update_existing", True),
                                                job.created_by)
                else:
                    action = _upsert_suppression(db, job.workspace_id, r, job.created_by)
            if action.endswith(":role"):
                role_accounts += 1
                action = action.split(":")[0]
            counts[action] += 1
        except Exception as e:  # noqa: BLE001 - every row error is reported, never fatal
            counts["skipped"] += 1
            if len(errors) < MAX_ERRORS:
                errors.append({"row": i, "error": str(e)[:300]})
        if total % BATCH == 0:
            job.total_rows, job.inserted, job.updated, job.skipped = (
                total, counts["inserted"], counts["updated"], counts["skipped"])
            db.commit()
    job.total_rows, job.inserted, job.updated, job.skipped = (
        total, counts["inserted"], counts["updated"], counts["skipped"])
    job.errors = errors
    if role_accounts:
        job.options = {**(job.options or {}), "role_accounts": role_accounts}
    job.status = JobStatus.COMPLETED
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
