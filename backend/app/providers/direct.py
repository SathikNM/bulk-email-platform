"""Direct delivery: the platform is its own mail server (no relay, no third-party service).

For each recipient it looks up the domain's MX hosts and delivers over SMTP port 25 with
opportunistic STARTTLS, signing every message with the sending domain's DKIM key.

Deliverability depends on infrastructure the platform cannot create by itself: a fixed public IP
whose reverse DNS (PTR) matches the HELO hostname, an SPF record listing that IP, the DKIM TXT record,
and a DMARC record. verify() checks all of them and returns the exact records to publish.
"""
from __future__ import annotations

import base64
import smtplib
import socket
import ssl
import time
from datetime import datetime, timezone
from email import policy as email_policy
from email.utils import formatdate

import dns.exception
import dns.resolver
import dns.reversename
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.providers.base import AccountError, EmailProvider, OutgoingEmail, PermanentError, TransientError

SIGNED_HEADERS = [b"from", b"to", b"subject", b"date", b"message-id", b"reply-to", b"mime-version",
                  b"content-type", b"list-unsubscribe", b"list-unsubscribe-post"]

# Gradual daily ramp for a new sending IP (day index -> max emails that day).
WARMUP_SCHEDULE = [(0, 50), (2, 100), (4, 250), (6, 500), (8, 1000), (11, 2000), (14, 3500),
                   (17, 5000), (20, 7500), (23, 10000), (27, 15000), (31, 25000), (35, 50000)]


SMTP_PORT = 25  # overridable in tests


class HardBounce(PermanentError):
    """The recipient address does not exist: suppress it."""


def generate_dkim_key() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()


def dkim_public_record(private_pem: str) -> str:
    key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    der = key.public_key().public_bytes(serialization.Encoding.DER,
                                        serialization.PublicFormat.SubjectPublicKeyInfo)
    return f"v=DKIM1; k=rsa; p={base64.b64encode(der).decode()}"


def warmup_limit(started: datetime | None, now: datetime | None = None) -> int | None:
    """Daily cap during warm-up, or None once warm-up is complete."""
    if started is None:
        return None
    day = ((now or datetime.now(timezone.utc)) - started).days
    if day > WARMUP_SCHEDULE[-1][0]:
        return None
    cap = WARMUP_SCHEDULE[0][1]
    for d, n in WARMUP_SCHEDULE:
        if day >= d:
            cap = n
    return cap


def _resolver() -> dns.resolver.Resolver:
    r = dns.resolver.Resolver()
    r.lifetime = 8.0
    return r


def _txt(name: str) -> list[str]:
    try:
        return [b"".join(r.strings).decode(errors="replace") for r in _resolver().resolve(name, "TXT")]
    except (dns.exception.DNSException, OSError):
        return []


def mx_hosts(domain: str) -> list[str]:
    """MX hosts in preference order; implicit MX (the domain itself) when none are published."""
    try:
        answers = sorted(_resolver().resolve(domain, "MX"), key=lambda r: r.preference)
    except dns.resolver.NXDOMAIN as e:
        raise HardBounce(f"Domain {domain} does not exist") from e
    except dns.resolver.NoAnswer:
        return [domain]
    except (dns.exception.DNSException, OSError) as e:
        raise TransientError(f"MX lookup failed for {domain}: {e}") from e
    hosts = [str(r.exchange).rstrip(".") for r in answers]
    if hosts == [""] or hosts == ["."]:
        raise HardBounce(f"{domain} does not accept email (null MX)")
    return hosts


def _mx_group(host: str) -> str:
    parts = host.lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _classify(code: int, text: str, where: str) -> Exception:
    """Map an SMTP reply to the platform's error classes."""
    msg = f"{where} {code}: {text[:300]}"
    if 400 <= code < 500:
        return TransientError(msg)
    low = text.lower()
    if code in (550, 551, 553) and ("5.1.1" in text or "5.1.0" in text or "5.1.10" in text or "does not exist"
                                     in low or "no such user" in low or "user unknown" in low
                                     or "recipient not found" in low or "address rejected" in low):
        return HardBounce(msg)
    return PermanentError(msg)


