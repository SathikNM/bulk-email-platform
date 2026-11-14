"""Passwords (Argon2id), JWT access tokens, opaque refresh tokens, signed public tokens,
and credential encryption (Fernet)."""
import base64
import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_ph = PasswordHasher()
JWT_ALG = "HS256"


# ---------- passwords ----------

def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def validate_password_strength(password: str) -> str | None:
    if len(password) < 10:
        return "Password must be at least 10 characters."
    classes = sum([any(c.islower() for c in password), any(c.isupper() for c in password),
                   any(c.isdigit() for c in password), any(not c.isalnum() for c in password)])
    if classes < 3:
        return "Password must mix at least three of: lower case, upper case, digits, symbols."
    return None


# ---------- access tokens ----------

def create_access_token(user_id: uuid.UUID) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "iat": now, "type": "access",
               "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALG)


def decode_access_token(token: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "access":
        return None
    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        return None


# ---------- refresh tokens ----------

def new_refresh_token() -> tuple[str, str]:
    """Returns (raw token for the client, sha256 hash for storage)."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------- signed public tokens (tracking / unsubscribe) ----------

def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign_payload(data: dict, purpose: str) -> str:
    body = _b64(json.dumps(data, separators=(",", ":")).encode())
    sig = hmac.new(f"{settings.SECRET_KEY}:{purpose}".encode(), body.encode(), hashlib.sha256)
    return f"{body}.{_b64(sig.digest()[:16])}"


def verify_payload(token: str, purpose: str) -> dict | None:
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(f"{settings.SECRET_KEY}:{purpose}".encode(), body.encode(), hashlib.sha256)
    if not hmac.compare_digest(_b64(expected.digest()[:16]), sig):
        return None
    try:
        return json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None


# ---------- credential encryption ----------

def _fernet() -> Fernet:
    key = settings.CREDENTIALS_ENCRYPTION_KEY
    if not key:
        if settings.ENVIRONMENT == "production":
            raise RuntimeError("CREDENTIALS_ENCRYPTION_KEY must be set in production")
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest()).decode()
    return Fernet(key)


def encrypt_json(data: dict) -> bytes:
    return _fernet().encrypt(json.dumps(data).encode())


def decrypt_json(blob: bytes | None) -> dict:
    if not blob:
        return {}
    try:
        return json.loads(_fernet().decrypt(bytes(blob)))
    except InvalidToken as e:
        raise RuntimeError("Stored credentials cannot be decrypted with the current key") from e
