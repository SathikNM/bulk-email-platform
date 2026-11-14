"""Phase 4: contacts, consent, unsubscribe/suppression, contact import, bulk ops, verification."""
import json

import pytest

from app.models.enums import VerificationStatus
from app.services import verification


def _company(api, name="Acme Construction", **kw):
    return api.post("/companies", json={"name": name, **kw}).json()["id"]


def _contact(api, company_id, email, **kw):
    r = api.post("/contacts", json={"company_id": company_id, "email": email, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_contact_defaults_pending_without_consent(api):
    c = _contact(api, _company(api), "cfo@acme.sa", first_name="Sara", last_name="Al-Qahtani",
                 job_title="CFO", department="Finance")
    assert c["subscription_status"] == "pending" and c["consents"] == []
    assert c["full_name"] == "Sara Al-Qahtani" and c["company_name"] == "Acme Construction"


def test_contact_with_consent_is_subscribed_and_recorded(api):
    c = _contact(api, _company(api), "fm@acme.sa", consent_source="Webinar signup form",
                 consent_date="2026-10-01T09:00:00Z")
    assert c["subscription_status"] == "subscribed"
    assert c["consents"][0]["lawful_basis"] == "explicit_consent"


def test_multiple_contacts_per_company_and_duplicate_email(api):
    co = _company(api)
    _contact(api, co, "a@acme.sa")
    _contact(api, co, "b@acme.sa")
    assert api.get(f"/companies/{co}").json()["contact_count"] == 2
    r = api.post("/contacts", json={"company_id": co, "email": "A@ACME.SA"})
    assert r.status_code == 409
    assert api.get("/contacts/check-email", params={"email": "a@acme.sa"}).json()["exists"] is True


def test_contact_requires_existing_company(api):
    import uuid
    r = api.post("/contacts", json={"company_id": str(uuid.uuid4()), "email": "x@y.com"})
    assert r.status_code == 404


def test_search_and_filters(api):
    co1 = _company(api, "Riyadh Builders")
    co2 = _company(api, "Jeddah Foods")
    _contact(api, co1, "cfo@rb.sa", first_name="Omar", job_title="CFO", department="Finance")
    _contact(api, co1, "fm@rb.sa", first_name="Lina", job_title="Finance Manager", department="Finance")
    _contact(api, co2, "ops@jf.sa", first_name="Ali", job_title="COO", department="Operations")
    assert api.get("/contacts?q=omar").json()["total"] == 1
    assert api.get("/contacts?q=jeddah").json()["total"] == 1          # by company name
    assert api.get("/contacts?q=finance manager").json()["total"] == 1  # by position
    assert api.get("/contacts?department=finance").json()["total"] == 2
    r = api.get("/contacts", params=[("job_title", "CFO"), ("job_title", "Finance Manager")])
    assert r.json()["total"] == 2
    assert api.get(f"/contacts?company_id={co2}").json()["total"] == 1
    f = api.get("/contacts/facets").json()
    assert f["departments"] == ["Finance", "Operations"]


def test_unsubscribe_adds_suppression_and_blocks_reconsent(api):
    c = _contact(api, _company(api), "u@acme.sa", consent_source="form", consent_date="2026-01-01T00:00:00Z")
    r = api.post(f"/contacts/{c['id']}/unsubscribe", json={"reason": "asked by phone"})
    assert r.json()["subscription_status"] == "unsubscribed" and r.json()["suppressed"] == "manual"
    assert r.json()["consents"][0]["withdrawn_at"] is not None
    assert api.post(f"/contacts/{c['id']}/consents",
                    json={"lawful_basis": "explicit_consent", "source": "form"}).status_code == 409
    # New contact with a suppressed address starts unsubscribed even with consent
    api.delete(f"/contacts/{c['id']}")
    c2 = _contact(api, _company(api, "Other"), "u@acme.sa", consent_source="x", consent_date="2026-01-01T00:00:00Z")
    assert c2["subscription_status"] == "unsubscribed"


def test_suppression_admin_flow(client, api):
    from tests.conftest import api_with_role
    r = api.post("/suppressions", json={"email": "bounce@x.com", "reason": "hard_bounce"})
    assert r.status_code == 201
    assert api.get("/suppressions?q=bounce").json()["total"] == 1
    marketer = api_with_role(client, api.ws, "marketer")
    assert marketer.post("/suppressions", json={"email": "m@x.com"}).status_code == 403
    sid = r.json()["id"]
    assert api.c.request("DELETE", f"/api/v1/suppressions/{sid}", headers=api.h,
                         json={"justification": "no"}).status_code == 422
    assert api.c.request("DELETE", f"/api/v1/suppressions/{sid}", headers=api.h,
                         json={"justification": "address recycled, confirmed by client"}).status_code == 204
    api.post("/suppressions", json={"email": "spam@x.com", "reason": "complaint"})
    sid2 = api.get("/suppressions?q=spam").json()["items"][0]["id"]
    assert api.c.request("DELETE", f"/api/v1/suppressions/{sid2}", headers=api.h,
                         json={"justification": "please remove this one"}).status_code == 409


def test_bulk_tag_category_unsubscribe(api):
    co = _company(api)
    ids = [_contact(api, co, f"b{i}@acme.sa")["id"] for i in range(3)]
    tag = api.post("/tags", json={"name": "Q4"}).json()["id"]
    r = api.post("/contacts/bulk", json={"contact_ids": ids, "add_tag_ids": [tag], "department": "Finance"})
    assert r.json() == {"affected": 3}
    assert api.get(f"/contacts?tag_id={tag}").json()["total"] == 3
    api.post("/contacts/bulk", json={"contact_ids": ids[:1], "unsubscribe": True})
    assert api.get("/contacts?subscription_status=unsubscribed").json()["total"] == 1


def test_contact_import_with_consent_mapping(api):
    api.post("/suppressions", json={"email": "suppressed@gulf.sa"})
    csv_data = (
        "Email,First Name,Last Name,Title,Company,Country,Consent Source,Consent Date,Tags\n"
        "cfo@gulf.sa,Huda,Saleh,CFO,Gulf Contracting,Saudi Arabia,Event badge scan,2026-09-15,VIP\n"
        "fm@gulf.sa,Faisal,Nasser,Finance Manager,Gulf Contracting,SA,,,\n"
        "info@gulf.sa,,,,Gulf Contracting,SA,Website form,15/09/2026,\n"
        "suppressed@gulf.sa,S,P,CEO,Gulf Contracting,SA,form,2026-09-15,\n"
        "not-an-email,X,Y,Z,Gulf Contracting,SA,,,\n"
        "cfo@gulf.sa,Dup,Row,CFO,Gulf Contracting,SA,,,\n"
    ).encode()
    files = {"file": ("contacts.csv", csv_data, "text/csv")}
    pv = api.post("/imports/preview", data={"entity": "contact"}, files=files).json()
    m = pv["suggested_mapping"]
    assert m["Email"] == "email" and m["Title"] == "job_title" and m["Company"] == "company_name"
    r = api.post("/imports", data={"entity": "contact", "column_mapping": json.dumps(m)}, files=files)
    job = api.get(f"/imports/{r.json()['id']}").json()
    assert job["status"] == "completed", job
    assert (job["inserted"], job["skipped"]) == (4, 2)
    assert {e["row"] for e in job["errors"]} == {6, 7}
    assert job["options"]["role_accounts"] == 1
    by_email = {c["email"]: c for c in api.get("/contacts?page_size=50").json()["items"]}
    assert by_email["cfo@gulf.sa"]["subscription_status"] == "subscribed"
    assert by_email["fm@gulf.sa"]["subscription_status"] == "pending"
    assert by_email["info@gulf.sa"]["is_role_account"] is True
    assert by_email["suppressed@gulf.sa"]["subscription_status"] == "unsubscribed"
    assert api.get("/companies?q=gulf contracting").json()["total"] == 1


def test_contact_export(api):
    _contact(api, _company(api), "exp@acme.sa", first_name="محمد", last_name="العتيبي")
    r = api.get("/contacts/export?format=csv")
    assert "exp@acme.sa" in r.text and "محمد" in r.text


def test_duplicates_report(api):
    co = _company(api)
    _contact(api, co, "john.smith@acme.sa", first_name="John", last_name="Smith")
    _contact(api, co, "jsmith@acme.sa", first_name="John", last_name="Smith")
    _contact(api, co, "johnsmith+news@acme.sa")
    reasons = {d["reason"] for d in api.get("/contacts/duplicates").json()}
    assert reasons == {"same name at same company", "same mailbox (dots/+tag variant)"}


def test_erasure_anonymises_and_keeps_suppression(api):
    c = _contact(api, _company(api), "erase.me@acme.sa", first_name="Erase", phone="+966500000000")
    assert api.post(f"/contacts/{c['id']}/erase").status_code == 204
    assert api.get(f"/contacts/{c['id']}").status_code == 404
    assert api.get("/suppressions?q=erase.me").json()["total"] == 1


def test_verification_syntax_and_disposable():
    assert verification.verify("bad@@x")[0] == VerificationStatus.INVALID
    assert verification.verify("x@mailinator.com")[0] == VerificationStatus.RISKY


def test_verification_dns_when_network_available():
    status, reason = verification.verify("someone@nonexistent-domain-bep-test.invalid")
    if status is None:
        pytest.skip("DNS not reachable from this environment")
    assert status == VerificationStatus.INVALID


def test_import_arabic_names_and_dash_as_empty(api):
    csv_data = (
        "Email,Full Name,Name (Arabic),Company Name,Company Name (Arabic),Phone,Job Title,Consent Source,Consent Date\n"
        "ahmed@alfaisal.sa,Ahmed Al Harbi,أحمد الحربي,Al Faisal Holding,شركة الفيصل القابضة,-,CFO,Client meeting,2026-10-15\n"
        "sara@alfaisal.sa,Sara Saleh,-,Al Faisal Holding,-,+966 50 123 4567,-,-,-\n"
    ).encode("utf-8")
    files = {"file": ("contacts.csv", csv_data, "text/csv")}
    pv = api.post("/imports/preview", data={"entity": "contact"}, files=files).json()
    m = pv["suggested_mapping"]
    assert m["Name (Arabic)"] == "name_ar" and m["Company Name (Arabic)"] == "company_name_ar"
    assert m["Full Name"] == "full_name" and m["Company Name"] == "company_name"
    r = api.post("/imports", data={"entity": "contact", "column_mapping": json.dumps(m)}, files=files)
    job = api.get(f"/imports/{r.json()['id']}").json()
    assert job["status"] == "completed" and job["inserted"] == 2, (job["errors"], job["inserted"], job.get("updated"), job["skipped"])
    by = {c["email"]: c for c in api.get("/contacts?page_size=50").json()["items"]}
    a, s = by["ahmed@alfaisal.sa"], by["sara@alfaisal.sa"]
    assert a["name_ar"] == "أحمد الحربي" and a["company_name_ar"] == "شركة الفيصل القابضة"
    assert a["phone"] is None and a["first_name"] == "Ahmed" and a["subscription_status"] == "subscribed"
    assert s["name_ar"] is None and s["job_title"] is None and s["subscription_status"] == "pending"
    assert api.get("/contacts", params={"q": "الحربي"}).json()["total"] == 1
    assert api.get("/companies", params={"q": "الفيصل"}).json()["total"] == 1
