"""Inspection, parts requests, inventory, approvals and completion (spec tests 9-21)."""
import threading
from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import InventoryMovement, User
from app.services import inventory
from tests import flow


def _job_with_request(w, parts, reg="MH12AB1234"):
    vehicle = flow.new_vehicle(w, reg=reg)
    job = flow.open_job(w, vehicle["id"])
    return flow.inspect(w, job["id"], parts=parts)


# 9. Inspection and parts-request creation
def test_inspection_and_parts_request(w):
    job = _job_with_request(w, parts=(("OIL", 2), ("PAD", 1)))
    request = job["parts_requests"][0]
    assert request["request_number"].startswith("REQ-") and len(request["lines"]) == 2
    assert all(l["status"] == "PENDING" and l["approval_status"] == "APPROVED" for l in request["lines"])
    assert flow.stock("OIL") == (10, 0) and flow.stock("PAD") == (1, 0)  # requesting never touches stock
    notes = w.ok("inventory", "GET", "/notifications")["items"]
    assert notes[0]["type"] == "PARTS_REQUEST"
    queue = w.ok("inventory", "GET", "/parts-requests", params={"open_only": True})
    assert queue["items"][0]["job"]["job_number"] == job["job_number"]
    job = w.ok("manager", "POST", f"/jobs/{job['id']}/inspection/submit")
    assert job["status"] == "AWAITING_PARTS"  # no customer-approval step
    assert job["estimates"] == [] and job["invoices"] == []  # mechanic view hides commercial documents


def test_inspection_requires_findings(w):
    vehicle = flow.new_vehicle(w)
    job = flow.open_job(w, vehicle["id"])
    assert w.call("manager", "POST", f"/jobs/{job['id']}/inspection/submit").status_code == 409


# 10 + 13. Full fulfilment, reservation and issuance
def test_reserve_and_issue_full(w):
    job = _job_with_request(w, parts=(("OIL", 2),))
    line = flow.lines(job)["OIL"]
    reserved = w.ok("inventory", "POST", f"/parts-request-lines/{line['id']}/reserve", json={"quantity": 2})
    assert reserved["status"] == "RESERVED" and flow.stock("OIL") == (10, 2)
    part = w.ok("inventory", "GET", "/parts", params={"q": "OIL"})["items"][0]
    assert Decimal(part["stock"]["qty_available"]) == 8
    job = flow.submit(w, job["id"])
    assert job["status"] == "AWAITING_PARTS"
    issued = w.ok("inventory", "POST", f"/parts-request-lines/{line['id']}/issue", json={"quantity": 2})
    assert issued["status"] == "ISSUED" and Decimal(issued["qty_outstanding"]) == 0
    assert flow.stock("OIL") == (8, 0)
    job = flow.get_job(w, job["id"])
    assert job["status"] == "READY_FOR_SERVICE" and job["parts_requests"][0]["status"] == "FULFILLED"
    with SessionLocal() as db:
        moves = db.scalars(select(InventoryMovement).order_by(InventoryMovement.id)).all()
        assert [m.movement_type for m in moves] == ["RESERVED", "ISSUED"]
        assert all(m.performed_by_id == w.ids["inventory"] and m.job_id == job["id"] for m in moves)


# 11 + 12. Partial fulfilment and unavailable parts
def test_partial_fulfilment_and_unavailable(w):
    job = _job_with_request(w, parts=(("OIL", 2), ("PAD", 2), ("CLUTCH", 1)))
    job = flow.submit(w, job["id"])
    ln = flow.lines(job)
    w.ok("inventory", "POST", f"/parts-request-lines/{ln['OIL']['id']}/issue", json={"quantity": 2})
    pad = w.ok("inventory", "POST", f"/parts-request-lines/{ln['PAD']['id']}/issue", json={"quantity": 1})
    assert pad["status"] == "PARTIALLY_ISSUED" and Decimal(pad["qty_outstanding"]) == 1
    clutch = w.ok("inventory", "POST", f"/parts-request-lines/{ln['CLUTCH']['id']}/unavailable",
                  json={"expected_restock_date": "2030-01-15", "notes": "On back order"})
    assert clutch["status"] == "UNAVAILABLE" and clutch["expected_restock_date"] == "2030-01-15"
    job = flow.get_job(w, job["id"])
    assert job["status"] == "AWAITING_PARTS" and job["parts_requests"][0]["status"] == "PARTIALLY_FULFILLED"
    types = [n["type"] for n in w.ok("manager", "GET", "/notifications")["items"]]
    assert "PARTS_UNAVAILABLE" in types
    report = w.ok("manager", "GET", "/reports/unavailable-parts")
    assert report["rows"][0]["sku"] == "CLUTCH" and report["rows"][0]["job_number"] == job["job_number"]
    assert w.ok("manager", "GET", "/dashboard")["cards"]["parts_shortages"] == 1


