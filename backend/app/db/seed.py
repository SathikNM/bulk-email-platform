"""Idempotent seed: demo workspace, admin user, standard industries, base categories.

Usage:  python -m app.db.seed
Env:    SEED_ADMIN_EMAIL (default admin@primecfo.local)
        SEED_ADMIN_PASSWORD (default: random, printed once)
"""
import os
import secrets

import sqlalchemy as sa

from app.core.security import hash_password
from app.db.session import system_scope
from app.models import User, Workspace, WorkspaceMember
from app.models.enums import MemberRole
from app.services.workspaces import bootstrap_workspace


def run() -> None:
    email = os.environ.get("SEED_ADMIN_EMAIL", "admin@primecfo.local")
    password = os.environ.get("SEED_ADMIN_PASSWORD")
    generated = password is None
    password = password or secrets.token_urlsafe(12)

    with system_scope() as s:
        ws = s.scalar(sa.select(Workspace).where(Workspace.slug == "demo"))
        if ws is None:
            ws = Workspace(name="Demo Workspace", slug="demo", default_locale="en",
                           legal_address="Riyadh, Saudi Arabia")
            s.add(ws)
            s.flush()

        user = s.scalar(sa.select(User).where(User.email == email))
        created_user = user is None
        if created_user:
            user = User(email=email, full_name="Platform Admin",
                        password_hash=hash_password(password), is_superadmin=True)
            s.add(user)
            s.flush()

        if s.get(WorkspaceMember, (ws.id, user.id)) is None:
            s.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=MemberRole.OWNER))
        bootstrap_workspace(s, ws.id)

    print(f"Seed complete. Workspace: demo  Admin: {email}")
    if created_user and generated:
        print(f"Generated admin password (shown once, change it after first login): {password}")


if __name__ == "__main__":
    run()
