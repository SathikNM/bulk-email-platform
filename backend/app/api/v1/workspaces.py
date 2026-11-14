"""Workspaces (tenants) and member/role management."""
import re
import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.deps import Admin, Ctx, Viewer, current_user, get_db
from app.core.errors import BadRequest, Conflict, Forbidden, NotFound
from app.core.security import hash_password, validate_password_strength
from app.models import User, Workspace, WorkspaceMember
from app.models.enums import MemberRole
from app.services.common import audit, row_dict
from app.services.workspaces import bootstrap_workspace

router = APIRouter(tags=["workspaces"])


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str | None = Field(default=None, max_length=80)
    default_locale: str = "en"
    timezone: str = "Asia/Riyadh"
    legal_address: str | None = None


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    default_locale: str | None = None
    timezone: str | None = None
    legal_address: str | None = None
    compliance_settings: dict | None = None


class MemberIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    role: MemberRole
    password: str | None = None  # required when the user does not exist yet


class MemberUpdate(BaseModel):
    role: MemberRole


@router.post("/workspaces", status_code=201)
def create_workspace(body: WorkspaceIn, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    if not user.is_superadmin:
        raise Forbidden("Only platform administrators can create workspaces")
    slug = body.slug or re.sub(r"[^a-z0-9]+", "-", body.name.lower()).strip("-")[:80]
    if db.scalar(sa.select(Workspace.id).where(Workspace.slug == slug)):
        raise Conflict(f"Workspace slug '{slug}' already exists")
    ws = Workspace(name=body.name, slug=slug, default_locale=body.default_locale,
                   timezone=body.timezone, legal_address=body.legal_address)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=MemberRole.OWNER))
    db.execute(sa.text("SELECT set_config('app.bypass_rls', 'on', true)"))
    bootstrap_workspace(db, ws.id)
    db.flush()
    db.execute(sa.text("SELECT set_config('app.bypass_rls', '', true)"))
    return row_dict(ws)


@router.get("/workspace")
def get_workspace(ctx: Ctx = Viewer):
    return row_dict(ctx.db.get(Workspace, ctx.workspace_id))


@router.patch("/workspace")
def update_workspace(body: WorkspaceUpdate, ctx: Ctx = Admin):
    ws = ctx.db.get(Workspace, ctx.workspace_id)
    before = row_dict(ws)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(ws, k, v)
    ctx.db.flush()
    audit(ctx, "update", "workspace", ws.id, before, row_dict(ws))
    return row_dict(ws)


def _member_out(m: WorkspaceMember, u: User) -> dict:
    return {"user_id": str(u.id), "email": u.email, "full_name": u.full_name, "role": m.role.value,
            "is_active": u.is_active, "last_login_at": u.last_login_at, "joined_at": m.created_at}


@router.get("/members")
def list_members(ctx: Ctx = Viewer):
    rows = ctx.db.execute(sa.select(WorkspaceMember, User).join(User, User.id == WorkspaceMember.user_id)
                          .where(WorkspaceMember.workspace_id == ctx.workspace_id)
                          .order_by(User.full_name)).all()
    return [_member_out(m, u) for m, u in rows]


@router.post("/members", status_code=201)
def add_member(body: MemberIn, ctx: Ctx = Admin):
    if body.role == MemberRole.OWNER and ctx.role != MemberRole.OWNER:
        raise Forbidden("Only owners can add owners")
    user = ctx.db.scalar(sa.select(User).where(User.email == body.email))
    if user is None:
        if not body.password:
            raise BadRequest("password is required to create a new user")
        if err := validate_password_strength(body.password):
            raise BadRequest(err)
        user = User(email=body.email, full_name=body.full_name,
                    password_hash=hash_password(body.password))
        ctx.db.add(user)
        ctx.db.flush()
    if ctx.db.get(WorkspaceMember, (ctx.workspace_id, user.id)):
        raise Conflict("User is already a member")
    m = WorkspaceMember(workspace_id=ctx.workspace_id, user_id=user.id, role=body.role)
    ctx.db.add(m)
    ctx.db.flush()
    audit(ctx, "add_member", "workspace_member", user.id, after={"role": body.role.value})
    return _member_out(m, user)


@router.patch("/members/{user_id}")
def update_member(user_id: uuid.UUID, body: MemberUpdate, ctx: Ctx = Admin):
    m = ctx.db.get(WorkspaceMember, (ctx.workspace_id, user_id))
    if m is None:
        raise NotFound("Member")
    if (m.role == MemberRole.OWNER or body.role == MemberRole.OWNER) and ctx.role != MemberRole.OWNER:
        raise Forbidden("Only owners can change owner roles")
    if m.role == MemberRole.OWNER and body.role != MemberRole.OWNER:
        _ensure_other_owner(ctx, user_id)
    before = m.role.value
    m.role = body.role
    audit(ctx, "change_role", "workspace_member", user_id, {"role": before}, {"role": body.role.value})
    return _member_out(m, ctx.db.get(User, user_id))


@router.delete("/members/{user_id}", status_code=204)
def remove_member(user_id: uuid.UUID, ctx: Ctx = Admin):
    m = ctx.db.get(WorkspaceMember, (ctx.workspace_id, user_id))
    if m is None:
        raise NotFound("Member")
    if m.role == MemberRole.OWNER:
        if ctx.role != MemberRole.OWNER:
            raise Forbidden("Only owners can remove owners")
        _ensure_other_owner(ctx, user_id)
    ctx.db.delete(m)
    audit(ctx, "remove_member", "workspace_member", user_id)
    return Response(status_code=204)


def _ensure_other_owner(ctx: Ctx, user_id: uuid.UUID) -> None:
    owners = ctx.db.scalar(sa.select(sa.func.count()).select_from(WorkspaceMember).where(
        WorkspaceMember.workspace_id == ctx.workspace_id, WorkspaceMember.role == MemberRole.OWNER,
        WorkspaceMember.user_id != user_id))
    if not owners:
        raise BadRequest("A workspace must keep at least one owner")