# 14. Prevention of negative stock
def test_negative_stock_is_prevented(w):
    job = _job_with_request(w, parts=(("PAD", 3),))
    job = flow.submit(w, job["id"])
    line = flow.lines(job)["PAD"]
    assert w.call("inventory", "POST", f"/parts-request-lines/{line['id']}/reserve", json={"quantity": 2}).status_code == 409
    assert w.call("inventory", "POST", f"/parts-request-lines/{line['id']}/issue", json={"quantity": 2}).status_code == 409
    assert w.call("inventory", "POST", f"/parts/{w.part['PAD']}/write-off", json={"quantity": 5, "reason": "damaged"}).status_code == 409
    assert w.call("inventory", "POST", f"/parts/{w.part['PAD']}/adjust", json={"delta": -5, "reason": "count"}).status_code == 409
    assert flow.stock("PAD") == (1, 0)
    # Cannot issue more than requested either.
    job2 = _job_with_request(w, parts=(("OIL", 1),), reg="MH12AA0002")
    job2 = flow.submit(w, job2["id"])
    oil = flow.lines(job2)["OIL"]
    assert w.call("inventory", "POST", f"/parts-request-lines/{oil['id']}/issue", json={"quantity": 2}).status_code == 409


# 15. Concurrent issuance protection
def test_concurrent_issue_cannot_double_spend_stock(w):
    """Two jobs each want the single PAD in stock; simultaneous issues must not both succeed."""
    job_a = flow.submit(w, _job_with_request(w, parts=(("PAD", 1),), reg="MH12AA0001")["id"])
    job_b = flow.submit(w, _job_with_request(w, parts=(("PAD", 1),), reg="MH12AA0002")["id"])
    line_ids = [flow.lines(job_a)["PAD"]["id"], flow.lines(job_b)["PAD"]["id"]]
    barrier = threading.Barrier(2)
    results: list[str] = []

    def issue(line_id):
        with SessionLocal() as db:
            user = db.get(User, w.ids["inventory"])
            barrier.wait()
            try:
                inventory.issue(db, line_id, Decimal(1), user)
                db.commit()
                results.append("ok")
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                results.append(type(exc).__name__)

    threads = [threading.Thread(target=issue, args=(i,)) for i in line_ids]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["DomainError", "ok"]
    assert flow.stock("PAD") == (0, 0)
    with SessionLocal() as db:
        issued = db.scalars(select(InventoryMovement).where(InventoryMovement.movement_type == "ISSUED")).all()
        assert len(issued) == 1


# 16. Stock return and reconciliation
def test_return_and_reconciliation(w):
    job = _job_with_request(w, parts=(("OIL", 3),))
    job = flow.submit(w, job["id"])
    flow.issue_all(w, job["id"])
    assert flow.stock("OIL") == (7, 0)
    flow.complete(w, job["id"], consumed={"OIL": 2})  # one unit left over
    job = flow.get_job(w, job["id"])
    assert job["status"] == "READY_FOR_BILLING"
    assert any("neither used nor returned" in b for b in job["billing_blockers"])
    r = w.call("manager", "POST", f"/jobs/{job['id']}/invoice")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "BILLING_BLOCKED"
    line = flow.lines(job)["OIL"]
    assert w.call("inventory", "POST", f"/parts-request-lines/{line['id']}/return", json={"quantity": 2}).status_code == 409
    returned = w.ok("inventory", "POST", f"/parts-request-lines/{line['id']}/return", json={"quantity": 1, "reason": "unused"})
    assert Decimal(returned["qty_returned"]) == 1 and Decimal(returned["qty_unreconciled"]) == 0
    assert flow.stock("OIL") == (8, 0)
    draft = w.ok("manager", "POST", f"/jobs/{job['id']}/invoice")
    part_line = next(l for l in draft["lines"] if l["line_type"] == "PART")
    assert Decimal(part_line["quantity"]) == 2  # billed on actual consumption, not the 3 requested
    moves = w.ok("inventory", "GET", "/inventory/movements", params={"job_id": job["id"]})["items"]
    assert [m["movement_type"] for m in moves] == ["RETURNED", "ISSUED"]


