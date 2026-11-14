"""Email rendering: personalisation variables, sanitising, RTL, compliance footer, CSS inlining,
plain-text alternative.

Variables use {{Name}} or {{Name|fallback}}. Values are HTML-escaped in HTML parts.
"""
import html as html_lib
import logging
import re

import lxml.html
from lxml import etree
from premailer import Premailer

log = logging.getLogger(__name__)

VARIABLES = {
    "FirstName": "first_name", "LastName": "last_name", "FullName": "full_name",
    "CompanyName": "company_name", "JobTitle": "job_title", "Email": "email",
    "Department": "department", "City": "city", "Country": "country_code",
}
SYSTEM_VARIABLES = {"UnsubscribeUrl", "ViewInBrowserUrl", "SenderAddress", "CurrentYear"}
VAR_RE = re.compile(r"\{\{\s*([A-Za-z][A-Za-z0-9_]*)\s*(?:\|\s*([^}]*?))?\s*\}\}")

SAMPLE = {"first_name": "Sara", "last_name": "Al-Qahtani", "full_name": "Sara Al-Qahtani",
          "company_name": "Acme Construction", "job_title": "Chief Financial Officer",
          "email": "sara@example.com", "department": "Finance", "city": "Riyadh", "country_code": "SA"}

BLOCKED_TAGS = {"script", "iframe", "object", "embed", "form", "input", "button", "textarea", "select",
                "frame", "frameset", "applet", "base", "meta-refresh"}


def merge_data_for(contact, company_name: str | None) -> dict:
    full = " ".join(x for x in (contact.first_name, contact.last_name) if x) or None
    return {"first_name": contact.first_name, "last_name": contact.last_name, "full_name": full,
            "company_name": company_name, "job_title": contact.job_title, "email": contact.email,
            "department": contact.department, "city": contact.city, "country_code": contact.country_code}


def find_variables(*texts: str | None) -> tuple[set[str], set[str]]:
    """Return (known, unknown) variable names used in the given texts."""
    names = {m.group(1) for t in texts if t for m in VAR_RE.finditer(t)}
    known = {n for n in names if n in VARIABLES or n in SYSTEM_VARIABLES}
    return known, names - known


def substitute(text: str | None, data: dict, system: dict, escape: bool) -> str:
    if not text:
        return ""

    def repl(m):
        name, fallback = m.group(1), m.group(2)
        if name in SYSTEM_VARIABLES:
            v = system.get(name, "")
            return html_lib.escape(v, quote=True) if escape else v
        key = VARIABLES.get(name)
        v = data.get(key) if key else None
        if v in (None, ""):
            v = fallback or ""
        v = str(v)
        return html_lib.escape(v, quote=True) if escape else v
    return VAR_RE.sub(repl, text)


def sanitize_html(html: str) -> str:
    """Remove active content (scripts, event handlers, javascript: URLs). Email clients
    strip these anyway; we never store or send them."""
    if not html or not html.strip():
        return ""
    doc = lxml.html.document_fromstring(html)
    for el in list(doc.iter()):
        if not isinstance(el.tag, str):
            continue
        if el.tag.lower() in BLOCKED_TAGS:
            el.drop_tree()
            continue
        if el.tag.lower() == "meta" and (el.get("http-equiv") or "").lower() == "refresh":
            el.drop_tree()
            continue
        for attr in list(el.attrib):
            a = attr.lower()
            val = (el.attrib[attr] or "").strip().lower().replace("\x00", "")
            if a.startswith("on") or a == "srcdoc":
                del el.attrib[attr]
            elif a in ("href", "src", "action", "background") and re.sub(r"\s", "", val).startswith(
                    ("javascript:", "vbscript:", "data:text/html")):
                del el.attrib[attr]
    return lxml.html.tostring(doc, encoding="unicode", doctype="<!DOCTYPE html>")


