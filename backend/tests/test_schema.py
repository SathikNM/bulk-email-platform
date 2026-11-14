"""Phase 2 database integrity tests (real PostgreSQL)."""
import uuid
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from alembic import command
from app.models import LATER_RLS_TABLES, RLS_TABLES, UPDATED_AT_TABLES, Base
from tests.conftest import _alembic_cfg, new_company, new_contact, new_workspace

pytestmark = pytest.mark.usefixtures("migrated")


def _violates(conn, sql: str, params: dict, exc=sa.exc.IntegrityError) -> None:
    sp = conn.begin_nested()
    with pytest.raises(exc):
        conn.execute(sa.text(sql), params)
    sp.rollback()


# ---------- migrations ----------

def test_models_match_migrations(engine):
    with engine.connect() as c:
        diff = compare_metadata(MigrationContext.configure(c), Base.metadata)
    assert diff == [], f"Model/migration drift: {diff}"


def test_downgrade_upgrade_round_trip(migrated, engine):
    cfg = _alembic_cfg(migrated)
    command.downgrade(cfg, "base")
    with engine.connect() as c:
        left = c.scalars(sa.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name <> 'alembic_version'"
        )).all()
        enums = c.scalar(sa.text(
            "SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace "
            "WHERE n.nspname='public' AND t.typtype='e'"
        ))
    assert left == [] and enums == 0
    command.upgrade(cfg, "head")


def test_expected_tables_exist(engine):
    expected = {
        "workspaces", "users", "workspace_members", "refresh_tokens", "companies", "contacts",
        "industries", "categories", "tags", "company_tags", "contact_tags", "company_categories",
        "segments", "email_templates", "email_blocks", "campaigns", "campaign_recipients",
        "email_events", "suppressions", "consent_records", "sending_accounts", "audit_logs",
        "tracked_links", "campaign_daily_stats", "import_jobs",
    }
    with engine.connect() as c:
        actual = set(c.scalars(sa.text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        )))
    assert expected <= actual


def test_rls_and_triggers_installed(engine):
    with engine.connect() as c:
        policies = set(c.scalars(sa.text("SELECT tablename FROM pg_policies")))
        forced = set(c.scalars(sa.text(
            "SELECT relname FROM pg_class WHERE relrowsecurity AND relforcerowsecurity"
        )))
        triggers = set(c.scalars(sa.text(
            "SELECT event_object_table FROM information_schema.triggers "
            "WHERE trigger_name LIKE 'trg_%_updated_at'"
        )))
    assert set(RLS_TABLES + LATER_RLS_TABLES) <= policies
    assert set(RLS_TABLES + LATER_RLS_TABLES) <= forced
    assert set(UPDATED_AT_TABLES) <= triggers


# ---------- contacts / companies ----------

def test_duplicate_contact_email_blocked_case_insensitive(conn):
    ws = new_workspace(conn)
    co = new_company(conn, ws)
    new_contact(conn, ws, co, "cfo@acme.sa")
    _violates(conn, "INSERT INTO contacts (workspace_id, company_id, email) VALUES (:w, :c, :e)",
              {"w": ws, "c": co, "e": "CFO@ACME.SA"})


def test_same_email_allowed_in_other_workspace(conn):
    ws1, ws2 = new_workspace(conn), new_workspace(conn)
    new_contact(conn, ws1, new_company(conn, ws1), "cfo@acme.sa")
    new_contact(conn, ws2, new_company(conn, ws2), "cfo@acme.sa")


def test_soft_deleted_contact_frees_email(conn):
    ws = new_workspace(conn)
    co = new_company(conn, ws)
    cid = new_contact(conn, ws, co, "cfo@acme.sa")
    conn.execute(sa.text("UPDATE contacts SET deleted_at = now() WHERE id = :i"), {"i": cid})
    new_contact(conn, ws, co, "cfo@acme.sa")


def test_contact_requires_company(conn):
    ws = new_workspace(conn)
    _violates(conn, "INSERT INTO contacts (workspace_id, company_id, email) VALUES (:w, :c, :e)",
              {"w": ws, "c": uuid.uuid4(), "e": "x@y.com"})


def test_company_with_contacts_cannot_be_hard_deleted(conn):
    ws = new_workspace(conn)
    co = new_company(conn, ws)
    new_contact(conn, ws, co, "a@b.com")
    _violates(conn, "DELETE FROM companies WHERE id = :i", {"i": co})


