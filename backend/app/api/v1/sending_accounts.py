"""Sending accounts (SES / SMTP). Credentials are encrypted at rest and never returned."""
import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Response
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy.exc import IntegrityError

from app.core.deps import Admin, Ctx, Viewer
from app.core.errors import BadRequest, Conflict
from app.core.security import decrypt_json, encrypt_json
from app.models import Campaign, SendingAccount
from app.models.enums import IdentityStatus, Provider
from app.providers import ProviderError, build_provider
from app.services.common import audit, get_or_404, row_dict

router = APIRouter(prefix="/sending-accounts", tags=["sending accounts"])


class SESCreds(BaseModel):
    access_key_id: str | None = None
    secret_access_key: str | None = None


class SMTPCreds(BaseModel):
    host: str
    port: int = Field(587, ge=1, le=65535)
    username: str | None = None
    password: str | None = None
    security: str = Field("starttls", pattern="^(starttls|ssl|none)$")


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    provider: Provider
    from_email: EmailStr
    from_name: str | None = Field(default=None, max_length=200)
    reply_to: EmailStr | None = None
    region: str | None = None
    configuration_set: str | None = None
    max_per_second: int = Field(1, ge=1, le=500)
    max_per_day: int = Field(200, ge=1, le=10_000_000)
    is_default: bool = False
    credentials: dict | None = None

    @model_validator(mode="after")
    def _creds(self):
        if self.credentials is not None:
            (SESCreds if self.provider == Provider.SES else SMTPCreds).model_validate(self.credentials)
        if self.provider == Provider.SES and not self.region:
            raise ValueError("region is required for SES")
        return self


class AccountUpdate(BaseModel):
    name: str | None = None
    from_name: str | None = None
    reply_to: EmailStr | None = None
    region: str | None = None
    configuration_set: str | None = None
    max_per_second: int | None = Field(default=None, ge=1, le=500)
    max_per_day: int | None = Field(default=None, ge=1, le=10_000_000)
    is_default: bool | None = None
    credentials: dict | None = None  # replaces stored credentials when provided


def _out(a: SendingAccount) -> dict:
    d = row_dict(a)
    creds = decrypt_json(a.encrypted_credentials)
    d["credentials_set"] = bool(creds)
    d["credentials_hint"] = {k: ("••••" if k in ("password", "secret_access_key") else v)
                             for k, v in creds.items() if v}
    return d


def _make_default(ctx: Ctx, a: SendingAccount):
    ctx.db.execute(sa.update(SendingAccount).where(SendingAccount.id != a.id).values(is_default=False))
    a.is_default = True


@router.get("")
def list_accounts(ctx: Ctx = Viewer):
    return [_out(a) for a in ctx.db.scalars(sa.select(SendingAccount).order_by(SendingAccount.name))]


@router.post("", status_code=201)
def create_account(body: AccountIn, ctx: Ctx = Admin):
    data = body.model_dump(exclude={"credentials", "is_default"})
    a = SendingAccount(workspace_id=ctx.workspace_id, domain=body.from_email.split("@", 1)[1].lower(),
                       encrypted_credentials=encrypt_json(body.credentials) if body.credentials else None, **data)
    try:
        with ctx.db.begin_nested():
            ctx.db.add(a)
            ctx.db.flush()
    except IntegrityError:
        raise Conflict("A sending account with this from address already exists") from None
    first = ctx.db.scalar(sa.select(sa.func.count()).select_from(SendingAccount)) == 1
    if body.is_default or first:
        _make_default(ctx, a)
    audit(ctx, "create", "sending_account", a.id, after=_out(a))
    return _out(a)


@router.patch("/{account_id}")
def update_account(account_id: uuid.UUID, body: AccountUpdate, ctx: Ctx = Admin):
    a = get_or_404(ctx.db, SendingAccount, account_id, "Sending account")
    before = _out(a)
    data = body.model_dump(exclude_unset=True, exclude={"credentials", "is_default"})
    for k, v in data.items():
        setattr(a, k, v)
    if body.credentials is not None:
        # Merge: fields left blank keep their stored value (secrets are never sent back to the
        # browser, so an edit form cannot resend them).
        merged = {**decrypt_json(a.encrypted_credentials),
                  **{k: v for k, v in body.credentials.items() if v not in (None, "")}}
        (SESCreds if a.provider == Provider.SES else SMTPCreds).model_validate(merged)
        a.encrypted_credentials = encrypt_json(merged)
        a.verification_status = IdentityStatus.PENDING
    if body.is_default:
        _make_default(ctx, a)
    audit(ctx, "update", "sending_account", a.id, before, _out(a))
    return _out(a)


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: uuid.UUID, ctx: Ctx = Admin):
    a = get_or_404(ctx.db, SendingAccount, account_id, "Sending account")
    if ctx.db.scalar(sa.select(Campaign.id).where(Campaign.sending_account_id == a.id).limit(1)):
        raise Conflict("Account is referenced by campaigns; it cannot be deleted (history must be kept)")
    ctx.db.delete(a)
    audit(ctx, "delete", "sending_account", account_id)
    return Response(status_code=204)


@router.post("/{account_id}/verify")
def verify_account(account_id: uuid.UUID, ctx: Ctx = Admin):
    a = get_or_404(ctx.db, SendingAccount, account_id, "Sending account")
    if not a.encrypted_credentials and a.provider == Provider.SMTP:
        raise BadRequest("Set SMTP credentials first")
    provider = build_provider(a)
    try:
        result = provider.verify()
    except ProviderError as e:
        a.verification_status = IdentityStatus.FAILED
        audit(ctx, "verify_failed", "sending_account", a.id, after={"error": str(e)})
        return {"ok": False, "error": str(e), "dns_records": _guidance(a)}
    finally:
        provider.close()
    a.verification_status = IdentityStatus.VERIFIED if result.get("ok") else IdentityStatus.PENDING
    a.dns_records = result.get("dns_records") or _guidance(a)
    return {**result, "dns_records": a.dns_records}


@router.get("/{account_id}/quota")
def quota(account_id: uuid.UUID, ctx: Ctx = Admin):
    a = get_or_404(ctx.db, SendingAccount, account_id, "Sending account")
    provider = build_provider(a)
    try:
        q = provider.quota()
    except ProviderError as e:
        raise BadRequest(str(e)) from None
    from app.services.sending import sent_today
    return {**q, "configured_max_per_day": a.max_per_day, "configured_max_per_second": a.max_per_second,
            "sent_today_by_platform": sent_today(a.id)}


def _guidance(a: SendingAccount) -> list[dict]:
    """Generic SPF/DKIM/DMARC guidance for SMTP relays (provider-specific values vary)."""
    d = a.domain
    return [
        {"type": "TXT", "name": d, "value": "v=spf1 include:<your-provider-spf-domain> ~all",
         "purpose": "SPF: authorise your SMTP relay to send for this domain"},
        {"type": "TXT/CNAME", "name": f"<selector>._domainkey.{d}", "value": "<public key from your provider>",
         "purpose": "DKIM: sign messages; get the selector and key from your provider"},
        {"type": "TXT", "name": f"_dmarc.{d}", "value": f"v=DMARC1; p=none; rua=mailto:dmarc@{d}; fo=1",
         "purpose": "DMARC: start with p=none, then tighten to quarantine/reject"},
    ]
