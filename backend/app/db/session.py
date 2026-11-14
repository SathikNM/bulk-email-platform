"""Engine, sessions and workspace-scoped transactions.

Every request/worker transaction that touches tenant data must go through
`workspace_scope()`. It switches to the non-owner `bep_app` role and sets
`app.workspace_id`, so PostgreSQL Row-Level Security filters every query to one
workspace even if application code forgets a WHERE clause.
"""
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = sa.create_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

APP_ROLE = "bep_app"


def apply_workspace_scope(session: Session, workspace_id: uuid.UUID | None) -> None:
    """Scope the *current transaction* to a workspace (SET LOCAL semantics)."""
    session.execute(sa.text(f"SET LOCAL ROLE {APP_ROLE}"))
    session.execute(
        sa.text("SELECT set_config('app.workspace_id', :ws, true)"),
        {"ws": str(workspace_id) if workspace_id else ""},
    )


@contextmanager
def workspace_scope(workspace_id: uuid.UUID, session: Session | None = None) -> Iterator[Session]:
    own = session is None
    s = session or SessionLocal()
    try:
        with s.begin() if own else s.begin_nested():
            apply_workspace_scope(s, workspace_id)
            yield s
    finally:
        if own:
            s.close()


@contextmanager
def system_scope() -> Iterator[Session]:
    """Cross-workspace access for trusted system jobs (seed, migrations, admin tooling)."""
    s = SessionLocal()
    try:
        with s.begin():
            s.execute(sa.text("SELECT set_config('app.bypass_rls', 'on', true)"))
            yield s
    finally:
        s.close()
