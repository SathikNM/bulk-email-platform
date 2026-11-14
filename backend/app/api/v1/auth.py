"""Authentication: login, refresh-token rotation, logout, profile, password change."""
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from fastapi import APIRouter, Cookie, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import client_ip, current_user, get_db
from app.core.errors import AppError, BadRequest
from app.core.redis import get_redis
from app.core.security import (
    create_access_token,
    hash_password,
    hash_token,
    new_refresh_token,
    validate_password_strength,
    verify_password,
)
from app.models import AuditLog, RefreshToken, User, Workspace, WorkspaceMember

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "bep_refresh"
COOKIE_PATH = "/api/v1/auth"


class LoginIn(BaseModel):
    # Plain string (not EmailStr): sign-in only looks the address up, and seeded/internal
    # accounts may use reserved domains such as .local that strict validation rejects.
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)
    otp: str | None = Field(default=None, max_length=12)


class TotpIn(BaseModel):
    code: str = Field(min_length=6, max_length=12)
    password: str | None = None


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


def _lock_key(email: str) -> str:
    return f"login_fail:{email.lower()}"


def _issue(db: Session, user: User, response: Response) -> dict:
    raw, hashed = new_refresh_token()
    db.add(RefreshToken(user_id=user.id, token_hash=hashed,
                        expires_at=datetime.now(timezone.utc)
                        + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)))
    response.set_cookie(COOKIE, raw, httponly=True, secure=settings.COOKIE_SECURE, samesite="lax",
                        path=COOKIE_PATH, max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400)
    return {"access_token": create_access_token(user.id), "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60, "refresh_token": raw}


def _check_otp(user: User, code: str, secret: str | None = None) -> bool:
    """Verify a TOTP code once (a code can't be replayed within its validity window)."""
    from app.core import totp
    from app.core.security import decrypt_json
    secret = secret or decrypt_json(user.totp_secret_enc).get("secret")
    if not secret:
        return False
    step = totp.verify(secret, code)
    if step is None:
        return False
    return bool(get_redis().set(f"totp_used:{user.id}:{step}", 1, nx=True, ex=120))


def _public(out: dict) -> dict:
    """The refresh token travels only in the httpOnly cookie, never in JSON."""
    return {k: v for k, v in out.items() if k != "refresh_token"}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db, scope="function")):
    r = get_redis()
    key = _lock_key(body.email)
    if int(r.get(key) or 0) >= settings.LOGIN_MAX_FAILURES:
        raise AppError(429, "Too many attempts",
                       f"Account temporarily locked. Try again in {settings.LOGIN_LOCK_MINUTES} minutes.")
    user = db.scalar(sa.select(User).where(User.email == body.email))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, settings.LOGIN_LOCK_MINUTES * 60)
        pipe.execute()
        raise AppError(401, "Unauthorized", "Invalid email or password")
    if user.totp_enabled:
        if not body.otp:
            raise AppError(401, "Two-factor code required", "Enter the 6-digit code from your authenticator app",
                           otp_required=True)
        if not _check_otp(user, body.otp):
            pipe = r.pipeline()
            pipe.incr(key)
            pipe.expire(key, settings.LOGIN_LOCK_MINUTES * 60)
            pipe.execute()
            raise AppError(401, "Unauthorized", "Invalid two-factor code", otp_required=True)
    r.delete(key)
    user.last_login_at = datetime.now(timezone.utc)
    db.add(AuditLog(user_id=user.id, action="login", entity_type="user", entity_id=str(user.id),
                    ip=client_ip(request),
                    user_agent=request.headers.get("user-agent")))
    return _public(_issue(db, user, response))


@router.post("/refresh")
def refresh(response: Response, db: Session = Depends(get_db, scope="function"),
            bep_refresh: str | None = Cookie(default=None)):
    raw = bep_refresh
    if not raw:
        raise AppError(401, "Unauthorized", "Missing refresh token")
    tok = db.scalar(sa.select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw))
                    .with_for_update())
    now = datetime.now(timezone.utc)
    if tok is None or tok.expires_at < now:
        raise AppError(401, "Unauthorized", "Invalid refresh token")
    if tok.revoked_at is not None:
        # Reuse of a rotated token: revoke the whole family (all user sessions).
        db.execute(sa.update(RefreshToken).where(RefreshToken.user_id == tok.user_id,
                                                 RefreshToken.revoked_at.is_(None))
                   .values(revoked_at=now))
        raise AppError(401, "Unauthorized", "Refresh token reuse detected; please sign in again")
    user = db.get(User, tok.user_id)
    if user is None or not user.is_active:
        raise AppError(401, "Unauthorized", "User disabled")
    out = _issue(db, user, response)
    db.flush()
    tok.revoked_at = now
    tok.replaced_by = db.scalar(sa.select(RefreshToken.id).where(
        RefreshToken.token_hash == hash_token(out["refresh_token"])))
    return _public(out)


