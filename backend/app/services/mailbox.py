"""Mailbox service: record every outbound email, capture replies, and send replies from the platform.

Reply capture: when INBOUND_DOMAIN is configured, outbound mail carries
Reply-To: "<From name>" <replies+<message-hex>.<sig>@INBOUND_DOMAIN>. The domain's MX points at the
platform's own SMTP receiver (port 25), which files the reply into the original thread and, optionally,
forwards a copy to the sending account's normal mailbox (e.g. Outlook) so nothing is missed.
"""
from __future__ import annotations

import hashlib
import hmac
import html as html_lib
import logging
import re
import uuid
from email import message_from_bytes
from email import policy as email_policy
from email.utils import formataddr, getaddresses, make_msgid, parseaddr

import bleach
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import SendingAccount
from app.models.mailbox import MailMessage

log = logging.getLogger(__name__)
REPLY_PREFIX = "replies"
_TOKEN = re.compile(r"^replies\+([0-9a-f]{32})\.([0-9a-z]{10})$")
SAFE_TAGS = ["a", "b", "blockquote", "br", "div", "em", "h1", "h2", "h3", "h4", "hr", "i", "img", "li", "ol",
             "p", "pre", "span", "strong", "table", "tbody", "td", "th", "thead", "tr", "u", "ul"]
SAFE_ATTRS = {"a": ["href", "title"], "img": ["src", "alt", "width", "height"], "td": ["colspan", "rowspan"],
              "th": ["colspan", "rowspan"]}


# ---------------- reply addresses ----------------

def _sig(hex_id: str) -> str:
    return hmac.new(f"{settings.SECRET_KEY}:reply".encode(), hex_id.encode(), hashlib.sha256).hexdigest()[:10]


def reply_address(message_id: uuid.UUID) -> str | None:
    if not settings.INBOUND_DOMAIN:
        return None
    h = message_id.hex
    return f"{REPLY_PREFIX}+{h}.{_sig(h)}@{settings.INBOUND_DOMAIN.lower()}"


def parse_reply_address(address: str) -> uuid.UUID | None:
    local = address.rsplit("@", 1)[0].lower()
    m = _TOKEN.match(local)
    if not m or not hmac.compare_digest(m.group(2), _sig(m.group(1))):
        return None
    return uuid.UUID(m.group(1))


def reply_to_header(account: SendingAccount, row: MailMessage) -> str | None:
    """Reply-To for an outbound email: the capture address when enabled, else the account's reply-to."""
    cap = reply_address(row.id)
    if cap:
        return formataddr((account.from_name, cap)) if account.from_name else cap
    return account.reply_to


# ---------------- outbound ----------------

def html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", html or "")
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_lib.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def start_outbound(db: Session, workspace_id, account: SendingAccount, to: str, subject: str, *, kind: str,
                   text: str | None = None, html: str | None = None, campaign_id=None, recipient_id=None,
                   contact_id=None, thread_id=None, in_reply_to: str | None = None, user_id=None) -> MailMessage:
    """Create the Sent-folder row before sending (its id is needed for the reply address)."""
    domain = account.from_email.rsplit("@", 1)[-1]
    row = MailMessage(
        id=uuid.uuid4(), workspace_id=workspace_id, direction="out", kind=kind, status="queued",
        account_id=account.id, campaign_id=campaign_id, recipient_id=recipient_id, contact_id=contact_id,
        from_addr=account.from_email, from_name=account.from_name, to_addr=to, subject=subject or "",
        body_text=(text if text is not None else html_to_text(html or ""))[:200_000],
        body_html=html if kind != "campaign" else None,   # campaign bodies live on the campaign itself
        message_id_hdr=make_msgid(domain=domain), in_reply_to=in_reply_to, is_read=True, sent_by=user_id)
    row.thread_id = thread_id or row.id
    db.add(row)
    db.flush()
    return row


def finish_outbound(row: MailMessage, ok: bool, error: str | None = None) -> None:
    row.status = "sent" if ok else "failed"
    row.error = None if ok else (error or "")[:1000]


# ---------------- inbound ----------------

def _decode_body(msg) -> tuple[str, str | None]:
    text_part = msg.get_body(preferencelist=("plain",))
    html_part = msg.get_body(preferencelist=("html",))
    html = html_part.get_content() if html_part is not None else None
    text = text_part.get_content() if text_part is not None else html_to_text(html or "")
    if html:
        html = bleach.clean(html, tags=SAFE_TAGS, attributes=SAFE_ATTRS, protocols=["http", "https", "mailto", "cid"],
                            strip=True)
    return text, html


def strip_quoted(text: str) -> str:
    """The new part of a reply (drops the quoted original), for previews."""
    lines = []
    for line in (text or "").splitlines():
        if re.match(r"^\s*>", line) or re.match(r"(?i)^\s*(on .+ wrote:|from:\s|-----original message-----|"
                                                  r"________________________________)", line):
            break
        lines.append(line)
    return "\n".join(lines).strip() or (text or "").strip()


