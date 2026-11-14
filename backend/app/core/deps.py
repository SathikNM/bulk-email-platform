"""Request dependencies: DB session, authenticated user, workspace context, RBAC."""
import ipaddress
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import sqlalchemy as sa
from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import AppError, Forbidden
from app.core.security import decode_access_token
from app.db.session import apply_workspace_scope, new_session
from app.models import User, WorkspaceMember
from app.models.enums import MemberRole


def client_ip(request: Request) -> str | None:
    """Client IP for audit logs; X-Forwarded-For first hop when behind the reverse proxy."""
    candidates = [request.headers.get("x-forwarded-for", "").split(",")[0].strip(),
                  request.client.host if request.client else ""]
    for c in candidates:
        try:
            return str(ipaddress.ip_address(c))
        except ValueError:
            continue
    return None


ROLE_RANK = {MemberRole.VIEWER: 0, MemberRole.ANALYST: 1, MemberRole.MARKETER: 2,
             MemberRole.ADMIN: 3, MemberRole.OWNER: 4}

_bearer = HTTPBearer(auto_error=False)


def get_db() -> Iterator[Session]:
    """One transaction per request: commit on success, rollback on any exception."""
    s = new_session()
    try:
        with s.begin():
            yield s
    finally:
        s.close()


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise AppError(401, "Unauthorized", "Missing bearer token")
    user_id = decode_access_token(creds.credentials)
    user = db.get(User, user_id) if user_id else None
    if user is None or not user.is_active:
        raise AppError(401, "Unauthorized", "Invalid or expired token")
    return user


@dataclass
class Ctx:
    db: Session
    user: User
    workspace_id: uuid.UUID
    role: MemberRole
    ip: str | None = None
    user_agent: str | None = None

    def at_least(self, role: MemberRole) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[role]


def workspace_ctx(
    request: Request,
    x_workspace_id: uuid.UUID = Header(..., alias="X-Workspace-Id"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Ctx:
    member = db.scalar(sa.select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == x_workspace_id, WorkspaceMember.user_id == user.id))
    if member is None and not user.is_superadmin:
        raise Forbidden("You are not a member of this workspace")
    role = member.role if member else MemberRole.OWNER
    apply_workspace_scope(db, x_workspace_id)
    return Ctx(db=db, user=user, workspace_id=x_workspace_id, role=role,
               ip=client_ip(request),
               user_agent=request.headers.get("user-agent"))


def require(role: MemberRole):
    def _dep(ctx: Ctx = Depends(workspace_ctx)) -> Ctx:
        if not ctx.at_least(role):
            raise Forbidden(f"Requires role '{role.value}' or higher")
        return ctx
    return _dep


Viewer = Depends(require(MemberRole.VIEWER))
Analyst = Depends(require(MemberRole.ANALYST))
Marketer = Depends(require(MemberRole.MARKETER))
Admin = Depends(require(MemberRole.ADMIN))
Owner = Depends(require(MemberRole.OWNER))
