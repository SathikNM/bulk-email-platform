"""Phase 5: segmentation engine (AND/OR rule trees, live counts, eligibility, CRUD)."""


def _industry(api, name):
    return next(i["id"] for i in api.get("/industries").json() if i["name"] == name)


def _seed(api):
    con, ret = _industry(api, "Construction"), _industry(api, "Retail")
    riyadh = api.post("/companies", json={"name": "Riyadh Build", "industry_id": con, "country_code": "SA",
                                          "city": "Riyadh", "company_size": "201-500"}).json()["id"]
    jeddah = api.post("/companies", json={"name": "Jeddah Build", "industry_id": con, "country_code": "SA",
                                          "city": "Jeddah"}).json()["id"]
    shop = api.post("/companies", json={"name": "Riyadh Shops", "industry_id": ret, "country_code": "SA",
                                        "city": "Riyadh"}).json()["id"]
    consent = {"consent_source": "event", "consent_date": "2026-09-01T00:00:00Z"}

    def add(co, email, title, dept="Finance", consented=True):
        return api.post("/contacts", json={"company_id": co, "email": email, "job_title": title,
                                           "department": dept, **(consent if consented else {})}).json()["id"]
    ids = {
        "cfo": add(riyadh, "cfo@rb.sa", "CFO"),
        "fm": add(riyadh, "fm@rb.sa", "Finance Manager"),
        "fm_pending": add(riyadh, "fm2@rb.sa", "Senior Finance Manager", consented=False),
        "ceo": add(riyadh, "ceo@rb.sa", "CEO", dept="Executive"),
        "jeddah_cfo": add(jeddah, "cfo@jb.sa", "CFO"),
        "shop_cfo": add(shop, "cfo@rs.sa", "CFO"),
    }
    return con, ids


BRIEF_EXAMPLE = lambda con: {"op": "and", "rules": [  # noqa: E731
    {"field": "industry", "operator": "eq", "value": con},
    {"field": "country", "operator": "eq", "value": "SA"},
    {"field": "city", "operator": "eq", "value": "Riyadh"},
    {"op": "or", "rules": [
        {"field": "job_title", "operator": "contains", "value": "CFO"},
        {"field": "job_title", "operator": "contains", "value": "Finance Manager"}]},
    {"field": "subscription_status", "operator": "eq", "value": "subscribed"},
]}


def test_brief_example_segment(api):
    con, ids = _seed(api)
    r = api.post("/segments/count", json={"rules": BRIEF_EXAMPLE(con)}).json()
    assert r["total"] == 2 and r["eligible"] == 2
    prev = api.post("/segments/preview", json={"rules": BRIEF_EXAMPLE(con)}).json()
    assert {c["email"] for c in prev["items"]} == {"cfo@rb.sa", "fm@rb.sa"}


def test_eligible_count_excludes_suppressed_and_pending(api):
    con, ids = _seed(api)
    rules = {"op": "and", "rules": [{"field": "industry", "operator": "eq", "value": con},
                                    {"field": "department", "operator": "eq", "value": "finance"}]}
    r = api.post("/segments/count", json={"rules": rules}).json()
    assert (r["total"], r["eligible"]) == (4, 3)
    assert r["excluded"]["not_subscribed"] == 1 and r["excluded"]["no_active_consent"] == 1
    api.post(f"/contacts/{ids['cfo']}/unsubscribe", json={})
    r = api.post("/segments/count", json={"rules": rules}).json()
    assert r["eligible"] == 2 and r["excluded"]["suppressed"] == 1
    only = api.post("/segments/preview?eligible_only=true", json={"rules": rules}).json()
    assert all(c["eligible"] for c in only["items"]) and only["total"] == 2


