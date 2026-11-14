"""Engine, sessions and workspace-scoped transactions.

Every request/worker transaction that touches tenant data must go through
`apply_workspace_scope()` / `workspace_scope()`. It switches to the non-owner
`bep_app` role and sets `app.workspace_id`, so PostgreSQL Row-Level Security
filters every query to one workspace even if application code forgets a WHERE.
"""
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

APP_ROLE = "bep_app"

_engine: sa.Engine | None = None
SessionLocal = sessionmaker(expire_on_commit=False, autoflush=False)


def configure_engine(url: str | None = None) -> sa.Engine:
    """(Re)bind the global engine. Tests call this with the test database URL."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = sa.create_engine(url or settings.DATABASE_URL, pool_pre_ping=True, pool_size=10,
                               max_overflow=20)
    SessionLocal.configure(bind=_engine)
    return _engine


def get_engine() -> sa.Engine:
    return _engine or configure_engine()


def new_session() -> Session:
    get_engine()
    return SessionLocal()


def apply_workspace_scope(session: Session, workspace_id: uuid.UUID | None) -> None:
    """Scope the *current transaction* to a workspace (SET LOCAL semantics)."""
    session.execute(sa.text(f"SET LOCAL ROLE {APP_ROLE}"))
    session.execute(
        sa.text("SELECT set_config('app.workspace_id', :ws, true)"),
        {"ws": str(workspace_id) if workspace_id else ""},
    )


def apply_system_scope(session: Session) -> None:
    session.execute(sa.text("SELECT set_config('app.bypass_rls', 'on', true)"))


@event.listens_for(Session, "after_begin")
def _reapply_scope(session: Session, transaction, connection) -> None:
    """Long-running worker sessions commit many times; re-scope every new transaction."""
    ws = session.info.get("workspace_scope")
    if ws is not None:
        connection.execute(sa.text(f"SET LOCAL ROLE {APP_ROLE}"))
        connection.execute(sa.text("SELECT set_config('app.workspace_id', :ws, true)"), {"ws": str(ws)})
    elif session.info.get("system_scope"):
        connection.execute(sa.text("SELECT set_config('app.bypass_rls', 'on', true)"))


def worker_session(workspace_id: uuid.UUID | None = None, system: bool = False) -> Session:
    """Session whose every transaction is scoped (to a workspace, or system-wide)."""
    s = new_session()
    if workspace_id is not None:
        s.info["workspace_scope"] = workspace_id
    elif system:
        s.info["system_scope"] = True
    return s


@contextmanager
def workspace_scope(workspace_id: uuid.UUID) -> Iterator[Session]:
    s = worker_session(workspace_id)
    try:
        with s.begin():
            yield s
    finally:
        s.close()


@contextmanager
def system_scope() -> Iterator[Session]:
    """Cross-workspace access for trusted system jobs (seed, schedulers, webhooks)."""
    s = worker_session(system=True)
    try:
        with s.begin():
            yield s
    finally:
        s.close()
