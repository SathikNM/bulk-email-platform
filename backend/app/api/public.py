"""Public (unauthenticated) endpoints: hosted images, open/click tracking, unsubscribe, SES webhook.

All tokens are HMAC-signed; click redirects only go to URLs stored for that campaign
(no open redirect). Tracking failures never break the recipient's experience.
"""
import html
import json
import logging
from pathlib import Path

import httpx
import sqlalchemy as sa
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from app.core.config import settings
from app.core.deps import client_ip
from app.core.security import verify_payload
from app.db.session import system_scope
from app.models import CampaignRecipient, TrackedLink, Workspace
from app.services import events

log = logging.getLogger(__name__)
router = APIRouter(tags=["public"])
MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
PIXEL = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,"
         b"\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")
NO_CACHE = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache"}


@router.get("/assets/{key:path}")
def asset(key: str):
    if settings.STORAGE_BACKEND != "local" or ".." in key or "/images/" not in key:
        return Response(status_code=404)
    base = Path(settings.LOCAL_STORAGE_DIR).resolve()
    path = (base / key).resolve()
    if base not in path.parents or not path.is_file() or path.suffix.lower() not in MEDIA:
        return Response(status_code=404)
    return FileResponse(path, media_type=MEDIA[path.suffix.lower()],
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.get("/t/o/{token}.gif")
def open_pixel(token: str, request: Request):
    try:
        with system_scope() as db:
            rec = events.recipient_from_token(db, verify_payload(token, "open"))
            if rec is not None:
                events.record_open(db, rec, request.headers.get("user-agent"), client_ip(request))
    except Exception:  # noqa: BLE001
        log.exception("open tracking failed")
    return Response(PIXEL, media_type="image/gif", headers=NO_CACHE)


@router.get("/t/c/{token}")
def click(token: str, request: Request):
    payload = verify_payload(token, "click")
    with system_scope() as db:
        rec = events.recipient_from_token(db, payload)
        if rec is None:
            return Response("Link not found", status_code=404)
        url = db.scalar(sa.select(TrackedLink.original_url).where(
            TrackedLink.campaign_id == rec.campaign_id, TrackedLink.token == payload.get("l")))
        if url is None:
            return Response("Link not found", status_code=404)
        try:
            events.record_click(db, rec, url, request.headers.get("user-agent"), client_ip(request))
        except Exception:  # noqa: BLE001
            log.exception("click tracking failed")
    return RedirectResponse(url, status_code=302, headers=NO_CACHE)


def _page(title: str, body: str, rtl: bool = False) -> HTMLResponse:
    d = "rtl" if rtl else "ltr"
    return HTMLResponse(
        f"<!doctype html><html lang='{'ar' if rtl else 'en'}' dir='{d}'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title>"
        "<style>body{font-family:system-ui,-apple-system,'Segoe UI',Tahoma,Arial,sans-serif;background:#f6f7f9;"
        "color:#111827;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}"
        ".card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:32px;max-width:440px;"
        "box-shadow:0 1px 2px rgba(0,0,0,.04)}h1{font-size:20px;margin:0 0 12px}p{color:#4b5563;line-height:1.5}"
        "button{background:#1f3a5f;color:#fff;border:0;border-radius:8px;padding:10px 18px;font-size:15px;"
        f"cursor:pointer}}</style></head><body><div class='card'>{body}</div></body></html>",
        headers={**NO_CACHE, "X-Robots-Tag": "noindex"})


def _ws_info(db, rec: CampaignRecipient) -> tuple[str, bool]:
    ws = db.get(Workspace, rec.workspace_id)
    return (ws.name if ws else ""), bool(ws and ws.default_locale == "ar")


@router.get("/u/{token}", response_class=HTMLResponse)
def unsubscribe_page(token: str):
    with system_scope() as db:
        rec = events.recipient_from_token(db, verify_payload(token, "unsub"))
        if rec is None:
            return _page("Invalid link", "<h1>Link not valid</h1><p>This unsubscribe link is invalid or expired.</p>")
        name, rtl = _ws_info(db, rec)
        email = html.escape(rec.email)
    if rtl:
        body = (f"<h1>إلغاء الاشتراك</h1><p>هل تريد إيقاف رسائل {html.escape(name)} إلى <b>{email}</b>؟</p>"
                "<form method='post'><button type='submit'>نعم، ألغِ اشتراكي</button></form>")
    else:
        body = (f"<h1>Unsubscribe</h1><p>Stop marketing emails from {html.escape(name)} to <b>{email}</b>?</p>"
                "<form method='post'><button type='submit'>Yes, unsubscribe me</button></form>")
    return _page("Unsubscribe", body, rtl)


@router.post("/u/{token}")
async def unsubscribe_post(token: str, request: Request):
    """Handles both the confirmation form and RFC 8058 one-click (List-Unsubscribe=One-Click)."""
    form = (await request.body()).decode(errors="ignore")
    one_click = "List-Unsubscribe=One-Click" in form
    with system_scope() as db:
        rec = events.recipient_from_token(db, verify_payload(token, "unsub"))
        if rec is None:
            return _page("Invalid link", "<h1>Link not valid</h1><p>This unsubscribe link is invalid.</p>") \
                if not one_click else Response(status_code=404)
        events.record_unsubscribe(db, rec, "one-click" if one_click else "unsubscribe page")
        name, rtl = _ws_info(db, rec)
    if one_click:
        return Response(status_code=200)
    if rtl:
        return _page("تم", "<h1>تم إلغاء اشتراكك</h1><p>لن تصلك رسائل تسويقية منا بعد الآن.</p>", True)
    return _page("Unsubscribed", f"<h1>You're unsubscribed</h1><p>You will no longer receive marketing emails from "
                                 f"{html.escape(name)}.</p>")


@router.post("/webhooks/ses")
async def ses_webhook(request: Request):
    try:
        msg = json.loads(await request.body())
    except json.JSONDecodeError:
        return Response(status_code=400)
    if settings.SES_WEBHOOK_VERIFY_SIGNATURE:
        try:
            events.verify_sns(msg)
        except Exception as e:  # noqa: BLE001
            log.warning("Rejected SNS message: %s", e)
            return Response(status_code=403)
    t = msg.get("Type")
    if t == "SubscriptionConfirmation":
        url = msg.get("SubscribeURL", "")
        if not events.valid_sns_url(url):
            return Response(status_code=400)
        httpx.get(url, timeout=10)
        return {"status": "subscribed"}
    if t != "Notification":
        return {"status": "ignored"}
    try:
        event = json.loads(msg.get("Message") or "{}")
    except json.JSONDecodeError:
        return Response(status_code=400)
    with system_scope() as db:
        result = events.handle_ses_event(db, msg.get("MessageId", ""), event)
    return {"status": result}
