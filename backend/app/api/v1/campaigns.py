"""Module 5: campaign management (wizard steps, validation, approval, scheduling, controls, history)."""
import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, EmailStr, Field

from app.core.deps import Admin, Analyst, Ctx, Marketer, Viewer
from app.core.errors import BadRequest, Conflict
from app.models import (
    Campaign,
    CampaignRecipient,
    Contact,
    EmailEvent,
    EmailTemplate,
    Segment,
    SendingAccount,
    TrackedLink,
)
from app.models.enums import CampaignStatus as S
from app.models.enums import EventType, RecipientStatus, TextDirection
from app.services import campaigns as svc
from app.services import rendering
from app.services.analytics import campaign_stats
from app.services.common import audit, get_or_404, paginate, row_dict
from app.services.jobs import enqueue_after_commit

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

EDITABLE = {S.DRAFT}


class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    segment_id: uuid.UUID | None = None
    manual_contact_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10_000)
    template_id: uuid.UUID | None = None
    subject: str | None = Field(default=None, max_length=300)
    preheader: str | None = Field(default=None, max_length=300)
    content_html: str | None = None
    direction: TextDirection | None = None
    sending_account_id: uuid.UUID | None = None


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    segment_id: uuid.UUID | None = None
    manual_contact_ids: list[uuid.UUID] | None = Field(default=None, max_length=10_000)
    template_id: uuid.UUID | None = None
    subject: str | None = Field(default=None, max_length=300)
    preheader: str | None = Field(default=None, max_length=300)
    content_html: str | None = None
    direction: TextDirection | None = None
    sending_account_id: uuid.UUID | None = None


class ApproveIn(BaseModel):
    scheduled_at: datetime | None = None  # None = approve only; send/schedule separately


class ScheduleIn(BaseModel):
    scheduled_at: datetime


class TestIn(BaseModel):
    to: list[EmailStr] = Field(min_length=1, max_length=5)
    contact_id: uuid.UUID | None = None


def _stats(ctx: Ctx, campaign_id) -> dict:
    return campaign_stats(ctx.db, campaign_id)


def _out(ctx: Ctx, c: Campaign, detail: bool = False) -> dict:
    d = row_dict(c, exclude={"html_snapshot", "text_snapshot"} if not detail else set())
    d["segment_name"] = ctx.db.scalar(sa.select(Segment.name).where(Segment.id == c.segment_id)) if c.segment_id else None
    d["template_name"] = ctx.db.scalar(sa.select(EmailTemplate.name).where(EmailTemplate.id == c.template_id)) \
        if c.template_id else None
    d["sending_account"] = ctx.db.scalar(sa.select(SendingAccount.from_email).where(
        SendingAccount.id == c.sending_account_id)) if c.sending_account_id else None
    d["is_approved"] = c.approved_at is not None
    d["manual_contact_count"] = len(c.manual_contact_ids or [])
    d["stats"] = _stats(ctx, c.id)
    return d


def _editable(c: Campaign) -> None:
    if c.status not in EDITABLE:
        raise Conflict(f"Campaign is '{c.status.value}'; only drafts can be edited. Duplicate it instead.")


def _check_refs(ctx: Ctx, data: dict) -> None:
    if data.get("segment_id"):
        get_or_404(ctx.db, Segment, data["segment_id"], "Segment")
    if data.get("template_id"):
        get_or_404(ctx.db, EmailTemplate, data["template_id"], "Template")
    if data.get("sending_account_id"):
        get_or_404(ctx.db, SendingAccount, data["sending_account_id"], "Sending account")
    ids = data.get("manual_contact_ids") or []
    if ids:
        found = ctx.db.scalar(sa.select(sa.func.count()).select_from(Contact).where(
            Contact.id.in_(ids), Contact.deleted_at.is_(None)))
        if found != len(set(ids)):
            raise BadRequest("Some selected contacts do not exist")


@router.get("")
def list_campaigns(ctx: Ctx = Viewer, q: str | None = None, status: list[S] | None = Query(None),
                   date_from: datetime | None = None, date_to: datetime | None = None,
                   page: int = 1, page_size: int = 25):
    stmt = sa.select(Campaign).where(Campaign.deleted_at.is_(None)).order_by(Campaign.created_at.desc())
    if q:
        stmt = stmt.where(sa.or_(Campaign.name.ilike(f"%{q}%"), Campaign.subject.ilike(f"%{q}%")))
    if status:
        stmt = stmt.where(Campaign.status.in_(status))
    if date_from:
        stmt = stmt.where(Campaign.created_at >= date_from)
    if date_to:
        stmt = stmt.where(Campaign.created_at <= date_to)
    return paginate(ctx.db, stmt, page, page_size, lambda c: _out(ctx, c))


