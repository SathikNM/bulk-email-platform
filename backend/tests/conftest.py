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


# ---------------------------------------------------------------- API fixtures
@pytest.fixture(scope="session", autouse=True)
def app_env(tmp_path_factory, request):
    """Point the app at the test DB, run Celery eagerly, store uploads in a temp dir."""
    from app.workers.celery_app import celery

    settings.LOCAL_STORAGE_DIR = str(tmp_path_factory.mktemp("uploads"))
    settings.STORAGE_BACKEND = "local"
    settings.SES_WEBHOOK_VERIFY_SIGNATURE = True
    settings.ENVIRONMENT = "test"
    settings.RATE_LIMIT_ENABLED = False
    celery.conf.task_always_eager = True
    celery.conf.task_eager_propagates = True
    yield


@pytest.fixture(scope="session")
def api_engine(migrated):
    from app.db.session import configure_engine

    return configure_engine(migrated)


@pytest.fixture
def client(api_engine):
    from fastapi.testclient import TestClient

    from app.core.redis import get_redis
    from app.main import app

    for k in get_redis().scan_iter("login_fail:*"):
        get_redis().delete(k)
    with TestClient(app) as c:
        yield c


def make_user(email=None, password="Str0ng!Passw0rd", superadmin=False):
    from app.core.security import hash_password
    from app.db.session import system_scope
    from app.models import User

    email = email or f"u{uuid.uuid4().hex[:10]}@example.com"
    with system_scope() as s:
        u = User(email=email, full_name="Test User", password_hash=hash_password(password),
                 is_superadmin=superadmin)
        s.add(u)
        s.flush()
        return u.id, email, password


def make_workspace_with(role="owner", user=None):
    from app.db.session import system_scope
    from app.models import Workspace, WorkspaceMember
    from app.models.enums import MemberRole
    from app.services.workspaces import bootstrap_workspace

    uid, email, pw = user or make_user()
    with system_scope() as s:
        slug = f"ws-{uuid.uuid4().hex[:8]}"
        ws = Workspace(name=slug, slug=slug, legal_address="Riyadh")
        s.add(ws)
        s.flush()
        s.add(WorkspaceMember(workspace_id=ws.id, user_id=uid, role=MemberRole(role)))
        bootstrap_workspace(s, ws.id)
        return ws.id, (uid, email, pw)


def login(client, email, password) -> str:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


class Api:
    """Small helper bound to a workspace + user for concise tests."""

    def __init__(self, client, ws_id, token):
        self.c, self.ws, self.token = client, ws_id, token

    @property
    def h(self):
        return {"Authorization": f"Bearer {self.token}", "X-Workspace-Id": str(self.ws)}

    def get(self, url, **kw):
        return self.c.get("/api/v1" + url, headers=self.h, **kw)

    def post(self, url, **kw):
        return self.c.post("/api/v1" + url, headers=self.h, **kw)

    def patch(self, url, **kw):
        return self.c.patch("/api/v1" + url, headers=self.h, **kw)

    def put(self, url, **kw):
        return self.c.put("/api/v1" + url, headers=self.h, **kw)

    def delete(self, url, **kw):
        return self.c.delete("/api/v1" + url, headers=self.h, **kw)


@pytest.fixture
def api(client):
    ws, (uid, email, pw) = make_workspace_with("owner")
    return Api(client, ws, login(client, email, pw))


def api_with_role(client, ws_id, role):
    from app.db.session import system_scope
    from app.models import WorkspaceMember
    from app.models.enums import MemberRole

    uid, email, pw = make_user()
    with system_scope() as s:
        s.add(WorkspaceMember(workspace_id=ws_id, user_id=uid, role=MemberRole(role)))
    return Api(client, ws_id, login(client, email, pw))


# ---------------------------------------------------------------- real SMTP sink
class _Sink:
    def __init__(self):
        self.messages = []

    async def handle_DATA(self, server, session, envelope):  # noqa: N802 - aiosmtpd API
        import email
        import email.policy
        self.messages.append({"from": envelope.mail_from, "to": list(envelope.rcpt_tos),
                              "msg": email.message_from_bytes(envelope.content, policy=email.policy.default)})
        return "250 OK"

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):  # noqa: N802
        if address.startswith("reject"):
            return "550 5.1.1 No such user"
        if address.startswith("busy"):
            return "451 4.3.0 Try again later"
        envelope.rcpt_tos.append(address)
        return "250 OK"


@pytest.fixture
def smtp_sink():
    """A real SMTP server on localhost (aiosmtpd) capturing everything sent to it."""
    import socket

    from aiosmtpd.controller import Controller

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    sink = _Sink()
    ctl = Controller(sink, hostname="127.0.0.1", port=port)
    ctl.start()
    sink.port = port
    yield sink
    ctl.stop()


def smtp_account(api, port, **kw):
    r = api.post("/sending-accounts", json={
        "name": "Local SMTP", "provider": "smtp", "from_email": "news@primecfo-demo.com", "from_name": "Prime CFO",
        "max_per_second": 50, "max_per_day": 10000,
        "credentials": {"host": "127.0.0.1", "port": port, "security": "none"}, **kw})
    assert r.status_code == 201, r.text
    return r.json()
