"""Campaign state machine, validation and approval snapshot."""
import re
import secrets
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.errors import Conflict
from app.models import Campaign, Company, Contact, EmailTemplate, SendingAccount, Suppression, TrackedLink, Workspace
from app.models.enums import CampaignStatus as S
from app.models.enums import IdentityStatus, SubscriptionStatus, VerificationStatus
from app.services import rendering
from app.services import segments as seg
from app.services.compliance import eligibility_clause
from app.services.sending import sent_today

TRANSITIONS: dict[S, set[S]] = {
    S.DRAFT: {S.SCHEDULED, S.CANCELLED},
    S.SCHEDULED: {S.PROCESSING, S.PAUSED, S.CANCELLED, S.DRAFT},
    S.PROCESSING: {S.SENDING, S.PAUSED, S.FAILED, S.CANCELLED, S.COMPLETED},
    S.SENDING: {S.COMPLETED, S.PAUSED, S.FAILED, S.CANCELLED},
    S.PAUSED: {S.SENDING, S.SCHEDULED, S.CANCELLED, S.PROCESSING},
    S.COMPLETED: set(),
    S.FAILED: {S.SCHEDULED},
    S.CANCELLED: set(),
}

LINK_RE = re.compile(r'(<a\b[^>]*?\bhref\s*=\s*)(["\'])(https?://[^"\']+)\2', re.I)


def transition(c: Campaign, to: S) -> None:
    if to not in TRANSITIONS[c.status]:
        raise Conflict(f"Cannot change campaign from '{c.status.value}' to '{to.value}'",
                       current_status=c.status.value)
    c.status = to


def build_audience(db: Session, c: Campaign, eligible_only: bool = True):
    from app.models import Segment
    parts = []
    if c.segment_id is not None:
        rules = db.scalar(sa.select(Segment.rules).where(Segment.id == c.segment_id))
        parts.append(seg.compile_rules(rules or {}))
    manual = [uuid.UUID(str(x)) for x in (c.manual_contact_ids or [])]
    if manual:
        parts.append(Contact.id.in_(manual))
    if not parts:
        return None
    # Explicit tenant filter in addition to RLS (defence in depth for system-scoped callers).
    stmt = seg.base_query().where(Contact.workspace_id == c.workspace_id, sa.or_(*parts))
    if eligible_only:
        stmt = stmt.where(eligibility_clause())
    return stmt