@router.post("", status_code=201)
def create_campaign(body: CampaignIn, ctx: Ctx = Marketer):
    data = body.model_dump()
    _check_refs(ctx, data)
    data["manual_contact_ids"] = [str(x) for x in data["manual_contact_ids"]]
    if data.get("content_html"):
        data["content_html"] = rendering.sanitize_html(data["content_html"])
    if body.template_id and not body.subject:
        data["subject"] = ctx.db.scalar(sa.select(EmailTemplate.subject).where(EmailTemplate.id == body.template_id))
        data["preheader"] = data["preheader"] or ctx.db.scalar(
            sa.select(EmailTemplate.preheader).where(EmailTemplate.id == body.template_id))
    c = Campaign(workspace_id=ctx.workspace_id, created_by=ctx.user.id, **data)
    ctx.db.add(c)
    ctx.db.flush()
    audit(ctx, "create", "campaign", c.id, after={"name": c.name})
    return _out(ctx, c, detail=True)


@router.get("/{campaign_id}")
def get_campaign(campaign_id: uuid.UUID, ctx: Ctx = Viewer):
    return _out(ctx, get_or_404(ctx.db, Campaign, campaign_id, "Campaign"), detail=True)


@router.patch("/{campaign_id}")
def update_campaign(campaign_id: uuid.UUID, body: CampaignUpdate, ctx: Ctx = Marketer):
    c = get_or_404(ctx.db, Campaign, campaign_id, "Campaign")
    _editable(c)
    data = body.model_dump(exclude_unset=True)
    _check_refs(ctx, data)
    if "manual_contact_ids" in data:
        data["manual_contact_ids"] = [str(x) for x in data["manual_contact_ids"] or []]
    if data.get("content_html"):
        data["content_html"] = rendering.sanitize_html(data["content_html"])
    for k, v in data.items():
        setattr(c, k, v)
    if data:
        svc.clear_approval(c)  # any change invalidates approval
    audit(ctx, "update", "campaign", c.id, after={k: v for k, v in data.items() if k != "content_html"})
    return _out(ctx, c, detail=True)


@router.delete("/{campaign_id}", status_code=204)
def delete_campaign(campaign_id: uuid.UUID, ctx: Ctx = Admin):
    c = get_or_404(ctx.db, Campaign, campaign_id, "Campaign")
    if c.status not in (S.DRAFT, S.CANCELLED):
        raise Conflict("Only draft or cancelled campaigns can be deleted; sent campaigns are kept for history")
    c.deleted_at = datetime.now(timezone.utc)
    audit(ctx, "delete", "campaign", c.id)
    return Response(status_code=204)


@router.post("/{campaign_id}/duplicate", status_code=201)
def duplicate_campaign(campaign_id: uuid.UUID, ctx: Ctx = Marketer):
    c = get_or_404(ctx.db, Campaign, campaign_id, "Campaign")
    new = Campaign(workspace_id=ctx.workspace_id, name=f"{c.name} (copy)"[:200], segment_id=c.segment_id,
                   manual_contact_ids=c.manual_contact_ids, template_id=c.template_id, subject=c.subject,
                   preheader=c.preheader, content_html=c.content_html, direction=c.direction,
                   sending_account_id=c.sending_account_id, duplicated_from=c.id, created_by=ctx.user.id)
    ctx.db.add(new)
    ctx.db.flush()
    audit(ctx, "duplicate", "campaign", new.id, after={"from": str(c.id)})
    return _out(ctx, new, detail=True)


@router.post("/{campaign_id}/validate")
def validate_campaign(campaign_id: uuid.UUID, ctx: Ctx = Marketer):
    return svc.validate(ctx.db, get_or_404(ctx.db, Campaign, campaign_id, "Campaign"))


@router.post("/{campaign_id}/preview")
def preview_campaign(campaign_id: uuid.UUID, body: dict | None = None, ctx: Ctx = Viewer):
    from app.api.v1.templates import render_template
    c = get_or_404(ctx.db, Campaign, campaign_id, "Campaign")
    t = ctx.db.get(EmailTemplate, c.template_id) if c.template_id else None
    contact_id = (body or {}).get("contact_id")
    return render_template(ctx, c.content_html or (t.html if t else ""), c.subject, c.preheader,
                           t.text_body if t else None, c.direction or (t.direction if t else TextDirection.LTR),
                           t.locale if t else "en", c.name, uuid.UUID(contact_id) if contact_id else None)


