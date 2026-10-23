import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.integrations.base import ProviderConfigError, SendResult, SmsContent

log = logging.getLogger("fsc.sms")


class DevSmsProvider:
    """DEVELOPMENT SIMULATOR. Appends the message to a local log file; nothing is sent."""

    name = "dev-simulator"
    supports_receipts = False
    simulated = True

    def __init__(self, outbox_dir: str):
        self.outbox_dir = Path(outbox_dir)

    def send(self, content: SmsContent, idempotency_key: str) -> SendResult:
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "simulated": True,
            "at": datetime.now(UTC).isoformat(),
            "to": content.to_e164,
            "body": content.body,
            "idempotency_key": idempotency_key,
        }
        with (self.outbox_dir / "sms.log").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        log.warning("[SIMULATED SMS - not sent] to=%s body=%r", content.to_e164, content.body)
        return SendResult(accepted=True, message_id=f"dev-sms-{idempotency_key}")


class Msg91SmsProvider:
    """MSG91 (India) "Flow" API adapter.

    Indian transactional SMS must use a DLT-registered template, so MSG91 renders the text from
    the template identified by `template_id`; this adapter sends the template variables
    (invoice_number, registration, amount, url, centre). The sender ID and DLT entity are bound
    to the template inside the MSG91 account.

    NOT verified against the live MSG91 service in this project: test with real credentials and
    an approved template before relying on it (see docs/deployment.md).
    """

    name = "msg91"
    supports_receipts = True
    simulated = False

    def __init__(self, auth_key: str, base_url: str, timeout: float = 15):
        if not auth_key:
            raise ProviderConfigError("MSG91 auth key is not configured")
        self.auth_key, self.base_url, self.timeout = auth_key, base_url.rstrip("/"), timeout

    def send(self, content: SmsContent, idempotency_key: str) -> SendResult:
        if not content.template_id:
            raise ProviderConfigError("SMS template ID (DLT-approved template) is not configured")
        payload = {
            "template_id": content.template_id,
            "short_url": "0",
            "recipients": [{"mobiles": content.to_e164.lstrip("+"), **content.variables}],
        }
        try:
            response = httpx.post(
                f"{self.base_url}/api/v5/flow",
                json=payload,
                headers={"authkey": self.auth_key, "accept": "application/json"},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            return SendResult(False, error=f"Could not reach the SMS gateway ({type(exc).__name__})")
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 500:
            return SendResult(False, error=f"SMS gateway error {response.status_code}")
        if response.status_code >= 400 or body.get("type") != "success":
            reason = str(body.get("message") or f"HTTP {response.status_code}")[:200]
            return SendResult(False, error=f"SMS gateway rejected the request: {reason}", permanent=True)
        return SendResult(True, message_id=str(body.get("message") or body.get("request_id") or ""))