def validate(db: Session, c: Campaign) -> dict:
    """Pre-send validation report. `errors` block approval; `warnings` do not."""
    errors, warnings = [], []
    if not c.subject:
        errors.append("Subject is required")
    html = c.content_html or (db.scalar(sa.select(EmailTemplate.html).where(EmailTemplate.id == c.template_id))
                              if c.template_id else None)
    if not html or not html.strip():
        errors.append("Email content is empty: select a template or write the content")
    account = db.get(SendingAccount, c.sending_account_id) if c.sending_account_id else \
        db.scalar(sa.select(SendingAccount).where(SendingAccount.is_default.is_(True)))
    if account is None:
        errors.append("No sending account configured")
    elif account.verification_status != IdentityStatus.VERIFIED:
        errors.append(f"Sending account '{account.name}' is not verified. Verify it under Sending Accounts.")
    ws = db.get(Workspace, c.workspace_id)
    if not ws.legal_address:
        errors.append("Workspace postal address is missing (required in every marketing email)")

    audience = build_audience(db, c, eligible_only=False)
    report = {"total_matched": 0, "eligible": 0, "excluded": {}, "duplicates_removed": 0,
              "missing_merge_fields": {}}
    if audience is None:
        errors.append("Select an audience segment or individual contacts")
    else:
        sub = audience.subquery()
        total = db.scalar(sa.select(sa.func.count()).select_from(sub))
        eligible_stmt = build_audience(db, c, eligible_only=True)
        el = eligible_stmt.with_only_columns(Contact.id, Contact.email, Contact.first_name, Contact.last_name,
                                             Contact.job_title, Company.name).subquery()
        eligible = db.scalar(sa.select(sa.func.count()).select_from(el))
        unique_emails = db.scalar(sa.select(sa.func.count(sa.distinct(sa.func.lower(sa.cast(el.c.email, sa.Text))))))
        excluded = db.execute(sa.select(
            sa.func.count().filter(Contact.subscription_status != SubscriptionStatus.SUBSCRIBED),
            sa.func.count().filter(sa.exists().where(Suppression.email == Contact.email)),
            sa.func.count().filter(Contact.email_verification_status == VerificationStatus.INVALID),
        ).select_from(Contact).where(Contact.id.in_(sa.select(sub.c.id)))).one()
        report.update(total_matched=total, eligible=unique_emails, duplicates_removed=eligible - unique_emails,
                      excluded={"not_subscribed": excluded[0], "suppressed": excluded[1],
                                "invalid_email": excluded[2], "other": max(total - eligible - 0, 0)})
        if unique_emails == 0:
            errors.append("No eligible recipients: everyone matched is unsubscribed, suppressed, invalid or "
                          "lacks recorded consent")
        known, unknown = rendering.find_variables(html, c.subject, c.preheader)
        if unknown:
            warnings.append(f"Unknown variables will render empty: {', '.join(sorted(unknown))}")
        for var, col in (("FirstName", el.c.first_name), ("LastName", el.c.last_name), ("JobTitle", el.c.job_title)):
            if var in known and not re.search(r"\{\{\s*%s\s*\|" % var, (html or "") + (c.subject or "")):
                missing = db.scalar(sa.select(sa.func.count()).select_from(el).where(
                    sa.or_(col.is_(None), col == "")))
                if missing:
                    report["missing_merge_fields"][var] = missing
                    warnings.append(f"{missing} recipient(s) have no {var}; add a fallback like "
                                    f"{{{{{var}|there}}}}")
        if account is not None:
            remaining = account.max_per_day - sent_today(account.id)
            if unique_emails > remaining:
                warnings.append(f"Audience ({unique_emails}) exceeds today's remaining sending limit ({remaining}); "
                                "sending will continue over multiple days")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "audience": report,
            "sending_account": {"id": str(account.id), "from": account.from_email,
                                "verified": account.verification_status == IdentityStatus.VERIFIED}
            if account else None}


def snapshot_content(db: Session, c: Campaign) -> None:
    """Freeze template content into the campaign and register tracked links (at approval)."""
    t = db.get(EmailTemplate, c.template_id) if c.template_id else None
    html = c.content_html or (t.html if t else "")
    direction = (c.direction.value if c.direction else None) or (t.direction.value if t else "ltr")
    locale = t.locale if t else "en"
    ws = db.get(Workspace, c.workspace_id)
    prepared = rendering.prepare_template_html(html, direction, locale, c.preheader, c.subject or c.name,
                                               ws.legal_address)
    db.execute(sa.delete(TrackedLink).where(TrackedLink.campaign_id == c.id))
    links: dict[str, str] = {}

    def repl(m):
        url = m.group(3)
        if "{{" in url:
            return m.group(0)
        token = links.get(url)
        if token is None:
            token = secrets.token_urlsafe(9)
            links[url] = token
            db.add(TrackedLink(campaign_id=c.id, original_url=url, token=token))
        return f'{m.group(1)}{m.group(2)}{{{{__L:{token}}}}}{m.group(2)}'
    c.html_snapshot = LINK_RE.sub(repl, prepared)
    c.text_snapshot = t.text_body if t and t.text_body else None
    if not c.sending_account_id:
        c.sending_account_id = db.scalar(sa.select(SendingAccount.id).where(SendingAccount.is_default.is_(True)))


def clear_approval(c: Campaign) -> None:
    c.approved_at = None
    c.approved_by = None


def now() -> datetime:
    return datetime.now(timezone.utc)
