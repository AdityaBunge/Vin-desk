"""Provider abstraction for customer email, SMS and WhatsApp.

The delivery service only ever talks to these interfaces, so a gateway can be swapped without
touching billing logic. `accepted=True` means the provider took the message for delivery; it
does NOT mean the customer received it. Delivery is confirmed only by a later receipt callback.
"""
from dataclasses import dataclass, field
from typing import Protocol


class ProviderConfigError(Exception):
    """The selected provider is missing configuration. Treated as a permanent failure."""


@dataclass
class SendResult:
    accepted: bool
    message_id: str | None = None
    error: str | None = None  # safe for administrators; never contains credentials
    permanent: bool = False  # True = retrying cannot help (bad address, rejected template...)


@dataclass
class EmailContent:
    to_address: str
    to_name: str
    subject: str
    text_body: str
    html_body: str
    sender_address: str
    sender_name: str
    attachments: list[tuple[str, bytes, str]] = field(default_factory=list)  # (filename, data, mime)


@dataclass
class SmsContent:
    to_e164: str  # +91XXXXXXXXXX
    body: str
    # Template variables for gateways (e.g. DLT-registered templates in India) that render the
    # text themselves from an approved template.
    variables: dict[str, str] = field(default_factory=dict)
    sender_id: str = ""
    template_id: str = ""
    dlt_entity_id: str = ""


@dataclass
class WhatsAppContent:
    to_e164: str  # +91XXXXXXXXXX
    # WhatsApp only lets a business start a conversation with a template approved by Meta; the
    # template's text lives in WhatsApp Manager and these values fill its {{1}}, {{2}}, ...
    template_name: str
    language: str
    body_params: list[str]
    body: str  # the message as the customer reads it, for the simulator and logs
    document: tuple[str, bytes] | None = None  # (filename, PDF) for a template with a document header


class EmailProvider(Protocol):
    name: str
    supports_receipts: bool
    simulated: bool

    def send(self, content: EmailContent, idempotency_key: str) -> SendResult: ...


class SmsProvider(Protocol):
    name: str
    supports_receipts: bool
    simulated: bool

    def send(self, content: SmsContent, idempotency_key: str) -> SendResult: ...


class WhatsAppProvider(Protocol):
    name: str
    supports_receipts: bool
    simulated: bool

    def send(self, content: WhatsAppContent, idempotency_key: str) -> SendResult: ...
