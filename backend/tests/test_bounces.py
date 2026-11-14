"""Async bounce handling: VERP signing, DSN parsing, the inbound receiver and suppression."""
import smtplib
import socket
import uuid

import pytest
import sqlalchemy as sa

from app.providers import direct
from app.services import bounces

DSN = b"""From: Mail Delivery System <MAILER-DAEMON@mx.example.org>
To: {to}
Subject: Undelivered Mail Returned to Sender
Auto-Submitted: auto-replied
MIME-Version: 1.0
Content-Type: multipart/report; report-type=delivery-status; boundary="B"

--B
Content-Type: text/plain

Your message could not be delivered.

--B
Content-Type: message/delivery-status

Reporting-MTA: dns; mx.example.org

Final-Recipient: rfc822; {rcpt}
Action: failed
Status: {status}
Diagnostic-Code: smtp; 550 {status} mailbox unavailable

--B--
"""


def dsn(to, rcpt, status="5.1.1"):
    return DSN.replace(b"{to}", to.encode()).replace(b"{rcpt}", rcpt.encode()).replace(b"{status}", status.encode())


def test_verp_signed_roundtrip():
    rid = uuid.uuid4()
    addr = bounces.verp_address(rid, "news.primecfo.sa")
    assert addr.startswith("bounces+") and addr.endswith("@news.primecfo.sa")
    assert bounces.parse_verp(addr) == rid
    forged = addr.replace(addr.split(".")[1][:3], "zzz", 1)
    assert bounces.parse_verp(forged) is None
    assert bounces.parse_verp("bounces@news.primecfo.sa") is None


def test_parse_dsn():
    r = bounces.parse_dsn(dsn("x@y", "gone@gulf.sa"))
    assert r[0]["status"] == "5.1.1" and r[0]["recipient"] == "gone@gulf.sa" and r[0]["action"] == "failed"
    assert bounces.HARD.match("5.1.1") and not bounces.HARD.match("5.7.1")


@pytest.fixture
def receiver():
    from app.workers import bounce_server
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    ctl = bounce_server.build(host="127.0.0.1", port=port)
    ctl.start()
    yield port
    ctl.stop()


def test_late_bounce_suppresses_contact(api, smtp_sink, receiver, monkeypatch):
    from app.db.session import system_scope
    from app.models import SendingAccount, Suppression
    from app.models.enums import IdentityStatus
    from tests.test_phase78_campaigns_engine import CONSENT, make_campaign, recipients, setup_world

    w = setup_world(api, smtp_sink.port, n=1)
    a = api.post("/sending-accounts", json={
        "name": "Direct", "provider": "direct", "from_email": "info@gulf-demo.sa", "max_per_second": 50,
        "max_per_day": 10000, "credentials": {"warmup": False, "return_path_domain": "news.gulf-demo.sa"}}).json()
    with system_scope() as s:
        s.get(SendingAccount, a["id"]).verification_status = IdentityStatus.VERIFIED
    monkeypatch.setattr(direct, "mx_hosts", lambda d: ["127.0.0.1"])
    monkeypatch.setattr(direct, "SMTP_PORT", smtp_sink.port)
    api.post("/contacts", json={"company_id": w["company"], "email": "gone@gulf.sa", "job_title": "CFO", **CONSENT})
    c = make_campaign(api, w, sending_account_id=a["id"])
    api.post(f"/campaigns/{c['id']}/approve", json={})
    api.post(f"/campaigns/{c['id']}/send")
    sent = [m for m in smtp_sink.messages if m["to"] == ["gone@gulf.sa"]][-1]
    verp = sent["from"]
    assert verp.startswith("bounces+") and verp.endswith("@news.gulf-demo.sa")

    with smtplib.SMTP("127.0.0.1", receiver, timeout=10) as conn:
        with pytest.raises(smtplib.SMTPRecipientsRefused):        # not an open relay
            conn.sendmail("", ["someone@gmail.com"], b"Subject: x\r\n\r\nx")
        with pytest.raises(smtplib.SMTPRecipientsRefused):        # forged/unsigned bounce address
            conn.sendmail("", ["bounces@news.gulf-demo.sa"], b"Subject: x\r\n\r\nx")
        conn.sendmail("", [verp], dsn(verp, "gone@gulf.sa"))

    st = {r.email: r for r in recipients(c["id"])}
    assert st["gone@gulf.sa"].status.value == "bounced"
    assert st["user0@gulf.sa"].status.value == "sent"
    with system_scope() as s:
        assert s.scalar(sa.select(Suppression).where(Suppression.email == "gone@gulf.sa")) is not None