def test_new_contact_defaults_to_pending_not_subscribed(conn):
    ws = new_workspace(conn)
    cid = new_contact(conn, ws, new_company(conn, ws), "a@b.com")
    row = conn.execute(sa.text(
        "SELECT subscription_status, email_verification_status, code FROM contacts WHERE id=:i"
    ), {"i": cid}).one()
    assert row.subscription_status == "pending"
    assert row.email_verification_status == "unverified"
    assert row.code.startswith("CONT-")


def test_company_code_and_normalized_name(conn):
    ws = new_workspace(conn)
    co = new_company(conn, ws, name="Al-Rajhi  Construction Co.")
    ar = new_company(conn, ws, name="شركة البناء")
    rows = dict(conn.execute(sa.text(
        "SELECT id, normalized_name FROM companies WHERE id IN (:a, :b)"), {"a": co, "b": ar}).all())
    assert rows[co] == "alrajhiconstructionco"
    assert rows[ar] == "شركةالبناء"  # Arabic letters preserved
    code = conn.scalar(sa.text("SELECT code FROM companies WHERE id=:i"), {"i": co})
    assert code.startswith("COMP-") and len(code) == 11


def test_duplicate_company_domain_blocked(conn):
    ws = new_workspace(conn)
    new_company(conn, ws, name="Acme", domain="acme.sa")
    _violates(conn, "INSERT INTO companies (workspace_id, name, domain) VALUES (:w, 'Acme 2', 'ACME.sa')",
              {"w": ws})


def test_trigram_duplicate_suggestion_query(conn):
    ws = new_workspace(conn)
    new_company(conn, ws, name="Saudi Binladin Group")
    hit = conn.scalar(sa.text(
        "SELECT name FROM companies WHERE workspace_id=:w AND "
        "similarity(normalized_name, lower(regexp_replace(:q, '[[:space:][:punct:]]+', '', 'g'))) > 0.5"
    ), {"w": ws, "q": "Saudi Bin Ladin Group"})
    assert hit == "Saudi Binladin Group"


def test_invalid_country_code_rejected(conn):
    ws = new_workspace(conn)
    # lower-case / non-ISO-2 hits the CHECK constraint; 3 letters hits varchar(2)
    _violates(conn, "INSERT INTO companies (workspace_id, name, country_code) VALUES (:w, 'X', 'sa')",
              {"w": ws})
    _violates(conn, "INSERT INTO companies (workspace_id, name, country_code) VALUES (:w, 'X', 'SAU')",
              {"w": ws}, exc=sa.exc.DataError)


def test_tag_names_unique_case_insensitive(conn):
    ws = new_workspace(conn)
    conn.execute(sa.text("INSERT INTO tags (workspace_id, name) VALUES (:w, 'VIP')"), {"w": ws})
    _violates(conn, "INSERT INTO tags (workspace_id, name) VALUES (:w, 'vip')", {"w": ws})


def test_updated_at_trigger(conn):
    """The trigger overrides any client-supplied updated_at with the transaction time."""
    ws = new_workspace(conn)
    co = new_company(conn, ws)
    conn.execute(sa.text("UPDATE companies SET city='Riyadh', "
                         "updated_at = '2000-01-01T00:00:00Z' WHERE id=:i"), {"i": co})
    row = conn.execute(sa.text("SELECT updated_at, now() AS tx_now FROM companies WHERE id=:i"),
                       {"i": co}).one()
    assert row.updated_at == row.tx_now


# ---------- suppressions / sending ----------

def test_suppression_unique_per_workspace(conn):
    ws = new_workspace(conn)
    conn.execute(sa.text("INSERT INTO suppressions (workspace_id, email, reason) "
                         "VALUES (:w, 'a@b.com', 'unsubscribe')"), {"w": ws})
    _violates(conn, "INSERT INTO suppressions (workspace_id, email, reason) "
                    "VALUES (:w, 'A@B.COM', 'hard_bounce')", {"w": ws})


def _campaign(conn, ws, **kw) -> uuid.UUID:
    cols = {"workspace_id": ws, "name": "Q4 Launch", **kw}
    keys = ", ".join(cols)
    vals = ", ".join(f":{k}" for k in cols)
    return conn.scalar(sa.text(f"INSERT INTO campaigns ({keys}) VALUES ({vals}) RETURNING id"), cols)


