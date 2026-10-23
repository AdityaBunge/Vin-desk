"""Helpers that drive a job through the workflow via the HTTP API, as each role would."""
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import InventoryStock, Part
from app.services import delivery


def new_vehicle(w, reg="MH12AB1234", email="owner@example.com", mobile="9822012345", model="Force Traveller"):
    models = {m["name"]: m["id"] for m in w.ok("manager", "GET", "/vehicle-models")}
    customer = w.ok("manager", "POST", "/customers", json={
        "name": "Ganesh Tours", "mobile": mobile, "email": email, "billing_address": "Pune"})
    return w.ok("manager", "POST", "/vehicles", json={
        "registration_number": reg, "model_id": models[model], "customer_id": customer["id"], "odometer": 50000})


def open_job(w, vehicle_id, assign=True, **extra):
    body = {"vehicle_id": vehicle_id, "odometer": 51000, "fuel_level": "HALF", "complaints": "Brake noise; due for service"}
    if assign:
        body["mechanic_id"] = w.ids["mechanic"]
    body.update(extra)
    return w.ok("manager", "POST", "/jobs", json=body)


def inspect(w, job_id, parts=(("OIL", 2),), labour=("LAB-GS",)):
    w.ok("manager", "PUT", f"/jobs/{job_id}/inspection", json={
        "initial_observations": "Front pads worn", "diagnostic_findings": "Pads below limit; oil overdue",
        "recommended_repairs": "Replace pads, general service", "safety_observations": "Brakes unsafe"})
    for code in labour:
        w.ok("manager", "POST", f"/jobs/{job_id}/labour", json={"labour_operation_id": w.labour[code]})
    job = get_job(w, job_id)
    if parts:
        job = w.ok("manager", "POST", f"/jobs/{job_id}/parts-requests", json={
            "lines": [{"part_id": w.part[sku], "quantity": qty, "urgency": "HIGH"} for sku, qty in parts]})
    return job


def submit(w, job_id):
    """Submit the inspection. There is no customer-approval step, so the job moves straight on."""
    w.ok("manager", "POST", f"/jobs/{job_id}/inspection/submit")
    return get_job(w, job_id)


def get_job(w, job_id, role="manager"):
    return w.ok(role, "GET", f"/jobs/{job_id}")


def lines(job) -> dict:
    return {l["part"]["sku"]: l for r in job["parts_requests"] for l in r["lines"] if l["status"] != "CANCELLED"}


def issue_all(w, job_id):
    for line in lines(get_job(w, job_id)).values():
        outstanding = float(line["qty_outstanding"])
        if outstanding > 0:
            w.ok("inventory", "POST", f"/parts-request-lines/{line['id']}/issue", json={"quantity": outstanding})
    return get_job(w, job_id)


def complete(w, job_id, consumed: dict | None = None, start=True):
    if start:
        w.ok("manager", "POST", f"/jobs/{job_id}/start-service")
    job = get_job(w, job_id)
    consumed = consumed or {}
    return w.ok("manager", "POST", f"/jobs/{job_id}/complete", json={
        "repairs_completed": "Replaced pads, changed oil and filter",
        "final_observations": "Road tested OK",
        "labour": [{"labour_id": l["id"], "actual_hours": l["estimated_hours"]} for l in job["labour"] if l["approval_status"] == "APPROVED"],
        "parts": [{"line_id": l["id"], "qty_consumed": consumed.get(sku, l["qty_issued"])} for sku, l in lines(job).items()],
    })


def to_billing(w, parts=(("OIL", 2),), labour=("LAB-GS",), reg="MH12AB1234", **vehicle_kw):
    """Open a job and take it all the way to READY_FOR_BILLING. Returns the job."""
    vehicle = new_vehicle(w, reg=reg, **vehicle_kw)
    job = open_job(w, vehicle["id"])
    inspect(w, job["id"], parts=parts, labour=labour)
    submit(w, job["id"])
    issue_all(w, job["id"])
    complete(w, job["id"])  # completed work goes straight to READY_FOR_BILLING
    return get_job(w, job["id"])


def finalise(w, job_id):
    draft = w.ok("manager", "POST", f"/jobs/{job_id}/invoice")
    return w.ok("manager", "POST", f"/invoices/{draft['id']}/finalise")


def run_worker() -> int:
    return delivery.run_once(SessionLocal)


def deliveries(w, invoice_id) -> dict:
    """Latest delivery job per channel."""
    inv = w.ok("manager", "GET", f"/invoices/{invoice_id}")
    latest = {}
    for d in inv["delivery_jobs"]:
        latest[d["channel"]] = d
    return latest


def stock(sku: str) -> tuple[float, float]:
    with SessionLocal() as db:
        s = db.scalar(select(InventoryStock).join(Part).where(Part.sku == sku))
        return float(s.qty_on_hand), float(s.qty_reserved)
