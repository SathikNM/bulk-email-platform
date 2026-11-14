"""Mailbox: Sent log, reply capture through the inbound receiver, threads, replying from the platform."""
import smtplib
import socket

import pytest

from app.core.config import settings
from app.services import mailbox
from tests.conftest import smtp_account


@pytest.fixture
def inbound(monkeypatch):
    monkeypatch.setattr(settings, "INBOUND_DOMAIN", "news.primecfo-demo.com")
    monkeypatch.setattr(settings, "INBOUND_FORWARD_COPY", True)
    from app.workers import bounce_server
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    ctl = bounce_server.build(host="127.0.0.1", port=port)
    ctl.start()
    yield port
    ctl.stop()


def test_reply_address_signed(monkeypatch):
    import uuid
    monkeypatch.setattr(settings, "INBOUND_DOMAIN", "news.x.sa")
    mid = uuid.uuid4()
    a = mailbox.reply_address(mid)
    assert a.endswith("@news.x.sa") and mailbox.parse_reply_address(a) == mid
    assert mailbox.parse_reply_address(a.replace(a.split(".")[1][:2], "zz", 1)) is None
    monkeypatch.setattr(settings, "INBOUND_DOMAIN", "")
    assert mailbox.reply_address(mid) is None


def test_test_send_logged_in_sent_folder(api, smtp_sink):
    smtp_account(api, smtp_sink.port, reply_to="info@primecfo-demo.com")
    t = api.post("/templates", json={"name": "T", "subject": "Hi {{FirstName|there}}", "editor_type": "html",
                                     "html": "<p>Hello there</p>"}).json()
    r = api.post(f"/templates/{t['id']}/test-send", json={"to": ["a@example.org"]}).json()
    assert r["results"][0]["ok"]
    sent = api.get("/mailbox", params={"folder": "sent"}).json()
    assert sent["total"] == 1
    m = sent["items"][0]
    assert m["kind"] == "test" and m["status"] == "sent" and m["to_addr"] == "a@example.org"
    assert m["subject"].startswith("[TEST] Hi")
    # no capture domain configured: Reply-To stays the account's own reply-to, Message-ID matches the log
    got = smtp_sink.messages[-1]["msg"]
    assert got["Reply-To"] == "info@primecfo-demo.com"
    th = api.get(f"/mailbox/threads/{m['thread_id']}").json()
    assert got["Message-ID"] and th["messages"][0]["body_html"]


def test_reply_captured_threaded_forwarded_and_answered(api, smtp_sink, inbound):
    smtp_account(api, smtp_sink.port, reply_to="info@primecfo-demo.com")
    t = api.post("/templates", json={"name": "T", "subject": "Offer", "editor_type": "html",
                                     "html": "<p>Our offer</p>"}).json()
    api.post(f"/templates/{t['id']}/test-send", json={"to": ["client@example.org"]})
    out = smtp_sink.messages[-1]["msg"]
    reply_to = out["Reply-To"].addresses[0].addr_spec
    assert reply_to.startswith("replies+") and reply_to.endswith("@news.primecfo-demo.com")

    raw = (f"From: Client Person <client@example.org>\r\nTo: {reply_to}\r\nSubject: Re: [TEST] Offer\r\n"
           f"Message-ID: <r1@example.org>\r\nIn-Reply-To: {out['Message-ID']}\r\n\r\n"
           "Yes please, call me tomorrow.\r\n\r\nOn Mon, Prime CFO wrote:\r\n> Our offer\r\n").encode()
    with smtplib.SMTP("127.0.0.1", inbound, timeout=10) as c:
        c.sendmail("client@example.org", [reply_to], raw)

    s = api.get("/mailbox/summary").json()
    assert s["unread"] == 1 and s["reply_capture"] is True
    inbox = api.get("/mailbox", params={"folder": "inbox"}).json()
    msg = inbox["items"][0]
    assert msg["from_addr"] == "client@example.org" and msg["from_name"] == "Client Person"
    assert msg["preview"] == "Yes please, call me tomorrow." and msg["is_read"] is False
    # a copy went to the account's normal mailbox, reply-to = the client
    fwd = smtp_sink.messages[-1]
    assert fwd["to"] == ["info@primecfo-demo.com"] and fwd["msg"]["Reply-To"] == "client@example.org"

    th = api.get(f"/mailbox/threads/{msg['thread_id']}").json()
    assert [m["direction"] for m in th["messages"]] == ["out", "in"]
    assert api.get("/mailbox/summary").json()["unread"] == 0          # opening the thread marks it read

    r = api.post(f"/mailbox/{msg['id']}/reply", json={"body": "Great, 10am works.\nRegards"})
    assert r.status_code == 201 and r.json()["status"] == "sent" and r.json()["to_addr"] == "client@example.org"
    sent = smtp_sink.messages[-1]["msg"]
    assert sent["Subject"] == "Re: [TEST] Offer" and sent["In-Reply-To"] == "<r1@example.org>"
    assert sent["Reply-To"].addresses[0].addr_spec.startswith("replies+")
    th = api.get(f"/mailbox/threads/{msg['thread_id']}").json()
    assert [m["direction"] for m in th["messages"]] == ["out", "in", "out"]


def test_receiver_rejects_unknown_reply_tokens(api, inbound):
    with smtplib.SMTP("127.0.0.1", inbound, timeout=10) as c:
        with pytest.raises(smtplib.SMTPRecipientsRefused):
            c.sendmail("x@y.z", ["replies+00000000000000000000000000000000.abcdefghij@news.primecfo-demo.com"], b"x")
        with pytest.raises(smtplib.SMTPRecipientsRefused):
            c.sendmail("x@y.z", ["anyone@news.primecfo-demo.com"], b"x")
