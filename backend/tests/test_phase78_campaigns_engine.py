"""Phases 7-8: campaign workflow + bulk engine, tracking, unsubscribe, SES webhooks.

Emails are delivered over real SMTP to a local aiosmtpd server; nothing is mocked except
the network fetch of the SNS signing certificate (we sign with our own test certificate).
"""
import base64
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from app.db.session import system_scope
from app.models import CampaignRecipient, EmailEvent
from tests.conftest import api_with_role, smtp_account

CONSENT = {"consent_source": "Webinar", "consent_date": "2026-09-01T00:00:00Z"}


def setup_world(api, port, n=3, **acct):
    api.patch("/workspace", json={"legal_address": "King Fahd Rd, Riyadh, Saudi Arabia"})
    a = smtp_account(api, port, **acct)
    assert api.post(f"/sending-accounts/{a['id']}/verify").json()["ok"]
    co = api.post("/companies", json={"name": "Gulf Contracting", "city": "Riyadh", "country_code": "SA"}).json()["id"]
    ids = [api.post("/contacts", json={"company_id": co, "email": f"user{i}@gulf.sa", "first_name": f"User{i}",
                                       "job_title": "CFO", **CONSENT}).json()["id"] for i in range(n)]
    pending = api.post("/contacts", json={"company_id": co, "email": "pending@gulf.sa", "job_title": "CFO"}).json()["id"]
    seg = api.post("/segments", json={"name": f"CFOs {uuid.uuid4().hex[:4]}", "rules": {"op": "and", "rules": [
        {"field": "job_title", "operator": "eq", "value": "CFO"}]}}).json()["id"]
    tpl = api.post("/templates", json={
        "name": "Launch", "subject": "Hello {{FirstName|there}} from Prime CFO", "editor_type": "html",
        "html": '<p>Dear {{FirstName}},</p><p><a href="https://primecfo.sa/offer?x=1">See the offer</a></p>'}).json()["id"]
    return {"account": a, "company": co, "contacts": ids, "pending": pending, "segment": seg, "template": tpl}


