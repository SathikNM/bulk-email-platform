"""Phase 9: analytics KPIs reconcile with raw email_events / recipients."""
import json
import re
import uuid
from datetime import date

import sqlalchemy as sa

from app.db.session import system_scope
from tests.test_phase78_campaigns_engine import UA, _sent_campaign, recipients, sns_signer  # noqa: F401


def test_kpis_trends_and_reconciliation(api, smtp_sink, sns_signer):  # noqa: F811
    w, c, m, html = _sent_campaign(api, smtp_sink)
    pixel = re.search(r'src="http://localhost:8000(/t/o/[^"]+)"', html).group(1)
    link = re.search(r'href="http://localhost:8000(/t/c/[^"]+)"', html).group(1)
    api.c.get(pixel, headers=UA)
    api.c.get(pixel, headers=UA)  # second open by same person: unique stays 1
    api.c.get(link, headers=UA, follow_redirects=False)
    recs = {r.email: r for r in recipients(c["id"])}
    api.c.post("/webhooks/ses", content=json.dumps(sns_signer(
        {"eventType": "Bounce", "bounce": {"bounceType": "Permanent"},
         "mail": {"messageId": recs["user2@gulf.sa"].provider_message_id}})))
    api.c.post("/webhooks/ses", content=json.dumps(sns_signer(
        {"eventType": "Delivery", "mail": {"messageId": recs["user1@gulf.sa"].provider_message_id}})))
    assert api.post("/analytics/refresh").json()["campaigns_refreshed"] == 1

    o = api.get("/analytics/overview").json()
    assert (o["total_companies"], o["total_contacts"], o["eligible_subscribers"]) == (1, 4, 2)
    assert o["total_campaigns"] == 1 and o["emails_sent"] == 3 and o["emails_delivered"] == 1
    assert o["bounces"] == 1 and o["bounce_rate"] == 33.33
    assert o["unique_opens"] == 1 and o["open_rate"] == 33.33 and o["click_rate"] == 33.33
    assert o["click_to_open_rate"] == 100.0

    t = api.get("/analytics/trends").json()
    assert len(t) == 30 and t[-1]["date"] == date.today().isoformat()
    today = t[-1]
    with system_scope() as s:
        raw = dict(s.execute(sa.text("SELECT event_type::text, count(*) FROM email_events WHERE campaign_id=:c "
                                     "GROUP BY 1"), {"c": c["id"]}).all())
    assert today["sent"] == raw["send"] == 3
    assert today["opened"] == raw["open"] == 2 and today["unique_opened"] == 1
    assert today["clicked"] == raw["click"] == 1 and today["bounced"] == raw["bounce_hard"] == 1

    camp = api.get("/analytics/campaigns").json()
    assert camp[0]["id"] == c["id"] and camp[0]["sent"] == 3 and camp[0]["unique_clicks"] == 1
    other = api.get("/analytics/overview", params={"campaign_id": str(uuid.uuid4())}).json()
    assert other["emails_sent"] == 0
    old = api.get("/analytics/overview", params={"date_from": "2020-01-01", "date_to": "2020-01-31"}).json()
    assert old["emails_sent"] == 0 and old["total_contacts"] == 4

    d = {x["status"]: x["count"] for x in api.get("/analytics/delivery").json()}
    assert d["sent"] == 1 and d["delivered"] == 1 and d["bounced"] == 1
    weekly = api.get("/analytics/trends?interval=week").json()
    assert sum(x["sent"] for x in weekly) == 3


def test_distribution_and_growth(api):
    ind = {i["name"]: i["id"] for i in api.get("/industries").json()}
    a = api.post("/companies", json={"name": "A", "industry_id": ind["Construction"], "country_code": "SA"}).json()["id"]
    b = api.post("/companies", json={"name": "B", "industry_id": ind["Retail"], "country_code": "AE"}).json()["id"]
    for i in range(3):
        api.post("/contacts", json={"company_id": a, "email": f"a{i}@a.sa"})
    api.post("/contacts", json={"company_id": b, "email": "b@b.ae", "country_code": "QA"})
    by_ind = {x["label"]: x["count"] for x in api.get("/analytics/distribution?by=industry").json()}
    assert by_ind == {"Construction": 3, "Retail": 1}
    by_cc = {x["label"]: x["count"] for x in api.get("/analytics/distribution?by=country").json()}
    assert by_cc == {"SA": 3, "QA": 1}  # contact country overrides company country
    g = api.get("/analytics/audience-growth").json()
    assert g[-1]["contacts_added"] == 4 and g[-1]["total_contacts"] == 4
