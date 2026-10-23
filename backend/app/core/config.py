"""Application configuration, loaded from environment variables / .env files.

Secrets (JWT secret, SMTP password, SMS auth key, WhatsApp token, webhook secrets) live only here and are
never returned by any API response.
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BACKEND_DIR.parent

DEV_JWT_SECRET = "dev-only-insecure-secret-do-not-use-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(ROOT_DIR / ".env"), str(BACKEND_DIR / ".env")), extra="ignore"
    )

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://fsc@localhost:5544/fsc_dev"

    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    bcrypt_rounds: int = 12

    cors_origins: str = "http://localhost:5173"
    public_base_url: str = "http://localhost:5173"
    invoice_link_secret: str = ""

    # Email
    email_provider: Literal["dev", "smtp"] = "dev"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    smtp_username: str = ""
    smtp_password: str = ""
    email_sender_address: str = ""

    # SMS. "disabled" = invoices go by email only; no SMS rows are queued.
    sms_provider: Literal["dev", "msg91", "disabled"] = "dev"
    msg91_auth_key: str = ""
    msg91_base_url: str = "https://control.msg91.com"

    # WhatsApp (Meta WhatsApp Cloud API). Sends invoices (PDF attached) and payment / service
    # reminders using message templates approved in WhatsApp Manager. "disabled" = no WhatsApp.
    whatsapp_provider: Literal["dev", "meta", "disabled"] = "disabled"
    whatsapp_access_token: str = ""  # permanent System User token
    whatsapp_phone_number_id: str = ""  # the sending number's ID in the Meta app, not the number
    whatsapp_app_secret: str = ""  # verifies X-Hub-Signature-256 on Meta's status webhooks
    whatsapp_verify_token: str = ""  # any random string; entered again when registering the webhook
    whatsapp_api_version: str = "v21.0"
    whatsapp_graph_url: str = "https://graph.facebook.com"

    # Provider delivery-receipt webhooks (HMAC shared secret)
    webhook_secret: str = ""

    run_worker_in_api: bool = True
    worker_poll_seconds: float = 5.0

    # Parts catalogue sync from the workshop's Google Sheet. Empty = off. The sheet adds parts and
    # updates names, landed cost and bin; stock quantities are maintained in the app.
    parts_sheet_url: str = ""
    parts_sheet_sync_seconds: float = 30.0
    parts_sheet_markup_percent: float = 20.0
    parts_sheet_tax: str = "GST 18%"

    upload_dir: str = str(BACKEND_DIR / "var" / "uploads")
    dev_outbox_dir: str = str(BACKEND_DIR / "var" / "dev_outbox")
    max_upload_bytes: int = 5 * 1024 * 1024

    login_rate_limit_per_minute: int = 10
    public_link_rate_limit_per_minute: int = 30

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def sms_enabled(self) -> bool:
        return self.sms_provider != "disabled"

    @property
    def whatsapp_enabled(self) -> bool:
        return self.whatsapp_provider != "disabled"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def link_secret(self) -> str:
        return self.invoice_link_secret or self.jwt_secret

    def production_problems(self) -> list[str]:
        """Configuration errors that must block a production start."""
        problems: list[str] = []
        if self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET must be set to a random value of at least 32 characters")
        if not self.public_base_url.startswith("https://"):
            problems.append("PUBLIC_BASE_URL must use https:// in production")
        if "*" in self.cors_origin_list:
            problems.append("CORS_ORIGINS must list explicit origins")
        if self.email_provider == "dev":
            problems.append("EMAIL_PROVIDER=dev is a simulator; configure a real provider (smtp)")
        elif self.email_provider == "smtp" and not (self.smtp_host and self.email_sender_address):
            problems.append("SMTP_HOST and EMAIL_SENDER_ADDRESS are required for EMAIL_PROVIDER=smtp")
        if self.sms_provider == "dev":
            problems.append("SMS_PROVIDER=dev is a simulator; configure a real provider (msg91) or set SMS_PROVIDER=disabled")
        elif self.sms_provider == "msg91" and not self.msg91_auth_key:
            problems.append("MSG91_AUTH_KEY is required for SMS_PROVIDER=msg91")
        if self.whatsapp_provider == "dev":
            problems.append("WHATSAPP_PROVIDER=dev is a simulator; configure a real provider (meta) or set WHATSAPP_PROVIDER=disabled")
        elif self.whatsapp_provider == "meta" and not (self.whatsapp_access_token and self.whatsapp_phone_number_id):
            problems.append("WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID are required for WHATSAPP_PROVIDER=meta")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