@router.post("/{campaign_id}/test-send")
def test_send_campaign(campaign_id: uuid.UUID, body: TestIn, ctx: Ctx = Marketer):
    from app.api.v1.templates import render_template, send_test
    c = get_or_404(ctx.db, Campaign, campaign_id, "Campaign")
    t = ctx.db.get(EmailTemplate, c.template_id) if c.template_id else None
    return send_test(ctx, lambda: render_template(
        ctx, c.content_html or (t.html if t else ""), c.subject, c.preheader, t.text_body if t else None,
        c.direction or (t.direction if t else TextDirection.LTR), t.locale if t else "en", c.name, body.contact_id),
        [str(x) for x in body.to], c.sending_account_id, "campaign")


@router.post("/{campaign_id}/approve")
def approve(campaign_id: uuid.UUID, body: ApproveIn, ctx: Ctx = Admin):
    c = get_or_404(ctx.db, Campaign, campaign_id, "Campaign")
    _editable(c)
    report = svc.validate(ctx.db, c)
    if not report["ok"]:
        raise BadRequest("Campaign failed validation", errors=report["errors"], warnings=report["warnings"])
    svc.snapshot_content(ctx.db, c)
    c.approved_at, c.approved_by = svc.now(), ctx.user.id
    audit(ctx, "approve", "campaign", c.id, after={"audience": report["audience"]})
    if body.scheduled_at:
        return schedule(campaign_id, ScheduleIn(scheduled_at=body.scheduled_at), ctx)
    return {**_out(ctx, c, detail=True), "validation": report}


@router.post("/{campaign_id}/schedule")
def schedule(campaign_id: uuid.UUID, body: ScheduleIn, ctx: Ctx = Admin):
    c = get_or_404(ctx.db, Campaign, campaign_id, "Campaign")
    if c.approved_at is None:
        raise Conflict("Approve the campaign before scheduling it")
    at = body.scheduled_at if body.scheduled_at.tzinfo else body.scheduled_at.replace(tzinfo=timezone.utc)
    if at < svc.now() - timedelta(minutes=1):
        raise BadRequest("scheduled_at is in the past")
    svc.transition(c, S.SCHEDULED)
    c.scheduled_at = at
    audit(ctx, "schedule", "campaign", c.id, after={"scheduled_at": at.isoformat()})
    if at <= svc.now() + timedelta(seconds=30):
        from app.workers.tasks import prepare_campaign
        enqueue_after_commit(ctx.db, prepare_campaign, str(c.id), str(ctx.workspace_id))
    return _out(ctx, c, detail=True)


@router.post("/{campaign_id}/send")
def send_now(campaign_id: uuid.UUID, ctx: Ctx = Admin):
    return schedule(campaign_id, ScheduleIn(scheduled_at=svc.now()), ctx)


@router.post("/{campaign_id}/pause")
def pause(campaign_id: uuid.UUID, ctx: Ctx = Admin):
    c = get_or_404(ctx.db, Campaign, campaign_id, "Campaign")
    svc.transition(c, S.PAUSED)
    audit(ctx, "pause", "campaign", c.id)
    return _out(ctx, c, detail=True)


@router.post("/{campaign_id}/resume")
def resume(campaign_id: uuid.UUID, ctx: Ctx = Admin):
    from app.services.sending import batches_needed
    from app.workers.tasks import prepare_campaign, send_batch
    c = get_or_404(ctx.db, Campaign, campaign_id, "Campaign")
    if c.status != S.PAUSED:
        raise Conflict("Only paused campaigns can be resumed")
    started = ctx.db.scalar(sa.select(sa.func.count()).select_from(CampaignRecipient).where(
        CampaignRecipient.campaign_id == c.id))
    if started:
        svc.transition(c, S.SENDING)
        c.last_error = None
        for _ in range(batches_needed(ctx.db, c.id)):
            enqueue_after_commit(ctx.db, send_batch, str(c.id), str(ctx.workspace_id))
    else:
        svc.transition(c, S.SCHEDULED)
        if (c.scheduled_at or svc.now()) <= svc.now():
            enqueue_after_commit(ctx.db, prepare_campaign, str(c.id), str(ctx.workspace_id))
    audit(ctx, "resume", "campaign", c.id)
    return _out(ctx, c, detail=True)


