import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

from app.integrations.base import EmailContent, ProviderConfigError, SendResult

log = logging.getLogger("fsc.email")


def build_mime(content: EmailContent, idempotency_key: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = content.subject
    msg["From"] = formataddr((content.sender_name, content.sender_address))
    msg["To"] = formataddr((content.to_name, content.to_address))
    msg["Message-ID"] = make_msgid(idstring=idempotency_key)
    msg["X-Idempotency-Key"] = idempotency_key
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(content.text_body)
    msg.add_alternative(content.html_body, subtype="html")
    for filename, data, mime in content.attachments:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return msg


class DevEmailProvider:
    """DEVELOPMENT SIMULATOR. Writes the message to a local .eml file; nothing is sent."""

    name = "dev-simulator"
    supports_receipts = False
    simulated = True

    def __init__(self, outbox_dir: str):
        self.outbox_dir = Path(outbox_dir)

    def send(self, content: EmailContent, idempotency_key: str) -> SendResult:
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        path = self.outbox_dir / f"email-{idempotency_key}.eml"
        path.write_bytes(bytes(build_mime(content, idempotency_key)))
        log.warning("[SIMULATED EMAIL - not sent] to=%s subject=%r file=%s", content.to_address, content.subject, path)
        return SendResult(accepted=True, message_id=f"dev-email-{idempotency_key}")


class SmtpEmailProvider:
    """Sends through any SMTP relay. SMTP gives no delivery receipts, so a message stays SENT
    (delivery status unknown) unless an external receipt webhook reports otherwise."""

    name = "smtp"
    supports_receipts = False
    simulated = False

    def __init__(self, host: str, port: int, security: str, username: str, password: str, timeout: float = 20):
        if not host:
            raise ProviderConfigError("SMTP host is not configured")
        self.host, self.port, self.security = host, port, security
        self.username, self.password, self.timeout = username, password, timeout

    def send(self, content: EmailContent, idempotency_key: str) -> SendResult:
        if not content.sender_address:
            raise ProviderConfigError("Sender email address is not configured")
        msg = build_mime(content, idempotency_key)
        try:
            context = ssl.create_default_context()
            if self.security == "ssl":
                client = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout, context=context)
            else:
                client = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
            with client:
                if self.security == "starttls":
                    client.starttls(context=context)
                if self.username:
                    client.login(self.username, self.password)
                refused = client.send_message(msg)
            if refused:
                return SendResult(False, error="Recipient refused by the mail server", permanent=True)
            return SendResult(True, message_id=msg["Message-ID"])
        except smtplib.SMTPAuthenticationError:
            return SendResult(False, error="SMTP authentication failed; check the configured credentials", permanent=True)
        except smtplib.SMTPRecipientsRefused:
            return SendResult(False, error="Recipient address refused by the mail server", permanent=True)
        except smtplib.SMTPResponseException as exc:
            # 5xx is a permanent rejection, 4xx a temporary one.
            return SendResult(False, error=f"SMTP error {exc.smtp_code}", permanent=exc.smtp_code >= 500)
        except (OSError, smtplib.SMTPException) as exc:
            return SendResult(False, error=f"Could not reach the mail server ({type(exc).__name__})")
