"""Chooses the email / SMS / WhatsApp provider from configuration.

Tests install fakes with `set_overrides`, so automated tests never reach a real provider.
"""
from app.core.config import get_settings
from app.integrations.base import EmailProvider, ProviderConfigError, SmsProvider, WhatsAppProvider
from app.integrations.email import DevEmailProvider, SmtpEmailProvider
from app.integrations.sms import DevSmsProvider, Msg91SmsProvider
from app.integrations.whatsapp import DevWhatsAppProvider, MetaWhatsAppProvider

_email_override: EmailProvider | None = None
_sms_override: SmsProvider | None = None
_whatsapp_override: WhatsAppProvider | None = None


def set_overrides(
    email: EmailProvider | None = None, sms: SmsProvider | None = None, whatsapp: WhatsAppProvider | None = None
) -> None:
    global _email_override, _sms_override, _whatsapp_override
    _email_override, _sms_override, _whatsapp_override = email, sms, whatsapp


def get_email_provider() -> EmailProvider:
    if _email_override is not None:
        return _email_override
    s = get_settings()
    if s.email_provider == "smtp":
        return SmtpEmailProvider(s.smtp_host, s.smtp_port, s.smtp_security, s.smtp_username, s.smtp_password)
    if s.is_production:
        raise ProviderConfigError("No real email provider is configured (EMAIL_PROVIDER=dev is not allowed in production)")
    return DevEmailProvider(s.dev_outbox_dir)


def get_sms_provider() -> SmsProvider:
    if _sms_override is not None:
        return _sms_override
    s = get_settings()
    if not s.sms_enabled:
        raise ProviderConfigError("SMS is turned off (SMS_PROVIDER=disabled)")
    if s.sms_provider == "msg91":
        return Msg91SmsProvider(s.msg91_auth_key, s.msg91_base_url)
    if s.is_production:
        raise ProviderConfigError("No real SMS provider is configured (SMS_PROVIDER=dev is not allowed in production)")
    return DevSmsProvider(s.dev_outbox_dir)


def get_whatsapp_provider() -> WhatsAppProvider:
    if _whatsapp_override is not None:
        return _whatsapp_override
    s = get_settings()
    if not s.whatsapp_enabled:
        raise ProviderConfigError("WhatsApp is turned off (WHATSAPP_PROVIDER=disabled)")
    if s.whatsapp_provider == "meta":
        return MetaWhatsAppProvider(s.whatsapp_access_token, s.whatsapp_phone_number_id, s.whatsapp_graph_url, s.whatsapp_api_version)
    if s.is_production:
        raise ProviderConfigError("No real WhatsApp provider is configured (WHATSAPP_PROVIDER=dev is not allowed in production)")
    return DevWhatsAppProvider(s.dev_outbox_dir)


def provider_status() -> dict:
    """Non-secret summary for the admin screen. Credentials are reported only as booleans."""
    s = get_settings()
    return {
        "environment": s.app_env,
        "email": {
            "provider": s.email_provider,
            "simulated": s.email_provider == "dev",
            "smtp_host": s.smtp_host,
            "smtp_port": s.smtp_port,
            "smtp_security": s.smtp_security,
            "smtp_username_configured": bool(s.smtp_username),
            "smtp_password_configured": bool(s.smtp_password),
            "sender_address": s.email_sender_address,
        },
        "sms": {
            "provider": s.sms_provider,
            "enabled": s.sms_enabled,
            "simulated": s.sms_provider == "dev",
            "auth_key_configured": bool(s.msg91_auth_key),
        },
        "whatsapp": {
            "provider": s.whatsapp_provider,
            "enabled": s.whatsapp_enabled,
            "simulated": s.whatsapp_provider == "dev",
            "access_token_configured": bool(s.whatsapp_access_token),
            "phone_number_id_configured": bool(s.whatsapp_phone_number_id),
            "app_secret_configured": bool(s.whatsapp_app_secret),
            "verify_token_configured": bool(s.whatsapp_verify_token),
        },
        "webhook_secret_configured": bool(s.webhook_secret),
        "public_base_url_env": s.public_base_url,
    }
