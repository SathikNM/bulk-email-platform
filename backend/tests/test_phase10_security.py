"""Phase 10: security headers, rate limiting, production config guard, tenant/role enforcement."""
import pytest

from app.core import middleware
from app.core.config import settings


def test_security_headers(client):
    r = client.get("/health")
    for h in ("x-request-id", "x-content-type-options", "x-frame-options", "referrer-policy",
              "content-security-policy"):
        assert h in r.headers
    assert client.get("/api/v1/meta").headers["cache-control"] == "no-store"


def test_login_rate_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    from app.core.redis import get_redis
    for k in get_redis().scan_iter("rl:*"):
        get_redis().delete(k)
    codes = [client.post("/api/v1/auth/login", json={"email": f"x{i}@example.com", "password": "nope"},
                         headers={"x-forwarded-for": "203.0.113.9"}).status_code for i in range(22)]
    assert codes[:20] == [401] * 20 and codes[-1] == 429
    assert client.post("/api/v1/auth/login", json={"email": "y@example.com", "password": "n"},
                       headers={"x-forwarded-for": "203.0.113.10"}).status_code == 401  # other IP fine


def test_production_guard(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "SECRET_KEY", "change-me-in-production-0123456789abcdef")
    monkeypatch.setattr(settings, "CREDENTIALS_ENCRYPTION_KEY", "")
    problems = middleware.validate_production_settings()
    assert len(problems) >= 3
    from app.main import create_app
    with pytest.raises(RuntimeError):
        create_app()


def test_credentials_encrypted_at_rest(api, smtp_sink):
    import sqlalchemy as sa

    from app.db.session import system_scope
    from tests.conftest import smtp_account
    smtp_account(api, smtp_sink.port, credentials={"host": "127.0.0.1", "port": smtp_sink.port,
                                                   "security": "none", "password": "TopSecret!"})
    with system_scope() as s:
        blob = s.scalar(sa.text("SELECT encrypted_credentials FROM sending_accounts WHERE workspace_id=:w"),
                        {"w": str(api.ws)})
    assert b"TopSecret" not in bytes(blob)


@pytest.mark.parametrize("method,path,role", [
    ("post", "/campaigns/00000000-0000-0000-0000-000000000000/approve", "marketer"),
    ("post", "/sending-accounts", "marketer"),
    ("get", "/audit-logs", "marketer"),
    ("post", "/companies", "analyst"),
    ("get", "/companies/export", "viewer"),
])
def test_role_matrix(client, api, method, path, role):
    from tests.conftest import api_with_role
    other = api_with_role(client, api.ws, role)
    r = getattr(other, method)(path, json={}) if method == "post" else other.get(path)
    assert r.status_code == 403