def test_duplicate_recipient_blocked(conn):
    ws = new_workspace(conn)
    cid = new_contact(conn, ws, new_company(conn, ws), "a@b.com")
    camp = _campaign(conn, ws)
    sql = ("INSERT INTO campaign_recipients (workspace_id, campaign_id, contact_id, email) "
           "VALUES (:w, :c, :ct, :e)")
    conn.execute(sa.text(sql), {"w": ws, "c": camp, "ct": cid, "e": "a@b.com"})
    _violates(conn, sql, {"w": ws, "c": camp, "ct": cid, "e": "a@b.com"})
    # ON CONFLICT DO NOTHING is the idempotent snapshot path used by the send engine
    res = conn.execute(sa.text(sql + " ON CONFLICT DO NOTHING"),
                       {"w": ws, "c": camp, "ct": cid, "e": "a@b.com"})
    assert res.rowcount == 0


def test_campaign_cannot_be_scheduled_without_time_or_approval(conn):
    ws = new_workspace(conn)
    _violates(conn, "INSERT INTO campaigns (workspace_id, name, status, approved_at) "
                    "VALUES (:w, 'X', 'scheduled', now())", {"w": ws})
    _violates(conn, "INSERT INTO campaigns (workspace_id, name, status, scheduled_at) "
                    "VALUES (:w, 'X', 'scheduled', now())", {"w": ws})
    _campaign(conn, ws, status="scheduled", scheduled_at=datetime.now(timezone.utc),
              approved_at=datetime.now(timezone.utc))


def test_webhook_event_replay_deduplicated(conn):
    ws = new_workspace(conn)
    sql = ("INSERT INTO email_events (workspace_id, event_type, provider_event_id, occurred_at) "
           "VALUES (:w, 'delivery', 'ses-evt-1', now())")
    conn.execute(sa.text(sql), {"w": ws})
    _violates(conn, sql, {"w": ws})


def test_invalid_enum_value_rejected(conn):
    ws = new_workspace(conn)
    co = new_company(conn, ws)
    _violates(conn, "INSERT INTO contacts (workspace_id, company_id, email, subscription_status) "
                    "VALUES (:w, :c, 'a@b.com', 'maybe')", {"w": ws, "c": co},
              exc=sa.exc.DataError)


# ---------- tenant isolation (RLS) ----------

def test_rls_isolates_workspaces(engine):
    with engine.connect() as c:
        tx = c.begin()
        c.execute(sa.text("SELECT set_config('app.bypass_rls', 'on', true)"))
        ws1, ws2 = new_workspace(c), new_workspace(c)
        new_contact(c, ws1, new_company(c, ws1, name="A"), "a@one.com")
        new_contact(c, ws2, new_company(c, ws2, name="B"), "b@two.com")

        c.execute(sa.text("SELECT set_config('app.bypass_rls', '', true)"))
        c.execute(sa.text("SET LOCAL ROLE bep_app"))

        # No workspace set → sees nothing
        c.execute(sa.text("SELECT set_config('app.workspace_id', '', true)"))
        assert c.scalar(sa.text("SELECT count(*) FROM contacts")) == 0

        c.execute(sa.text("SELECT set_config('app.workspace_id', :w, true)"), {"w": str(ws1)})
        emails = c.scalars(sa.text("SELECT email FROM contacts")).all()
        assert emails == ["a@one.com"]

        # Cannot write into another workspace
        sp = c.begin_nested()
        with pytest.raises(sa.exc.ProgrammingError):
            c.execute(sa.text("INSERT INTO tags (workspace_id, name) VALUES (:w, 'x')"), {"w": ws2})
        sp.rollback()

        # Cannot update another workspace's rows (silently 0 rows)
        res = c.execute(sa.text("UPDATE contacts SET city='Hacked' WHERE email='b@two.com'"))
        assert res.rowcount == 0
        tx.rollback()


def test_app_role_cannot_touch_alembic_version(engine):
    with engine.connect() as c:
        tx = c.begin()
        c.execute(sa.text("SET LOCAL ROLE bep_app"))
        with pytest.raises(sa.exc.ProgrammingError):
            c.execute(sa.text("SELECT * FROM alembic_version"))
        tx.rollback()