class DirectProvider(EmailProvider):
    name = "direct"

    def __init__(self, domain: str, helo_hostname: str | None, dkim_selector: str, dkim_private_key: str | None,
                 timeout: float = 30.0, rate_per_group: int = 2, port: int | None = None,
                 return_path_domain: str | None = None):
        self.domain = domain.lower()
        # Envelope sender (bounce) domain, e.g. news.primecfo.sa: SPF is checked on it, so the main
        # domain's SPF (Outlook etc.) stays untouched while From: stays info@<domain> (DMARC aligns via DKIM).
        self.rp = (return_path_domain or "").strip().lower() or None
        self.helo = (helo_hostname or f"mail.{self.domain}").strip().lower()
        self.selector = (dkim_selector or "bep").strip()
        self.key = dkim_private_key
        self.timeout, self.rate_per_group, self.port = timeout, rate_per_group, port or SMTP_PORT
        self._conns: dict[str, smtplib.SMTP] = {}
        self._mx_cache: dict[str, list[str]] = {}

    # ---------- signing ----------
    def sign(self, raw: bytes) -> bytes:
        if not self.key:
            raise AccountError("No DKIM key: open the account and save it once to generate one")
        import dkim
        sig = dkim.sign(raw, self.selector.encode(), self.domain.encode(), self.key.encode(),
                        include_headers=SIGNED_HEADERS, canonicalize=(b"relaxed", b"relaxed"))
        return sig + raw

    # ---------- transport ----------
    def _pace(self, group: str) -> None:
        """Per-destination limit (e.g. google.com, outlook.com) shared by all workers."""
        try:
            from app.core.redis import get_redis
            r = get_redis()
        except Exception:  # noqa: BLE001 - Redis optional (pacing is best-effort)
            return
        while True:
            sec = int(time.time())
            key = f"rate:direct:{self.domain}:{group}:{sec}"
            try:
                n = r.incr(key)
                if n == 1:
                    r.expire(key, 3)
            except Exception:  # noqa: BLE001 - pacing is best-effort; never block delivery on Redis
                return
            if n <= self.rate_per_group:
                return
            time.sleep(max(0.0, sec + 1 - time.time()) + 0.01)

    def _open(self, host: str) -> smtplib.SMTP:
        conn = self._conns.get(host)
        if conn is not None:
            try:
                if conn.noop()[0] == 250:
                    return conn
            except (smtplib.SMTPException, OSError):
                pass
            self._conns.pop(host, None)
        conn = smtplib.SMTP(host, self.port, local_hostname=self.helo, timeout=self.timeout)
        conn.ehlo()
        if conn.has_extn("starttls"):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False          # opportunistic TLS (RFC 3207): encrypt, don't
            ctx.verify_mode = ssl.CERT_NONE     # fail delivery on a mismatched MX certificate
            conn.starttls(context=ctx)
            conn.ehlo()
        self._conns[host] = conn
        return conn

    def envelope_sender(self, email: OutgoingEmail) -> str:
        """VERP address on the bounce subdomain (identifies the recipient in late bounces)."""
        if not self.rp:
            return email.from_email
        rid = email.tags.get("recipient")
        if rid:
            from app.services.bounces import verp_address
            return verp_address(rid, self.rp)
        return f"bounces@{self.rp}"

    def send(self, email: OutgoingEmail) -> str:
        msg = email.to_mime(domain=self.domain)
        if "Date" not in msg:
            msg["Date"] = formatdate(localtime=False)
        raw = self.sign(msg.as_bytes(policy=email_policy.SMTP))  # CRLF line endings, as sent on the wire
        rcpt_domain = email.to.rsplit("@", 1)[-1].lower()
        hosts = self._mx_cache.get(rcpt_domain) or mx_hosts(rcpt_domain)
        self._mx_cache[rcpt_domain] = hosts
        last: Exception | None = None
        for host in hosts[:4]:
            self._pace(_mx_group(host))
            try:
                conn = self._open(host)
                conn.sendmail(self.envelope_sender(email), [email.to], raw)
                return msg["Message-ID"].strip("<>")
            except smtplib.SMTPRecipientsRefused as e:
                code, text = next(iter(e.recipients.values()))
                raise _classify(code, text.decode(errors="replace"), "Recipient refused") from e
            except smtplib.SMTPSenderRefused as e:
                err = _classify(e.smtp_code, e.smtp_error.decode(errors="replace"), "Sender refused")
                raise (err if isinstance(err, TransientError) else PermanentError(str(err))) from e
            except smtplib.SMTPDataError as e:
                raise _classify(e.smtp_code, e.smtp_error.decode(errors="replace"), "Message rejected") from e
            except smtplib.SMTPResponseException as e:
                self._conns.pop(host, None)
                last = _classify(e.smtp_code, e.smtp_error.decode(errors="replace"), f"{host} refused connection")
                if isinstance(last, PermanentError):
                    raise last from e
            except (TimeoutError, smtplib.SMTPException, OSError) as e:
                self._conns.pop(host, None)
                last = TransientError(f"Could not deliver via {host}: {e}")
        raise last or TransientError(f"No mail server reachable for {rcpt_domain}")

    def close(self) -> None:
        for c in self._conns.values():
            try:
                c.quit()
            except (smtplib.SMTPException, OSError):
                pass
        self._conns.clear()

    # ---------- readiness checks ----------
    @staticmethod
    def public_ip() -> str | None:
        import httpx
        for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
            try:
                ip = httpx.get(url, timeout=8).text.strip()
                socket.inet_aton(ip)
                return ip
            except Exception:  # noqa: BLE001, S112 - try the next IP echo service
                continue
        return None

    def verify(self) -> dict:
        checks: list[dict] = []

        def add(name, ok, detail):
            checks.append({"check": name, "ok": bool(ok), "detail": detail})

        ip = self.public_ip()
        add("Public IP", ip, ip or "Could not determine the server's public IP")

        ptr = None
        if ip:
            try:
                ptr = str(_resolver().resolve(dns.reversename.from_address(ip), "PTR")[0]).rstrip(".").lower()
            except (dns.exception.DNSException, OSError):
                ptr = None
        add("Reverse DNS (PTR)", ptr and ptr == self.helo,
            f"{ip} → {ptr}" if ptr else f"{ip} has no reverse DNS; ask your ISP/host to set it to {self.helo}")

        try:
            a_ips = {str(r) for r in _resolver().resolve(self.helo, "A")}
        except (dns.exception.DNSException, OSError):
            a_ips = set()
        add("HELO hostname", ip in a_ips, f"{self.helo} → {', '.join(sorted(a_ips)) or 'not found'}")

        spf_domain = self.rp or self.domain
        spf = next((t for t in _txt(spf_domain) if t.lower().startswith("v=spf1")), None)
        add("SPF" + (f" ({spf_domain})" if self.rp else ""), spf and ip and f"ip4:{ip}" in spf, spf or f"No SPF record on {spf_domain}")

        pub = dkim_public_record(self.key) if self.key else None
        dk = " ".join(_txt(f"{self.selector}._domainkey.{self.domain}")).replace(" ", "")
        add("DKIM", pub and pub.replace(" ", "").split("p=")[1] in dk, "Published and matching" if pub and dk
            and pub.replace(" ", "").split("p=")[1] in dk else ("Published but different key" if dk else "Not published"))

        dmarc = next((t for t in _txt(f"_dmarc.{self.domain}") if t.lower().startswith("v=dmarc1")), None)
        add("DMARC", dmarc, dmarc or "No DMARC record")

        try:
            c = smtplib.SMTP("gmail-smtp-in.l.google.com", 25, local_hostname=self.helo, timeout=12)
            c.ehlo()
            c.quit()
            add("Outbound port 25", True, "Open")
        except (smtplib.SMTPException, OSError) as e:
            add("Outbound port 25", False, f"Blocked: {e}")

        ok = all(c["ok"] for c in checks)
        failing = [c["check"] for c in checks if not c["ok"]]
        return {"ok": ok, "checks": checks, "dns_records": self.dns_records(ip, spf, dmarc),
                "error": None if ok else "Not ready for direct delivery: fix " + ", ".join(failing)}

    def dns_records(self, ip: str | None, spf: str | None = None, dmarc: str | None = None) -> list[dict]:
        ip_s = ip or "<server public IP>"
        if spf and f"ip4:{ip_s}" not in spf:
            spf_value = spf.replace("v=spf1", f"v=spf1 ip4:{ip_s}", 1)
        else:
            spf_value = spf or f"v=spf1 ip4:{ip_s} -all"
        recs = [
            {"type": "A", "name": self.helo, "value": ip_s,
             "purpose": "Name of this mail server (HELO)"},
            {"type": "PTR", "name": ip_s, "value": self.helo,
             "purpose": "Reverse DNS: set by your internet provider / server host, not in your DNS zone"},
        ]
        if self.rp:
            recs += [{"type": "A", "name": self.rp, "value": ip_s,
                      "purpose": "Bounce (envelope) domain: must exist"},
                     {"type": "TXT", "name": self.rp, "value": spf_value,
                      "purpose": f"SPF for the bounce domain only; the SPF of {self.domain} stays unchanged"}]
        else:
            recs.append({"type": "TXT", "name": self.domain, "value": spf_value,
                         "purpose": "SPF: replace the existing SPF record with this one (keeps your current senders)"})
        if self.key:
            recs.append({"type": "TXT", "name": f"{self.selector}._domainkey.{self.domain}",
                         "value": dkim_public_record(self.key), "purpose": "DKIM: signature key for this domain"})
        recs.append({"type": "TXT", "name": f"_dmarc.{self.domain}",
                     "value": dmarc or f"v=DMARC1; p=none; rua=mailto:dmarc@{self.domain}; fo=1",
                     "purpose": "DMARC: start with p=none, tighten to quarantine after warm-up"})
        return recs
