"""Suppression list management and audit log access (compliance)."""
import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Response
from pydantic import BaseModel, EmailStr, Field

from app.core.deps import Admin, Ctx, Viewer
from app.core.errors import NotFound
from app.models import AuditLog, Contact, Suppression, User
from app.models.enums import SuppressionReason
from app.services.common import audit, paginate, row_dict
from app.services.compliance import suppress_email

router = APIRouter(tags=["compliance"])


class SuppressionIn(BaseModel):
    email: EmailStr
    reason: SuppressionReason = SuppressionReason.MANUAL
    source: str | None = Field(default=None, max_length=200)


class RemoveIn(BaseModel):
    justification: str = Field(min_length=5, max_length=500)


@router.get("/suppressions")
def list_suppressions(ctx: Ctx = Viewer, q: str | None = None, reason: SuppressionReason | None = None,
                      page: int = 1, page_size: int = 50):
    stmt = sa.select(Suppression).order_by(Suppression.created_at.desc())
    if q:
        stmt = stmt.where(Suppression.email.ilike(f"%{q}%"))
    if reason:
        stmt = stmt.where(Suppression.reason == reason)
    return paginate(ctx.db, stmt, page, page_size, row_dict)


@router.post("/suppressions", status_code=201)
def add_suppression(body: SuppressionIn, ctx: Ctx = Admin):
    suppress_email(ctx.db, ctx.workspace_id, body.email, body.reason, body.source or "manual", ctx.user.id)
    from app.models.enums import SubscriptionStatus
    from app.services.compliance import STATUS_FOR_REASON
    ctx.db.execute(sa.update(Contact).where(Contact.email == body.email).values(
        subscription_status=STATUS_FOR_REASON.get(body.reason, SubscriptionStatus.UNSUBSCRIBED)))
    audit(ctx, "suppress", "suppression", after=body.model_dump(mode="json"))
    return row_dict(ctx.db.scalar(sa.select(Suppression).where(Suppression.email == body.email)))


@router.delete("/suppressions/{suppression_id}", status_code=204)
def remove_suppression(suppression_id: uuid.UUID, body: RemoveIn, ctx: Ctx = Admin):
    """Removing a suppression does NOT re-subscribe anyone: the contact stays unsubscribed
    until fresh consent is recorded."""
    s = ctx.db.get(Suppression, suppression_id)
    if s is None:
        raise NotFound("Suppression")
    if s.reason == SuppressionReason.COMPLAINT:
        from app.core.errors import Conflict
        raise Conflict("Spam-complaint suppressions cannot be removed")
    audit(ctx, "unsuppress", "suppression", s.id, before=row_dict(s), after={"justification": body.justification})
    ctx.db.delete(s)
    return Response(status_code=204)


@router.get("/audit-logs")
def audit_logs(ctx: Ctx = Admin, entity_type: str | None = None, entity_id: str | None = None,
               action: str | None = None, page: int = 1, page_size: int = 50):
    stmt = (sa.select(AuditLog).where(AuditLog.workspace_id == ctx.workspace_id)
            .order_by(AuditLog.created_at.desc()))
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    names = dict(ctx.db.execute(sa.select(User.id, User.full_name)).all())

    def m(a: AuditLog):
        return {**row_dict(a), "user_name": names.get(a.user_id)}
    return paginate(ctx.db, stmt, page, page_size, m)


