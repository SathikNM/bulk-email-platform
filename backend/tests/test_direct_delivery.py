"""Built-in direct delivery: DKIM signing, MX delivery, bounce classification, warm-up, API."""
from datetime import datetime, timedelta, timezone

import dkim
import pytest

from app.providers import direct
from app.providers.base import OutgoingEmail, PermanentError, TransientError
from app.providers.direct import DirectProvider, HardBounce, dkim_public_record, generate_dkim_key, warmup_limit


@pytest.fixture(scope="module")
def key():
    return generate_dkim_key()


def _provider(key, port, monkeypatch):
    monkeypatch.setattr(direct, "mx_hosts", lambda d: ["127.0.0.1"])
    return DirectProvider("primecfo-demo.com", "mail.primecfo-demo.com", "bep", key, timeout=5, port=port)


def _mail(to):
    return OutgoingEmail(from_email="info@primecfo-demo.com", to=to, subject="Hello", html="<p>Hi</p>",
                         text="Hi", from_name="Prime CFO", headers={"List-Unsubscribe": "<https://x/u>"})


def test_delivers_dkim_signed_message(key, smtp_sink, monkeypatch):
    p = _provider(key, smtp_sink.port, monkeypatch)
    mid = p.send(_mail("someone@example.org"))
    p.close()
    assert mid and smtp_sink.messages
    raw = smtp_sink.messages[-1]["raw"]
    assert raw.startswith(b"DKIM-Signature:")
    pub = dkim_public_record(key).encode()
    assert dkim.verify(raw, dnsfunc=lambda name, timeout=5: pub)


def test_bounce_classification(key, smtp_sink, monkeypatch):
    p = _provider(key, smtp_sink.port, monkeypatch)
    with pytest.raises(HardBounce):
        p.send(_mail("reject-me@example.org"))
    with pytest.raises(TransientError):
        p.send(_mail("busy@example.org"))
    p.close()
    assert isinstance(direct._classify(550, "5.7.1 Message rejected as spam", "x"), PermanentError)
    assert not isinstance(direct._classify(550, "5.7.1 Message rejected as spam", "x"), HardBounce)


def test_unreachable_mx_is_transient(key, monkeypatch):
    monkeypatch.setattr(direct, "mx_hosts", lambda d: ["127.0.0.1"])
    p = DirectProvider("primecfo-demo.com", None, "bep", key, timeout=2, port=1)
    with pytest.raises(TransientError):
        p.send(_mail("a@example.org"))


def test_warmup_schedule():
    now = datetime.now(timezone.utc)
    assert warmup_limit(now, now) == 50
    assert warmup_limit(now - timedelta(days=9), now) == 1000
    assert warmup_limit(now - timedelta(days=23), now) == 10000
    assert warmup_limit(now - timedelta(days=60), now) is None
    assert warmup_limit(None) is None


def test_direct_account_api(api, monkeypatch):
    r = api.post("/sending-accounts", json={"name": "Direct", "provider": "direct", "from_email": "info@primecfo-demo.com",
                                            "max_per_second": 2, "max_per_day": 10000})
    assert r.status_code == 201, r.text
    a = r.json()
    h = a["credentials_hint"]
    assert h["dkim_private_key"] == "••••" and h["helo_hostname"] == "mail.primecfo-demo.com" and h["dkim_selector"] == "bep"
    assert a["warmup_active"] is True and a["warmup_limit_today"] == 50

    monkeypatch.setattr(DirectProvider, "public_ip", staticmethod(lambda: "203.0.113.7"))
    monkeypatch.setattr(direct, "_txt", lambda name: ["v=spf1 include:spf.protection.outlook.com -all"]
                        if name == "primecfo-demo.com" else [])
    monkeypatch.setattr(direct, "_resolver", lambda: (_ for _ in ()).throw(OSError("offline")))
    import smtplib
    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: (_ for _ in ()).throw(OSError("blocked")))
    v = api.post(f"/sending-accounts/{a['id']}/verify").json()
    assert v["ok"] is False and "PTR" in v["error"]
    recs = {r["name"]: r["value"] for r in v["dns_records"]}
    assert recs["primecfo-demo.com"] == "v=spf1 ip4:203.0.113.7 include:spf.protection.outlook.com -all"
    assert recs["bep._domainkey.primecfo-demo.com"].startswith("v=DKIM1; k=rsa; p=")
    assert recs["mail.primecfo-demo.com"] == "203.0.113.7"

    old = recs["bep._domainkey.primecfo-demo.com"]
    assert api.post(f"/sending-accounts/{a['id']}/rotate-dkim").status_code == 200
    v2 = api.post(f"/sending-accounts/{a['id']}/verify").json()
    assert {r["name"]: r["value"] for r in v2["dns_records"]}["bep._domainkey.primecfo-demo.com"] != old


def test_campaign_via_direct_delivery_suppresses_hard_bounce(api, smtp_sink, monkeypatch):
    import sqlalchemy as sa

    from app.db.session import system_scope
    from app.models import SendingAccount, Suppression
    from app.models.enums import IdentityStatus
    from tests.test_phase78_campaigns_engine import CONSENT, make_campaign, recipients, setup_world

    w = setup_world(api, smtp_sink.port, n=2)
    a = api.post("/sending-accounts", json={"name": "Direct", "provider": "direct", "from_email": "info@gulf-demo.sa",
                                            "max_per_second": 50, "max_per_day": 10000,
                                            "credentials": {"warmup": False}}).json()
    with system_scope() as s:
        s.get(SendingAccount, a["id"]).verification_status = IdentityStatus.VERIFIED
    monkeypatch.setattr(direct, "mx_hosts", lambda d: ["127.0.0.1"])
    monkeypatch.setattr(direct, "SMTP_PORT", smtp_sink.port)
    api.post("/contacts", json={"company_id": w["company"], "email": "reject@gulf.sa", "job_title": "CFO", **CONSENT})
    c = make_campaign(api, w, sending_account_id=a["id"])
    assert api.post(f"/campaigns/{c['id']}/approve", json={}).status_code == 200
    api.post(f"/campaigns/{c['id']}/send")
    st = {r.email: r for r in recipients(c["id"])}
    assert st["user0@gulf.sa"].status.value == "sent", st["user0@gulf.sa"].last_error
    assert st["reject@gulf.sa"].status.value == "bounced"
    with system_scope() as s:
        assert s.scalar(sa.select(Suppression).where(Suppression.email == "reject@gulf.sa")) is not None
    sent = [m for m in smtp_sink.messages if m["to"] == ["user0@gulf.sa"]][-1]
    assert sent["raw"].startswith(b"DKIM-Signature:") and sent["from"] == "info@gulf-demo.sa"
