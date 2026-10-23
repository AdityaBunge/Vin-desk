"""Billing, payments, and invoice delivery by email + SMS (spec tests 22-38)."""
import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select, update

from app.core.database import SessionLocal
from app.core.utils import utcnow
from app.integrations import registry
from app.models import AuditLog, Customer, DeliveryJob, Invoice, InvoiceLink
from app.services import delivery
from tests import flow


def _finalised(w, **kw):
    job = flow.to_billing(w, **kw)
    return job, flow.finalise(w, job["id"])


def _due_now(invoice_id):
    with SessionLocal() as db:
        db.execute(update(DeliveryJob).where(DeliveryJob.invoice_id == invoice_id).values(next_attempt_at=utcnow() - timedelta(seconds=1)))
        db.commit()


def _link_from(w) -> str:
    """The customer link, as it appears in the SMS body."""
    body = w.sms.sent[-1].body
    return body.split("securely: ")[1].split(" ")[0]


def _token(url: str) -> str:
    assert url.startswith("https://service.test/i/")
    return url.rsplit("/i/", 1)[1]


# 22 + 23. Invoice calculations, tax and discounts
def test_invoice_calculations_tax_and_discount(w):
    job = flow.to_billing(w, parts=(("OIL", 2), ("PAD", 1)))
    draft = w.ok("manager", "POST", f"/jobs/{job['id']}/invoice")
    by_code = {l["code"]: l for l in draft["lines"]}
    # Labour 2h x 650 @18%; oil 2 x 1000 @18%; pad 1 x 2400 @28% - different tax treatment per line.
    assert (by_code["LAB-GS"]["tax_amount"], by_code["LAB-GS"]["line_total"]) == ("234.00", "1534.00")
    assert (by_code["OIL"]["tax_amount"], by_code["OIL"]["line_total"]) == ("360.00", "2360.00")
    assert (by_code["PAD"]["tax_rate"], by_code["PAD"]["tax_amount"], by_code["PAD"]["line_total"]) == ("28.00", "672.00", "3072.00")
    assert (draft["subtotal_labour"], draft["subtotal_parts"], draft["tax_total"], draft["total"]) == ("1300.00", "4400.00", "1266.00", "6966.00")
    assert draft["invoice_number"] is None and draft["status"] == "DRAFT"

    labour_id = by_code["LAB-GS"]["id"]
    too_much = w.call("manager", "PATCH", f"/invoices/{draft['id']}", json={"discounts": [{"line_id": labour_id, "discount_amount": "130.01"}]})
    assert too_much.status_code == 409  # above the authorised 10%
    draft = w.ok("manager", "PATCH", f"/invoices/{draft['id']}", json={"discounts": [{"line_id": labour_id, "discount_amount": "100.00"}]})
    lab = next(l for l in draft["lines"] if l["code"] == "LAB-GS")
    assert (lab["tax_amount"], lab["line_total"]) == ("216.00", "1416.00")  # tax on the discounted amount
    assert (draft["discount_total"], draft["taxable_total"], draft["tax_total"], draft["total"]) == ("100.00", "5600.00", "1248.00", "6848.00")
    breakdown = {b["name"]: b for b in draft["tax_breakdown"]}
    assert (breakdown["GST 18%"]["taxable"], breakdown["GST 18%"]["cgst"], breakdown["GST 18%"]["sgst"]) == ("3200.00", "288.00", "288.00")
    assert breakdown["GST 28%"]["tax"] == "672.00"

    pdf = w.call("manager", "GET", f"/invoices/{draft['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    final = w.ok("manager", "POST", f"/invoices/{draft['id']}/finalise")
    assert final["total"] == "6848.00" and final["discount_total"] == "100.00"


def test_rounding_is_half_up_to_paise():
    from app.services.estimates import calc_line

    assert calc_line("3", "33.335", "0", "18") == (Decimal("100.01"), Decimal("18.00"), Decimal("118.01"))
    assert calc_line("1", "0.125", "0", "0")[0] == Decimal("0.13")


# 26. Invoice finalisation and audit logging
def test_finalisation_freezes_invoice_and_is_audited(w):
    job, inv = _finalised(w)
    assert inv["status"] == "FINALISED" and inv["invoice_number"].startswith("INV-") and inv["invoice_number"].endswith("-0001")
    assert inv["customer_name"] == "Ganesh Tours" and inv["vehicle_registration"] == "MH12AB1234" and inv["vehicle_model"] == "Force Traveller"
    assert inv["job_number"] == job["job_number"] and inv["payment_status"] == "UNPAID"
    # Finalised invoices cannot be edited, re-finalised or rebuilt.
    assert w.call("manager", "PATCH", f"/invoices/{inv['id']}", json={"notes": "changed"}).status_code == 409
    assert w.call("manager", "POST", f"/invoices/{inv['id']}/finalise").status_code == 409
    assert w.call("manager", "POST", f"/jobs/{job['id']}/invoice").status_code == 409
    # Later master-data changes do not alter the frozen invoice.
    w.ok("manager", "PATCH", f"/customers/{inv['customer_id']}", json={"name": "Renamed Travels"})
    assert w.ok("manager", "GET", f"/invoices/{inv['id']}")["customer_name"] == "Ganesh Tours"
    with SessionLocal() as db:
        entry = db.scalar(select(AuditLog).where(AuditLog.action == "invoice.finalise"))
        assert entry.entity_id == str(inv["id"]) and entry.actor_email == "manager@test.local" and entry.details["total"] == inv["total"]


def test_cancel_and_reissue_invoice(w):
    job, inv = _finalised(w)
    flow.run_worker()
    link = _link_from(w)
    payment = w.ok("manager", "POST", f"/invoices/{inv['id']}/payments", json={"amount": "100", "method": "CASH"})
    assert w.call("manager", "POST", f"/invoices/{inv['id']}/cancel", json={"reason": "Wrong labour hours"}).status_code == 409
    w.ok("manager", "POST", f"/payments/{payment['id']}/void", json={"reason": "Invoice being corrected"})
    cancelled = w.ok("manager", "POST", f"/invoices/{inv['id']}/cancel", json={"reason": "Wrong labour hours"})
    assert cancelled["status"] == "CANCELLED" and cancelled["invoice_number"] == inv["invoice_number"]
    assert w.client.get(f"/api/public/invoices/{_token(link)}").status_code == 404  # link revoked
    new = flow.finalise(w, job["id"])
    assert new["id"] != inv["id"] and new["invoice_number"].endswith("-0002")


# 24 + 25. Payments and outstanding balance
def test_payments_and_outstanding_balance(w):
    job, inv = _finalised(w)  # total 3894.00
    total = Decimal(inv["total"])
    assert w.call("manager", "POST", f"/invoices/{inv['id']}/payments", json={"amount": str(total + 1), "method": "CASH"}).status_code == 409
    assert w.call("manager", "POST", f"/invoices/{inv['id']}/payments", json={"amount": "0", "method": "CASH"}).status_code == 422
    assert w.call("manager", "POST", f"/invoices/{inv['id']}/payments", json={"amount": "10", "method": "CHEQUE"}).status_code == 422
    assert w.call("inventory", "POST", f"/invoices/{inv['id']}/payments", json={"amount": "10", "method": "CASH"}).status_code == 403
    p1 = w.ok("manager", "POST", f"/invoices/{inv['id']}/payments", json={
        "amount": "1500.00", "method": "UPI", "external_reference": "UPI-7781", "idempotency_key": "form-submit-0001"})
    assert p1["reference"].startswith("PAY-")
    # A double-submitted form (same key) does not create a second payment.
    again = w.ok("manager", "POST", f"/invoices/{inv['id']}/payments", json={"amount": "1500.00", "method": "UPI", "idempotency_key": "form-submit-0001"})
    assert again["id"] == p1["id"]
    state = w.ok("manager", "GET", f"/invoices/{inv['id']}")
    assert (state["amount_paid"], state["outstanding"], state["payment_status"]) == ("1500.00", "2394.00", "PARTIALLY_PAID")
    assert w.call("manager", "POST", f"/invoices/{inv['id']}/payments", json={"amount": "2394.01", "method": "CARD"}).status_code == 409
    w.ok("manager", "POST", f"/invoices/{inv['id']}/payments", json={"amount": "2394.00", "method": "BANK_TRANSFER"})
    state = w.ok("manager", "GET", f"/invoices/{inv['id']}")
    assert (state["outstanding"], state["payment_status"]) == ("0.00", "PAID")
    w.ok("manager", "POST", f"/payments/{p1['id']}/void", json={"reason": "UPI reversal"})
    state = w.ok("manager", "GET", f"/invoices/{inv['id']}")
    assert (state["amount_paid"], state["outstanding"], state["payment_status"]) == ("2394.00", "1500.00", "PARTIALLY_PAID")
    with SessionLocal() as db:
        actions = db.scalars(select(AuditLog.action).where(AuditLog.action.like("payment.%"))).all()
        assert sorted(actions) == ["payment.record", "payment.record", "payment.void"]
    dash = w.ok("manager", "GET", "/dashboard")["cards"]
    assert Decimal(dash["outstanding_total"]) == Decimal("1500.00") and dash["partially_paid_invoices"] == 1


def test_handover_requires_confirmation_when_balance_outstanding(w):
    job, inv = _finalised(w)
    w.ok("manager", "POST", f"/jobs/{job['id']}/ready-for-delivery")
    r = w.call("manager", "POST", f"/jobs/{job['id']}/handover", json={"received_by": "Driver"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "OUTSTANDING_BALANCE"
    done = w.ok("manager", "POST", f"/jobs/{job['id']}/handover", json={"received_by": "Driver", "allow_outstanding": True})
    assert done["status"] == "COMPLETED" and done["handover_to"] == "Driver"


# 27 + 28. Successful email and SMS delivery through mocked providers
def test_finalise_queues_then_delivers_email_and_sms(w):
    job, inv = _finalised(w)
    # Finalisation only writes the outbox; nothing has been sent yet.
    assert w.email.calls == [] and w.sms.calls == []
    d = flow.deliveries(w, inv["id"])
    assert d["EMAIL"]["status"] == "PENDING" and d["SMS"]["status"] == "PENDING"
    assert d["EMAIL"]["destination"] == "owner@example.com" and d["SMS"]["destination"] == "+919822012345"

    assert flow.run_worker() == 2
    d = flow.deliveries(w, inv["id"])
    # Provider acceptance is SENT, never DELIVERED.
    assert d["EMAIL"]["status"] == "SENT" and d["SMS"]["status"] == "SENT"
    assert d["EMAIL"]["attempts"][0]["outcome"] == "ACCEPTED" and d["EMAIL"]["delivered_at"] is None

    email = w.email.sent[0]
    assert email.subject == f"Your Vehicle Service Invoice - {job['job_number']}"
    assert email.to_address == "owner@example.com"
    for text in (inv["invoice_number"], "MH12AB1234", "Force Traveller", job["job_number"], "3,894.00", "Ganesh Tours"):
        assert text in email.text_body and text in email.html_body
    filename, data, mime = email.attachments[0]
    assert filename == f"{inv['invoice_number']}.pdf" and mime == "application/pdf" and data.startswith(b"%PDF")

    sms = w.sms.sent[0]
    assert sms.to_e164 == "+919822012345"
    for text in (inv["invoice_number"], "MH12AB1234", "INR 3,894.00", "https://service.test/i/"):
        assert text in sms.body
    assert "owner@example.com" not in sms.body and "Ganesh" not in sms.body  # no personal data in the SMS
    assert _link_from(w) in email.text_body


# 29. Email fails while SMS succeeds
def test_email_failure_does_not_block_sms(w):
    w.email.script = ["perm"]
    _, inv = _finalised(w)
    flow.run_worker()
    d = flow.deliveries(w, inv["id"])
    assert d["EMAIL"]["status"] == "FAILED" and d["EMAIL"]["last_error"] == "permanently rejected"
    assert d["SMS"]["status"] == "SENT" and len(w.sms.sent) == 1
    assert "INVOICE_EMAIL_FAILED" in [n["type"] for n in w.ok("manager", "GET", "/notifications")["items"]]
    assert w.ok("manager", "GET", "/dashboard")["cards"]["email_failures"] == 1


# 30. SMS fails while email succeeds; retrying SMS does not resend the email
def test_sms_failure_does_not_block_email_and_retry_is_channel_specific(w):
    w.sms.script = ["raise", "raise", "raise", "raise", "raise"]
    _, inv = _finalised(w)
    for _ in range(5):
        flow.run_worker()
        _due_now(inv["id"])
    d = flow.deliveries(w, inv["id"])
    assert d["EMAIL"]["status"] == "SENT" and len(w.email.sent) == 1
    assert d["SMS"]["status"] == "FAILED" and d["SMS"]["attempt_count"] == 5 and "gave up after 5 attempts" in d["SMS"]["last_error"]
    retried = w.ok("manager", "POST", f"/deliveries/{d['SMS']['id']}/retry")
    assert retried["status"] == "PENDING"
    flow.run_worker()
    d = flow.deliveries(w, inv["id"])
    assert d["SMS"]["status"] == "SENT" and len(w.sms.sent) == 1
    assert len(w.email.sent) == 1 and len(w.email.calls) == 1  # the successful email was not sent again
    assert w.call("manager", "POST", f"/deliveries/{d['EMAIL']['id']}/retry").status_code == 409  # nothing to retry


# 31. Both channels fail; the finalised invoice is unaffected
def test_both_channels_failing_keeps_invoice(w):
    w.email.script, w.sms.script = ["perm"], ["perm"]
    job, inv = _finalised(w)
    flow.run_worker()
    d = flow.deliveries(w, inv["id"])
    assert d["EMAIL"]["status"] == "FAILED" and d["SMS"]["status"] == "FAILED"
    state = w.ok("manager", "GET", f"/invoices/{inv['id']}")
    assert state["status"] == "FINALISED" and state["invoice_number"] == inv["invoice_number"]
    failures = w.ok("manager", "GET", "/reports/sms-failures")
    assert failures["rows"][0]["invoice_number"] == inv["invoice_number"]
    rates = {r["channel"]: r for r in w.ok("manager", "GET", "/reports/delivery-rates")["rows"]}
    assert rates["EMAIL"]["failed"] == 1 and rates["EMAIL"]["success_rate"] == 0.0
    # Payment and delivery still proceed.
    w.ok("manager", "POST", f"/invoices/{inv['id']}/payments", json={"amount": inv["total"], "method": "CASH"})
    assert w.ok("manager", "POST", f"/jobs/{job['id']}/ready-for-delivery")["status"] == "READY_FOR_DELIVERY"


# 32. Retry handling with exponential backoff
def test_temporary_failure_is_retried_with_backoff(w):
    w.email.script = ["temp", "temp"]
    _, inv = _finalised(w)
    flow.run_worker()
    with SessionLocal() as db:
        job = db.scalar(select(DeliveryJob).where(DeliveryJob.channel == "EMAIL"))
        assert job.status == "RETRY_SCHEDULED" and job.attempt_count == 1
        first_delay = (job.next_attempt_at - utcnow()).total_seconds()
        assert 50 < first_delay <= 60
    assert flow.run_worker() == 0  # not due yet: no premature retry
    _due_now(inv["id"])
    flow.run_worker()
    with SessionLocal() as db:
        job = db.scalar(select(DeliveryJob).where(DeliveryJob.channel == "EMAIL"))
        assert job.status == "RETRY_SCHEDULED" and 110 < (job.next_attempt_at - utcnow()).total_seconds() <= 120
    _due_now(inv["id"])
    flow.run_worker()
    d = flow.deliveries(w, inv["id"])["EMAIL"]
    assert d["status"] == "SENT" and d["attempt_count"] == 3
    assert [a["outcome"] for a in d["attempts"]] == ["TEMPORARY_FAILURE", "TEMPORARY_FAILURE", "ACCEPTED"]
    assert len(w.email.sent) == 1


# 33. Duplicate delivery prevention
def test_no_duplicate_messages(w):
    w.sms.script = ["temp"]
    _, inv = _finalised(w)
    flow.run_worker()
    _due_now(inv["id"])
    flow.run_worker()
    assert flow.run_worker() == 0 and flow.run_worker() == 0  # nothing left to do
    assert len(w.email.sent) == 1 and len(w.sms.sent) == 1
    # Every attempt of one delivery job carries the same idempotency key.
    keys = [key for _, key in w.sms.calls]
    assert len(keys) == 2 and keys[0] == keys[1]
    assert keys[0] != w.email.calls[0][1]
    # A job that is already claimed is not picked up by a second worker.
    w.ok("manager", "POST", f"/invoices/{inv['id']}/resend", json={"channel": "SMS", "confirm": True})
    with SessionLocal() as db:
        first = delivery.claim_due(db)
        second = delivery.claim_due(db)
        assert len(first) == 1 and second == []
    # While that delivery is in progress, another resend on the channel is refused.
    assert w.call("manager", "POST", f"/invoices/{inv['id']}/resend", json={"channel": "SMS", "confirm": True}).status_code == 409


def test_stale_claim_is_recovered_after_worker_crash(w):
    _, inv = _finalised(w)
    with SessionLocal() as db:
        assert len(delivery.claim_due(db)) == 2  # worker claims the jobs, then "crashes"
    assert flow.run_worker() == 0
    with SessionLocal() as db:
        db.execute(update(DeliveryJob).values(locked_until=utcnow() - timedelta(seconds=1)))
        db.commit()
    assert flow.run_worker() == 2 and len(w.email.sent) == 1 and len(w.sms.sent) == 1


# 34. Provider delivery-status callbacks
def test_delivery_receipt_webhook(w):
    _, inv = _finalised(w)
    flow.run_worker()

    def post(payload, signature=None):
        raw = json.dumps(payload).encode()
        sig = signature or hmac.new(b"test-webhook-secret", raw, hashlib.sha256).hexdigest()
        return w.client.post("/api/webhooks/delivery/fake-sms", content=raw, headers={"X-Webhook-Signature": sig, "Content-Type": "application/json"})

    event = {"event_id": "evt-1", "message_id": "fake-sms-msg-1", "status": "delivered"}
    assert post(event, signature="0" * 64).status_code == 401
    assert w.client.post("/api/webhooks/delivery/fake-sms", json=event).status_code == 401
    assert flow.deliveries(w, inv["id"])["SMS"]["status"] == "SENT"
    assert post(event).json() == {"result": "applied"}
    sms = flow.deliveries(w, inv["id"])["SMS"]
    assert sms["status"] == "DELIVERED" and sms["delivered_at"] is not None
    assert post(event).json() == {"result": "duplicate"}  # replayed callback is ignored
    assert post({"event_id": "evt-2", "message_id": "unknown-id", "status": "delivered"}).json() == {"result": "ignored"}
    assert post({"event_id": "evt-3", "message_id": "fake-email-msg-1", "status": "delivered"}).json() == {"result": "ignored"}  # wrong provider
    assert flow.deliveries(w, inv["id"])["EMAIL"]["status"] == "SENT"


def test_delivery_status_is_unknown_without_receipts(w):
    w.email.supports_receipts = False
    _, inv = _finalised(w)
    flow.run_worker()
    d = flow.deliveries(w, inv["id"])
    assert d["EMAIL"]["status"] == "SENT" and d["EMAIL"]["display_status"] == "DELIVERY_STATUS_UNKNOWN"
    assert d["SMS"]["display_status"] == "SENT"


# 35. Secure invoice-link access and expiry
def test_secure_invoice_link(w):
    _, inv = _finalised(w)
    flow.run_worker()
    token = _token(_link_from(w))
    assert len(token) > 60 and str(inv["id"]) != token and inv["invoice_number"] not in token
    view = w.client.get(f"/api/public/invoices/{token}")  # no login needed
    assert view.status_code == 200
    body = view.json()
    assert body["invoice_number"] == inv["invoice_number"] and body["total"] == inv["total"]
    assert "customer_email" not in body and "customer_mobile" not in body and "id" not in body
    pdf = w.client.get(f"/api/public/invoices/{token}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    # Guessing or tampering does not work; neither do sequential IDs.
    assert w.client.get(f"/api/public/invoices/{token[:-1]}x").status_code == 404
    assert w.client.get(f"/api/public/invoices/{inv['id']}").status_code == 404
    assert w.client.get("/api/public/invoices/1.abcdef").status_code == 404
    with SessionLocal() as db:
        link = db.scalar(select(InvoiceLink))
        assert link.access_count == 2 and token.split(".")[1] not in (link.public_id,)
        link.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    assert w.client.get(f"/api/public/invoices/{token}").status_code == 410  # expired
    # The manager resends: a fresh link is issued automatically.
    w.ok("manager", "POST", f"/invoices/{inv['id']}/resend", json={"channel": "SMS", "confirm": True})
    flow.run_worker()
    new_token = _token(_link_from(w))
    assert new_token != token and w.client.get(f"/api/public/invoices/{new_token}").status_code == 200
    # Explicit reissue revokes every earlier link.
    reissued = w.ok("manager", "POST", f"/invoices/{inv['id']}/link")
    assert w.client.get(f"/api/public/invoices/{new_token}").status_code == 404
    assert w.client.get(f"/api/public/invoices/{_token(reissued['url'])}").status_code == 200
    assert w.call("inventory", "POST", f"/invoices/{inv['id']}/link").status_code == 403


def test_public_link_is_rate_limited(w, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "public_link_rate_limit_per_minute", 3)
    codes = [w.client.get("/api/public/invoices/guess.guess").status_code for _ in range(5)]
    assert codes == [404, 404, 404, 429, 429]


# 36. Manual resend authorisation, confirmation and rate limiting
def test_manual_resend_rules(w):
    _, inv = _finalised(w)
    flow.run_worker()
    url = f"/invoices/{inv['id']}/resend"
    for role in ("inventory", "admin"):
        assert w.call(role, "POST", url, json={"channel": "EMAIL", "confirm": True}).status_code == 403
    assert w.call("manager", "POST", url, json={"channel": "EMAIL"}).status_code == 400  # must be confirmed
    assert w.call("manager", "POST", url, json={"channel": "FAX", "confirm": True}).status_code == 422
    for _ in range(3):
        job = w.ok("manager", "POST", url, json={"channel": "EMAIL", "confirm": True})
        assert job["trigger"] == "MANUAL" and job["channel"] == "EMAIL"
        flow.run_worker()
    assert len(w.email.sent) == 4 and len(w.sms.sent) == 1  # the SMS channel was never touched
    limited = w.call("manager", "POST", url, json={"channel": "EMAIL", "confirm": True})
    assert limited.status_code == 429
    assert w.call("manager", "POST", url, json={"channel": "SMS", "confirm": True}).status_code == 201  # per-channel limit
    with SessionLocal() as db:
        assert len(db.scalars(select(AuditLog).where(AuditLog.action == "delivery.resend")).all()) == 4


# 37. Missing or invalid customer contact details
def test_missing_email_and_invalid_mobile(w):
    job = flow.to_billing(w)
    with SessionLocal() as db:
        customer = db.scalar(select(Customer))
        customer.mobile, customer.email = "12345", None  # legacy bad data (email is now mandatory for new entries)
        db.commit()
    inv = flow.finalise(w, job["id"])
    assert inv["status"] == "FINALISED"
    d = flow.deliveries(w, inv["id"])
    assert d["EMAIL"]["status"] == "FAILED" and "no email address" in d["EMAIL"]["last_error"]
    assert d["SMS"]["status"] == "FAILED" and "not a valid Indian mobile" in d["SMS"]["last_error"]
    assert flow.run_worker() == 0 and w.email.calls == [] and w.sms.calls == []
    types = [n["type"] for n in w.ok("manager", "GET", "/notifications")["items"]]
    assert "INVOICE_EMAIL_FAILED" in types and "INVOICE_SMS_FAILED" in types
    # Retrying before correcting the contact is refused with a clear reason.
    r = w.call("manager", "POST", f"/deliveries/{d['EMAIL']['id']}/retry")
    assert r.status_code == 409 and "Correct the customer" in r.json()["detail"]
    # The manager corrects the details and retries each channel.
    w.ok("manager", "PATCH", f"/customers/{inv['customer_id']}", json={"email": "fixed@example.com", "mobile": "98220 12345"})
    w.ok("manager", "POST", f"/deliveries/{d['EMAIL']['id']}/retry")
    w.ok("manager", "POST", f"/deliveries/{d['SMS']['id']}/retry")
    assert flow.run_worker() == 2
    d = flow.deliveries(w, inv["id"])
    assert d["EMAIL"]["status"] == "SENT" and d["EMAIL"]["destination"] == "fixed@example.com"
    assert d["SMS"]["status"] == "SENT" and w.sms.sent[0].to_e164 == "+919822012345"


def test_opted_out_channel_is_skipped(w):
    job = flow.to_billing(w)
    w.ok("manager", "PATCH", f"/customers/{job['customer']['id']}", json={"sms_opt_in": False})
    inv = flow.finalise(w, job["id"])
    flow.run_worker()
    d = flow.deliveries(w, inv["id"])
    assert d["SMS"]["status"] == "SKIPPED" and d["EMAIL"]["status"] == "SENT" and w.sms.calls == []
    consents = w.ok("manager", "GET", f"/customers/{job['customer']['id']}")["consents"]
    assert [(c["channel"], c["granted"]) for c in consents][-1] == ("SMS", False)


# 38. No real provider messages during automated tests
def test_no_real_providers_in_tests(w):
    assert registry.get_email_provider() is w.email and registry.get_sms_provider() is w.sms
    registry.set_overrides(None, None)
    try:
        # Even without the fakes, the test environment resolves to the simulators.
        assert registry.get_email_provider().simulated and registry.get_sms_provider().simulated
    finally:
        registry.set_overrides(w.email, w.sms)


def test_dev_simulator_is_labelled_and_sends_nothing(w, tmp_path, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "dev_outbox_dir", str(tmp_path))
    registry.set_overrides(None, None)
    _, inv = _finalised(w)
    flow.run_worker()
    d = flow.deliveries(w, inv["id"])
    assert d["EMAIL"]["simulated"] and d["EMAIL"]["display_status"] == "SIMULATED" and d["EMAIL"]["provider"] == "dev-simulator"
    assert d["SMS"]["display_status"] == "SIMULATED"
    assert len(list(tmp_path.glob("email-*.eml"))) == 1 and (tmp_path / "sms.log").exists()


def test_sms_disabled_sends_email_only(w, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "sms_provider", "disabled")
    _, inv = _finalised(w)
    d = flow.deliveries(w, inv["id"])
    assert set(d) == {"EMAIL"}  # no SMS row is queued at all
    assert flow.run_worker() == 1 and len(w.email.sent) == 1 and w.sms.calls == []
    r = w.call("manager", "POST", f"/invoices/{inv['id']}/resend", json={"channel": "SMS", "confirm": True})
    assert r.status_code == 409 and "email only" in r.json()["detail"]
    assert "sms_failures" not in w.ok("manager", "GET", "/dashboard")["cards"]
    # A production start no longer demands an SMS provider when SMS is turned off.
    assert not any("SMS" in p for p in get_settings().production_problems())


def test_production_never_falls_back_to_simulator(w, monkeypatch):
    from app.core.config import get_settings

    registry.set_overrides(None, None)
    _, inv = _finalised(w)
    monkeypatch.setattr(get_settings(), "app_env", "production")
    flow.run_worker()
    monkeypatch.setattr(get_settings(), "app_env", "test")
    d = flow.deliveries(w, inv["id"])
    assert d["EMAIL"]["status"] == "FAILED" and "No real email provider" in d["EMAIL"]["last_error"]
    assert d["SMS"]["status"] == "FAILED" and d["SMS"]["sent_at"] is None


# --- Service Manager edits on the draft bill --------------------------------------------------


def test_manager_adds_items_and_edits_rates_on_the_draft_bill(w):
    job = flow.to_billing(w)
    draft = w.ok("manager", "POST", f"/jobs/{job['id']}/invoice")
    tax18 = next(t["id"] for t in w.ok("manager", "GET", "/tax-rates") if t["name"] == "GST 18%")
    url = f"/invoices/{draft['id']}/lines"
    draft = w.ok("manager", "POST", url, json={"description": "Wheel wash", "quantity": "1", "unit_price": "150", "tax_rate_id": tax18, "hsn_code": "998714"})
    custom = next(l for l in draft["lines"] if l["is_custom"])
    assert custom["description"] == "Wheel wash" and custom["tax_rate"] == "18.00" and custom["line_total"] == "177.00"
    labour = next(l for l in draft["lines"] if l["line_type"] == "LABOUR")
    draft = w.ok("manager", "PATCH", f"{url}/{labour['id']}", json={"unit_price": "500"})
    assert next(l for l in draft["lines"] if l["id"] == labour["id"])["unit_price"] == "500.00"
    # Only the rate can change on items that come from the job.
    assert w.call("manager", "PATCH", f"{url}/{labour['id']}", json={"quantity": "9"}).status_code == 409
    assert w.call("manager", "DELETE", f"{url}/{labour['id']}").status_code == 409
    assert w.call("inventory", "POST", url, json={"description": "x", "quantity": "1", "unit_price": "1"}).status_code == 403

    # Rebuilding the draft from the job keeps the manager's item and rate.
    draft = w.ok("manager", "POST", f"/jobs/{job['id']}/invoice")
    assert any(l["is_custom"] and l["description"] == "Wheel wash" for l in draft["lines"])
    assert next(l for l in draft["lines"] if l["line_type"] == "LABOUR")["unit_price"] == "500.00"

    custom = next(l for l in draft["lines"] if l["is_custom"])
    draft = w.ok("manager", "PATCH", f"{url}/{custom['id']}", json={"quantity": "2", "description": "Wheel wash (x2)"})
    assert next(l for l in draft["lines"] if l["is_custom"])["quantity"] == "2.00"
    inv = flow.finalise(w, job["id"])
    assert any(l["description"] == "Wheel wash (x2)" for l in inv["lines"])
    assert next(l for l in inv["lines"] if l["line_type"] == "LABOUR")["unit_price"] == "500.00"
    # Finalised invoices are frozen.
    assert w.call("manager", "POST", f"/invoices/{inv['id']}/lines", json={"description": "x", "quantity": "1", "unit_price": "1"}).status_code == 409


def test_manager_removes_an_added_item(w):
    job = flow.to_billing(w)
    draft = w.ok("manager", "POST", f"/jobs/{job['id']}/invoice")
    before = draft["total"]
    draft = w.ok("manager", "POST", f"/invoices/{draft['id']}/lines", json={"description": "Towing", "quantity": "1", "unit_price": "1000"})
    custom = next(l for l in draft["lines"] if l["is_custom"])
    draft = w.ok("manager", "DELETE", f"/invoices/{draft['id']}/lines/{custom['id']}")
    assert draft["total"] == before and not any(l["is_custom"] for l in draft["lines"])


# --- Mandatory email and the mechanic's view of finished work ---------------------------------


def test_customer_email_is_mandatory(w):
    r = w.call("manager", "POST", "/customers", json={"name": "No Mail", "mobile": "9822099999", "email": ""})
    assert r.status_code == 422 and "Email address is required" in r.text
    assert w.call("manager", "POST", "/customers", json={"name": "No Mail", "mobile": "9822099999"}).status_code == 422
    c = w.ok("manager", "POST", "/customers", json={"name": "Has Mail", "mobile": "9822099998", "email": "a@example.com"})
    assert w.call("manager", "PATCH", f"/customers/{c['id']}", json={"email": ""}).status_code == 422
    assert w.ok("manager", "PATCH", f"/customers/{c['id']}", json={"name": "Renamed"})["email"] == "a@example.com"


def test_features_report_sms_switched_off(w, monkeypatch):
    from app.core.config import get_settings

    assert w.ok("manager", "GET", "/features")["sms"] is True  # tests run with the dev simulator
    monkeypatch.setattr(get_settings(), "sms_provider", "disabled")
    assert w.ok("manager", "GET", "/features")["sms"] is False
    assert w.client.get("/api/features").status_code == 401


def test_returned_only_lists_jobs_sent_back_to_the_mechanic(w):
    job = flow.to_billing(w)
    assert w.ok("manager", "GET", "/jobs", params={"returned_only": "true"})["items"] == []
    w.ok("manager", "POST", f"/jobs/{job['id']}/return-to-mechanic", json={"reason": "Recheck brakes"})
    items = w.ok("manager", "GET", "/jobs", params={"returned_only": "true"})["items"]
    assert [j["id"] for j in items] == [job["id"]]


def test_each_role_dashboard_has_its_own_data(w):
    job = flow.to_billing(w)
    inv = flow.finalise(w, job["id"])
    w.ok("manager", "POST", f"/invoices/{inv['id']}/payments", json={"amount": "100", "method": "CASH"})
    manager = w.ok("manager", "GET", "/dashboard")
    assert manager["pipeline"] == {"READY_FOR_BILLING": 1}
    assert len(manager["trend"]) == 7 and float(manager["trend"][-1]["invoiced"]) == float(inv["total"])
    assert float(manager["trend"][-1]["collected"]) == 100
    inventory = w.ok("inventory", "GET", "/dashboard")
    assert isinstance(inventory["low_stock"], list) and inventory["trend"][-1]["movements"] >= 1
    assert len(w.ok("admin", "GET", "/dashboard")["trend"]) == 7


# --- Direct billing (no inspection or workshop steps) -------------------------------------------


def test_direct_billing_a_vehicle_creates_job_and_draft_invoice(w):
    vehicle = flow.new_vehicle(w)
    url = f"/vehicles/{vehicle['id']}/direct-bill"
    assert w.call("inventory", "POST", url, json={"description": "Wash", "odometer": 1}).status_code == 403
    draft = w.ok("manager", "POST", url, json={"description": "Full body wash and polish", "odometer": 52000})
    assert draft["status"] == "DRAFT" and draft["lines"] == []
    job = flow.get_job(w, draft["job_id"])
    assert job["status"] == "READY_FOR_BILLING" and job["complaints"] == "Full body wash and polish"
    assert "Billed directly" in job["completions"][0]["final_observations"]
    assert any("Billed directly" in e["message"] for e in job["events"])
    # The manager adds what was done, then finalises; the invoice goes out as usual.
    w.ok("manager", "POST", f"/invoices/{draft['id']}/lines", json={"line_type": "LABOUR", "description": "Wash and polish", "quantity": "1", "unit_price": "800"})
    inv = w.ok("manager", "POST", f"/invoices/{draft['id']}/finalise")
    assert inv["status"] == "FINALISED" and float(inv["total"]) == 800
    flow.run_worker()
    assert len(w.email.sent) == 1


def test_direct_billing_an_open_job_skips_the_workshop_steps(w):
    job = flow.open_job(w, flow.new_vehicle(w)["id"])  # inspection in progress
    draft = w.ok("manager", "POST", f"/jobs/{job['id']}/direct-bill", json={"description": "Customer only wanted a check-up"})
    assert flow.get_job(w, job["id"])["status"] == "READY_FOR_BILLING" and draft["job_id"] == job["id"]
    # A second open job on the same vehicle still needs an override reason.
    r = w.call("manager", "POST", f"/vehicles/{job['vehicle']['id']}/direct-bill", json={"description": "Wash", "odometer": 1})
    assert r.status_code == 409


def test_direct_billing_is_blocked_when_stock_is_not_accounted_for(w):
    job = flow.open_job(w, flow.new_vehicle(w)["id"])
    flow.inspect(w, job["id"], parts=(("OIL", 1),))
    flow.submit(w, job["id"])
    flow.issue_all(w, job["id"])  # oil issued but not recorded as used or returned
    r = w.call("manager", "POST", f"/jobs/{job['id']}/direct-bill", json={"description": "Quick bill"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "BILLING_BLOCKED"
    assert flow.get_job(w, job["id"])["status"] == "READY_FOR_SERVICE"  # nothing changed
