"""The simplified inspection: recommended repairs, priority and a hand-written spare-parts list."""
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models import PartsRequestLine
from tests import flow


def test_hand_written_spare_parts_are_text_only(w):
    vehicle = flow.new_vehicle(w)
    job = flow.open_job(w, vehicle["id"])
    parts = "Front brake pad set - 1\nEngine oil 15W-40 (5 L) - 2"
    job = w.ok("manager", "PUT", f"/jobs/{job['id']}/inspection", json={
        "recommended_repairs": "Replace front pads; change engine oil", "spare_parts_notes": parts, "priority": "HIGH"})
    assert job["inspection"]["spare_parts_notes"] == parts and job["inspection"]["priority"] == "HIGH"
    # Nothing goes to inventory and no stock moves.
    assert job["parts_requests"] == []
    assert flow.stock("OIL") == (10, 0)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(PartsRequestLine)) == 0
    # The Service Manager sees the list too.
    assert flow.get_job(w, job["id"])["inspection"]["spare_parts_notes"] == parts


def test_submit_requires_recommended_repairs(w):
    vehicle = flow.new_vehicle(w)
    job = flow.open_job(w, vehicle["id"])
    w.ok("manager", "PUT", f"/jobs/{job['id']}/inspection", json={"spare_parts_notes": "Oil filter - 1", "priority": "NORMAL"})
    r = w.call("manager", "POST", f"/jobs/{job['id']}/inspection/submit")
    assert r.status_code == 409 and "recommended repairs" in r.json()["detail"]
    w.ok("manager", "PUT", f"/jobs/{job['id']}/inspection", json={"recommended_repairs": "General service"})
    # A written spare parts list goes to inventory, so the job waits for parts.
    assert w.ok("manager", "POST", f"/jobs/{job['id']}/inspection/submit")["status"] == "AWAITING_PARTS"


def test_inspection_without_spare_parts_is_ready_for_service(w):
    job = flow.open_job(w, flow.new_vehicle(w)["id"])
    w.ok("manager", "PUT", f"/jobs/{job['id']}/inspection", json={"recommended_repairs": "Adjust clutch"})
    assert w.ok("manager", "POST", f"/jobs/{job['id']}/inspection/submit")["status"] == "READY_FOR_SERVICE"
    assert w.ok("inventory", "GET", "/spare-parts-lists") == []


def test_saving_the_short_form_keeps_other_fields(w):
    vehicle = flow.new_vehicle(w)
    job = flow.open_job(w, vehicle["id"])
    w.ok("manager", "PUT", f"/jobs/{job['id']}/inspection", json={"diagnostic_findings": "Recorded before the form changed", "recommended_repairs": "A"})
    job = w.ok("manager", "PUT", f"/jobs/{job['id']}/inspection", json={"recommended_repairs": "B", "spare_parts_notes": "Fan belt - 1", "priority": "LOW"})
    assert job["inspection"]["diagnostic_findings"] == "Recorded before the form changed"
    assert job["inspection"]["recommended_repairs"] == "B"


def test_catalogue_parts_requests_still_work(w):
    vehicle = flow.new_vehicle(w)
    job = flow.open_job(w, vehicle["id"])
    job = flow.inspect(w, job["id"], parts=(("OIL", 2),))
    assert flow.lines(job)["OIL"]["status"] == "PENDING"
    history = w.ok("manager", "GET", f"/vehicles/{vehicle['id']}/history")
    assert "recommended_repairs" in history[0] and "spare_parts_notes" in history[0]


def _submitted_with_list(w, text="Engine oil 15W-40 - 2\nOil filter - 1"):
    job = flow.open_job(w, flow.new_vehicle(w)["id"])
    w.ok("manager", "PUT", f"/jobs/{job['id']}/inspection", json={"recommended_repairs": "General service", "spare_parts_notes": text})
    return w.ok("manager", "POST", f"/jobs/{job['id']}/inspection/submit")


def test_written_spare_parts_list_reaches_inventory(w):
    job = _submitted_with_list(w)
    assert job["status"] == "AWAITING_PARTS" and job["inspection"]["spare_parts_status"] == "PENDING"
    lists = w.ok("inventory", "GET", "/spare-parts-lists")
    assert len(lists) == 1 and lists[0]["job_number"] == job["job_number"] and "Oil filter - 1" in lists[0]["notes"]
    assert lists[0]["mechanic_name"] and lists[0]["registration_number"] == "MH12AB1234"
    notes = w.ok("inventory", "GET", "/notifications")["items"]
    assert any(n["type"] == "PARTS_REQUEST" and job["job_number"] in n["title"] for n in notes)
    assert w.ok("inventory", "GET", "/dashboard")["cards"]["spare_parts_lists"] == 1
    # Mechanics cannot confirm availability for inventory.
    url = f"/jobs/{job['id']}/spare-parts-list/unavailable"
    assert w.call("manager", "POST", url, json={"note": "none left"}).status_code == 403


AVAILABLE = [
    {"description": "Engine oil 15W-40", "quantity": "2", "unit": "Nos", "unit_price": "288.13", "hsn_code": "27101980"},
    {"description": "Oil filter", "quantity": "1", "unit_price": "340"},
]


