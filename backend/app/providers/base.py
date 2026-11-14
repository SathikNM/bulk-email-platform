"""Email provider abstraction. Messages are built once as MIME and handed to the provider."""
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, make_msgid


class ProviderError(Exception):
    """Base provider failure."""


class TransientError(ProviderError):
    """Retry later (throttling, timeouts, 4xx SMTP, 5xx service)."""


class PermanentError(ProviderError):
    """Do not retry this recipient (rejected address/content)."""


class AccountError(ProviderError):
    """The sending account itself is unusable (unverified, paused, bad credentials): pause the campaign."""


@dataclass
class OutgoingEmail:
    from_email: str
    to: str
    subject: str
    html: str
    text: str
    from_name: str | None = None
    reply_to: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)

    def to_mime(self, domain: str | None = None) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = formataddr((self.from_name, self.from_email)) if self.from_name else self.from_email
        msg["To"] = self.to
        msg["Subject"] = self.subject
        msg["Message-ID"] = make_msgid(domain=domain or self.from_email.split("@", 1)[1])
        if self.reply_to:
            msg["Reply-To"] = self.reply_to
        for k, v in self.headers.items():
            msg[k] = v
        msg.set_content(self.text or " ", charset="utf-8")
        msg.add_alternative(self.html, subtype="html", charset="utf-8")
        return msg


class EmailProvider:
    name = "base"

    def send(self, email: OutgoingEmail) -> str:  # returns provider message id
        raise NotImplementedError

    def verify(self) -> dict:
        """Check credentials/identity. Returns details incl. DNS records where applicable."""
        raise NotImplementedError

    def quota(self) -> dict:
        return {}

    def close(self) -> None:
        pass
