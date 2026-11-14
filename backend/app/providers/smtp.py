"""SMTP provider (any SMTP relay; Mailpit locally for capture-only testing)."""
import smtplib
import socket
import ssl

from app.providers.base import AccountError, EmailProvider, OutgoingEmail, PermanentError, TransientError


class SMTPProvider(EmailProvider):
    name = "smtp"

    def __init__(self, host: str, port: int = 587, username: str | None = None, password: str | None = None,
                 security: str = "starttls", timeout: float = 20.0):
        self.host, self.port, self.username, self.password = (host or "").strip(), int(port), (username or "").strip(), password
        self.security, self.timeout = security, timeout  # security: starttls | ssl | none
        self._conn: smtplib.SMTP | None = None

    def _connect(self) -> smtplib.SMTP:
        if self._conn is not None:
            try:
                self._conn.noop()
                return self._conn
            except smtplib.SMTPException:
                self._conn = None
        try:
            if self.security == "ssl":
                conn = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout,
                                        context=ssl.create_default_context())
            else:
                conn = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
                if self.security == "starttls":
                    conn.starttls(context=ssl.create_default_context())
            if self.username:
                try:
                    conn.login(self.username, self.password or "")
                except smtplib.SMTPServerDisconnected as e:
                    raise AccountError(
                        "The server closed the connection during sign-in: the username or password was "
                        "rejected. Gmail and Microsoft 365 require an app password (Gmail: 16 letters, "
                        "from myaccount.google.com/apppasswords), not your normal password.") from e
        except smtplib.SMTPAuthenticationError as e:
            detail = (e.smtp_error or b"").decode(errors="replace").split("[")[0].strip()
            raise AccountError(f"SMTP sign-in rejected ({e.smtp_code}): {detail or 'check the username and (app) password'}") from e
        except (OSError, socket.timeout, smtplib.SMTPException) as e:
            raise TransientError(f"SMTP connection failed: {e}") from e
        self._conn = conn
        return conn

    def send(self, email: OutgoingEmail) -> str:
        msg = email.to_mime()
        try:
            conn = self._connect()
            refused = conn.send_message(msg)
        except smtplib.SMTPRecipientsRefused as e:
            code = next(iter(e.recipients.values()))[0]
            raise (TransientError if 400 <= code < 500 else PermanentError)(f"Recipient refused ({code})") from e
        except smtplib.SMTPSenderRefused as e:
            raise AccountError(f"Sender refused ({e.smtp_code})") from e
        except smtplib.SMTPDataError as e:
            raise (TransientError if 400 <= e.smtp_code < 500 else PermanentError)(
                f"Message rejected ({e.smtp_code})") from e
        except (smtplib.SMTPServerDisconnected, OSError, socket.timeout) as e:
            self._conn = None
            raise TransientError(f"SMTP connection lost: {e}") from e
        if refused:
            raise PermanentError(f"Recipient refused: {refused}")
        return msg["Message-ID"].strip("<>")

    def verify(self) -> dict:
        conn = self._connect()
        conn.noop()
        return {"ok": True, "detail": f"Connected to {self.host}:{self.port}"}

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.quit()
            except smtplib.SMTPException:
                pass
            self._conn = None