def test_inventory_confirms_available_by_hand_and_the_parts_are_billed(w):
    job = _submitted_with_list(w)
    out = w.ok("inventory", "POST", f"/jobs/{job['id']}/spare-parts-list/available", json={"lines": AVAILABLE})
    assert out["status"] == "AVAILABLE" and [p["description"] for p in out["parts"]] == ["Engine oil 15W-40", "Oil filter"]
    job = flow.get_job(w, job["id"])
    assert job["status"] == "READY_FOR_SERVICE" and len(job["manual_parts"]) == 2
    assert job["parts_requests"] == [] and flow.stock("OIL") == (10, 0)  # no stock records touched
    assert w.ok("inventory", "GET", "/spare-parts-lists") == []

    # The confirmed parts go onto the invoice at the entered price, with HSN and unit.
    flow.complete(w, job["id"])
    inv = flow.finalise(w, job["id"])
    oil = next(l for l in inv["lines"] if l["description"] == "Engine oil 15W-40")
    assert (oil["quantity"], oil["unit_price"], oil["hsn_code"], oil["unit"]) == ("2.00", "288.13", "27101980", "Nos")
    assert any(l["description"] == "Oil filter" and l["unit_price"] == "340.00" for l in inv["lines"])
    # Once invoiced, the confirmed parts can no longer be changed.
    r = w.call("inventory", "POST", f"/jobs/{job['id']}/spare-parts-list/available", json={"lines": AVAILABLE[:1]})
    assert r.status_code == 409


def test_parts_picked_from_the_catalogue_are_billed_at_the_catalogue_rate(w):
    job = _submitted_with_list(w)
    url = f"/jobs/{job['id']}/spare-parts-list/available"
    # The client's rate and tax are ignored for a catalogue part; a line with neither part nor rate is refused.
    assert w.call("inventory", "POST", url, json={"lines": [{"description": "Oil filter", "quantity": "1"}]}).status_code == 422
    out = w.ok("inventory", "POST", url, json={"lines": [
        {"part_id": w.part["OIL"], "description": "Engine oil 15W-40", "quantity": "2", "unit_price": "1"},
        AVAILABLE[1],
    ]})
    oil = out["parts"][0]
    assert (oil["part"]["sku"], oil["description"], oil["unit_price"], oil["tax_rate"]["name"]) == ("OIL", "Engine oil", "1000.00", "GST 18%")
    assert out["parts"][1]["part"] is None and flow.stock("OIL") == (10, 0)

    flow.complete(w, job["id"])
    inv = flow.finalise(w, job["id"])
    line = next(l for l in inv["lines"] if l["description"] == "Engine oil")
    assert (line["code"], line["quantity"], line["unit_price"], line["tax_rate"]) == ("OIL", "2.00", "1000.00", "18.00")


def test_not_available_keeps_the_job_waiting_until_confirmed_later(w):
    job = _submitted_with_list(w)
    assert w.call("inventory", "POST", f"/jobs/{job['id']}/spare-parts-list/unavailable", json={"note": ""}).status_code == 422
    out = w.ok("inventory", "POST", f"/jobs/{job['id']}/spare-parts-list/unavailable", json={"note": "Oil filter out of stock, expected Friday"})
    assert out["status"] == "UNAVAILABLE"
    assert flow.get_job(w, job["id"])["status"] == "AWAITING_PARTS"
    for role in ("manager",):
        assert any(n["type"] == "PARTS_UNAVAILABLE" for n in w.ok(role, "GET", "/notifications")["items"])
    assert w.ok("inventory", "GET", "/spare-parts-lists")[0]["status"] == "UNAVAILABLE"  # still on inventory's list
    w.ok("inventory", "POST", f"/jobs/{job['id']}/spare-parts-list/available", json={"lines": AVAILABLE, "note": "Arrived"})
    assert flow.get_job(w, job["id"])["status"] == "READY_FOR_SERVICE"


def test_confirmed_prices_can_be_corrected_before_invoicing(w):
    job = _submitted_with_list(w)
    url = f"/jobs/{job['id']}/spare-parts-list/available"
    w.ok("inventory", "POST", url, json={"lines": AVAILABLE})
    w.ok("inventory", "POST", url, json={"lines": [{**AVAILABLE[0], "unit_price": "300"}]})
    parts = flow.get_job(w, job["id"])["manual_parts"]
    assert len(parts) == 1 and parts[0]["unit_price"] == "300.00"
    assert w.call("inventory", "POST", url, json={"lines": []}).status_code == 422


def test_editing_the_list_after_submission_sends_it_again(w):
    job = _submitted_with_list(w)
    w.ok("inventory", "POST", f"/jobs/{job['id']}/spare-parts-list/available", json={"lines": AVAILABLE})
    job = w.ok("manager", "PUT", f"/jobs/{job['id']}/inspection", json={"spare_parts_notes": "Fan belt - 1"})
    assert job["inspection"]["spare_parts_status"] == "PENDING"
    assert w.ok("inventory", "GET", "/spare-parts-lists")[0]["notes"] == "Fan belt - 1"
