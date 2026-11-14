"""Provider factory: builds a provider from a SendingAccount (decrypting its credentials)."""
from app.core.security import decrypt_json
from app.models import SendingAccount
from app.models.enums import Provider
from app.providers.base import (
    AccountError,
    EmailProvider,
    OutgoingEmail,
    PermanentError,
    ProviderError,
    TransientError,
)

__all__ = ["build_provider", "EmailProvider", "OutgoingEmail", "ProviderError", "TransientError",
           "PermanentError", "AccountError"]


def build_provider(account: SendingAccount) -> EmailProvider:
    creds = decrypt_json(account.encrypted_credentials)
    if account.provider == Provider.SES:
        from app.providers.ses import SESProvider
        return SESProvider(region=account.region or "eu-west-1", access_key_id=creds.get("access_key_id"),
                           secret_access_key=creds.get("secret_access_key"),
                           configuration_set=account.configuration_set, domain=account.domain)
    if account.provider == Provider.DIRECT:
        from app.providers.direct import DirectProvider
        return DirectProvider(domain=account.domain, helo_hostname=creds.get("helo_hostname"),
                              dkim_selector=creds.get("dkim_selector") or "bep",
                              dkim_private_key=creds.get("dkim_private_key"),
                              return_path_domain=creds.get("return_path_domain"))
    from app.providers.smtp import SMTPProvider
    return SMTPProvider(host=creds.get("host", "localhost"), port=int(creds.get("port", 587)),
                        username=creds.get("username"), password=creds.get("password"),
                        security=creds.get("security", "starttls"))