def test_stock_receipt_adjustment_and_low_stock(w):
    w.ok("inventory", "POST", f"/parts/{w.part['CLUTCH']}/receive", json={"quantity": 4, "reason": "GRN 118"})
    assert flow.stock("CLUTCH") == (4, 0)
    w.ok("inventory", "POST", f"/parts/{w.part['CLUTCH']}/adjust", json={"delta": -1, "reason": "Stock count variance"})
    w.ok("inventory", "POST", f"/parts/{w.part['CLUTCH']}/write-off", json={"quantity": 1, "reason": "Damaged in storage"})
    assert flow.stock("CLUTCH") == (2, 0)
    low = w.ok("inventory", "GET", "/reports/low-stock")
    assert "PAD" in {r["sku"] for r in low["rows"]}
    assert w.call("inventory", "GET", "/reports/revenue").status_code == 403
    csv = w.call("inventory", "GET", "/reports/low-stock", params={"format": "csv"})
    assert csv.status_code == 200 and "Part number" in csv.text and csv.headers["content-type"].startswith("text/csv")


def test_alternative_part_and_purchase_request(w):
    job = _job_with_request(w, parts=(("PAD", 2),))
    job = flow.submit(w, job["id"])
    line = flow.lines(job)["PAD"]
    w.ok("inventory", "POST", f"/parts-request-lines/{line['id']}/unavailable", json={"notes": "Only 1 in stock"})
    pr = w.ok("inventory", "POST", "/purchase-requests", json={
        "lines": [{"part_id": w.part["PAD"], "quantity": 4, "parts_request_line_id": line["id"]}], "notes": "Urgent"})
    assert pr["status"] == "PENDING_APPROVAL" and pr["pr_number"].startswith("PUR-")
    assert w.call("inventory", "POST", f"/purchase-requests/{pr['id']}/decision", json={"approve": True}).status_code == 403
    assert w.call("inventory", "POST", f"/purchase-requests/{pr['id']}/receive", json={}).status_code == 409  # not approved yet
    w.ok("inventory", "POST", f"/parts-request-lines/{line['id']}/alternative", json={"part_id": w.part["PAD-HD"], "notes": "HD pads fit"})
    assert w.call("inventory", "POST", f"/parts-request-lines/{line['id']}/alternative-decision", json={"approve": True}).status_code == 403
    decided = w.ok("manager", "POST", f"/parts-request-lines/{line['id']}/alternative-decision", json={"approve": True})
    assert decided["part"]["sku"] == "PAD-HD" and decided["original_part"]["sku"] == "PAD" and decided["status"] == "PENDING"
    w.ok("inventory", "POST", f"/parts-request-lines/{line['id']}/issue", json={"quantity": 2})
    assert flow.stock("PAD-HD") == (3, 0) and flow.get_job(w, job["id"])["status"] == "READY_FOR_SERVICE"
    approved = w.ok("manager", "POST", f"/purchase-requests/{pr['id']}/decision", json={"approve": True, "notes": "OK"})
    assert approved["status"] == "APPROVED"
    received = w.ok("inventory", "POST", f"/purchase-requests/{pr['id']}/receive", json={})
    assert received["status"] == "RECEIVED" and flow.stock("PAD") == (5, 0)


