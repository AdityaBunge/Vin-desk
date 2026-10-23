"""Send ONE test email through the SMTP settings in .env, to check them before going live.

    python scripts/send_test_email.py you@example.com

Prints a clear reason on failure (wrong app password, blocked port, missing sender, ...).
The password is never printed.
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.integrations.base import EmailContent, ProviderConfigError  # noqa: E402
from app.integrations.email import SmtpEmailProvider  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2 or "@" not in sys.argv[1]:
        print("Usage: python scripts/send_test_email.py you@example.com")
        return 2
    to = sys.argv[1]
    s = get_settings()
    print(f"EMAIL_PROVIDER = {s.email_provider}")
    print(f"SMTP           = {s.smtp_host}:{s.smtp_port} ({s.smtp_security})")
    print(f"Username       = {s.smtp_username or '(none)'}")
    print(f"Password set   = {'yes' if s.smtp_password else 'NO'}")
    print(f"Sender         = {s.email_sender_address or '(none)'}")
    if s.email_provider != "smtp":
        print("\nEMAIL_PROVIDER is not 'smtp' - set it in .env first.")
        return 1
    try:
        provider = SmtpEmailProvider(s.smtp_host, s.smtp_port, s.smtp_security, s.smtp_username, s.smtp_password)
        result = provider.send(EmailContent(
            to_address=to, to_name="", subject="Vin Desk - SMTP test",
            text_body="This is a test email from Vin Desk. If you can read this, invoice emails will work.",
            html_body="<p>This is a test email from <strong>Vin Desk</strong>.</p><p>If you can read this, invoice emails will work.</p>",
            sender_address=s.email_sender_address, sender_name="Vin Desk",
        ), uuid.uuid4().hex)
    except ProviderConfigError as exc:
        print(f"\nNot sent: {exc}")
        return 1
    if result.accepted:
        print(f"\nSent to {to}. Check the inbox (and the spam folder).")
        return 0
    print(f"\nNot sent: {result.error}")
    if "authentication" in (result.error or "").lower():
        print("For Gmail: use a 16-character App Password (not your normal password), with 2-Step Verification on.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