@router.post("/{campaign_id}/cancel")
def cancel(campaign_id: uuid.UUID, ctx: Ctx = Admin):
    c = get_or_404(ctx.db, Campaign, campaign_id, "Campaign")
    svc.transition(c, S.CANCELLED)
    n = ctx.db.execute(sa.update(CampaignRecipient).where(CampaignRecipient.campaign_id == c.id,
                                                          CampaignRecipient.status == RecipientStatus.QUEUED)
                       .values(status=RecipientStatus.SKIPPED_SUPPRESSED, last_error="Campaign cancelled")).rowcount
    audit(ctx, "cancel", "campaign", c.id, after={"unsent": n})
    return _out(ctx, c, detail=True)


@router.post("/{campaign_id}/unapprove")
def unapprove(campaign_id: uuid.UUID, ctx: Ctx = Admin):
    c = get_or_404(ctx.db, Campaign, campaign_id, "Campaign")
    if c.status == S.SCHEDULED:
        svc.transition(c, S.DRAFT)
    _editable(c)
    svc.clear_approval(c)
    c.scheduled_at = None
    audit(ctx, "unapprove", "campaign", c.id)
    return _out(ctx, c, detail=True)


@router.get("/{campaign_id}/recipients")
def recipients(campaign_id: uuid.UUID, ctx: Ctx = Viewer, status: list[RecipientStatus] | None = Query(None),
               q: str | None = None, page: int = 1, page_size: int = 50):
    get_or_404(ctx.db, Campaign, campaign_id, "Campaign")
    stmt = (sa.select(CampaignRecipient).where(CampaignRecipient.campaign_id == campaign_id)
            .order_by(CampaignRecipient.created_at))
    if status:
        stmt = stmt.where(CampaignRecipient.status.in_(status))
    if q:
        stmt = stmt.where(CampaignRecipient.email.ilike(f"%{q}%"))
    return paginate(ctx.db, stmt, page, page_size,
                    lambda r: {**row_dict(r, exclude={"merge_data"}),
                               "name": (r.merge_data or {}).get("full_name"),
                               "company_name": (r.merge_data or {}).get("company_name")})


@router.get("/{campaign_id}/logs")
def logs(campaign_id: uuid.UUID, ctx: Ctx = Analyst, event_type: list[EventType] | None = Query(None),
         page: int = 1, page_size: int = 100):
    get_or_404(ctx.db, Campaign, campaign_id, "Campaign")
    stmt = (sa.select(EmailEvent, CampaignRecipient.email).outerjoin(
        CampaignRecipient, CampaignRecipient.id == EmailEvent.recipient_id)
        .where(EmailEvent.campaign_id == campaign_id).order_by(EmailEvent.occurred_at.desc(), EmailEvent.id.desc()))
    if event_type:
        stmt = stmt.where(EmailEvent.event_type.in_(event_type))
    total = ctx.db.scalar(sa.select(sa.func.count()).select_from(stmt.order_by(None).subquery()))
    rows = ctx.db.execute(stmt.limit(min(page_size, 500)).offset((max(page, 1) - 1) * page_size)).all()
    return {"items": [{**row_dict(e, exclude={"raw"}), "email": em} for e, em in rows], "total": total,
            "page": page, "page_size": page_size}


@router.get("/{campaign_id}/links")
def links(campaign_id: uuid.UUID, ctx: Ctx = Analyst):
    get_or_404(ctx.db, Campaign, campaign_id, "Campaign")
    clicks = dict(ctx.db.execute(sa.select(EmailEvent.url, sa.func.count()).where(
        EmailEvent.campaign_id == campaign_id, EmailEvent.event_type == EventType.CLICK).group_by(EmailEvent.url)).all())
    uniq = dict(ctx.db.execute(sa.select(EmailEvent.url, sa.func.count(sa.distinct(EmailEvent.recipient_id))).where(
        EmailEvent.campaign_id == campaign_id, EmailEvent.event_type == EventType.CLICK).group_by(EmailEvent.url)).all())
    return [{"url": u, "clicks": clicks.get(u, 0), "unique_clicks": uniq.get(u, 0)}
            for (u,) in ctx.db.execute(sa.select(TrackedLink.original_url).where(TrackedLink.campaign_id == campaign_id))]


