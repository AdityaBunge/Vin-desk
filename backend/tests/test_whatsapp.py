"""WhatsApp: invoice with PDF, payment-due and service-due reminders, Meta webhooks and adapter."""
import hashlib
import hmac
import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.utils import utcnow
from app.integrations.base import WhatsAppContent
from app.integrations.whatsapp import MetaWhatsAppProvider
from app.models import DeliveryJob, Invoice, Notification, ServiceJob
from app.models.enums import JobStatus
from app.services import reminders
from tests import flow


@pytest.fixture
def wa(w, monkeypatch):
    """The test world with WhatsApp switched on (sends go to w.whatsapp)."""
    monkeypatch.setattr(get_settings(), "whatsapp_provider", "dev")
    return w


def _finalised(w, **kw):
    job = flow.to_billing(w, **kw)
    return flow.finalise(w, job["id"])


def _jobs(kind: str | None = None) -> list[DeliveryJob]:
    with SessionLocal() as db:
        stmt = select(DeliveryJob).where(DeliveryJob.channel == "WHATSAPP").order_by(DeliveryJob.id)
        if kind:
            stmt = stmt.where(DeliveryJob.kind == kind)
        return list(db.scalars(stmt))


def _shift(model, column: str, where, days: int) -> None:
    """Move a timestamp `days` into the past."""
    with SessionLocal() as db:
        db.execute(update(model).where(where).values({column: utcnow() - timedelta(days=days)}))
        db.commit()


def _schedule() -> int:
    return reminders.run_once(SessionLocal)


# --- Invoice ----------------------------------------------------------------------------


def test_invoice_is_sent_on_whatsapp_with_pdf(wa):
    inv = _finalised(wa)
    assert sorted(d["channel"] for d in inv["delivery_jobs"]) == ["EMAIL", "SMS", "WHATSAPP"]
    flow.run_worker()
    msg = wa.whatsapp.sent[-1]
    assert msg.to_e164 == "+919822012345" and msg.template_name == "invoice_ready" and msg.language == "en"
    name, number, reg, amount, url, centre = msg.body_params
    assert (name, number, reg, amount) == ("Ganesh Tours", inv["invoice_number"], "MH12AB1234", "3,894.00")
    assert url.startswith("https://service.test/i/") and centre == "Positive Sales"
    assert msg.document[0] == f"{inv['invoice_number']}.pdf" and msg.document[1].startswith(b"%PDF")
    assert url in msg.body and "{{" not in msg.body
    whatsapp = flow.deliveries(wa, inv["id"])["WHATSAPP"]
    assert whatsapp["status"] == "SENT" and whatsapp["kind"] == "INVOICE" and whatsapp["provider"] == "fake-whatsapp"

    again = wa.ok("manager", "POST", f"/invoices/{inv['id']}/resend", json={"channel": "WHATSAPP", "confirm": True})
    assert again["channel"] == "WHATSAPP" and again["trigger"] == "MANUAL"
    flow.run_worker()
    assert len(wa.whatsapp.sent) == 2 and len(wa.sms.sent) == 1  # the other channels are untouched


def test_whatsapp_opt_out_is_respected(wa):
    job = flow.to_billing(wa)
    wa.ok("manager", "PATCH", f"/customers/{job['customer']['id']}", json={"whatsapp_opt_in": False})
    inv = flow.finalise(wa, job["id"])
    whatsapp = flow.deliveries(wa, inv["id"])["WHATSAPP"]
    assert whatsapp["status"] == "SKIPPED" and whatsapp["last_error"] == "Customer has opted out of WhatsApp"
    customer = wa.ok("manager", "GET", f"/customers/{job['customer']['id']}")
    assert customer["whatsapp_opt_in"] is False and customer["consents"][-1]["channel"] == "WHATSAPP"
    flow.run_worker()
    assert wa.whatsapp.calls == [] and len(wa.sms.sent) == 1


def test_whatsapp_off_by_default(w):
    inv = _finalised(w)
    assert "WHATSAPP" not in {d["channel"] for d in inv["delivery_jobs"]}
    assert w.ok("manager", "GET", "/features")["whatsapp"] is False
    r = w.call("manager", "POST", f"/invoices/{inv['id']}/payment-reminder")
    assert r.status_code == 409 and "WhatsApp is turned off" in r.text
    assert w.call("manager", "POST", f"/invoices/{inv['id']}/resend", json={"channel": "WHATSAPP", "confirm": True}).status_code == 409
    assert reminders.run_once(SessionLocal) == 0


