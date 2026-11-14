"""Amazon SES (v2 API) provider. Sends raw MIME so List-Unsubscribe headers are preserved."""
import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError

from app.providers.base import AccountError, EmailProvider, OutgoingEmail, PermanentError, TransientError

TRANSIENT = {"Throttling", "ThrottlingException", "TooManyRequestsException", "ServiceUnavailable",
             "InternalFailure", "LimitExceededException", "RequestTimeout"}
ACCOUNT = {"AccountSendingPausedException", "MailFromDomainNotVerifiedException", "SendingPausedException",
           "AccessDeniedException", "UnrecognizedClientException", "InvalidClientTokenId",
           "SignatureDoesNotMatch", "NotFoundException"}


class SESProvider(EmailProvider):
    name = "ses"

    def __init__(self, region: str, access_key_id: str | None = None, secret_access_key: str | None = None,
                 configuration_set: str | None = None, domain: str | None = None):
        self.region, self.configuration_set, self.domain = region, configuration_set, domain
        self.client = boto3.client(
            "sesv2", region_name=region, aws_access_key_id=access_key_id or None,
            aws_secret_access_key=secret_access_key or None,
            config=Config(retries={"max_attempts": 2, "mode": "standard"}, connect_timeout=5, read_timeout=15))

    def send(self, email: OutgoingEmail) -> str:
        raw = email.to_mime(self.domain).as_bytes()
        kwargs = {"Content": {"Raw": {"Data": raw}}, "Destination": {"ToAddresses": [email.to]}}
        if self.configuration_set:
            kwargs["ConfigurationSetName"] = self.configuration_set
        if email.tags:
            kwargs["EmailTags"] = [{"Name": k, "Value": v} for k, v in email.tags.items()]
        try:
            return self.client.send_email(**kwargs)["MessageId"]
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            msg = e.response.get("Error", {}).get("Message", "")
            if code in TRANSIENT:
                raise TransientError(f"{code}: {msg}") from e
            if code in ACCOUNT:
                raise AccountError(f"{code}: {msg}") from e
            raise PermanentError(f"{code}: {msg}") from e
        except (EndpointConnectionError, BotoCoreError) as e:
            raise TransientError(str(e)) from e

    def verify(self) -> dict:
        if not self.domain:
            raise AccountError("Sending domain is not set")
        try:
            ident = self.client.get_email_identity(EmailIdentity=self.domain)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code == "NotFoundException":
                created = self.client.create_email_identity(EmailIdentity=self.domain)
                ident = {"DkimAttributes": created.get("DkimAttributes", {}),
                         "VerifiedForSendingStatus": False}
            else:
                raise AccountError(f"{code}: {e.response.get('Error', {}).get('Message', '')}") from e
        dkim = ident.get("DkimAttributes", {})
        records = [{"type": "CNAME", "name": f"{t}._domainkey.{self.domain}", "value": f"{t}.dkim.amazonses.com",
                    "purpose": "DKIM"} for t in dkim.get("Tokens", [])]
        records.append({"type": "TXT", "name": self.domain, "value": "v=spf1 include:amazonses.com ~all",
                        "purpose": "SPF (merge with any existing SPF record; only one SPF TXT per domain)"})
        records.append({"type": "TXT", "name": f"_dmarc.{self.domain}",
                        "value": f"v=DMARC1; p=none; rua=mailto:dmarc@{self.domain}; fo=1",
                        "purpose": "DMARC (start with p=none, move to quarantine/reject after monitoring)"})
        return {"ok": bool(ident.get("VerifiedForSendingStatus")), "dkim_status": dkim.get("Status"),
                "verified_for_sending": bool(ident.get("VerifiedForSendingStatus")), "dns_records": records}

    def quota(self) -> dict:
        try:
            acct = self.client.get_account()
        except ClientError as e:
            raise AccountError(e.response.get("Error", {}).get("Message", "")) from e
        q = acct.get("SendQuota", {})
        return {"max_24_hour_send": q.get("Max24HourSend"), "max_send_rate": q.get("MaxSendRate"),
                "sent_last_24_hours": q.get("SentLast24Hours"), "production_access": acct.get("ProductionAccessEnabled"),
                "sending_enabled": acct.get("SendingEnabled"), "enforcement_status": acct.get("EnforcementStatus")}