def make_campaign(api, w, **kw):
    r = api.post("/campaigns", json={"name": "Q4 Launch", "segment_id": w["segment"], "template_id": w["template"], **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _prepare_only(campaign_id):
    """Snapshot recipients (scheduled -> sending) without enqueueing any batch."""
    from app.db.session import worker_session
    from app.services import sending
    db = worker_session(system=True)
    try:
        sending.prepare(db, uuid.UUID(campaign_id))
    finally:
        db.close()


def recipients(campaign_id):
    with system_scope() as s:
        return s.scalars(sa.select(CampaignRecipient).where(CampaignRecipient.campaign_id == campaign_id)
                         .order_by(CampaignRecipient.email)).all()


# ---------------- workflow ----------------

def test_validation_reports_problems(api, smtp_sink):
    api.patch("/workspace", json={"legal_address": None})
    c = api.post("/campaigns", json={"name": "Empty"}).json()
    v = api.post(f"/campaigns/{c['id']}/validate").json()
    assert v["ok"] is False
    joined = " ".join(v["errors"])
    for frag in ("Subject", "content", "sending account", "postal address", "audience"):
        assert frag.lower() in joined.lower()


def test_validation_counts_and_merge_warnings(api, smtp_sink):
    w = setup_world(api, smtp_sink.port)
    tpl = api.post("/templates", json={"name": "NoFallback", "subject": "Hi {{LastName}}", "editor_type": "html",
                                       "html": "<p>{{LastName}}</p>"}).json()["id"]
    c = make_campaign(api, w, template_id=tpl, subject=None)
    assert c["subject"] == "Hi {{LastName}}"  # copied from template
    v = api.post(f"/campaigns/{c['id']}/validate").json()
    assert v["ok"] is True, v
    assert v["audience"]["total_matched"] == 4 and v["audience"]["eligible"] == 3
    assert v["audience"]["excluded"]["not_subscribed"] == 1
    assert v["audience"]["missing_merge_fields"]["LastName"] == 3


def test_approval_rules(client, api, smtp_sink):
    w = setup_world(api, smtp_sink.port)
    c = make_campaign(api, w)
    marketer = api_with_role(client, api.ws, "marketer")
    assert marketer.post(f"/campaigns/{c['id']}/approve", json={}).status_code == 403
    assert api.post(f"/campaigns/{c['id']}/schedule",
                    json={"scheduled_at": "2030-01-01T09:00:00Z"}).status_code == 409  # not approved
    ap = api.post(f"/campaigns/{c['id']}/approve", json={})
    assert ap.status_code == 200 and ap.json()["is_approved"]
    snap = ap.json()["html_snapshot"]
    assert "{{__L:" in snap and "primecfo.sa/offer" not in snap and "King Fahd Rd" in snap
    upd = api.patch(f"/campaigns/{c['id']}", json={"subject": "Changed"}).json()
    assert upd["is_approved"] is False  # edits invalidate approval
    api.post(f"/campaigns/{c['id']}/approve", json={"scheduled_at": "2030-01-01T09:00:00Z"})
    got = api.get(f"/campaigns/{c['id']}").json()
    assert got["status"] == "scheduled"
    assert api.patch(f"/campaigns/{c['id']}", json={"name": "x"}).status_code == 409
    assert api.post(f"/campaigns/{c['id']}/resume").status_code == 409
    assert api.post(f"/campaigns/{c['id']}/pause").json()["status"] == "paused"
    assert api.post(f"/campaigns/{c['id']}/cancel").json()["status"] == "cancelled"
    assert api.post(f"/campaigns/{c['id']}/pause").status_code == 409  # cancelled is terminal


def test_unverified_account_blocks_approval(api, smtp_sink):
    w = setup_world(api, smtp_sink.port)
    bad = api.post("/sending-accounts", json={"name": "Unverified", "provider": "smtp",
                                              "from_email": "x@other-demo.com",
                                              "credentials": {"host": "127.0.0.1", "port": 1, "security": "none"}})
    c = make_campaign(api, w, sending_account_id=bad.json()["id"])
    r = api.post(f"/campaigns/{c['id']}/approve", json={})
    assert r.status_code == 400 and any("not verified" in e for e in r.json()["errors"])


# ---------------- sending ----------------

def test_send_now_end_to_end(api, smtp_sink):
    w = setup_world(api, smtp_sink.port)
    c = make_campaign(api, w)
    api.post(f"/campaigns/{c['id']}/approve", json={})
    r = api.post(f"/campaigns/{c['id']}/send")
    assert r.status_code == 200, r.text
    got = api.get(f"/campaigns/{c['id']}").json()
    assert got["status"] == "completed", got
    assert got["stats"]["sent"] == 3 and got["stats"]["recipients"] == 3
    assert sorted(m["to"][0] for m in smtp_sink.messages) == ["user0@gulf.sa", "user1@gulf.sa", "user2@gulf.sa"]
    m = next(x["msg"] for x in smtp_sink.messages if x["to"][0] == "user1@gulf.sa")
    assert m["Subject"] == "Hello User1 from Prime CFO"
    assert m["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert re.match(r"<http://localhost:8000/u/[^>]+>", m["List-Unsubscribe"])
    html = next(p for p in m.walk() if p.get_content_type() == "text/html").get_content()
    assert "Dear User1" in html and "/t/c/" in html and "/t/o/" in html and "primecfo.sa/offer" not in html
    assert all(r.status.value == "sent" and r.provider_message_id for r in recipients(c["id"]))
    with system_scope() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(EmailEvent).where(
            EmailEvent.campaign_id == c["id"], EmailEvent.event_type == "send")) == 3


def test_no_duplicate_sends_on_rerun(api, smtp_sink):
    from app.workers.tasks import prepare_campaign, send_batch
    w = setup_world(api, smtp_sink.port)
    c = make_campaign(api, w, manual_contact_ids=[w["contacts"][0]])  # also in the segment -> deduplicated
    api.post(f"/campaigns/{c['id']}/approve", json={})
    api.post(f"/campaigns/{c['id']}/send")
    assert len(smtp_sink.messages) == 3
    prepare_campaign(c["id"], str(api.ws))
    send_batch(c["id"], str(api.ws))
    send_batch(c["id"], str(api.ws))
    assert len(smtp_sink.messages) == 3
    assert len(recipients(c["id"])) == 3


def test_suppression_rechecked_at_send_time(api, smtp_sink):
    from app.workers.tasks import send_batch
    w = setup_world(api, smtp_sink.port)
    c = make_campaign(api, w)
    api.post(f"/campaigns/{c['id']}/approve", json={"scheduled_at": "2030-01-01T09:00:00Z"})
    _prepare_only(c["id"])
    assert len(recipients(c["id"])) == 3
    api.post(f"/contacts/{w['contacts'][1]}/unsubscribe", json={})
    send_batch(c["id"], str(api.ws))
    statuses = {r.email: r.status.value for r in recipients(c["id"])}
    assert statuses["user1@gulf.sa"] == "skipped_suppressed"
    assert len(smtp_sink.messages) == 2
    assert api.get(f"/campaigns/{c['id']}").json()["status"] == "completed"


def test_transient_and_permanent_failures(api, smtp_sink):
    w = setup_world(api, smtp_sink.port, n=1)
    busy = api.post("/contacts", json={"company_id": w["company"], "email": "busy@gulf.sa", "job_title": "CFO",
                                       **CONSENT}).json()["id"]
    rej = api.post("/contacts", json={"company_id": w["company"], "email": "reject@gulf.sa", "job_title": "CFO",
                                      **CONSENT}).json()["id"]
    assert busy and rej
    c = make_campaign(api, w)
    api.post(f"/campaigns/{c['id']}/approve", json={})
    api.post(f"/campaigns/{c['id']}/send")
    st = {r.email: r for r in recipients(c["id"])}
    assert st["user0@gulf.sa"].status.value == "sent"
    assert st["reject@gulf.sa"].status.value == "failed" and "550" in st["reject@gulf.sa"].last_error
    b = st["busy@gulf.sa"]
    assert b.status.value == "queued" and b.attempts == 1 and b.next_attempt_at > datetime.now(timezone.utc)
    assert api.get(f"/campaigns/{c['id']}").json()["status"] == "sending"  # retry pending


def test_daily_limit_defers_remaining(api, smtp_sink):
    w = setup_world(api, smtp_sink.port, n=3, max_per_day=2)
    c = make_campaign(api, w)
    api.post(f"/campaigns/{c['id']}/approve", json={})
    api.post(f"/campaigns/{c['id']}/send")
    assert len(smtp_sink.messages) == 2
    got = api.get(f"/campaigns/{c['id']}").json()
    assert got["status"] == "sending" and got["stats"]["queued"] == 1


def test_pause_stops_and_resume_finishes(api, smtp_sink):
    w = setup_world(api, smtp_sink.port)
    c = make_campaign(api, w)
    api.post(f"/campaigns/{c['id']}/approve", json={"scheduled_at": "2030-01-01T09:00:00Z"})
    _prepare_only(c["id"])
    assert api.post(f"/campaigns/{c['id']}/pause").json()["status"] == "paused"
    from app.workers.tasks import send_batch
    assert send_batch(c["id"], str(api.ws))["stop"] is True
    assert smtp_sink.messages == []
    assert api.post(f"/campaigns/{c['id']}/resume").status_code == 200
    assert len(smtp_sink.messages) == 3 and api.get(f"/campaigns/{c['id']}").json()["status"] == "completed"


def test_scheduled_dispatch(api, smtp_sink):
    from app.workers.tasks import dispatch_due_campaigns
    w = setup_world(api, smtp_sink.port)
    c = make_campaign(api, w)
    api.post(f"/campaigns/{c['id']}/approve", json={"scheduled_at": "2030-01-01T09:00:00Z"})
    assert dispatch_due_campaigns() == 0 or smtp_sink.messages == []
    with system_scope() as s:
        s.execute(sa.text("UPDATE campaigns SET scheduled_at = now() - interval '1 minute' WHERE id = :i"),
                  {"i": c["id"]})
    dispatch_due_campaigns()
    assert len(smtp_sink.messages) == 3
    assert api.get(f"/campaigns/{c['id']}").json()["status"] == "completed"


def test_duplicate_campaign(api, smtp_sink):
    w = setup_world(api, smtp_sink.port)
    c = make_campaign(api, w)
    api.post(f"/campaigns/{c['id']}/approve", json={})
    api.post(f"/campaigns/{c['id']}/send")
    d = api.post(f"/campaigns/{c['id']}/duplicate").json()
    assert d["status"] == "draft" and d["is_approved"] is False and d["duplicated_from"] == c["id"]
    assert api.get("/campaigns?status=completed").json()["total"] == 1


# ---------------- tracking & unsubscribe ----------------

def _sent_campaign(api, smtp_sink):
    w = setup_world(api, smtp_sink.port)
    c = make_campaign(api, w)
    api.post(f"/campaigns/{c['id']}/approve", json={})
    api.post(f"/campaigns/{c['id']}/send")
    with system_scope() as s:
        s.execute(sa.text("UPDATE campaign_recipients SET sent_at = now() - interval '1 hour' "
                          "WHERE campaign_id = :i"), {"i": c["id"]})
    m = next(x["msg"] for x in smtp_sink.messages if x["to"][0] == "user0@gulf.sa")
    html = next(p for p in m.walk() if p.get_content_type() == "text/html").get_content()
    return w, c, m, html


UA = {"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}


def test_open_click_tracking(api, smtp_sink):
    w, c, m, html = _sent_campaign(api, smtp_sink)
    pixel = re.search(r'src="http://localhost:8000(/t/o/[^"]+)"', html).group(1)
    link = re.search(r'href="http://localhost:8000(/t/c/[^"]+)"', html).group(1)
    r = api.c.get(pixel, headers=UA)
    assert r.status_code == 200 and r.headers["content-type"] == "image/gif"
    r = api.c.get(link, headers=UA, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "https://primecfo.sa/offer?x=1"
    assert api.c.get(link[:-3] + "AAA", follow_redirects=False).status_code == 404  # tampered
    stats = api.get(f"/campaigns/{c['id']}").json()["stats"]
    assert stats["unique_opens"] == 1 and stats["unique_clicks"] == 1 and stats["open_rate"] == 33.33
    links = api.get(f"/campaigns/{c['id']}/links").json()
    assert links == [{"url": "https://primecfo.sa/offer?x=1", "clicks": 1, "unique_clicks": 1}]
    api.c.get(pixel, headers={"user-agent": "Barracuda scanner"})  # machine open not counted
    assert api.get(f"/campaigns/{c['id']}").json()["stats"]["unique_opens"] == 1


def test_unsubscribe_page_and_one_click(api, smtp_sink):
    w, c, m, html = _sent_campaign(api, smtp_sink)
    unsub = re.match(r"<http://localhost:8000(/u/[^>]+)>", m["List-Unsubscribe"]).group(1)
    page = api.c.get(unsub)
    assert page.status_code == 200 and "user0@gulf.sa" in page.text and "<form method='post'>" in page.text
    assert api.get(f"/contacts/{w['contacts'][0]}").json()["subscription_status"] == "subscribed"  # GET is safe
    r = api.c.post(unsub, content="List-Unsubscribe=One-Click",
                   headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200
    contact = api.get(f"/contacts/{w['contacts'][0]}").json()
    assert contact["subscription_status"] == "unsubscribed" and contact["suppressed"] == "unsubscribe"
    assert api.get(f"/campaigns/{c['id']}").json()["stats"]["unsubscribes"] == 1
    assert api.c.post("/u/bogus.token").status_code == 200  # friendly page, no crash


# ---------------- SES webhook ----------------

@pytest.fixture
def sns_signer(monkeypatch):
    from app.services import events
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sns.amazonaws.com")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1)).sign(key, hashes.SHA256()))
    pem = cert.public_bytes(serialization.Encoding.PEM)
    monkeypatch.setattr(events, "fetch_cert", lambda url: pem)

    def sign(event: dict, msg_id=None, cert_url="https://sns.eu-west-1.amazonaws.com/cert.pem") -> dict:
        msg = {"Type": "Notification", "MessageId": msg_id or str(uuid.uuid4()),
               "TopicArn": "arn:aws:sns:eu-west-1:123:ses-events", "Message": json.dumps(event),
               "Timestamp": datetime.now(timezone.utc).isoformat(), "SignatureVersion": "2",
               "SigningCertURL": cert_url}
        canonical = "".join(f"{k}\n{msg[k]}\n" for k in ["Message", "MessageId", "Timestamp", "TopicArn", "Type"])
        msg["Signature"] = base64.b64encode(key.sign(canonical.encode(), padding.PKCS1v15(), hashes.SHA256())).decode()
        return msg
    return sign


def test_ses_bounce_complaint_delivery(api, smtp_sink, sns_signer):
    w, c, m, html = _sent_campaign(api, smtp_sink)
    recs = {r.email: r for r in recipients(c["id"])}

    def post(ev, **kw):
        return api.c.post("/webhooks/ses", content=json.dumps(sns_signer(ev, **kw)))
    bounce = {"eventType": "Bounce", "bounce": {"bounceType": "Permanent"},
              "mail": {"messageId": recs["user0@gulf.sa"].provider_message_id}}
    mid = str(uuid.uuid4())
    assert post(bounce, msg_id=mid).json()["status"] == "bounce_hard"
    assert post(bounce, msg_id=mid).json()["status"] == "duplicate"
    assert post({"notificationType": "Complaint",
                 "mail": {"messageId": recs["user1@gulf.sa"].provider_message_id}}).json()["status"] == "complaint"
    assert post({"eventType": "Delivery",
                 "mail": {"messageId": recs["user2@gulf.sa"].provider_message_id}}).json()["status"] == "delivery"
    after = {r.email: r.status.value for r in recipients(c["id"])}
    assert after == {"user0@gulf.sa": "bounced", "user1@gulf.sa": "complained", "user2@gulf.sa": "delivered"}
    sup = {s["email"]: s["reason"] for s in api.get("/suppressions").json()["items"]}
    assert sup == {"user0@gulf.sa": "hard_bounce", "user1@gulf.sa": "complaint"}
    assert api.get(f"/contacts/{w['contacts'][0]}").json()["email_verification_status"] == "invalid"
    stats = api.get(f"/campaigns/{c['id']}").json()["stats"]
    assert stats["bounced"] == 1 and stats["complained"] == 1 and stats["bounce_rate"] == 33.33


def test_ses_webhook_rejects_forgeries(api, sns_signer):
    good = sns_signer({"eventType": "Delivery", "mail": {"messageId": "x"}})
    tampered = {**good, "Message": json.dumps({"eventType": "Complaint", "mail": {"messageId": "x"}})}
    assert api.c.post("/webhooks/ses", content=json.dumps(tampered)).status_code == 403
    evil = sns_signer({"eventType": "Delivery", "mail": {"messageId": "x"}}, cert_url="https://evil.example.com/c.pem")
    assert api.c.post("/webhooks/ses", content=json.dumps(evil)).status_code == 403
    assert api.c.post("/webhooks/ses", content=json.dumps(good)).json()["status"] == "ignored: unknown message"