# --- Payment reminders ------------------------------------------------------------------


def test_manual_payment_reminder(wa):
    inv = _finalised(wa)
    flow.run_worker()
    wa.ok("manager", "POST", f"/invoices/{inv['id']}/payments", json={"amount": "1000.00", "method": "CASH"})
    job = wa.ok("manager", "POST", f"/invoices/{inv['id']}/payment-reminder")
    assert job["kind"] == "PAYMENT_REMINDER" and job["trigger"] == "MANUAL" and job["status"] == "PENDING"
    busy = wa.call("manager", "POST", f"/invoices/{inv['id']}/payment-reminder")
    assert busy.status_code == 409 and "already in progress" in busy.text
    assert wa.call("inventory", "POST", f"/invoices/{inv['id']}/payment-reminder").status_code == 403
    flow.run_worker()
    msg = wa.whatsapp.sent[-1]
    assert msg.template_name == "payment_reminder" and msg.document is None
    assert msg.body_params[1] == inv["invoice_number"] and msg.body_params[3] == "2,894.00"  # the outstanding balance

    wa.ok("manager", "POST", f"/invoices/{inv['id']}/payments", json={"amount": "2894.00", "method": "UPI"})
    paid = wa.call("manager", "POST", f"/invoices/{inv['id']}/payment-reminder")
    assert paid.status_code == 409 and "no outstanding balance" in paid.text


def test_payment_reminder_is_cancelled_if_paid_before_sending(wa):
    inv = _finalised(wa)
    flow.run_worker()
    wa.ok("manager", "POST", f"/invoices/{inv['id']}/payment-reminder")
    wa.ok("manager", "POST", f"/invoices/{inv['id']}/payments", json={"amount": inv["total"], "method": "CASH"})
    flow.run_worker()
    (job,) = _jobs("PAYMENT_REMINDER")
    assert job.status == "CANCELLED" and job.last_error == "Not sent: the invoice has been paid"
    assert len(wa.whatsapp.sent) == 1  # only the invoice itself


def test_automatic_payment_reminders(wa):
    inv = _finalised(wa)
    flow.run_worker()
    assert _schedule() == 0  # not yet 3 days old
    _shift(Invoice, "finalised_at", Invoice.id == inv["id"], 4)
    assert _schedule() == 1
    assert _schedule() == 0  # the next one is a week later
    flow.run_worker()
    assert wa.whatsapp.sent[-1].template_name == "payment_reminder"
    for expected in (1, 1, 0):  # at most 3 automatic reminders
        _shift(DeliveryJob, "created_at", DeliveryJob.kind == "PAYMENT_REMINDER", 8)
        assert _schedule() == expected
    assert [j.trigger for j in _jobs("PAYMENT_REMINDER")] == ["AUTO"] * 3

    # Paid invoices and invoices already long overdue when reminders were switched on are left alone.
    other = _finalised(wa, reg="MH12CD5678", email="other@example.com", mobile="9822054321")
    _shift(Invoice, "finalised_at", Invoice.id == other["id"], 60)
    assert _schedule() == 0
    _shift(Invoice, "finalised_at", Invoice.id == other["id"], 5)
    wa.ok("manager", "POST", f"/invoices/{other['id']}/payments", json={"amount": other["total"], "method": "CASH"})
    assert _schedule() == 0


def test_automatic_reminders_can_be_switched_off(wa):
    inv = _finalised(wa)
    _shift(Invoice, "finalised_at", Invoice.id == inv["id"], 4)
    wa.ok("admin", "PUT", "/settings", json={"payment_reminder_enabled": False})
    assert _schedule() == 0
    wa.ok("admin", "PUT", "/settings", json={"payment_reminder_enabled": True, "payment_reminder_after_days": 10})
    assert _schedule() == 0
    assert wa.call("admin", "PUT", "/settings", json={"whatsapp_invoice_template": "Invoice Ready"}).status_code == 422


# --- Service reminders ------------------------------------------------------------------


