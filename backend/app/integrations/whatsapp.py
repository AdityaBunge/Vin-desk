import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.integrations.base import ProviderConfigError, SendResult, WhatsAppContent

log = logging.getLogger("fsc.whatsapp")

# Meta error codes that mean "try again later" (rate limits, temporary outages). Any other
# 4xx error (bad number, unapproved template, wrong parameters, expired token) cannot be fixed
# by retrying. https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes
TEMPORARY_ERROR_CODES = {1, 2, 4, 80007, 130429, 131000, 131016, 131056, 133004}


class DevWhatsAppProvider:
    """DEVELOPMENT SIMULATOR. Appends the message to a local log file (and saves any attached PDF
    next to it); nothing is sent."""

    name = "dev-simulator"
    supports_receipts = False
    simulated = True

    def __init__(self, outbox_dir: str):
        self.outbox_dir = Path(outbox_dir)

    def send(self, content: WhatsAppContent, idempotency_key: str) -> SendResult:
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        attachment = None
        if content.document:
            attachment = f"whatsapp-{idempotency_key}-{content.document[0]}"
            (self.outbox_dir / attachment).write_bytes(content.document[1])
        record = {
            "simulated": True,
            "at": datetime.now(UTC).isoformat(),
            "to": content.to_e164,
            "template": content.template_name,
            "params": content.body_params,
            "body": content.body,
            "attachment": attachment,
            "idempotency_key": idempotency_key,
        }
        with (self.outbox_dir / "whatsapp.log").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        log.warning("[SIMULATED WHATSAPP - not sent] to=%s template=%s body=%r", content.to_e164, content.template_name, content.body)
        return SendResult(accepted=True, message_id=f"dev-wa-{idempotency_key}")


class MetaWhatsAppProvider:
    """Meta WhatsApp Cloud API adapter.

    Sends an approved template message. When the content carries a PDF, it is first uploaded to
    the media endpoint and the returned media ID fills the template's document header. The
    message ID ("wamid....") is matched later by the status webhook (sent / delivered / read /
    failed). The Cloud API has no idempotency key, so a send whose response was lost in a network
    failure can, rarely, reach the customer twice.

    NOT verified against the live Meta service in this project: test with real credentials and
    approved templates before relying on it (see docs/deployment.md).
    """

    name = "meta-whatsapp"
    supports_receipts = True
    simulated = False

    def __init__(self, access_token: str, phone_number_id: str, graph_url: str, api_version: str, timeout: float = 20):
        if not access_token or not phone_number_id:
            raise ProviderConfigError("WhatsApp access token or phone number ID is not configured")
        self.base = f"{graph_url.rstrip('/')}/{api_version}/{phone_number_id}"
        self.headers = {"Authorization": f"Bearer {access_token}"}
        self.timeout = timeout

    def send(self, content: WhatsAppContent, idempotency_key: str) -> SendResult:
        if not content.template_name:
            raise ProviderConfigError("WhatsApp template name is not configured")
        components: list[dict] = []
        if content.document:
            filename, data = content.document
            media_id, failure = self._upload(filename, data)
            if failure:
                return failure
            components.append({"type": "header", "parameters": [
                {"type": "document", "document": {"id": media_id, "filename": filename}}]})
        components.append({"type": "body", "parameters": [{"type": "text", "text": p} for p in content.body_params]})
        payload = {
            "messaging_product": "whatsapp",
            "to": content.to_e164.lstrip("+"),
            "type": "template",
            "template": {"name": content.template_name, "language": {"code": content.language}, "components": components},
        }
        body, failure = self._post("/messages", "send the message", json=payload)
        if failure:
            return failure
        try:
            return SendResult(True, message_id=str(body["messages"][0]["id"]))
        except (KeyError, IndexError, TypeError):
            return SendResult(False, error="WhatsApp accepted the request but returned no message ID")

    def _upload(self, filename: str, data: bytes) -> tuple[str, SendResult | None]:
        body, failure = self._post(
            "/media", "upload the invoice PDF",
            data={"messaging_product": "whatsapp", "type": "application/pdf"},
            files={"file": (filename, data, "application/pdf")},
        )
        if failure:
            return "", failure
        if not body.get("id"):
            return "", SendResult(False, error="WhatsApp did not return a media ID for the invoice PDF")
        return str(body["id"]), None

    def _post(self, path: str, action: str, **kwargs) -> tuple[dict, SendResult | None]:
        try:
            response = httpx.post(self.base + path, headers=self.headers, timeout=self.timeout, **kwargs)
        except httpx.HTTPError as exc:
            return {}, SendResult(False, error=f"Could not reach WhatsApp ({type(exc).__name__})")
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code < 400:
            return body, None
        error = body.get("error") if isinstance(body.get("error"), dict) else {}
        code = error.get("code")
        detail = (error.get("error_data") or {}).get("details") or error.get("message") or f"HTTP {response.status_code}"
        message = f"WhatsApp could not {action}: {str(detail)[:200]}"
        temporary = response.status_code >= 500 or response.status_code == 429 or code in TEMPORARY_ERROR_CODES
        return body, SendResult(False, error=message, permanent=not temporary)
