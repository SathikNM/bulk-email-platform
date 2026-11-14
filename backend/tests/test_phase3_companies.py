"""Phase 3: auth, RBAC, workspaces, taxonomy, companies, imports/exports (real DB + Redis)."""
import io
import json

from openpyxl import Workbook, load_workbook

from tests.conftest import Api, api_with_role, login, make_user, make_workspace_with

# ---------------- auth ----------------

def test_login_me_refresh_logout(client):
    ws, (uid, email, pw) = make_workspace_with("admin")
    r = client.post("/api/v1/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200
    assert "refresh_token" not in r.json()  # only in httpOnly cookie
    assert "bep_refresh" in r.cookies
    tok = r.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()
    assert me["email"] == email and me["workspaces"][0]["role"] == "admin"

    old_cookie = r.cookies["bep_refresh"]
    r2 = client.post("/api/v1/auth/refresh")
    assert r2.status_code == 200 and r2.json()["access_token"]
    # Reusing the rotated token revokes the family
    client.cookies.set("bep_refresh", old_cookie, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_bad_password_and_lockout(client):
    _, email, _ = make_user()
    for _ in range(5):
        assert client.post("/api/v1/auth/login", json={"email": email, "password": "nope"}).status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "nope"})
    assert r.status_code == 429


def test_requires_token_and_membership(client, api):
    assert client.get("/api/v1/companies", headers={"X-Workspace-Id": str(api.ws)}).status_code == 401
    other_ws, _ = make_workspace_with("owner")
    r = client.get("/api/v1/companies", headers={**api.h, "X-Workspace-Id": str(other_ws)})
    assert r.status_code == 403


def test_role_permissions(client, api):
    viewer = api_with_role(client, api.ws, "viewer")
    assert viewer.get("/companies").status_code == 200
    assert viewer.post("/companies", json={"name": "X"}).status_code == 403
    marketer = api_with_role(client, api.ws, "marketer")
    cid = marketer.post("/companies", json={"name": "Y"}).json()["id"]
    assert marketer.delete(f"/companies/{cid}").status_code == 403  # delete = admin
    assert api.delete(f"/companies/{cid}").status_code == 204


def test_member_management_keeps_an_owner(client, api):
    r = api.post("/members", json={"email": "new.member@example.com", "full_name": "New",
                                   "role": "marketer", "password": "Str0ng!Passw0rd"})
    assert r.status_code == 201
    weak = api.post("/members", json={"email": "weak@example.com", "full_name": "W",
                                      "role": "viewer", "password": "short"})
    assert weak.status_code == 400
    me = api.c.get("/api/v1/auth/me", headers=api.h).json()
    assert api.patch(f"/members/{me['id']}", json={"role": "admin"}).status_code == 400
    assert len(api.get("/members").json()) == 2