def _ensure_document(html: str, direction: str, locale: str, preheader: str | None, title: str) -> str:
    doc = lxml.html.document_fromstring(html if html.strip() else "<p></p>")
    root = doc if doc.tag == "html" else doc.getroottree().getroot()
    root.set("lang", locale or "en")
    root.set("dir", direction)
    head = root.find("head")
    if head is None:
        head = etree.SubElement(root, "head")
        root.insert(0, head)
    if head.find("meta[@charset]") is None:
        m = etree.Element("meta", charset="utf-8")
        head.insert(0, m)
    if head.find("meta[@name='viewport']") is None:
        head.append(etree.Element("meta", name="viewport", content="width=device-width, initial-scale=1"))
    if head.find("title") is None:
        t = etree.SubElement(head, "title")
        t.text = title
    body = root.find("body")
    if body is None:
        body = etree.SubElement(root, "body")
    body.set("dir", direction)
    style = body.get("style") or ""
    if direction == "rtl" and "text-align" not in style:
        body.set("style", (style + ";direction:rtl;text-align:right").strip(";"))
    if preheader:
        ph = etree.Element("div", style="display:none;max-height:0;overflow:hidden;mso-hide:all;"
                                        "font-size:1px;line-height:1px;color:#ffffff;opacity:0")
        ph.text = preheader
        body.insert(0, ph)
    return lxml.html.tostring(root, encoding="unicode", doctype="<!DOCTYPE html>")


FOOTER_EN = ("<table role=\"presentation\" width=\"100%\" style=\"margin-top:24px\"><tr><td "
             "style=\"font-family:Arial,sans-serif;font-size:12px;color:#6b7280;text-align:center;padding:16px\">"
             "{address}<br>You are receiving this email because you agreed to hear from us. "
             "<a href=\"{{{{UnsubscribeUrl}}}}\" style=\"color:#6b7280\">Unsubscribe</a></td></tr></table>")
FOOTER_AR = ("<table role=\"presentation\" width=\"100%\" dir=\"rtl\" style=\"margin-top:24px\"><tr><td "
             "style=\"font-family:Tahoma,Arial,sans-serif;font-size:12px;color:#6b7280;text-align:center;padding:16px\">"
             "{address}<br>تصلك هذه الرسالة لأنك وافقت على تلقي رسائلنا. "
             "<a href=\"{{{{UnsubscribeUrl}}}}\" style=\"color:#6b7280\">إلغاء الاشتراك</a></td></tr></table>")


def ensure_footer(html: str, direction: str, sender_address: str | None) -> str:
    """Guarantee a visible unsubscribe link and the sender's postal address."""
    if "{{UnsubscribeUrl}}" in re.sub(r"\{\{\s*UnsubscribeUrl\s*\}\}", "{{UnsubscribeUrl}}", html):
        return html
    footer = (FOOTER_AR if direction == "rtl" else FOOTER_EN).format(
        address=html_lib.escape(sender_address or ""))
    if re.search(r"</body\s*>", html, re.I):
        return re.sub(r"</body\s*>", footer + "</body>", html, count=1, flags=re.I)
    return html + footer


def inline_css(html: str) -> str:
    try:
        return Premailer(html, keep_style_tags=True, strip_important=False, remove_classes=False,
                         cssutils_logging_level=logging.CRITICAL, allow_network=False,
                         disable_validation=True).transform()
    except Exception:  # noqa: BLE001 - never fail a send because of CSS
        log.warning("CSS inlining failed; sending un-inlined HTML", exc_info=True)
        return html


def html_to_text(html: str) -> str:
    if not html:
        return ""
    doc = lxml.html.document_fromstring(html)
    for bad in doc.xpath("//style|//script|//head"):
        bad.drop_tree()
    for a in doc.xpath("//a[@href]"):
        href = a.get("href")
        if href and not href.startswith("#") and (a.text_content() or "").strip() != href:
            a.tail = f" ({href})" + (a.tail or "")
    for br in doc.xpath("//br"):
        br.tail = "\n" + (br.tail or "")
    for blk in doc.xpath("//p|//div|//tr|//h1|//h2|//h3|//h4|//li|//table"):
        blk.tail = "\n" + (blk.tail or "")
    text = doc.text_content()
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines()).strip()


def prepare_template_html(html: str, direction: str, locale: str, preheader: str | None, title: str,
                          sender_address: str | None) -> str:
    """Template-level processing done once per campaign (not per recipient)."""
    clean = sanitize_html(html)
    doc = _ensure_document(clean, direction, locale, preheader, title)
    doc = ensure_footer(doc, direction, sender_address)
    return inline_css(doc)


def render_for_recipient(prepared_html: str, subject: str, text_body: str | None, data: dict,
                         system: dict) -> tuple[str, str, str]:
    html_out = substitute(prepared_html, data, system, escape=True)
    subj = substitute(subject, data, system, escape=False).replace("\n", " ").strip()
    text = substitute(text_body, data, system, escape=False) if text_body else html_to_text(html_out)
    return subj, html_out, text