def test_operators(api):
    con, ids = _seed(api)

    def n(rule):
        return api.post("/segments/count", json={"rules": {"op": "and", "rules": [rule]}}).json()["total"]
    assert n({"field": "job_title", "operator": "in", "value": ["cfo", "CEO"]}) == 4
    assert n({"field": "job_title", "operator": "starts_with", "value": "Senior"}) == 1
    assert n({"field": "job_title", "operator": "not_contains", "value": "CFO"}) == 3
    assert n({"field": "city", "operator": "neq", "value": "Riyadh"}) == 1
    assert n({"field": "company_size", "operator": "eq", "value": "201-500"}) == 4
    assert n({"field": "industry", "operator": "not_in", "value": [con]}) == 1
    assert n({"field": "email_domain", "operator": "eq", "value": "rb.sa"}) == 4
    assert n({"field": "tags", "operator": "is_empty"}) == 6
    tag = api.post("/tags", json={"name": "Hot"}).json()["id"]
    api.post("/contacts/bulk", json={"contact_ids": [ids["ceo"]], "add_tag_ids": [tag]})
    assert n({"field": "tags", "operator": "in", "value": [tag]}) == 1
    assert n({"field": "created_at", "operator": "after", "value": "2000-01-01"}) == 6
    # literal % and _ are escaped, not wildcards
    assert n({"field": "job_title", "operator": "contains", "value": "%"}) == 0


def test_nested_or_of_ands(api):
    con, ids = _seed(api)
    rules = {"op": "or", "rules": [
        {"op": "and", "rules": [{"field": "city", "operator": "eq", "value": "Jeddah"},
                                {"field": "job_title", "operator": "eq", "value": "CFO"}]},
        {"op": "and", "rules": [{"field": "department", "operator": "eq", "value": "Executive"}]}]}
    prev = api.post("/segments/preview", json={"rules": rules}).json()
    assert {c["email"] for c in prev["items"]} == {"cfo@jb.sa", "ceo@rb.sa"}


def test_invalid_rules_rejected(api):
    bad = [{"field": "password_hash", "operator": "eq", "value": "x"},
           {"field": "city", "operator": "before", "value": "x"},
           {"field": "industry", "operator": "eq", "value": "not-a-uuid"},
           {"field": "subscription_status", "operator": "eq", "value": "maybe"}]
    for rule in bad:
        r = api.post("/segments/count", json={"rules": {"op": "and", "rules": [rule]}})
        assert r.status_code == 400, rule
    deep = {"op": "and", "rules": []}
    node = deep
    for _ in range(7):
        child = {"op": "and", "rules": []}
        node["rules"].append(child)
        node = child
    assert api.post("/segments/count", json={"rules": deep}).status_code == 400


def test_segment_crud_duplicate_and_contacts(api):
    con, ids = _seed(api)
    s = api.post("/segments", json={"name": "KSA Construction Finance", "rules": BRIEF_EXAMPLE(con)})
    assert s.status_code == 201 and s.json()["cached_eligible_count"] == 2
    assert api.post("/segments", json={"name": "ksa construction finance", "rules": {}}).status_code == 409
    sid = s.json()["id"]
    d = api.post(f"/segments/{sid}/duplicate").json()
    assert d["name"] == "KSA Construction Finance (copy)" and d["rules"] == s.json()["rules"]
    upd = api.patch(f"/segments/{d['id']}", json={"rules": {"op": "and", "rules": [
        {"field": "job_title", "operator": "eq", "value": "CFO"}]}}).json()
    assert upd["counts"]["total"] == 3
    assert api.get(f"/segments/{sid}/contacts").json()["total"] == 2
    assert len(api.get("/segments").json()["items"]) == 2
    assert api.delete(f"/segments/{d['id']}").status_code == 204


def test_fields_catalogue(api):
    _seed(api)
    f = {x["field"]: x for x in api.get("/segments/fields").json()}
    assert {"industry", "country", "city", "company", "company_size", "job_title", "department",
            "contact_category", "tags", "subscription_status", "email_verification_status"} <= set(f)
    assert "Riyadh" in [o["value"] for o in f["city"]["options"]]
    assert "contains" in f["job_title"]["operators"]


def test_segment_isolated_per_workspace(client, api):
    from tests.conftest import Api, login, make_workspace_with
    _seed(api)
    ws, (_, email, pw) = make_workspace_with("owner")
    other = Api(client, ws, login(client, email, pw))
    assert other.post("/segments/count", json={"rules": {}}).json()["total"] == 0