def _past_visit(w, days_ago: int, reg="MH12AB1234", mobile="9822012345", email="owner@example.com"):
    """A vehicle whose last (completed) visit was `days_ago` days ago."""
    vehicle = flow.new_vehicle(w, reg=reg, mobile=mobile, email=email)
    job = flow.open_job(w, vehicle["id"])
    with SessionLocal() as db:
        db.execute(update(ServiceJob).where(ServiceJob.id == job["id"]).values(
            status=JobStatus.COMPLETED, visit_at=utcnow() - timedelta(days=days_ago)))
        db.commit()
    return vehicle, job


def test_service_due_reminder(wa):
    vehicle, visit = _past_visit(wa, 175)  # due in 5 days with the default 180-day interval
    _past_visit(wa, 150, reg="MH12CD5678", mobile="9822054321", email="b@example.com")  # not due yet
    _past_visit(wa, 400, reg="MH12EF9012", mobile="9822011111", email="c@example.com")  # long overdue
    assert _schedule() == 1
    assert _schedule() == 0  # one reminder per visit
    flow.run_worker()
    msg = wa.whatsapp.sent[-1]
    assert msg.template_name == "service_reminder" and msg.to_e164 == "+919822012345"
    name, reg, model, due, centre = msg.body_params
    assert (name, reg, model, centre) == ("Ganesh Tours", "MH12AB1234", "Force Traveller", "Positive Sales")
    (job,) = _jobs("SERVICE_REMINDER")
    assert job.invoice_id is None and job.vehicle_id == vehicle["id"] and job.service_job_id == visit["id"]
    assert job.status == "SENT"
    page = wa.ok("manager", "GET", "/deliveries", params={"kind": "SERVICE_REMINDER"})
    assert page["total"] == 1 and page["items"][0]["vehicle_id"] == vehicle["id"]


def test_service_reminder_waits_for_open_jobs_and_cancels_after_a_new_visit(wa):
    vehicle, _ = _past_visit(wa, 178)
    with SessionLocal() as db:  # back in the workshop: no reminder
        db.execute(update(ServiceJob).values(status=JobStatus.IN_SERVICE))
        db.commit()
    assert _schedule() == 0
    with SessionLocal() as db:
        db.execute(update(ServiceJob).values(status=JobStatus.COMPLETED))
        db.commit()
    assert _schedule() == 1
    flow.open_job(wa, vehicle["id"])  # the customer came in before the reminder went out
    flow.run_worker()
    (job,) = _jobs("SERVICE_REMINDER")
    assert job.status == "CANCELLED" and job.last_error == "Not sent: the vehicle has visited again"
    assert wa.whatsapp.calls == []


def test_failed_service_reminder_notifies_and_can_be_retried(wa):
    _past_visit(wa, 175)
    _schedule()
    wa.whatsapp.script = ["perm"]
    flow.run_worker()
    (job,) = _jobs("SERVICE_REMINDER")
    assert job.status == "FAILED"
    with SessionLocal() as db:
        note = db.scalar(select(Notification).where(Notification.type == "SERVICE_REMINDER_FAILED"))
        assert note.title == "Service reminder failed: MH12AB1234" and note.entity_type == "vehicle"
    retried = wa.ok("manager", "POST", f"/deliveries/{job.id}/retry")
    assert retried["status"] == "PENDING"
    flow.run_worker()
    assert _jobs("SERVICE_REMINDER")[0].status == "SENT"


# --- Meta webhooks ----------------------------------------------------------------------


def _status_event(message_id: str, status: str, **extra) -> dict:
    return {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "statuses": [{"id": message_id, "status": status, "timestamp": "1", **extra}]}}]}]}


