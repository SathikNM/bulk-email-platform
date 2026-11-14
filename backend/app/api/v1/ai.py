"""AI writing assistant (Anthropic Messages API). Disabled (HTTP 503) when no API key is configured."""
import json
import re

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.deps import Ctx, Marketer
from app.core.errors import AppError
from app.services.common import audit

router = APIRouter(prefix="/ai", tags=["ai assistant"])

KINDS = {
    "subject": "5 distinct email subject lines (max 60 characters each)",
    "body": "1 complete professional email body in simple HTML (p, ul, li, strong, a only)",
    "marketing": "1 persuasive marketing message in simple HTML (p, ul, li, strong, a only)",
    "follow_up": "1 polite follow-up email body in simple HTML (p, strong, a only)",
    "cta": "5 short call-to-action button labels (max 4 words each)",
}


class GenerateIn(BaseModel):
    kind: str = Field(pattern="^(subject|body|marketing|follow_up|cta)$")
    language: str = Field("en", pattern="^(en|ar)$")
    tone: str = Field("professional", max_length=40)
    context: str = Field(min_length=10, max_length=4000)
    audience: str | None = Field(default=None, max_length=300)


@router.get("/status")
def status(ctx: Ctx = Marketer):
    return {"enabled": bool(settings.LLM_API_KEY), "model": settings.LLM_MODEL if settings.LLM_API_KEY else None}


@router.post("/generate")
def generate(body: GenerateIn, ctx: Ctx = Marketer):
    if not settings.LLM_API_KEY:
        raise AppError(503, "AI assistant not configured", "Set LLM_API_KEY on the server to enable the AI assistant.")
    lang = "Modern Standard Arabic" if body.language == "ar" else "English"
    system = ("You write B2B marketing emails for a company that serves clients in the GCC and beyond. "
              "Be accurate and specific; never invent statistics, prices, dates or testimonials. "
              "You may use personalisation tokens exactly as written: {{FirstName}}, {{CompanyName}}, {{JobTitle}}. "
              "Never include an unsubscribe link (the platform adds it). "
              'Reply with JSON only: {"suggestions": ["..."]}')
    prompt = (f"Write {KINDS[body.kind]} in {lang}. Tone: {body.tone}.\n"
              f"Audience: {body.audience or 'business decision makers'}.\nBrief:\n{body.context}")
    try:
        r = httpx.post(settings.LLM_API_URL, timeout=60, headers={
            "x-api-key": settings.LLM_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": settings.LLM_MODEL, "max_tokens": 1500, "system": system,
                  "messages": [{"role": "user", "content": prompt}]})
    except httpx.HTTPError as e:
        raise AppError(502, "AI provider unreachable", str(e)) from None
    if r.status_code != 200:
        raise AppError(502, "AI provider error", r.text[:300])
    text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    try:
        suggestions = json.loads(m.group(0))["suggestions"] if m else [text.strip()]
    except (json.JSONDecodeError, KeyError, TypeError):
        suggestions = [text.strip()]
    audit(ctx, "ai_generate", "ai", after={"kind": body.kind, "language": body.language})
    return {"kind": body.kind, "language": body.language, "suggestions": [str(s) for s in suggestions][:10]}
