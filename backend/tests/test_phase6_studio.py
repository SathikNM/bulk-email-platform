"""Phase 6: rendering, templates, blocks, images, sending accounts, test send, AI assistant."""
import base64

from app.services import rendering
from tests.conftest import smtp_account

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


# ---------------- rendering ----------------

def test_variables_fallback_and_escaping():
    data = {"first_name": "<b>Omar</b>", "company_name": None}
    out = rendering.substitute("Hi {{FirstName}} at {{ CompanyName | your company }}", data, {}, escape=True)
    assert out == "Hi &lt;b&gt;Omar&lt;/b&gt; at your company"
    assert rendering.substitute("{{FirstName|there}}", {}, {}, escape=False) == "there"
    known, unknown = rendering.find_variables("{{FirstName}} {{Foo}} {{UnsubscribeUrl}}")
    assert known == {"FirstName", "UnsubscribeUrl"} and unknown == {"Foo"}


def test_sanitizer_strips_active_content():
    dirty = ('<p onclick="x()">Hi</p><script>alert(1)</script><a href="javascript:alert(1)">x</a>'
             '<iframe src="https://evil"></iframe><img src="https://ok/x.png" onerror="y()">')
    clean = rendering.sanitize_html(dirty)
    for bad in ("onclick", "<script", "javascript:", "<iframe", "onerror"):
        assert bad not in clean
    assert "https://ok/x.png" in clean


def test_rtl_footer_and_inlining():
    html = "<style>.t{color:#123456}</style><p class='t'>مرحبا {{FirstName}}</p>"
    prepared = rendering.prepare_template_html(html, "rtl", "ar", "معاينة", "عنوان", "الرياض، السعودية")
    assert 'dir="rtl"' in prepared and 'lang="ar"' in prepared
    assert "إلغاء الاشتراك" in prepared and "{{UnsubscribeUrl}}" in prepared
    assert "color:#123456" in prepared.replace(" ", "")  # CSS inlined
    subj, out, text = rendering.render_for_recipient(prepared, "مرحبا {{FirstName}}", None,
                                                     {"first_name": "سارة"}, {"UnsubscribeUrl": "https://u/x"})
    assert subj == "مرحبا سارة" and "https://u/x" in out and "سارة" in text


def test_existing_unsubscribe_link_not_duplicated():
    html = '<p>Hi</p><a href="{{ UnsubscribeUrl }}">Opt out</a>'
    out = rendering.ensure_footer(html, "ltr", "Riyadh")
    assert out.count("UnsubscribeUrl") == 1


# ---------------- templates ----------------

def test_template_crud_duplicate_render(api):
    t = api.post("/templates", json={"name": "Welcome", "subject": "Hello {{FirstName|there}}",
                                     "editor_type": "html", "html": "<h1>Hi {{FirstName}}</h1><script>x</script>",
                                     "preheader": "Quick update"}).json()
    assert "<script" not in t["html"]
    upd = api.patch(f"/templates/{t['id']}", json={"is_draft": False, "subject": "Hi {{FirstName}} {{Nope}}"}).json()
    assert upd["is_draft"] is False
    r = api.post(f"/templates/{t['id']}/render", json={}).json()
    assert r["subject"] == "Hi Sara" and "Sara" in r["html"] and "Unsubscribe" in r["html"]
    assert r["unknown_variables"] == ["Nope"] and any("Unknown variables" in w for w in r["warnings"])
    assert "Quick update" in r["html"]
    d = api.post(f"/templates/{t['id']}/duplicate").json()
    assert d["name"] == "Welcome (copy)" and d["is_draft"] is True and d["duplicated_from"] == t["id"]
    assert api.get("/templates?q=welcome").json()["total"] == 2
    assert api.delete(f"/templates/{d['id']}").status_code == 204
    assert api.get("/templates").json()["total"] == 1


def test_render_with_real_contact_and_unsaved(api):
    co = api.post("/companies", json={"name": "Gulf Steel"}).json()["id"]
    c = api.post("/contacts", json={"company_id": co, "email": "huda@gs.sa", "first_name": "Huda",
                                    "job_title": "CFO"}).json()
    r = api.post("/templates/render", json={"html": "<p>{{FirstName}}, {{JobTitle}} at {{CompanyName}}</p>",
                                            "subject": "For {{CompanyName}}", "contact_id": c["id"],
                                            "direction": "ltr"}).json()
    assert "Huda, CFO at Gulf Steel" in r["html"] and r["subject"] == "For Gulf Steel"


