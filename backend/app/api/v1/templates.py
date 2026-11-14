"""Module 4: Email creation studio (templates, reusable blocks, images, render/preview, test send)."""
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from fastapi import APIRouter, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field

from app.core.deps import Ctx, Marketer, Viewer
from app.core.errors import BadRequest
from app.models import Campaign, Company, Contact, EmailBlock, EmailTemplate, SendingAccount, Suppression, Workspace
from app.models.enums import BlockType, EditorType, TextDirection
from app.providers import OutgoingEmail, ProviderError, build_provider
from app.services import rendering, storage
from app.services.common import audit, get_or_404, paginate, row_dict

router = APIRouter(tags=["email studio"])

IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}
MAGIC = {b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg", b"GIF8": "image/gif", b"RIFF": "image/webp"}


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    subject: str | None = Field(default=None, max_length=300)
    preheader: str | None = Field(default=None, max_length=300)
    editor_type: EditorType = EditorType.DRAG_DROP
    design_json: dict | None = None
    html: str | None = None
    text_body: str | None = None
    direction: TextDirection = TextDirection.LTR
    locale: str = Field("en", max_length=10)
    is_draft: bool = True


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    subject: str | None = Field(default=None, max_length=300)
    preheader: str | None = Field(default=None, max_length=300)
    editor_type: EditorType | None = None
    design_json: dict | None = None
    html: str | None = None
    text_body: str | None = None
    direction: TextDirection | None = None
    locale: str | None = Field(default=None, max_length=10)
    is_draft: bool | None = None


class RenderIn(BaseModel):
    contact_id: uuid.UUID | None = None
    # Allow rendering unsaved editor content
    html: str | None = None
    subject: str | None = None
    preheader: str | None = None
    direction: TextDirection | None = None


class TestSendIn(BaseModel):
    to: list[EmailStr] = Field(min_length=1, max_length=5)
    sending_account_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None


class BlockIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    block_type: BlockType
    content: dict  # {"html": "..."} plus editor metadata


def _sender_address(ctx: Ctx) -> str | None:
    return ctx.db.scalar(sa.select(Workspace.legal_address).where(Workspace.id == ctx.workspace_id))


def render_template(ctx: Ctx, html: str | None, subject: str | None, preheader: str | None, text_body: str | None,
                    direction: TextDirection, locale: str, name: str, contact_id: uuid.UUID | None) -> dict:
    data = dict(rendering.SAMPLE)
    if contact_id:
        c = get_or_404(ctx.db, Contact, contact_id, "Contact")
        data = rendering.merge_data_for(c, ctx.db.scalar(sa.select(Company.name).where(Company.id == c.company_id)))
    known, unknown = rendering.find_variables(html, subject, text_body, preheader)
    prepared = rendering.prepare_template_html(html or "", direction.value, locale,
                                               rendering.substitute(preheader, data, {}, escape=False),
                                               subject or name, _sender_address(ctx))
    system = {"UnsubscribeUrl": "#unsubscribe-preview", "ViewInBrowserUrl": "#", "SenderAddress":
              _sender_address(ctx) or "", "CurrentYear": str(datetime.now().year)}
    subj, out_html, text = rendering.render_for_recipient(prepared, subject or "", text_body, data, system)
    warnings = []
    if unknown:
        warnings.append(f"Unknown variables will render empty: {', '.join(sorted(unknown))}")
    if not subject:
        warnings.append("Subject is empty")
    if not _sender_address(ctx):
        warnings.append("Workspace has no postal address; add it in Settings (required by anti-spam laws)")
    if len(out_html.encode()) > 102_000:
        warnings.append("HTML is over 102 KB; Gmail will clip the message")
    return {"subject": subj, "html": out_html, "text": text, "variables_used": sorted(known),
            "unknown_variables": sorted(unknown), "warnings": warnings}


# ---------------- templates ----------------

@router.get("/templates")
def list_templates(ctx: Ctx = Viewer, q: str | None = None, page: int = 1, page_size: int = 50,
                   include_drafts: bool = True):
    stmt = sa.select(EmailTemplate).where(EmailTemplate.deleted_at.is_(None)).order_by(EmailTemplate.updated_at.desc())
    if q:
        stmt = stmt.where(EmailTemplate.name.ilike(f"%{q}%"))
    if not include_drafts:
        stmt = stmt.where(EmailTemplate.is_draft.is_(False))
    return paginate(ctx.db, stmt, page, page_size,
                    lambda t: {k: v for k, v in row_dict(t).items() if k not in ("html", "design_json", "text_body")})


@router.get("/templates/variables")
def variables(ctx: Ctx = Viewer):
    return {"contact": [{"name": k, "token": f"{{{{{k}}}}}", "sample": rendering.SAMPLE.get(v)}
                        for k, v in rendering.VARIABLES.items()],
            "system": [{"name": k, "token": f"{{{{{k}}}}}"} for k in sorted(rendering.SYSTEM_VARIABLES)],
            "fallback_syntax": "{{FirstName|there}}"}


@router.post("/templates", status_code=201)
def create_template(body: TemplateIn, ctx: Ctx = Marketer):
    t = EmailTemplate(workspace_id=ctx.workspace_id, created_by=ctx.user.id, **body.model_dump())
    if t.html:
        t.html = rendering.sanitize_html(t.html)
    ctx.db.add(t)
    ctx.db.flush()
    audit(ctx, "create", "template", t.id, after={"name": t.name})
    return row_dict(t)


@router.get("/templates/{template_id}")
def get_template(template_id: uuid.UUID, ctx: Ctx = Viewer):
    return row_dict(get_or_404(ctx.db, EmailTemplate, template_id, "Template"))


@router.patch("/templates/{template_id}")
def update_template(template_id: uuid.UUID, body: TemplateUpdate, ctx: Ctx = Marketer):
    t = get_or_404(ctx.db, EmailTemplate, template_id, "Template")
    data = body.model_dump(exclude_unset=True)
    if data.get("html"):
        data["html"] = rendering.sanitize_html(data["html"])
    for k, v in data.items():
        setattr(t, k, v)
    audit(ctx, "update", "template", t.id, after={k: v for k, v in data.items() if k not in ("html", "design_json")})
    return row_dict(t)


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(template_id: uuid.UUID, ctx: Ctx = Marketer):
    t = get_or_404(ctx.db, EmailTemplate, template_id, "Template")
    t.deleted_at = datetime.now(timezone.utc)
    audit(ctx, "delete", "template", t.id)
    return Response(status_code=204)


@router.post("/templates/{template_id}/duplicate", status_code=201)
def duplicate_template(template_id: uuid.UUID, ctx: Ctx = Marketer):
    t = get_or_404(ctx.db, EmailTemplate, template_id, "Template")
    data = {k: v for k, v in row_dict(t).items() if k in TemplateIn.model_fields}
    new = EmailTemplate(workspace_id=ctx.workspace_id, created_by=ctx.user.id, duplicated_from=t.id,
                        **{**data, "name": f"{t.name} (copy)"[:200], "is_draft": True,
                           "design_json": t.design_json})
    ctx.db.add(new)
    ctx.db.flush()
    audit(ctx, "duplicate", "template", new.id, after={"from": str(t.id)})
    return row_dict(new)


@router.post("/templates/{template_id}/render")
def render(template_id: uuid.UUID, body: RenderIn, ctx: Ctx = Viewer):
    t = get_or_404(ctx.db, EmailTemplate, template_id, "Template")
    return render_template(ctx, body.html if body.html is not None else t.html,
                           body.subject if body.subject is not None else t.subject,
                           body.preheader if body.preheader is not None else t.preheader, t.text_body,
                           body.direction or t.direction, t.locale, t.name, body.contact_id)


@router.post("/templates/render")
def render_unsaved(body: RenderIn, ctx: Ctx = Viewer):
    return render_template(ctx, body.html, body.subject, body.preheader, None,
                           body.direction or TextDirection.LTR, "en", "Preview", body.contact_id)


def send_test(ctx: Ctx, rendered_fn, to: list[str], account_id: uuid.UUID | None, label: str) -> dict:
    account = (get_or_404(ctx.db, SendingAccount, account_id, "Sending account") if account_id else
               ctx.db.scalar(sa.select(SendingAccount).where(SendingAccount.is_default.is_(True))))
    if account is None:
        raise BadRequest("No sending account configured. Add one under Sending Accounts.")
    suppressed = set(ctx.db.scalars(sa.select(Suppression.email).where(Suppression.email.in_(to))))
    if suppressed:
        raise BadRequest(f"Suppressed address(es) cannot receive email: {', '.join(sorted(suppressed))}")
    r = rendered_fn()
    provider = build_provider(account)
    results = []
    try:
        for addr in to:
            try:
                mid = provider.send(OutgoingEmail(
                    from_email=account.from_email, from_name=account.from_name, reply_to=account.reply_to, to=addr,
                    subject=f"[TEST] {r['subject']}", html=r["html"], text=r["text"],
                    tags={"type": "test"}))
                results.append({"to": addr, "ok": True, "message_id": mid})
            except ProviderError as e:
                results.append({"to": addr, "ok": False, "error": str(e)})
    finally:
        provider.close()
    audit(ctx, "test_send", label, after={"to": to, "account": str(account.id),
                                          "ok": all(x["ok"] for x in results)})
    return {"provider": account.provider.value, "from": account.from_email, "results": results,
            "warnings": r["warnings"]}


@router.post("/templates/{template_id}/test-send")
def test_send(template_id: uuid.UUID, body: TestSendIn, ctx: Ctx = Marketer):
    t = get_or_404(ctx.db, EmailTemplate, template_id, "Template")
    return send_test(ctx, lambda: render_template(ctx, t.html, t.subject, t.preheader, t.text_body, t.direction,
                                                  t.locale, t.name, body.contact_id),
                     [str(x) for x in body.to], body.sending_account_id, "template")


@router.get("/templates/{template_id}/usage")
def usage(template_id: uuid.UUID, ctx: Ctx = Viewer):
    get_or_404(ctx.db, EmailTemplate, template_id, "Template")
    return [{"id": str(i), "name": n, "status": s.value} for i, n, s in ctx.db.execute(
        sa.select(Campaign.id, Campaign.name, Campaign.status).where(Campaign.template_id == template_id))]


# ---------------- reusable blocks ----------------

@router.get("/blocks")
def list_blocks(ctx: Ctx = Viewer):
    return [row_dict(b) for b in ctx.db.scalars(sa.select(EmailBlock).where(EmailBlock.is_reusable.is_(True))
                                                .order_by(EmailBlock.block_type, EmailBlock.name))]


@router.post("/blocks", status_code=201)
def create_block(body: BlockIn, ctx: Ctx = Marketer):
    content = dict(body.content)
    if content.get("html"):
        content["html"] = rendering.sanitize_html(content["html"])
    b = EmailBlock(workspace_id=ctx.workspace_id, name=body.name, block_type=body.block_type, content=content,
                   is_reusable=True)
    ctx.db.add(b)
    ctx.db.flush()
    return row_dict(b)


@router.delete("/blocks/{block_id}", status_code=204)
def delete_block(block_id: uuid.UUID, ctx: Ctx = Marketer):
    ctx.db.delete(get_or_404(ctx.db, EmailBlock, block_id, "Block"))
    return Response(status_code=204)


# ---------------- images ----------------

@router.post("/assets", status_code=201)
async def upload_asset(file: UploadFile = File(...), ctx: Ctx = Marketer):
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise BadRequest("Images must be 5 MB or smaller")
    kind = next((t for sig, t in MAGIC.items() if data.startswith(sig)), None)
    if kind is None or (kind == "image/webp" and data[8:12] != b"WEBP"):
        raise BadRequest("Only PNG, JPEG, GIF or WebP images are allowed")
    key = storage.new_key(ctx.workspace_id, "images", (file.filename or "image").rsplit(".", 1)[0] + IMAGE_TYPES[kind])
    storage.put(key, data, kind)
    audit(ctx, "upload", "asset", after={"key": key, "bytes": len(data)})
    return {"key": key, "url": storage.public_url(key), "content_type": kind, "bytes": len(data)}