def test_superadmin_creates_workspace_with_default_taxonomy(client):
    _, email, pw = make_user(superadmin=True)
    tok = login(client, email, pw)
    r = client.post("/api/v1/workspaces", json={"name": "Client Alpha"},
                    headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 201, r.text
    a = Api(client, r.json()["id"], tok)
    assert len(a.get("/industries").json()) == 28


# ---------------- taxonomy ----------------

def test_taxonomy_crud_and_uniqueness(api):
    t = api.post("/tags", json={"name": "VIP", "color": "#ff0000"})
    assert t.status_code == 201
    assert api.post("/tags", json={"name": "vip"}).status_code == 409
    c = api.post("/categories", json={"name": "Strategic", "scope": "company"})
    assert c.status_code == 201
    assert api.patch(f"/tags/{t.json()['id']}", json={"name": "Key Account"}).json()["name"] == "Key Account"
    assert api.delete(f"/tags/{t.json()['id']}").status_code == 204
    assert any(i["name"] == "Construction" for i in api.get("/industries").json())


# ---------------- companies ----------------

def _industry(api, name="Construction"):
    return next(i["id"] for i in api.get("/industries").json() if i["name"] == name)


def test_company_crud_profile_tags_categories(api):
    tag = api.post("/tags", json={"name": "Target"}).json()["id"]
    cat = next(c["id"] for c in api.get("/categories?scope=company").json() if c["name"] == "Prospect")
    r = api.post("/companies", json={
        "name": "Al Rajhi Construction", "industry_id": _industry(api), "country_code": "sa",
        "city": "Riyadh", "website": "www.alrajhi-construction.sa", "company_size": "201-500",
        "annual_revenue": "125000000", "tag_ids": [tag], "category_ids": [cat]})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["code"].startswith("COMP-") and c["domain"] == "alrajhi-construction.sa"
    assert c["country_code"] == "SA" and c["industry"] == "Construction"
    assert [t["name"] for t in c["tags"]] == ["Target"] and c["categories"][0]["name"] == "Prospect"

    dup = api.post("/companies", json={"name": "Other", "website": "https://alrajhi-construction.sa/x"})
    assert dup.status_code == 409

    upd = api.patch(f"/companies/{c['id']}", json={"city": "Jeddah", "tag_ids": []})
    assert upd.json()["city"] == "Jeddah" and upd.json()["tags"] == []
    prof = api.get(f"/companies/{c['id']}").json()
    assert prof["contacts"] == [] and prof["contact_count"] == 0


def test_company_validation(api):
    r = api.post("/companies", json={"name": "", "country_code": "SAU"})
    assert r.status_code == 422 and r.json()["title"] == "Validation error"


def test_company_search_filter_sort_paginate(api):
    ind = _industry(api)
    for i, (name, cc, city) in enumerate([("Alpha Build", "SA", "Riyadh"), ("Beta Steel", "SA", "Jeddah"),
                                          ("Gamma Retail", "AE", "Dubai")]):
        api.post("/companies", json={"name": name, "country_code": cc, "city": city,
                                     "industry_id": ind if i < 2 else None})
    assert api.get("/companies?q=steel").json()["total"] == 1
    assert api.get("/companies?country_code=SA").json()["total"] == 2
    assert api.get(f"/companies?industry_id={ind}&city=riyadh").json()["total"] == 1
    p = api.get("/companies?sort=name&page_size=2&page=1").json()
    assert p["total"] == 3 and [x["name"] for x in p["items"]] == ["Alpha Build", "Beta Steel"]
    assert api.get("/companies?sort=name&page_size=2&page=2").json()["items"][0]["name"] == "Gamma Retail"


def test_duplicate_detection_and_merge(api):
    a = api.post("/companies", json={"name": "Saudi Binladin Group", "city": "Jeddah"}).json()
    b = api.post("/companies", json={"name": "Saudi Bin Ladin Group", "website": "sbg.com.sa",
                                     "industry_id": _industry(api)}).json()
    api.post("/companies", json={"name": "Completely Different Co"})
    dups = api.get("/companies/duplicates").json()
    assert any({d["a"]["id"], d["b"]["id"]} == {a["id"], b["id"]} for d in dups)
    chk = api.get("/companies/check-duplicate", params={"name": "Saudi Binladin Grp"}).json()
    assert chk and chk[0]["id"] == a["id"]

    m = api.post("/companies/merge", json={"primary_id": a["id"], "duplicate_ids": [b["id"]]})
    assert m.status_code == 200, m.text
    merged = m.json()
    assert merged["domain"] == "sbg.com.sa" and merged["industry"] == "Construction"
    assert api.get(f"/companies/{b['id']}").status_code == 404


def test_delete_company_with_contacts_requires_cascade(api):
    from app.db.session import system_scope
    from app.models import Contact

    c = api.post("/companies", json={"name": "HasContacts"}).json()
    with system_scope() as s:
        s.add(Contact(workspace_id=api.ws, company_id=c["id"], email="x@hascontacts.com"))
    r = api.delete(f"/companies/{c['id']}")
    assert r.status_code == 409 and r.json()["contact_count"] == 1
    assert api.delete(f"/companies/{c['id']}?cascade_archive=true").status_code == 204


def test_workspace_isolation_via_api(client, api):
    c = api.post("/companies", json={"name": "Private Co"}).json()
    other_ws, (uid, email, pw) = make_workspace_with("owner")
    other = Api(client, other_ws, login(client, email, pw))
    assert other.get(f"/companies/{c['id']}").status_code == 404
    assert other.get("/companies").json()["total"] == 0


# ---------------- import / export ----------------

def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_company_import_xlsx_with_errors_and_upsert(api):
    api.post("/companies", json={"name": "Existing Co", "website": "existing.sa", "city": "Old"})
    data = _xlsx([
        ["Company Name", "Sector", "Country", "City", "Website", "Size", "Tags"],
        ["Existing Co", "Construction", "Saudi Arabia", "Riyadh", "existing.sa", "120", "VIP, Gulf"],
        ["New Arabic Co شركة", "Brand New Industry", "AE", "Dubai", "newco.ae", "51-200", "Gulf"],
        ["", "Construction", "SA", "Riyadh", "", "", ""],
        ["Bad Country Co", "", "Atlantis", "", "", "", ""],
    ])
    files = {"file": ("companies.xlsx", data, "application/octet-stream")}
    pv = api.post("/imports/preview", data={"entity": "company"}, files=files).json()
    assert pv["total_rows"] == 4
    assert pv["suggested_mapping"]["Company Name"] == "name"
    assert pv["suggested_mapping"]["Sector"] == "industry"
    assert pv["suggested_mapping"]["Size"] == "company_size"

    r = api.post("/imports", data={"entity": "company", "column_mapping": json.dumps(pv["suggested_mapping"])},
                 files=files)
    assert r.status_code == 202, r.text
    job = api.get(f"/imports/{r.json()['id']}").json()
    assert job["status"] == "completed", job
    assert (job["inserted"], job["updated"], job["skipped"]) == (1, 1, 2)
    assert {e["row"] for e in job["errors"]} == {4, 5}
    ex = api.get("/companies?q=existing").json()["items"][0]
    assert ex["city"] == "Riyadh" and ex["company_size"] == "51-200" and len(ex["tags"]) == 2
    assert any(i["name"] == "Brand New Industry" for i in api.get("/industries").json())
    err_csv = api.get(f"/imports/{r.json()['id']}/errors.csv")
    assert "Company name is required" in err_csv.text


def test_import_rejects_unknown_target_field(api):
    files = {"file": ("c.csv", b"name\nA\n", "text/csv")}
    r = api.post("/imports", data={"entity": "company", "column_mapping": '{"name": "hacker_field"}'},
                 files=files)
    assert r.status_code == 400


def test_company_export_csv_and_xlsx(api):
    api.post("/companies", json={"name": "Export Me", "country_code": "SA"})
    r = api.get("/companies/export?format=csv")
    assert r.status_code == 200 and "Export Me" in r.text and r.text.startswith("﻿Company ID")
    x = api.get("/companies/export?format=xlsx")
    wb = load_workbook(io.BytesIO(x.content))
    assert wb.active["B2"].value == "Export Me"


def test_audit_log_written(api):
    import sqlalchemy as sa

    from app.db.session import system_scope

    c = api.post("/companies", json={"name": "Audited"}).json()
    with system_scope() as s:
        n = s.scalar(sa.text("SELECT count(*) FROM audit_logs WHERE entity_id = :i AND action='create'"),
                     {"i": c["id"]})
    assert n == 1


def test_login_accepts_reserved_domain_accounts(client):
    """Seeded admin uses admin@primecfo.local; sign-in must not reject reserved TLDs."""
    _, email, pw = make_user(email="admin-test@primecfo.local")
    assert client.post("/api/v1/auth/login", json={"email": email, "password": pw}).status_code == 200
