"""Mailbox API: Inbox (replies), Sent (everything the platform sent) and threaded conversations."""
import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.deps import Ctx, Marketer, Viewer
from app.core.errors import BadRequest
from app.models import Campaign, Contact
from app.models.mailbox import MailMessage
from app.services import mailbox
from app.services.common import audit, get_or_404, paginate

router = APIRouter(prefix="/mailbox", tags=["mailbox"])


class ReplyIn(BaseModel):
    body: str = Field(min_length=1, max_length=50_000)


def _summary(m: MailMessage) -> dict:
    preview = mailbox.strip_quoted(m.body_text or "") if m.direction == "in" else (m.body_text or "")
    return {"id": str(m.id), "thread_id": str(m.thread_id), "direction": m.direction, "kind": m.kind,
            "status": m.status, "from_addr": m.from_addr, "from_name": m.from_name, "to_addr": m.to_addr,
            "subject": m.subject, "preview": " ".join(preview.split())[:180], "is_read": m.is_read,
            "error": m.error, "campaign_id": str(m.campaign_id) if m.campaign_id else None,
            "contact_id": str(m.contact_id) if m.contact_id else None, "created_at": m.created_at.isoformat()}


@router.get("")
def list_messages(ctx: Ctx = Viewer, folder: str = Query("inbox", pattern="^(inbox|sent|failed)$"),
                  q: str | None = None, unread: bool = False, page: int = 1, page_size: int = 50):
    stmt = sa.select(MailMessage)
    if folder == "inbox":
        stmt = stmt.where(MailMessage.direction == "in")
    elif folder == "sent":
        stmt = stmt.where(MailMessage.direction == "out", MailMessage.status != "queued")
    else:
        stmt = stmt.where(MailMessage.direction == "out", MailMessage.status == "failed")
    if unread:
        stmt = stmt.where(MailMessage.is_read.is_(False))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(sa.or_(MailMessage.subject.ilike(like), MailMessage.from_addr.ilike(like),
                                 MailMessage.to_addr.ilike(like), MailMessage.from_name.ilike(like)))
    return paginate(ctx.db, stmt.order_by(MailMessage.created_at.desc()), page, page_size, _summary)


@router.get("/summary")
def summary(ctx: Ctx = Viewer):
    unread = ctx.db.scalar(sa.select(sa.func.count()).select_from(MailMessage).where(
        MailMessage.direction == "in", MailMessage.is_read.is_(False))) or 0
    return {"unread": unread, "reply_capture": bool(settings.INBOUND_DOMAIN),
            "inbound_domain": settings.INBOUND_DOMAIN or None}


@router.get("/threads/{thread_id}")
def thread(thread_id: uuid.UUID, ctx: Ctx = Viewer):
    rows = ctx.db.scalars(sa.select(MailMessage).where(MailMessage.thread_id == thread_id)
                          .order_by(MailMessage.created_at)).all()
    if not rows:
        get_or_404(ctx.db, MailMessage, thread_id, "Conversation")
    for r in rows:
        if r.direction == "in" and not r.is_read:
            r.is_read = True
    first = rows[0]
    contact = ctx.db.get(Contact, first.contact_id) if first.contact_id else None
    campaign = ctx.db.get(Campaign, first.campaign_id) if first.campaign_id else None
    return {
        "thread_id": str(thread_id), "subject": first.subject,
        "contact": {"id": str(contact.id), "email": contact.email,
                    "name": " ".join(x for x in (contact.first_name, contact.last_name) if x) or None}
        if contact else None,
        "campaign": {"id": str(campaign.id), "name": campaign.name} if campaign else None,
        "messages": [{**_summary(r), "body_text": r.body_text, "body_html": r.body_html} for r in rows],
    }


@router.post("/{message_id}/read")
def mark(message_id: uuid.UUID, ctx: Ctx = Viewer, read: bool = True):
    m = get_or_404(ctx.db, MailMessage, message_id, "Message")
    m.is_read = read
    return _summary(m)


@router.post("/{message_id}/reply", status_code=201)
def reply(message_id: uuid.UUID, body: ReplyIn, ctx: Ctx = Marketer):
    original = get_or_404(ctx.db, MailMessage, message_id, "Message")
    try:
        row = mailbox.send_reply(ctx.db, ctx.workspace_id, original, body.body, user_id=ctx.user.id)
    except ValueError as e:
        raise BadRequest(str(e)) from None
    audit(ctx, "reply", "mail_message", row.id, after={"to": row.to_addr, "status": row.status})
    if row.status == "failed":
        raise BadRequest(f"Reply not sent: {row.error}")
    return _summary(row)