def test_whatsapp_webhook(wa):
    verify = {"hub.mode": "subscribe", "hub.verify_token": "test-whatsapp-verify-token", "hub.challenge": "12345"}
    r = wa.client.get("/api/webhooks/whatsapp", params=verify)
    assert r.status_code == 200 and r.text == "12345"
    assert wa.client.get("/api/webhooks/whatsapp", params={**verify, "hub.verify_token": "wrong"}).status_code == 403

    wa.whatsapp.name = MetaWhatsAppProvider.name  # receipts are matched on the provider that sent
    inv = _finalised(wa)
    flow.run_worker()
    message_id = _jobs("INVOICE")[0].provider_message_id

    def post(payload, secret=b"test-whatsapp-app-secret"):
        raw = json.dumps(payload).encode()
        sig = "sha256=" + hmac.new(secret, raw, hashlib.sha256).hexdigest()
        return wa.client.post("/api/webhooks/whatsapp", content=raw, headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"})

    assert post(_status_event(message_id, "delivered"), secret=b"wrong").status_code == 401
    assert wa.client.post("/api/webhooks/whatsapp", json=_status_event(message_id, "delivered")).status_code == 401
    assert post(_status_event(message_id, "sent")).json() == {"results": []}
    assert post(_status_event(message_id, "delivered")).json() == {"results": ["applied"]}
    assert post(_status_event(message_id, "delivered")).json() == {"results": ["duplicate"]}
    assert post(_status_event(message_id, "read")).json() == {"results": ["applied"]}
    assert flow.deliveries(wa, inv["id"])["WHATSAPP"]["status"] == "DELIVERED"

    wa.ok("manager", "POST", f"/invoices/{inv['id']}/payment-reminder")
    flow.run_worker()
    reminder_id = _jobs("PAYMENT_REMINDER")[0].provider_message_id
    failed = _status_event(reminder_id, "failed", errors=[{"code": 131026, "title": "Message undeliverable",
                                                           "error_data": {"details": "Receiver is not on WhatsApp"}}])
    assert post(failed).json() == {"results": ["applied"]}
    (reminder,) = _jobs("PAYMENT_REMINDER")
    assert reminder.status == "FAILED" and reminder.last_error == "Receiver is not on WhatsApp"


# --- Meta Cloud API adapter (HTTP mocked) -----------------------------------------------


class FakeHttp:
    def __init__(self, *responses: tuple[int, dict]):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        status, body = self.responses.pop(0)
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))


def _content(document=None):
    return WhatsAppContent(to_e164="+919822012345", template_name="invoice_ready", language="en",
                           body_params=["Ganesh Tours", "INV-1"], body="", document=document)


def _provider():
    return MetaWhatsAppProvider("token-123", "555", "https://graph.example", "v21.0")


def test_meta_adapter_uploads_pdf_then_sends_template(monkeypatch):
    http = FakeHttp((200, {"id": "media-1"}), (200, {"messages": [{"id": "wamid.ABC"}]}))
    monkeypatch.setattr("httpx.post", http)
    result = _provider().send(_content(("INV-1.pdf", b"%PDF-1.4")), "key")
    assert result.accepted and result.message_id == "wamid.ABC"
    (upload_url, upload), (send_url, send) = http.calls
    assert upload_url == "https://graph.example/v21.0/555/media" and upload["files"]["file"][0] == "INV-1.pdf"
    assert upload["headers"]["Authorization"] == "Bearer token-123"
    assert send_url == "https://graph.example/v21.0/555/messages"
    payload = send["json"]
    assert payload["to"] == "919822012345" and payload["template"]["name"] == "invoice_ready"
    header, body = payload["template"]["components"]
    assert header == {"type": "header", "parameters": [{"type": "document", "document": {"id": "media-1", "filename": "INV-1.pdf"}}]}
    assert body["parameters"] == [{"type": "text", "text": "Ganesh Tours"}, {"type": "text", "text": "INV-1"}]


@pytest.mark.parametrize(("status", "code", "permanent"), [
    (400, 132001, True),   # template does not exist
    (400, 131026, True),   # message undeliverable
    (400, 130429, False),  # throughput limit
    (429, None, False),
    (503, None, False),
])
def test_meta_adapter_error_classification(monkeypatch, status, code, permanent):
    monkeypatch.setattr("httpx.post", FakeHttp((status, {"error": {"code": code, "message": "nope"}})))
    result = _provider().send(_content(), "key")
    assert not result.accepted and result.permanent is permanent and "nope" in result.error


def test_meta_adapter_network_error_is_temporary(monkeypatch):
    def down(*a, **kw):
        raise httpx.ConnectError("down")

    monkeypatch.setattr("httpx.post", down)
    result = _provider().send(_content(), "key")
    assert not result.accepted and not result.permanent and "Could not reach WhatsApp" in result.error
