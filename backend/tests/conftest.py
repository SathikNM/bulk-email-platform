"""Integration-test fixtures against a REAL PostgreSQL database (no mocks).

Uses TEST_DATABASE_URL (default: DATABASE_URL with the database renamed to `<name>_test`).
The test database is created if missing and migrated from scratch each session.
"""
import os
import uuid

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.engine import make_url

from alembic import command
from app.core.config import settings

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _test_url() -> str:
    if os.environ.get("TEST_DATABASE_URL"):
        return os.environ["TEST_DATABASE_URL"]
    u = make_url(settings.DATABASE_URL)
    return u.set(database=f"{u.database}_test").render_as_string(hide_password=False)


def _alembic_cfg(url: str) -> Config:
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    cfg.attributes["url"] = url
    return cfg


@pytest.fixture(scope="session")
def db_url() -> str:
    url = _test_url()
    u = make_url(url)
    admin = sa.create_engine(u.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as c:
            exists = c.scalar(sa.text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": u.database})
            if not exists:
                c.execute(sa.text(f'CREATE DATABASE "{u.database}"'))
    except sa.exc.OperationalError as e:
        pytest.skip(f"PostgreSQL not reachable for integration tests: {e.orig}")
    finally:
        admin.dispose()
    return url


@pytest.fixture(scope="session")
def migrated(db_url: str) -> str:
    cfg = _alembic_cfg(db_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    return db_url


@pytest.fixture(scope="session")
def engine(migrated: str):
    eng = sa.create_engine(migrated, future=True)
    yield eng
    eng.dispose()


@pytest.fixture
def conn(engine):
    """A connection inside a transaction that is always rolled back."""
    with engine.connect() as c:
        tx = c.begin()
        c.execute(sa.text("SELECT set_config('app.bypass_rls', 'on', true)"))
        yield c
        tx.rollback()


def new_workspace(conn, slug: str | None = None) -> uuid.UUID:
    slug = slug or f"ws-{uuid.uuid4().hex[:8]}"
    return conn.scalar(
        sa.text("INSERT INTO workspaces (name, slug) VALUES (:n, :s) RETURNING id"),
        {"n": slug, "s": slug},
    )


def new_company(conn, ws: uuid.UUID, name: str = "Acme Construction", **kw) -> uuid.UUID:
    cols = {"workspace_id": ws, "name": name, **kw}
    keys = ", ".join(cols)
    vals = ", ".join(f":{k}" for k in cols)
    return conn.scalar(sa.text(f"INSERT INTO companies ({keys}) VALUES ({vals}) RETURNING id"), cols)


def new_contact(conn, ws: uuid.UUID, company: uuid.UUID, email: str, **kw) -> uuid.UUID:
    cols = {"workspace_id": ws, "company_id": company, "email": email, **kw}
    keys = ", ".join(cols)
    vals = ", ".join(f":{k}" for k in cols)
    return conn.scalar(sa.text(f"INSERT INTO contacts ({keys}) VALUES ({vals}) RETURNING id"), cols)