def receive(db: Session, rcpt_address: str, raw: bytes) -> str:
    """File an inbound reply into its thread. Returns an outcome string."""
    oid = parse_reply_address(rcpt_address)
    if oid is None:
        return "ignored: unsigned address"
    original = db.get(MailMessage, oid)
    if original is None:
        return "ignored: unknown thread"
    msg = message_from_bytes(raw, policy=email_policy.default)
    name, addr = parseaddr(str(msg.get("From", "")))
    auto = (str(msg.get("Auto-Submitted", "no")).lower() not in ("", "no") or bool(msg.get("X-Autoreply"))
            or str(msg.get("Precedence", "")).lower() in ("auto_reply", "bulk", "junk"))
    text, html = _decode_body(msg)
    row = MailMessage(
        workspace_id=original.workspace_id, direction="in", kind="auto_reply" if auto else "inbound",
        status="received", thread_id=original.thread_id, account_id=original.account_id,
        campaign_id=original.campaign_id, recipient_id=original.recipient_id, contact_id=original.contact_id,
        from_addr=(addr or "unknown").lower()[:320], from_name=(name or None) and name[:200],
        to_addr=original.from_addr, subject=str(msg.get("Subject", ""))[:2000], body_text=text[:200_000],
        body_html=html, message_id_hdr=str(msg.get("Message-ID", ""))[:500] or None,
        in_reply_to=str(msg.get("In-Reply-To", ""))[:500] or None, is_read=False)
    db.add(row)
    db.flush()
    if settings.INBOUND_FORWARD_COPY and not auto:
        try:
            forward_copy(db, row)
        except Exception:  # noqa: BLE001 - the reply is already stored; a failed copy must not lose it
            log.exception("forwarding reply copy failed")
    return row.kind


def forward_copy(db: Session, reply: MailMessage) -> None:
    """Send a copy of an inbound reply to the account's own mailbox (Reply-To = the original sender)."""
    from app.providers import OutgoingEmail, build_provider
    account = db.get(SendingAccount, reply.account_id) if reply.account_id else None
    if account is None:
        return
    target = account.reply_to or account.from_email
    who = formataddr((reply.from_name, reply.from_addr)) if reply.from_name else reply.from_addr
    body = (f"Reply received in the Bulk Email Platform from {who}:\n\n{reply.body_text or ''}")
    provider = build_provider(account)
    try:
        provider.send(OutgoingEmail(from_email=account.from_email, from_name=account.from_name, to=target,
                                    reply_to=reply.from_addr, subject=f"[Reply] {reply.subject}",
                                    text=body, html=f"<pre style='font-family:inherit;white-space:pre-wrap'>"
                                                    f"{html_lib.escape(body)}</pre>", tags={"type": "forward"}))
    finally:
        provider.close()


# ---------------- replying from the platform ----------------

def send_reply(db: Session, workspace_id, original: MailMessage, body_text: str, user_id=None) -> MailMessage:
    from app.providers import OutgoingEmail, ProviderError, build_provider
    account = db.get(SendingAccount, original.account_id) if original.account_id else None
    if account is None:
        account = db.scalar(sa.select(SendingAccount).where(SendingAccount.is_default.is_(True)))
    if account is None:
        raise ValueError("No sending account available")
    to = original.from_addr if original.direction == "in" else original.to_addr
    subj = original.subject if re.match(r"(?i)^re:", original.subject or "") else f"Re: {original.subject}"
    html = "<div>" + "<br>".join(html_lib.escape(line) for line in body_text.splitlines()) + "</div>"
    row = start_outbound(db, workspace_id, account, to, subj, kind="reply", text=body_text, html=html,
                         contact_id=original.contact_id, thread_id=original.thread_id,
                         in_reply_to=original.message_id_hdr, user_id=user_id)
    refs = " ".join(m for m in db.scalars(sa.select(MailMessage.message_id_hdr).where(
        MailMessage.thread_id == original.thread_id, MailMessage.message_id_hdr.is_not(None))
        .order_by(MailMessage.created_at)) if m)
    headers = {"Message-ID": row.message_id_hdr}
    if original.message_id_hdr:
        headers |= {"In-Reply-To": original.message_id_hdr, "References": refs[-1900:]}
    provider = build_provider(account)
    try:
        provider.send(OutgoingEmail(from_email=account.from_email, from_name=account.from_name, to=to,
                                    reply_to=reply_to_header(account, row), subject=subj, html=html,
                                    text=body_text, headers=headers, tags={"type": "reply"}))
        finish_outbound(row, True)
    except ProviderError as e:
        finish_outbound(row, False, str(e))
    finally:
        provider.close()
    return row


def compose(db: Session, workspace_id, account: SendingAccount, to: str, subject: str, body_text: str,
            user_id=None) -> MailMessage:
    """A new one-to-one email (not a test, not a campaign), written in the platform."""
    from app.models import Contact
    from app.providers import OutgoingEmail, ProviderError, build_provider
    html = "<div>" + "<br>".join(html_lib.escape(line) for line in body_text.splitlines()) + "</div>"
    contact_id = db.scalar(sa.select(Contact.id).where(sa.func.lower(Contact.email) == to.lower()).limit(1))
    row = start_outbound(db, workspace_id, account, to, subject, kind="direct", text=body_text, html=html,
                         contact_id=contact_id, user_id=user_id)
    provider = build_provider(account)
    try:
        provider.send(OutgoingEmail(from_email=account.from_email, from_name=account.from_name, to=to,
                                    reply_to=reply_to_header(account, row), subject=subject, html=html,
                                    text=body_text, headers={"Message-ID": row.message_id_hdr},
                                    tags={"type": "direct"}))
        finish_outbound(row, True)
    except ProviderError as e:
        finish_outbound(row, False, str(e))
    finally:
        provider.close()
    return row


def recipients_of(addresses: str) -> list[str]:
    return [a.lower() for _, a in getaddresses([addresses]) if a]
