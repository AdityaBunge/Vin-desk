"""The 19-step "definition of done" scenario, end to end through the HTTP API."""
from decimal import Decimal

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models import AuditLog, CommunicationAttempt, DeliveryJob, InventoryMovement, Invoice, Payment, ServiceJob
from tests import flow


def test_complete_service_visit(w):
    # 1-2. The Service Manager receives a Force Traveller, searches the registration, opens a job card.
    assert w.ok("manager", "GET", "/vehicles/lookup", params={"registration": "MH12AB1234"})["found"] is False
    vehicle = flow.new_vehicle(w, reg="MH12AB1234", model="Force Traveller")
    lookup = w.ok("manager", "GET", "/vehicles/lookup", params={"registration": "mh12ab1234"})
    assert lookup["found"] and lookup["vehicle"]["model"]["name"] == "Force Traveller"
    job = flow.open_job(w, vehicle["id"], assign=False)
    jid = job["id"]

    # 3. Assign to a mechanic.
    job = w.ok("manager", "POST", f"/jobs/{jid}/assign", json={"mechanic_id": w.ids["mechanic"]})
    assert job["status"] == "INSPECTION_IN_PROGRESS"

    # 4. The mechanic inspects and requests several parts.
    flow.inspect(w, jid, parts=(("OIL", 2), ("PAD", 2), ("CLUTCH", 1)), labour=("LAB-GS", "LAB-BRK"))
    w.ok("manager", "POST", f"/jobs/{jid}/inspection/submit")
    assert flow.stock("OIL") == (10, 0)
    job = flow.get_job(w, jid)
    assert job["status"] == "AWAITING_PARTS"
    ln = flow.lines(job)

    # 5. Inventory fulfils what is available: oil in full; the single pad set in stock is reserved.
    w.ok("inventory", "POST", f"/parts-request-lines/{ln['OIL']['id']}/issue", json={"quantity": 2})
    w.ok("inventory", "POST", f"/parts-request-lines/{ln['PAD']['id']}/reserve", json={"quantity": 1})
    assert flow.stock("PAD") == (1, 1)

    # 6. Shortages are recorded and reported to the Service Manager.
    w.ok("inventory", "POST", f"/parts-request-lines/{ln['PAD']['id']}/unavailable", json={"notes": "1 short"})
    w.ok("inventory", "POST", f"/parts-request-lines/{ln['CLUTCH']['id']}/unavailable", json={"expected_restock_date": "2030-02-01"})
    assert w.ok("manager", "GET", "/dashboard")["cards"]["parts_shortages"] == 2
    shortages = {r["sku"]: r for r in w.ok("manager", "GET", "/reports/unavailable-parts")["rows"]}
    assert Decimal(shortages["PAD"]["outstanding"]) == 2 and Decimal(shortages["CLUTCH"]["outstanding"]) == 1

    # 7. The manager arranges replenishment for the clutch and approves an alternative for the pads.
    pr = w.ok("inventory", "POST", "/purchase-requests", json={"lines": [{"part_id": w.part["CLUTCH"], "quantity": 2}]})
    w.ok("manager", "POST", f"/purchase-requests/{pr['id']}/decision", json={"approve": True})
    w.ok("inventory", "POST", f"/purchase-requests/{pr['id']}/receive", json={})
    assert flow.stock("CLUTCH") == (2, 0)
    w.ok("inventory", "POST", f"/parts-request-lines/{ln['PAD']['id']}/alternative", json={"part_id": w.part["PAD-HD"]})
    alt = w.ok("manager", "POST", f"/parts-request-lines/{ln['PAD']['id']}/alternative-decision", json={"approve": True})
    assert alt["part"]["sku"] == "PAD-HD" and flow.stock("PAD") == (1, 0)  # reservation on the original released

    # 8. Inventory issues the remaining parts.
    job = flow.issue_all(w, jid)
    assert job["status"] == "READY_FOR_SERVICE" and flow.stock("CLUTCH") == (1, 0) and flow.stock("PAD-HD") == (3, 0)
    assert flow.stock("PAD") == (1, 0)

    # 9. The mechanic completes the repair and records actual parts used (one oil can unused).
    flow.complete(w, jid, consumed={"OIL": 1})
    oil = flow.lines(flow.get_job(w, jid))["OIL"]
    w.ok("inventory", "POST", f"/parts-request-lines/{oil['id']}/return", json={"quantity": 1})
    assert flow.stock("OIL") == (9, 0)

    # 10. Completed work goes straight to the Service Manager for billing (no quality step).
    job = flow.get_job(w, jid)
    assert job["status"] == "READY_FOR_BILLING" and job["billing_blockers"] == []

    # 11. The manager reviews labour, parts, taxes and the total.
    draft = w.ok("manager", "POST", f"/jobs/{jid}/invoice")
    amounts = {l["code"]: (l["quantity"], l["line_total"]) for l in draft["lines"]}
    assert amounts == {
        "LAB-GS": ("2.00", "1534.00"),      # 1300 + 18%
        "LAB-BRK": ("1.50", "1150.50"),     # 975 + 18%
        "OIL": ("1.00", "1180.00"),         # consumed 1 of the 2 requested
        "PAD-HD": ("2.00", "7296.00"),      # 5700 + 28%
        "CLUTCH": ("1.00", "13952.00"),     # 10900 + 28%
    }
    # Line totals add up to 25112.50; the invoice is payable in whole rupees.
    assert draft["total"] == "25113.00" and draft["round_off"] == "0.50"
    assert draft["total_in_words"] == "INR Twenty Five Thousand One Hundred Thirteen Only"
    assert w.call("manager", "GET", f"/invoices/{draft['id']}/pdf").content.startswith(b"%PDF")

    # 12-13. Finalise: invoice and both delivery jobs are saved together.
    inv = w.ok("manager", "POST", f"/invoices/{draft['id']}/finalise")
    assert inv["status"] == "FINALISED" and {d["channel"] for d in inv["delivery_jobs"]} == {"EMAIL", "SMS"}
    assert all(d["status"] == "PENDING" for d in inv["delivery_jobs"])

    # 14-15. The worker sends the PDF by email and the secure link by SMS; tracked independently.
    w.sms.script = ["perm"]
    flow.run_worker()
    d = flow.deliveries(w, inv["id"])
    assert d["EMAIL"]["status"] == "SENT" and d["SMS"]["status"] == "FAILED"
    assert w.email.sent[0].attachments[0][0] == f"{inv['invoice_number']}.pdf"

    # 16. Retry the failed channel only; the email is not duplicated.
    w.ok("manager", "POST", f"/deliveries/{d['SMS']['id']}/retry")
    flow.run_worker()
    d = flow.deliveries(w, inv["id"])
    assert d["SMS"]["status"] == "SENT" and len(w.email.sent) == 1 and len(w.sms.sent) == 1
    token = w.sms.sent[0].body.split("/i/")[1].split(" ")[0]
    assert w.client.get(f"/api/public/invoices/{token}").json()["total"] == "25113.00"

    # 17. Record payment; verify the outstanding balance.
    w.ok("manager", "POST", f"/invoices/{inv['id']}/payments", json={"amount": "20000", "method": "BANK_TRANSFER"})
    assert w.ok("manager", "GET", f"/invoices/{inv['id']}")["outstanding"] == "5113.00"
    w.ok("manager", "POST", f"/invoices/{inv['id']}/payments", json={"amount": "5113.00", "method": "UPI"})
    paid = w.ok("manager", "GET", f"/invoices/{inv['id']}")
    assert paid["payment_status"] == "PAID" and paid["outstanding"] == "0.00"

    # 18. Ready for delivery, then handover.
    assert w.ok("manager", "POST", f"/jobs/{jid}/ready-for-delivery")["status"] == "READY_FOR_DELIVERY"
    job = w.ok("manager", "POST", f"/jobs/{jid}/handover", json={"received_by": "Mr. Ganesh (owner)", "notes": "Keys and old parts returned"})
    assert job["status"] == "COMPLETED" and job["delivered_at"]

    # 19. Everything remains on record.
    statuses = [e["to_status"] for e in job["events"] if e["to_status"]]
    assert statuses == ["RECEIVED", "AWAITING_ASSIGNMENT", "INSPECTION_IN_PROGRESS",
                        "AWAITING_PARTS", "READY_FOR_SERVICE", "IN_SERVICE",
                        "READY_FOR_BILLING", "READY_FOR_DELIVERY", "COMPLETED"]
    assert all(e["actor"] for e in job["events"])
    with SessionLocal() as db:
        count = lambda model: db.scalar(select(func.count()).select_from(model))  # noqa: E731
        assert count(ServiceJob) == 1 and count(Invoice) == 1 and count(Payment) == 2 and count(DeliveryJob) == 2
        assert count(CommunicationAttempt) == 3  # email ok, sms failed, sms ok
        types = db.scalars(select(InventoryMovement.movement_type).order_by(InventoryMovement.id)).all()
        assert types.count("ISSUED") == 3 and types.count("RETURNED") == 1 and types.count("RECEIVED") == 1
        assert types.count("RESERVED") == 1 and types.count("RESERVATION_RELEASED") == 1
        actions = set(db.scalars(select(AuditLog.action)))
        assert {"job.create", "job.assign", "purchase.approve", "parts.alternative_decision",
                "invoice.finalise", "delivery.retry", "payment.record", "job.handover"} <= actions
    revenue = w.ok("manager", "GET", "/reports/revenue")
    assert Decimal(revenue["summary"]["invoiced_total"]) == Decimal("25113.00")
    assert Decimal(revenue["summary"]["payments_collected"]) == Decimal("25113.00")
    history = w.ok("manager", "GET", f"/vehicles/{vehicle['id']}/history")
    assert history[0]["invoice_number"] == inv["invoice_number"] and len(history[0]["parts"]) == 3
