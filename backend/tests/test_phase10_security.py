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


def test_two_factor_login(client, api):
    import time

    from app.core import totp
    from app.core.redis import get_redis
    me = api.get("/auth/me").json()
    assert me["totp_enabled"] is False
    s = api.post("/auth/2fa/setup").json()
    assert s["otpauth_uri"].startswith("otpauth://totp/") and s["secret"] in s["otpauth_uri"]
    assert api.post("/auth/2fa/enable", json={"code": "000000"}).status_code == 400
    assert api.post("/auth/2fa/enable", json={"code": totp.now_code(s["secret"])}).status_code == 204
    assert api.get("/auth/me").json()["totp_enabled"] is True

    email, pw = me["email"], "Str0ng!Passw0rd"
    r = client.post("/api/v1/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 401 and r.json().get("otp_required") is True
    assert client.post("/api/v1/auth/login", json={"email": email, "password": pw, "otp": "123456"}).status_code == 401
    get_redis().delete(f"login_fail:{email.lower()}")
    code = totp.now_code(s["secret"], time.time() + 30)        # next step (still within the window)
    assert client.post("/api/v1/auth/login", json={"email": email, "password": pw, "otp": code}).status_code == 200
    # the same code cannot be replayed
    assert client.post("/api/v1/auth/login", json={"email": email, "password": pw, "otp": code}).status_code == 401
    get_redis().delete(f"login_fail:{email.lower()}")
    code2 = totp.now_code(s["secret"], time.time() - 30)
    assert api.post("/auth/2fa/disable", json={"code": code2, "password": pw}).status_code == 204
    assert api.get("/auth/me").json()["totp_enabled"] is False


def test_totp_rfc6238_vector():
    import base64

    from app.core import totp
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert totp._code(secret, 59 // 30) == "287082"          # RFC 6238 appendix B (SHA1, 6 digits)
    assert totp._code(secret, 1111111109 // 30) == "081804"