def test_variables_endpoint_and_blocks(api):
    v = api.get("/templates/variables").json()
    assert {x["name"] for x in v["contact"]} >= {"FirstName", "LastName", "CompanyName", "JobTitle", "Email"}
    b = api.post("/blocks", json={"name": "Footer", "block_type": "footer",
                                  "content": {"html": "<p onclick='x'>Footer</p>"}}).json()
    assert "onclick" not in b["content"]["html"]
    assert len(api.get("/blocks").json()) == 1


def test_image_upload_and_public_serving(api):
    r = api.post("/assets", files={"file": ("banner.png", PNG, "image/png")})
    assert r.status_code == 201, r.text
    url = r.json()["url"]
    got = api.c.get(url.replace("http://localhost:8000", ""))
    assert got.status_code == 200 and got.headers["content-type"] == "image/png"
    bad = api.post("/assets", files={"file": ("x.png", b"<svg onload=alert(1)>", "image/png")})
    assert bad.status_code == 400


# ---------------- sending accounts + test send ----------------

def test_sending_account_credentials_never_returned(api, smtp_sink):
    a = smtp_account(api, smtp_sink.port, credentials={"host": "127.0.0.1", "port": smtp_sink.port,
                                                       "security": "none", "username": "u", "password": "secret!"})
    assert a["is_default"] is True and a["domain"] == "primecfo-demo.com"
    assert "encrypted_credentials" not in a and a["credentials_hint"]["password"] == "••••"
    assert "secret!" not in api.get("/sending-accounts").text


def test_smtp_verify_and_test_send_real_delivery(api, smtp_sink):
    a = smtp_account(api, smtp_sink.port)
    v = api.post(f"/sending-accounts/{a['id']}/verify").json()
    assert v["ok"] is True
    api.patch("/workspace", json={"legal_address": "King Fahd Rd, Riyadh"})
    t = api.post("/templates", json={"name": "T", "subject": "Hello {{FirstName}}", "editor_type": "html",
                                     "html": "<p>Hello {{FirstName}}</p>"}).json()
    r = api.post(f"/templates/{t['id']}/test-send", json={"to": ["me@primecfo-demo.com", "reject@primecfo-demo.com"]}).json()
    assert [x["ok"] for x in r["results"]] == [True, False]
    assert len(smtp_sink.messages) == 1
    m = smtp_sink.messages[0]["msg"]
    assert m["Subject"] == "[TEST] Hello Sara" and m["From"] == "Prime CFO <news@primecfo-demo.com>"
    html = next(p for p in m.walk() if p.get_content_type() == "text/html").get_content()
    assert "King Fahd Rd, Riyadh" in html and "Unsubscribe" in html
    assert any(p.get_content_type() == "text/plain" for p in m.walk())


def test_test_send_blocks_suppressed_and_requires_account(api, smtp_sink):
    t = api.post("/templates", json={"name": "T", "subject": "S", "editor_type": "html", "html": "<p>x</p>"}).json()
    assert api.post(f"/templates/{t['id']}/test-send", json={"to": ["a@b.com"]}).status_code == 400
    smtp_account(api, smtp_sink.port)
    api.post("/suppressions", json={"email": "blocked@b.com"})
    r = api.post(f"/templates/{t['id']}/test-send", json={"to": ["blocked@b.com"]})
    assert r.status_code == 400 and "Suppressed" in r.json()["detail"]
    assert smtp_sink.messages == []


def test_sending_account_bad_smtp_credentials_reported(api):
    a = api.post("/sending-accounts", json={"name": "Dead", "provider": "smtp", "from_email": "x@dead-demo.com",
                                            "credentials": {"host": "127.0.0.1", "port": 1, "security": "none"}}).json()
    v = api.post(f"/sending-accounts/{a['id']}/verify").json()
    assert v["ok"] is False and v["dns_records"]


def test_ai_assistant_disabled_without_key(api):
    assert api.get("/ai/status").json()["enabled"] is False
    r = api.post("/ai/generate", json={"kind": "subject", "context": "Launch of our FP&A advisory service"})
    assert r.status_code == 503


def test_editing_account_keeps_saved_password(api, smtp_sink):
    from app.core.security import decrypt_json
    from app.db.session import system_scope
    from app.models import SendingAccount
    a = smtp_account(api, smtp_sink.port, credentials={"host": "127.0.0.1", "port": smtp_sink.port,
                                                       "security": "none", "username": "u", "password": "Secret!"})
    r = api.patch(f"/sending-accounts/{a['id']}", json={"credentials": {"host": "127.0.0.1", "port": smtp_sink.port,
                                                                         "security": "none", "username": "u2",
                                                                         "password": ""}})
    assert r.status_code == 200 and r.json()["credentials_hint"]["password"] == "••••"
    with system_scope() as s:
        creds = decrypt_json(s.get(SendingAccount, a["id"]).encrypted_credentials)
    assert creds["password"] == "Secret!" and creds["username"] == "u2"
