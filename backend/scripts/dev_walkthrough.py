"""Walk the complete service-visit scenario against a RUNNING development server.

Uses the demo accounts and demo parts created by `python -m app.seed`, and talks to the API
through the same URL the browser uses (default: the Vite dev server proxy), so it exercises
the real HTTP stack, the background delivery worker and the development email/SMS simulators.

    python scripts/dev_walkthrough.py [--base http://localhost:5173]

It creates real rows in the development database (a new customer, vehicle and job each run).
"""
import argparse
import sys
import time

import httpx

PASSWORD = "Demo@12345"
step_no = 0


def step(text: str) -> None:
    global step_no
    step_no += 1
    print(f"{step_no:>2}. {text}")


class Role:
    def __init__(self, base: str, email: str):
        self.http = httpx.Client(base_url=base + "/api", timeout=30)
        r = self.http.post("/auth/login", json={"email": email, "password": PASSWORD})
        r.raise_for_status()
        self.http.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        self.id = r.json()["user"]["id"]

    def call(self, method: str, url: str, **kw):
        r = self.http.request(method, url, **kw)
        if r.status_code >= 400:
            sys.exit(f"FAILED {method} {url} -> {r.status_code}: {r.text}")
        return r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else r


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:5173")
    base = parser.parse_args().base.rstrip("/")

    # Mechanics do not sign in: the Service Manager records the inspection and work for them.
    manager = Role(base, "manager@demo.local")
    mechanic = manager
    mechanic_id = manager.call("GET", "/mechanics")[0]["id"]
    inventory = Role(base, "inventory@demo.local")
    parts = {p["sku"]: p for p in inventory.call("GET", "/parts", params={"page_size": 100})["items"]}
    labour = {l["code"]: l["id"] for l in mechanic.call("GET", "/labour-operations")}
    models = {m["name"]: m["id"] for m in manager.call("GET", "/vehicle-models")}

    suffix = int(time.time()) % 10000
    reg = f"MH14WT{suffix:04d}"
    step(f"Service Manager signs in and receives a Force Traveller, registration {reg}")
    assert manager.call("GET", "/vehicles/lookup", params={"registration": reg})["found"] is False
    customer = manager.call("POST", "/customers", json={
        "name": "Walkthrough Travels", "mobile": f"98{suffix:04d}1234"[:10].ljust(10, "0"), "email": "walkthrough@customer.example",
        "billing_address": "Hinjawadi Phase 1, Pune 411057"})
    vehicle = manager.call("POST", "/vehicles", json={"registration_number": reg, "model_id": models["Force Traveller"], "customer_id": customer["id"], "odometer": 61200})

    step("Searches the registration and creates a job card")
    assert manager.call("GET", "/vehicles/lookup", params={"registration": reg.lower()})["found"]
    job = manager.call("POST", "/jobs", json={"vehicle_id": vehicle["id"], "odometer": 61850, "fuel_level": "HALF",
                                              "complaints": "Brake noise from front; clutch slipping; general service due"})
    jid = job["id"]
    print(f"     job card {job['job_number']} ({job['status']})")

    step("Assigns the job to a mechanic; the manager records the mechanic's inspection and work")
    manager.call("POST", f"/jobs/{jid}/assign", json={"mechanic_id": mechanic_id})

    step("Mechanic inspects, adds labour and requests four spare parts")
    mechanic.call("PUT", f"/jobs/{jid}/inspection", json={
        "initial_observations": "Front pads worn to backing plate", "diagnostic_findings": "Pads below limit; clutch plate glazed; oil overdue",
        "recommended_repairs": "Replace front pads and clutch kit; general service", "safety_observations": "Braking distance increased"})
    for code in ("LAB-GS", "LAB-BRK-F", "LAB-CLU"):
        mechanic.call("POST", f"/jobs/{jid}/labour", json={"labour_operation_id": labour[code]})
    wanted = [("FM-OIL-15W40-5L", 2), ("FM-FLT-OIL-01", 1), ("FM-BRK-PAD-TRV", 1), ("FM-CLU-KIT-TRV", 1)]
    job = mechanic.call("POST", f"/jobs/{jid}/parts-requests", json={
        "lines": [{"part_id": parts[sku]["id"], "quantity": qty, "urgency": "HIGH"} for sku, qty in wanted]})
    mechanic.call("POST", f"/jobs/{jid}/inspection/submit")
    lines = {l["part"]["sku"]: l for r in job["parts_requests"] for l in r["lines"]}

    step("Service Manager prepares an estimate (quote) for the customer")
    est = manager.call("POST", f"/jobs/{jid}/estimates")
    print(f"     estimate total INR {est['total']}")

    step("Inventory checks availability and issues what is in stock (oil, filter)")
    for sku in ("FM-OIL-15W40-5L", "FM-FLT-OIL-01"):
        inventory.call("POST", f"/parts-request-lines/{lines[sku]['id']}/issue", json={"quantity": lines[sku]["qty_requested"]})

    step("The clutch kit is out of stock: shortage recorded and reported to the Service Manager")
    inventory.call("POST", f"/parts-request-lines/{lines['FM-CLU-KIT-TRV']['id']}/unavailable", json={"notes": "None in stock"})
    shortages = manager.call("GET", "/reports/unavailable-parts")["rows"]
    assert any(r["job_number"] == job["job_number"] and r["sku"] == "FM-CLU-KIT-TRV" for r in shortages)
    print(f"     manager dashboard shows {manager.call('GET', '/dashboard')['cards']['parts_shortages']} shortage(s)")

    step("Manager approves a purchase request for the clutch kit and an alternative brake pad")
    pr = inventory.call("POST", "/purchase-requests", json={"lines": [{"part_id": parts["FM-CLU-KIT-TRV"]["id"], "quantity": 2}], "notes": f"For {job['job_number']}"})
    manager.call("POST", f"/purchase-requests/{pr['id']}/decision", json={"approve": True, "notes": "Approved"})
    inventory.call("POST", f"/purchase-requests/{pr['id']}/receive", json={})
    pad = lines["FM-BRK-PAD-TRV"]["id"]
    inventory.call("POST", f"/parts-request-lines/{pad}/alternative", json={"part_id": parts["FM-BRK-PAD-TRV-HD"]["id"], "notes": "Heavy-duty pads recommended for tour use"})
    manager.call("POST", f"/parts-request-lines/{pad}/alternative-decision", json={"approve": True})

    step("Inventory issues the remaining parts")
    inventory.call("POST", f"/parts-request-lines/{lines['FM-CLU-KIT-TRV']['id']}/issue", json={"quantity": 1})
    inventory.call("POST", f"/parts-request-lines/{pad}/issue", json={"quantity": 1})
    job = manager.call("GET", f"/jobs/{jid}")
    assert job["status"] == "READY_FOR_SERVICE", job["status"]

    step("Mechanic completes the repair and records actual parts used (1 of 2 oil cans)")
    mechanic.call("POST", f"/jobs/{jid}/start-service")
    job = mechanic.call("GET", f"/jobs/{jid}")
    lines = {l["part"]["sku"]: l for r in job["parts_requests"] for l in r["lines"]}
    mechanic.call("POST", f"/jobs/{jid}/complete", json={
        "repairs_completed": "Replaced front brake pads (HD) and clutch kit; engine oil and filter changed", "final_observations": "Road tested 6 km",
        "labour": [{"labour_id": l["id"], "actual_hours": l["estimated_hours"]} for l in job["labour"]],
        "parts": [{"line_id": l["id"], "qty_consumed": 1 if sku == "FM-OIL-15W40-5L" else l["qty_issued"]} for sku, l in lines.items()]})
    inventory.call("POST", f"/parts-request-lines/{lines['FM-OIL-15W40-5L']['id']}/return", json={"quantity": 1, "reason": "Unused"})

    step("Completed work goes straight to the Service Manager for billing")
    job = manager.call("GET", f"/jobs/{jid}")
    assert job["status"] == "READY_FOR_BILLING" and job["billing_blockers"] == []

    step("Service Manager reviews labour, parts, taxes and the final amount")
    draft = manager.call("POST", f"/jobs/{jid}/invoice")
    for line in draft["lines"]:
        print(f"     {line['line_type']:<6} {line['code']:<18} qty {line['quantity']:>5}  tax {line['tax_rate']:>5}%  INR {line['line_total']:>10}")
    print(f"     labour {draft['subtotal_labour']} + parts {draft['subtotal_parts']} + tax {draft['tax_total']} = INR {draft['total']}")
    pdf = manager.call("GET", f"/invoices/{draft['id']}/pdf")
    assert pdf.content.startswith(b"%PDF")

    step("Finalises the invoice (invoice + email job + SMS job are committed together)")
    inv = manager.call("POST", f"/invoices/{draft['id']}/finalise")
    print(f"     {inv['invoice_number']}: " + ", ".join(f"{d['channel']} {d['status']}" for d in inv["delivery_jobs"]))

    step("The background worker sends the email (PDF attached) and the SMS (secure link)")
    for _ in range(40):
        inv = manager.call("GET", f"/invoices/{inv['id']}")
        if all(d["status"] not in ("PENDING", "QUEUED") for d in inv["delivery_jobs"]):
            break
        time.sleep(1)
    step("Email and SMS delivery statuses are tracked independently")
    for d in inv["delivery_jobs"]:
        print(f"     {d['channel']:<5} -> {d['destination']:<32} {d['display_status']} via {d['provider']} ({d['attempt_count']} attempt)")
    assert all(d["status"] == "SENT" for d in inv["delivery_jobs"]), "deliveries did not complete - is the worker running?"

    step("Manager resends the SMS only; the email is not sent again")
    manager.call("POST", f"/invoices/{inv['id']}/resend", json={"channel": "SMS", "confirm": True})
    time.sleep(8)
    inv = manager.call("GET", f"/invoices/{inv['id']}")
    counts = {ch: sum(1 for d in inv["delivery_jobs"] if d["channel"] == ch) for ch in ("EMAIL", "SMS")}
    assert counts == {"EMAIL": 1, "SMS": 2}, counts
    link = manager.call("POST", f"/invoices/{inv['id']}/link")
    public = httpx.get(link["url"].replace("/i/", "/api/public/invoices/"), timeout=30)
    assert public.status_code == 200 and public.json()["invoice_number"] == inv["invoice_number"]
    print(f"     customer link works without sign-in: {link['url'][:60]}...")

    step("Records the payment and verifies the outstanding balance")
    manager.call("POST", f"/invoices/{inv['id']}/payments", json={"amount": "5000", "method": "CASH"})
    inv = manager.call("GET", f"/invoices/{inv['id']}")
    print(f"     after INR 5000 cash: outstanding INR {inv['outstanding']} ({inv['payment_status']})")
    manager.call("POST", f"/invoices/{inv['id']}/payments", json={"amount": inv["outstanding"], "method": "UPI", "external_reference": "UPI-WALKTHROUGH"})
    inv = manager.call("GET", f"/invoices/{inv['id']}")
    assert inv["payment_status"] == "PAID" and inv["outstanding"] == "0.00"

    step("Marks the vehicle ready for delivery and records the handover")
    manager.call("POST", f"/jobs/{jid}/ready-for-delivery")
    job = manager.call("POST", f"/jobs/{jid}/handover", json={"received_by": "Owner", "notes": "Old parts returned"})
    assert job["status"] == "COMPLETED"

    step("All records remain available")
    history = manager.call("GET", f"/vehicles/{vehicle['id']}/history")
    moves = inventory.call("GET", "/inventory/movements", params={"job_id": jid})["total"]
    print(f"     history: {history[0]['job_number']} / {history[0]['invoice_number']}; {len(job['events'])} timeline events; {moves} stock movements")
    print(f"\nWalkthrough complete: {job['job_number']} -> {inv['invoice_number']} (INR {inv['total']}, PAID).")
    print(f"Open {base}/jobs/{jid} to see it in the UI.")


if __name__ == "__main__":
    main()
