"""Each role can correct its own records at any stage while the job is open."""
from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import AuditLog
from tests import flow


def test_manager_edits_job_card_at_any_stage(w):
    job = flow.to_billing(w)  # READY_FOR_BILLING: far past reception
    edited = w.ok("manager", "PATCH", f"/jobs/{job['id']}", json={
        "complaints": "Brake noise and steering vibration", "odometer": 51250, "fuel_level": "FULL", "priority": "URGENT"})
    assert (edited["complaints"], edited["odometer"], edited["fuel_level"], edited["priority"]) == ("Brake noise and steering vibration", 51250, "FULL", "URGENT")
    assert edited["status"] == "READY_FOR_BILLING"  # editing never moves the workflow
    assert edited["events"][-1]["event_type"] == "JOB_EDITED"
    with SessionLocal() as db:
        entry = db.scalar(select(AuditLog).where(AuditLog.action == "job.edit"))
        assert entry.details["odometer"] == ["51000", "51250"]
    # Only the Service Manager edits the job card.
    assert w.call("inventory", "PATCH", f"/jobs/{job['id']}", json={"complaints": "changed"}).status_code == 403


def test_closed_job_records_are_locked(w):
    job = flow.to_billing(w)
    inv = flow.finalise(w, job["id"])
    w.ok("manager", "POST", f"/invoices/{inv['id']}/payments", json={"amount": inv["total"], "method": "CASH"})
    w.ok("manager", "POST", f"/jobs/{job['id']}/ready-for-delivery")
    assert w.call("manager", "PATCH", f"/jobs/{job['id']}", json={"priority": "LOW"}).status_code == 200  # still open
    w.ok("manager", "POST", f"/jobs/{job['id']}/handover", json={"received_by": "Driver"})
    assert w.call("manager", "PATCH", f"/jobs/{job['id']}", json={"priority": "HIGH"}).status_code == 409
    assert w.call("manager", "PUT", f"/jobs/{job['id']}/inspection", json={"diagnostic_findings": "late edit"}).status_code == 409


def test_mechanic_edits_inspection_after_submission(w):
    vehicle = flow.new_vehicle(w)
    job = flow.open_job(w, vehicle["id"])
    flow.inspect(w, job["id"])
    flow.submit(w, job["id"])
    edited = w.ok("manager", "PUT", f"/jobs/{job['id']}/inspection", json={
        "diagnostic_findings": "Pads below limit; disc scored", "recommended_repairs": "Replace pads, skim discs"})
    assert edited["inspection"]["diagnostic_findings"] == "Pads below limit; disc scored"
    assert edited["status"] == "AWAITING_PARTS"
    assert any(e["event_type"] == "INSPECTION_EDITED" for e in edited["events"])


def test_mechanic_edits_labour_and_parts_lines(w):
    vehicle = flow.new_vehicle(w)
    job = flow.open_job(w, vehicle["id"])
    job = flow.inspect(w, job["id"], parts=(("OIL", 2),))
    labour_id, line = job["labour"][0]["id"], flow.lines(job)["OIL"]
    job = w.ok("manager", "PATCH", f"/jobs/{job['id']}/labour/{labour_id}", json={"estimated_hours": "3.5", "notes": "Seized bolts"})
    assert job["labour"][0]["estimated_hours"] == "3.50" and job["labour"][0]["notes"] == "Seized bolts"
    updated = w.ok("manager", "PATCH", f"/parts-request-lines/{line['id']}", json={"quantity": 3, "urgency": "URGENT", "notes": "Top-up too"})
    assert Decimal(updated["qty_requested"]) == 3 and updated["urgency"] == "URGENT"
    assert flow.stock("OIL") == (10, 0)
    assert w.call("inventory", "PATCH", f"/parts-request-lines/{line['id']}", json={"quantity": 9}).status_code == 403

    # Hours stay editable after submission while the work is in progress...
    flow.submit(w, job["id"])
    assert w.ok("manager", "PATCH", f"/jobs/{job['id']}/labour/{labour_id}", json={"estimated_hours": "3"})["labour"][0]["estimated_hours"] == "3.00"
    # ...but a parts quantity is fixed once stock is issued against it.
    flow.issue_all(w, job["id"])
    assert w.call("manager", "PATCH", f"/parts-request-lines/{line['id']}", json={"quantity": 9}).status_code == 409
    assert w.ok("manager", "PATCH", f"/parts-request-lines/{line['id']}", json={"notes": "Bring to bay 2"})["notes"] == "Bring to bay 2"
    # Once the work is completed and handed to the Service Manager the billed hours are fixed.
    flow.complete(w, job["id"])
    assert w.call("manager", "PATCH", f"/jobs/{job['id']}/labour/{labour_id}", json={"estimated_hours": "9"}).status_code == 409
    assert w.call("manager", "PATCH", f"/jobs/{job['id']}/labour/{labour_id}", json={"notes": "Done with care"}).status_code == 200


def test_mechanic_edits_completion_report_later(w):
    job = flow.to_billing(w)
    completion_id = job["completions"][0]["id"]
    edited = w.ok("manager", "PATCH", f"/jobs/{job['id']}/completions/{completion_id}", json={
        "repairs_completed": "Changed oil and filter; topped up coolant", "outstanding_issues": "Rear tyres near wear limit"})
    assert edited["completions"][0]["outstanding_issues"] == "Rear tyres near wear limit"
    assert edited["status"] == "READY_FOR_BILLING" and edited["billing_blockers"] == []


def test_inventory_edits_purchase_request_until_decided(w):
    pr = w.ok("inventory", "POST", "/purchase-requests", json={"lines": [{"part_id": w.part["CLUTCH"], "quantity": 2}]})
    edited = w.ok("inventory", "PUT", f"/purchase-requests/{pr['id']}", json={
        "notes": "Add pads", "lines": [{"part_id": w.part["CLUTCH"], "quantity": 3}, {"part_id": w.part["PAD"], "quantity": 4}]})
    assert [(l["part"]["sku"], Decimal(l["quantity"])) for l in edited["lines"]] == [("CLUTCH", 3), ("PAD", 4)]
    assert w.call("manager", "PUT", f"/purchase-requests/{pr['id']}", json={"lines": [{"part_id": w.part["PAD"], "quantity": 1}]}).status_code == 403
    w.ok("manager", "POST", f"/purchase-requests/{pr['id']}/decision", json={"approve": True})
    r = w.call("inventory", "PUT", f"/purchase-requests/{pr['id']}", json={"lines": [{"part_id": w.part["PAD"], "quantity": 99}]})
    assert r.status_code == 409


def test_manager_edits_vehicle_and_customer(w):
    vehicle = flow.new_vehicle(w)
    models = {m["name"]: m["id"] for m in w.ok("manager", "GET", "/vehicle-models")}
    edited = w.ok("manager", "PATCH", f"/vehicles/{vehicle['id']}", json={"model_id": models["Force Urbania"], "vin": "MC1URB000111", "engine_number": "ENG42"})
    assert (edited["model"]["name"], edited["vin"], edited["engine_number"]) == ("Force Urbania", "MC1URB000111", "ENG42")
    assert w.call("inventory", "PATCH", f"/vehicles/{vehicle['id']}", json={"vin": "X"}).status_code == 403