# 17. Estimates are optional quotes; there is no customer-approval step
def test_estimate_is_an_optional_quote(w):
    job = _job_with_request(w, parts=(("OIL", 2),))
    job = flow.submit(w, job["id"])
    assert job["status"] == "AWAITING_PARTS"
    est = w.ok("manager", "POST", f"/jobs/{job['id']}/estimates")
    # labour 2h x 650 = 1300 (+18% = 234); parts 2 x 1000 = 2000 (+18% = 360)
    assert (est["subtotal_labour"], est["subtotal_parts"], est["tax_total"], est["total"]) == ("1300.00", "2000.00", "594.00", "3894.00")
    assert est["status"] == "DRAFT"
    # The approval endpoints no longer exist.
    assert w.call("manager", "POST", f"/estimates/{est['id']}/send").status_code in (404, 405)
    assert w.call("manager", "POST", f"/estimates/{est['id']}/decision", json={"decision": "APPROVED", "method": "PHONE"}).status_code in (404, 405)
    assert w.call("manager", "POST", f"/jobs/{job['id']}/return-for-reinspection", json={"reason": "xyz"}).status_code in (404, 405)
    # A revised estimate keeps the earlier version.
    est2 = w.ok("manager", "POST", f"/jobs/{job['id']}/estimates")
    job = flow.get_job(w, job["id"])
    assert est2["version"] == 2 and [(e["version"], e["status"]) for e in job["estimates"]] == [(1, "SUPERSEDED"), (2, "DRAFT")]
    # Estimate never gates the work: parts can be issued and service started without it.
    flow.issue_all(w, job["id"])
    assert w.ok("manager", "POST", f"/jobs/{job['id']}/start-service")["status"] == "IN_SERVICE"


def test_job_without_parts_skips_inventory(w):
    vehicle = flow.new_vehicle(w)
    job = flow.open_job(w, vehicle["id"])
    flow.inspect(w, job["id"], parts=())
    job = flow.submit(w, job["id"])
    assert job["status"] == "READY_FOR_SERVICE"


# 18. Additional parts during service: typed by the mechanic, checked by inventory, billed
def test_additional_parts_are_typed_checked_and_billed(w):
    job = _job_with_request(w, parts=(("OIL", 1),))
    flow.submit(w, job["id"])
    flow.issue_all(w, job["id"])
    w.ok("manager", "POST", f"/jobs/{job['id']}/start-service")
    # Labour is fixed once the service has started.
    r = w.call("manager", "POST", f"/jobs/{job['id']}/labour", json={"labour_operation_id": w.labour["LAB-BRK"]})
    assert r.status_code == 409
    labour_id = flow.get_job(w, job["id"])["labour"][0]["id"]
    assert w.call("manager", "DELETE", f"/jobs/{job['id']}/labour/{labour_id}").status_code == 409
    assert w.call("manager", "PATCH", f"/jobs/{job['id']}/labour/{labour_id}", json={"estimated_hours": "5"}).status_code == 409

    job = w.ok("manager", "POST", f"/jobs/{job['id']}/additional-parts", json={"text": "Brake pad set - 1"})
    assert job["status"] == "IN_SERVICE" and job["inspection"]["spare_parts_status"] == "PENDING"
    assert "Brake pad set - 1" in job["inspection"]["spare_parts_notes"]
    lists = w.ok("inventory", "GET", "/spare-parts-lists")
    assert lists[0]["unconfirmed"] == "Brake pad set - 1"
    types = [n["type"] for n in w.ok("manager", "GET", "/notifications")["items"]]
    assert "ADDITIONAL_WORK" in types
    # Work cannot be completed while inventory has not confirmed the additional parts.
    blocked = w.call("manager", "POST", f"/jobs/{job['id']}/complete", json={"repairs_completed": "Done"})
    assert blocked.status_code == 409
    w.ok("inventory", "POST", f"/jobs/{job['id']}/spare-parts-list/available", json={
        "lines": [{"description": "Brake pad set", "quantity": "1", "unit": "SET", "unit_price": "2400", "hsn_code": "87083000"}]})
    flow.complete(w, job["id"], start=False)
    draft = w.ok("manager", "POST", f"/jobs/{job['id']}/invoice")
    descriptions = [l["description"] for l in draft["lines"]]
    assert "Brake pad set" in descriptions and len(descriptions) == 3  # labour, catalogue oil, typed pads


def test_labour_can_change_until_service_starts(w):
    job = _job_with_request(w, parts=(("OIL", 1),))
    flow.submit(w, job["id"])
    flow.issue_all(w, job["id"])  # READY_FOR_SERVICE
    job = w.ok("manager", "POST", f"/jobs/{job['id']}/labour", json={"labour_operation_id": w.labour["LAB-BRK"]})
    extra = next(l for l in job["labour"] if l["code"] == "LAB-BRK")
    w.ok("manager", "DELETE", f"/jobs/{job['id']}/labour/{extra['id']}")
    # Completion no longer asks for hours: the planned hours are recorded and billed.
    w.ok("manager", "POST", f"/jobs/{job['id']}/start-service")
    done = w.ok("manager", "POST", f"/jobs/{job['id']}/complete", json={
        "repairs_completed": "Serviced", "parts": [{"line_id": flow.lines(job)["OIL"]["id"], "qty_consumed": 1}]})
    assert done["status"] == "READY_FOR_BILLING" and done["labour"][0]["actual_hours"] == done["labour"][0]["estimated_hours"]


