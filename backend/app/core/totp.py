"""RFC 6238 time-based one-time passwords (Google Authenticator, Microsoft Authenticator, 1Password...)."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP, DIGITS = 30, 6


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = digest[-1] & 0x0F
    n = (struct.unpack(">I", digest[off:off + 4])[0] & 0x7FFFFFFF) % 10 ** DIGITS
    return str(n).zfill(DIGITS)


def now_code(secret: str, at: float | None = None) -> str:
    return _code(secret, int((at or time.time()) // STEP))


def verify(secret: str, code: str, at: float | None = None, window: int = 1) -> int | None:
    """Return the matched time-step (for replay protection) or None."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != DIGITS:
        return None
    step = int((at or time.time()) // STEP)
    for s in range(step - window, step + window + 1):
        if hmac.compare_digest(_code(secret, s), code):
            return s
    return None


def uri(secret: str, account: str, issuer: str = "Prime CFO Bulk Email") -> str:
    return (f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}&issuer={quote(issuer)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP}")
