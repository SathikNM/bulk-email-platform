"""Security headers, request IDs, structured access logs and Redis rate limiting."""
import json
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings

log = logging.getLogger("bep.access")

# (path prefix, method or None, limit per window, window seconds)
RATE_RULES = [
    ("/api/v1/auth/login", "POST", 20, 60),
    ("/api/v1/auth/refresh", "POST", 60, 60),
    ("/api/v1/ai/", None, 20, 60),
    ("/webhooks/", None, 600, 60),
    ("/u/", None, 60, 60),
    ("/t/", None, 1200, 60),
    ("/api/v1/", None, 900, 60),
]


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        start = time.perf_counter()
        response = await call_next(request)
        h = response.headers
        h["X-Request-ID"] = rid
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if not request.url.path.startswith(("/api/docs", "/u/")):
            h.setdefault("Content-Security-Policy", "default-src 'none'; img-src 'self' data:; frame-ancestors 'none'")
        if settings.ENVIRONMENT == "production":
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.url.path.startswith("/api/"):
            h.setdefault("Cache-Control", "no-store")
        if settings.ENVIRONMENT != "test":
            log.info(json.dumps({"rid": rid, "method": request.method, "path": request.url.path,
                                 "status": response.status_code,
                                 "ms": round((time.perf_counter() - start) * 1000, 1)}))
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window limiter per client IP and rule. Fails open if Redis is unavailable."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path, method = request.url.path, request.method
        rule = next((r for r in RATE_RULES if path.startswith(r[0]) and (r[1] is None or r[1] == method)), None)
        if rule is None or request.method == "OPTIONS" or not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)
        prefix, _, limit, window = rule
        ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
              or (request.client.host if request.client else "unknown"))
        key = f"rl:{prefix}:{ip}:{int(time.time() // window)}"
        try:
            from app.core.redis import get_redis
            r = get_redis()
            n = r.incr(key)
            if n == 1:
                r.expire(key, window + 1)
        except Exception:  # noqa: BLE001 - never take the API down because Redis blipped
            return await call_next(request)
        if n > limit:
            retry = window - int(time.time()) % window
            return JSONResponse({"type": "about:blank", "title": "Too many requests", "status": 429,
                                 "detail": f"Rate limit exceeded. Retry in {retry}s."},
                                status_code=429, headers={"Retry-After": str(retry)},
                                media_type="application/problem+json")
        return await call_next(request)


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def validate_production_settings() -> list[str]:
    """Return configuration problems that must block a production start."""
    problems = []
    if settings.ENVIRONMENT != "production":
        return problems
    if settings.SECRET_KEY.startswith("change-me") or len(settings.SECRET_KEY) < 32:
        problems.append("SECRET_KEY must be a random value of at least 32 characters")
    if not settings.CREDENTIALS_ENCRYPTION_KEY:
        problems.append("CREDENTIALS_ENCRYPTION_KEY must be set (Fernet key)")
    if not settings.COOKIE_SECURE:
        problems.append("COOKIE_SECURE must be true (HTTPS only)")
    if not settings.PUBLIC_BASE_URL.startswith("https://"):
        problems.append("PUBLIC_BASE_URL must be https:// (tracking/unsubscribe links)")
    if not settings.SES_WEBHOOK_VERIFY_SIGNATURE:
        problems.append("SES_WEBHOOK_VERIFY_SIGNATURE must stay enabled")
    if settings.CELERY_TASK_ALWAYS_EAGER:
        problems.append("CELERY_TASK_ALWAYS_EAGER must be false (use real workers)")
    return problems