@router.post("/logout", status_code=204)
def logout(response: Response, db: Session = Depends(get_db, scope="function"),
           bep_refresh: str | None = Cookie(default=None)):
    if bep_refresh:
        db.execute(sa.update(RefreshToken).where(RefreshToken.token_hash == hash_token(bep_refresh))
                   .values(revoked_at=datetime.now(timezone.utc)))
    response.delete_cookie(COOKIE, path=COOKIE_PATH)
    response.status_code = 204
    return response


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")):
    if user.is_superadmin:
        rows = db.execute(sa.select(Workspace, WorkspaceMember.role).outerjoin(
            WorkspaceMember, sa.and_(WorkspaceMember.workspace_id == Workspace.id,
                                     WorkspaceMember.user_id == user.id))
            .order_by(Workspace.name)).all()
    else:
        rows = db.execute(sa.select(Workspace, WorkspaceMember.role).join(
            WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user.id).order_by(Workspace.name)).all()
    return {
        "id": str(user.id), "email": user.email, "full_name": user.full_name,
        "is_superadmin": user.is_superadmin, "totp_enabled": user.totp_enabled,
        "workspaces": [{"id": str(w.id), "name": w.name, "slug": w.slug,
                        "role": (role.value if role else "owner"),
                        "default_locale": w.default_locale} for w, role in rows],
    }


@router.post("/change-password", status_code=204)
def change_password(body: PasswordChangeIn, user: User = Depends(current_user),
                    db: Session = Depends(get_db, scope="function")):
    if not verify_password(body.current_password, user.password_hash):
        raise BadRequest("Current password is incorrect")
    if err := validate_password_strength(body.new_password):
        raise BadRequest(err)
    user.password_hash = hash_password(body.new_password)
    db.execute(sa.update(RefreshToken).where(RefreshToken.user_id == user.id,
                                             RefreshToken.revoked_at.is_(None))
               .values(revoked_at=datetime.now(timezone.utc)))
    return Response(status_code=204)


@router.post("/2fa/setup")
def totp_setup(user: User = Depends(current_user)):
    """Start enrolment: a new secret, held for 10 minutes until confirmed with a code."""
    from app.core import totp
    secret = totp.new_secret()
    get_redis().set(f"totp_pending:{user.id}", secret, ex=600)
    return {"secret": secret, "otpauth_uri": totp.uri(secret, user.email)}


@router.post("/2fa/enable", status_code=204)
def totp_enable(body: TotpIn, request: Request, user: User = Depends(current_user),
                db: Session = Depends(get_db, scope="function")):
    from app.core.security import encrypt_json
    pending = get_redis().get(f"totp_pending:{user.id}")
    secret = pending.decode() if isinstance(pending, bytes) else pending
    if not secret:
        raise BadRequest("Setup expired: start again")
    if not _check_otp(user, body.code, secret):
        raise BadRequest("That code is not valid: check the time on your phone and try the newest code")
    user.totp_secret_enc = encrypt_json({"secret": secret})
    user.totp_enabled = True
    get_redis().delete(f"totp_pending:{user.id}")
    db.add(AuditLog(user_id=user.id, action="2fa_enabled", entity_type="user", entity_id=str(user.id),
                    ip=client_ip(request)))
    return Response(status_code=204)


@router.post("/2fa/disable", status_code=204)
def totp_disable(body: TotpIn, request: Request, user: User = Depends(current_user),
                 db: Session = Depends(get_db, scope="function")):
    if not user.totp_enabled:
        return Response(status_code=204)
    if not body.password or not verify_password(body.password, user.password_hash):
        raise BadRequest("Current password is incorrect")
    if not _check_otp(user, body.code):
        raise BadRequest("Invalid two-factor code")
    user.totp_enabled, user.totp_secret_enc = False, None
    db.add(AuditLog(user_id=user.id, action="2fa_disabled", entity_type="user", entity_id=str(user.id),
                    ip=client_ip(request)))
    return Response(status_code=204)