# 19. Mechanic completion
def test_mechanic_completion_rules(w):
    job = _job_with_request(w, parts=(("OIL", 2), ("PAD", 2)))
    flow.submit(w, job["id"])
    ln = flow.lines(flow.get_job(w, job["id"]))
    w.ok("inventory", "POST", f"/parts-request-lines/{ln['OIL']['id']}/issue", json={"quantity": 2})
    w.ok("inventory", "POST", f"/parts-request-lines/{ln['PAD']['id']}/issue", json={"quantity": 1})
    assert w.call("manager", "POST", f"/jobs/{job['id']}/start-service").status_code == 409  # still awaiting parts
    # The manager waives the second pad set so the job can proceed with what was issued.
    w.ok("inventory", "POST", f"/parts-request-lines/{ln['PAD']['id']}/return", json={"quantity": 1})
    w.ok("manager", "POST", f"/parts-request-lines/{ln['PAD']['id']}/cancel", json={"reason": "Customer will fit later"})
    assert flow.get_job(w, job["id"])["status"] == "READY_FOR_SERVICE"
    w.ok("manager", "POST", f"/jobs/{job['id']}/start-service")
    over = {"repairs_completed": "Oil changed", "labour": [{"labour_id": flow.get_job(w, job["id"])["labour"][0]["id"], "actual_hours": 2}],
            "parts": [{"line_id": ln["OIL"]["id"], "qty_consumed": 3}]}
    assert w.call("manager", "POST", f"/jobs/{job['id']}/complete", json=over).status_code == 400
    done = flow.complete(w, job["id"], start=False)
    # No quality-inspection step: completed work goes straight to the Service Manager for billing.
    assert done["status"] == "READY_FOR_BILLING" and done["completions"][0]["repairs_completed"]
    assert done["labour"][0]["actual_hours"] == "2.00"
    assert "WORK_COMPLETED" in [n["type"] for n in w.ok("manager", "GET", "/notifications")["items"]]


# 20. No quality inspection: the manager can still send the work back
def test_completed_work_goes_to_manager_who_can_return_it(w):
    job = _job_with_request(w, parts=(("OIL", 1),))
    flow.submit(w, job["id"])
    flow.issue_all(w, job["id"])
    job = flow.complete(w, job["id"])
    assert job["status"] == "READY_FOR_BILLING" and job["billing_blockers"] == []
    assert w.call("manager", "POST", f"/jobs/{job['id']}/quality-inspections", json={"result": "PASS"}).status_code in (404, 405)
    assert w.call("admin", "GET", "/quality-checklist").status_code in (404, 405)
    r = w.call("manager", "POST", f"/jobs/{job['id']}/return-to-mechanic", json={"reason": "Brake pedal still soft"})
    assert r.status_code == 200
    job = flow.get_job(w, job["id"])
    assert job["status"] == "IN_SERVICE" and job["returned_for_rework"] and job["rework_count"] == 1
    assert flow.complete(w, job["id"], start=False)["status"] == "READY_FOR_BILLING"


# 21. Preventing premature invoice generation
def test_premature_invoice_is_blocked(w):
    job = _job_with_request(w, parts=(("OIL", 1),))
    for step in ("inspection", "approved", "issued"):
        r = w.call("manager", "POST", f"/jobs/{job['id']}/invoice")
        assert r.status_code == 409 and r.json()["detail"]["code"] == "BILLING_BLOCKED", step
        if step == "inspection":
            flow.submit(w, job["id"])
        elif step == "approved":
            flow.issue_all(w, job["id"])
        elif step == "issued":
            flow.complete(w, job["id"])
    # Completing the work is all that is needed before invoicing (no quality inspection).
    assert w.call("manager", "POST", f"/jobs/{job['id']}/invoice").status_code == 200
    # Vehicle cannot be released before the invoice is finalised.
    assert w.call("manager", "POST", f"/jobs/{job['id']}/ready-for-delivery").status_code == 409
