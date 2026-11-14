"""Email verification: syntax, disposable/role detection, and DNS MX/A lookup.

Results: valid (domain accepts mail), invalid (bad syntax or domain does not exist / null MX),
risky (role account, disposable domain, or no MX but has A record). DNS failures that are
not definitive (timeouts, no resolver) leave the status unchanged.
"""
from functools import lru_cache

import dns.exception
import dns.resolver
from email_validator import EmailNotValidError, validate_email

from app.models.enums import VerificationStatus
from app.services.common import is_role_account

DISPOSABLE = {"mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com", "yopmail.com",
              "trashmail.com", "sharklasers.com", "getnada.com", "temp-mail.org", "dispostable.com"}


@lru_cache(maxsize=4096)
def _domain_status(domain: str) -> str:
    resolver = dns.resolver.Resolver()
    resolver.lifetime = 4.0
    try:
        answers = resolver.resolve(domain, "MX")
        hosts = [str(r.exchange).rstrip(".") for r in answers]
        if hosts == [""] or hosts == ["."]:
            return "null_mx"
        return "mx"
    except dns.resolver.NXDOMAIN:
        return "nxdomain"
    except dns.resolver.NoAnswer:
        try:
            resolver.resolve(domain, "A")
            return "a_only"
        except dns.resolver.NXDOMAIN:
            return "nxdomain"
        except (dns.resolver.NoAnswer, dns.resolver.NoNameservers):
            return "no_mail"
        except dns.exception.DNSException:
            return "unknown"
    except (dns.resolver.NoNameservers, dns.exception.Timeout, dns.exception.DNSException):
        return "unknown"


def verify(email: str) -> tuple[VerificationStatus | None, str]:
    """Returns (status or None if inconclusive, reason)."""
    try:
        normalized = validate_email(email, check_deliverability=False).normalized
    except EmailNotValidError as e:
        return VerificationStatus.INVALID, f"syntax: {e}"
    domain = normalized.split("@", 1)[1].lower()
    if domain in DISPOSABLE:
        return VerificationStatus.RISKY, "disposable domain"
    status = _domain_status(domain)
    if status in ("nxdomain", "null_mx", "no_mail"):
        return VerificationStatus.INVALID, f"domain: {status}"
    if status == "unknown":
        return None, "dns lookup inconclusive"
    if is_role_account(normalized):
        return VerificationStatus.RISKY, "role account"
    if status == "a_only":
        return VerificationStatus.RISKY, "no MX record (A record only)"
    return VerificationStatus.VALID, "mx found"
