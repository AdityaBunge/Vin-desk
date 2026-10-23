"""Authentication, permissions, customers/vehicles, reception and assignment (spec tests 1-8)."""
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import AuditLog, User, Vehicle
from app.services import jobs as jobs_service
from tests import flow
from tests.conftest import PASSWORD


# 1. Login and protected endpoints
def test_login_and_protected_endpoints(w):
    assert w.client.get("/api/jobs").status_code == 401
    assert w.client.get("/api/jobs", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    bad = w.client.post("/api/auth/login", json={"email": "manager@test.local", "password": "wrong-password"})
    assert bad.status_code == 401
    me = w.ok("manager", "GET", "/auth/me")
    assert me["role_code"] == "SERVICE_MANAGER" and "invoice.manage" in me["permissions"]
    assert "password_hash" not in me


def test_refresh_token_rotation_and_logout(w):
    r = w.client.post("/api/auth/login", json={"email": "admin@test.local", "password": PASSWORD})
    assert r.status_code == 200 and "fsc_refresh" in r.cookies
    old_cookie = r.cookies["fsc_refresh"]
    refreshed = w.client.post("/api/auth/refresh")
    assert refreshed.status_code == 200 and refreshed.json()["access_token"]
    # The old refresh token is single-use.
    w.client.cookies.set("fsc_refresh", old_cookie, path="/api/auth")
    assert w.client.post("/api/auth/refresh").status_code == 401


def test_deactivated_user_loses_access_immediately(w):
    w.ok("admin", "PATCH", f"/users/{w.ids['inventory']}", json={"is_active": False})
    assert w.call("inventory", "GET", "/parts-requests").status_code == 401
    r = w.client.post("/api/auth/login", json={"email": "inventory@test.local", "password": PASSWORD})
    assert r.status_code == 401


def test_demo_accounts_cannot_sign_in_in_production(w, monkeypatch):
    with SessionLocal() as db:
        db.scalar(select(User).where(User.email == "manager@test.local")).is_demo = True
        db.commit()
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "app_env", "production")
    r = w.client.post("/api/auth/login", json={"email": "manager@test.local", "password": PASSWORD})
    assert r.status_code == 401


def test_production_refuses_simulated_providers():
    from app.core.config import Settings

    problems = Settings(app_env="production", jwt_secret="x" * 40, public_base_url="https://x.example").production_problems()
    assert any("EMAIL_PROVIDER" in p for p in problems) and any("SMS_PROVIDER" in p for p in problems)


# 2 + 3. Role-based access restrictions; unauthorised invoice and inventory operations
def test_role_restrictions(w):
    job = flow.to_billing(w)
    draft = w.ok("manager", "POST", f"/jobs/{job['id']}/invoice")
    line = flow.lines(job)["OIL"]
    forbidden = [
        ("inventory", "POST", "/jobs", {}),                                            # reception is manager-only
        ("manager", "POST", f"/parts-request-lines/{line['id']}/issue", {"quantity": 1}),  # only stores issue stock
        ("inventory", "PUT", f"/jobs/{job['id']}/inspection", {"recommended_repairs": "x"}),  # only the manager records work
        ("inventory", "POST", f"/invoices/{draft['id']}/finalise", None),
        ("inventory", "PATCH", f"/invoices/{draft['id']}", {"discounts": []}),         # cannot alter invoices
        ("inventory", "POST", "/purchase-requests/1/decision", {"approve": True}),     # cannot approve purchases
        ("inventory", "GET", "/jobs", None),
        ("manager", "POST", f"/parts/{w.part['OIL']}/adjust", {"delta": 5, "reason": "count"}),
        ("manager", "POST", "/users", {}),
        ("admin", "POST", f"/invoices/{draft['id']}/finalise", None),                  # admin has no billing bypass
        ("admin", "GET", "/invoices", None),
        ("manager", "GET", "/audit-logs", None),
    ]
    for role, method, url, body in forbidden:
        r = w.call(role, method, url, json=body)
        assert r.status_code == 403, f"{role} {method} {url} -> {r.status_code}"


def test_admin_actions_are_audited(w):
    w.ok("admin", "POST", "/vehicle-models", json={"name": "Force Citiline"})
    w.ok("admin", "PUT", "/settings", json={"centre_name": "New Name Motors"})
    logs = w.ok("admin", "GET", "/audit-logs")["items"]
    actions = {l["action"] for l in logs}
    assert {"vehicle_model.create", "settings.update"} <= actions
    settings = w.ok("admin", "GET", "/settings")
    assert "password" not in str(settings).lower().replace("password_configured", "")
    assert settings["providers"]["email"]["smtp_password_configured"] is False


def test_audit_log_is_append_only(w):
    w.ok("admin", "POST", "/vehicle-models", json={"name": "Force Citiline"})
    with SessionLocal() as db:
        entry = db.scalar(select(AuditLog).limit(1))
        entry.summary = "tampered"
        try:
            db.commit()
            raise AssertionError("audit log row was modified")
        except Exception as exc:  # noqa: BLE001
            assert "append-only" in str(exc)


# 4. Creating customers and vehicles
def test_create_customer_and_vehicle(w):
    vehicle = flow.new_vehicle(w, reg="mh 12-ab 1234")
    assert vehicle["registration_number"] == "MH12AB1234"
    assert vehicle["customer"]["mobile"] == "+919822012345"
    assert vehicle["customer"]["code"] == "CUST-000001"
    r = w.call("manager", "POST", "/customers", json={"name": "X", "mobile": "12345"})
    assert r.status_code == 422
    detail = w.ok("manager", "GET", f"/customers/{vehicle['customer']['id']}")
    assert {c["channel"] for c in detail["consents"]} == {"EMAIL", "SMS", "WHATSAPP"}
    models = [m["name"] for m in w.ok("manager", "GET", "/vehicle-models")]
    assert models == ["Force Gurkha", "Force Urbania", "Force Trax Cruiser", "Force Trax Toofan", "Force Traveller", "Force Monobus"]


# 7. Duplicate registration handling
def test_duplicate_registration_is_rejected(w):
    vehicle = flow.new_vehicle(w, reg="MH12AB1234")
    r = w.call("manager", "POST", "/vehicles", json={
        "registration_number": "mh-12 ab 1234", "model_id": vehicle["model"]["id"], "customer_id": vehicle["customer"]["id"]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "DUPLICATE_REGISTRATION"
    assert r.json()["detail"]["vehicle_id"] == vehicle["id"]


# 5. Registering a new service visit
def test_register_service_visit(w):
    vehicle = flow.new_vehicle(w)
    job = flow.open_job(w, vehicle["id"], assign=False)
    assert job["job_number"].startswith("SC-") and job["job_number"].endswith("-0001")
    assert job["status"] == "AWAITING_ASSIGNMENT"
    assert [e["to_status"] for e in job["events"] if e["to_status"]] == ["RECEIVED", "AWAITING_ASSIGNMENT"]
    lookup = w.ok("manager", "GET", "/vehicles/lookup", params={"registration": "mh12 ab-1234"})
    assert lookup["found"] and lookup["vehicle"]["odometer"] == 51000 and len(lookup["active_jobs"]) == 1
    assert w.ok("manager", "GET", "/vehicles/lookup", params={"registration": "KA01ZZ9999"})["found"] is False


# 6. Returning vehicle gets a new job card; history is preserved
def test_returning_vehicle_gets_new_job_card(w):
    job1 = flow.to_billing(w)
    inv = flow.finalise(w, job1["id"])
    w.ok("manager", "POST", f"/invoices/{inv['id']}/payments", json={"amount": inv["total"], "method": "CASH"})
    w.ok("manager", "POST", f"/jobs/{job1['id']}/ready-for-delivery")
    w.ok("manager", "POST", f"/jobs/{job1['id']}/handover", json={"received_by": "Driver"})
    job2 = flow.open_job(w, job1["vehicle"]["id"])
    assert job2["id"] != job1["id"] and job2["job_number"] != job1["job_number"]
    assert flow.get_job(w, job1["id"])["status"] == "COMPLETED"  # old visit untouched
    lookup = w.ok("manager", "GET", "/vehicles/lookup", params={"registration": "MH12AB1234"})
    assert [h["job_number"] for h in lookup["history"]] == [job2["job_number"], job1["job_number"]]
    assert lookup["history"][1]["parts"][0]["sku"] == "OIL"
    history = w.ok("manager", "GET", f"/jobs/{job2['id']}/history")
    assert history[0]["job_number"] == job1["job_number"]


def test_active_job_warning_and_override(w):
    vehicle = flow.new_vehicle(w)
    flow.open_job(w, vehicle["id"])
    body = {"vehicle_id": vehicle["id"], "odometer": 51010, "fuel_level": "FULL", "complaints": "Second visit"}
    r = w.call("manager", "POST", "/jobs", json=body)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ACTIVE_JOB_EXISTS"
    job = w.ok("manager", "POST", "/jobs", json={**body, "override_reason": "Separate accident repair claim"})
    assert job["active_job_override_reason"] == "Separate accident repair claim"


def test_job_numbers_are_unique_under_concurrency(w):
    for n in range(8):
        flow.new_vehicle(w, reg=f"MH12ZZ{n:04d}", mobile=f"98220000{n:02d}")

    def create(n):
        with SessionLocal() as db:
            vehicle = db.scalar(select(Vehicle).where(Vehicle.registration_number == f"MH12ZZ{n:04d}"))
            manager = db.get(User, w.ids["manager"])
            job = jobs_service.create_job(db, manager, vehicle=vehicle, odometer=60000, fuel_level="HALF", complaints="Concurrent")
            db.commit()
            return job.job_number

    with ThreadPoolExecutor(max_workers=8) as pool:
        numbers = list(pool.map(create, range(8)))
    assert len(set(numbers)) == 8
    assert sorted(int(n.rsplit("-", 1)[1]) for n in numbers) == list(range(1, 9))


# 8. Mechanic assignment
def test_mechanic_assignment(w):
    vehicle = flow.new_vehicle(w)
    job = flow.open_job(w, vehicle["id"], assign=False)
    r = w.call("manager", "POST", f"/jobs/{job['id']}/assign", json={"mechanic_id": w.ids["inventory"]})
    assert r.status_code == 400  # not a mechanic
    job = w.ok("manager", "POST", f"/jobs/{job['id']}/assign", json={"mechanic_id": w.ids["mechanic"]})
    assert job["status"] == "INSPECTION_IN_PROGRESS" and job["assigned_mechanic"]["id"] == w.ids["mechanic"]


def test_invalid_status_transition_is_rejected(w):
    vehicle = flow.new_vehicle(w)
    job = flow.open_job(w, vehicle["id"])
    assert w.call("manager", "POST", f"/jobs/{job['id']}/start-service").status_code == 409
    assert w.call("manager", "POST", f"/jobs/{job['id']}/ready-for-delivery").status_code == 409
    held = w.ok("manager", "POST", f"/jobs/{job['id']}/hold", json={"reason": "Customer unreachable"})
    assert held["status"] == "ON_HOLD"
    assert w.ok("manager", "POST", f"/jobs/{job['id']}/resume")["status"] == "INSPECTION_IN_PROGRESS"


def test_photo_upload_validates_content(w):
    vehicle = flow.new_vehicle(w)
    job = flow.open_job(w, vehicle["id"])
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    ok = w.call("manager", "POST", f"/jobs/{job['id']}/photos", files={"file": ("../../evil.png", png, "image/png")})
    assert ok.status_code == 201 and ok.json()["original_name"] == "evil.png"
    bad = w.call("manager", "POST", f"/jobs/{job['id']}/photos", files={"file": ("x.png", b"<script>alert(1)</script>", "image/png")})
    assert bad.status_code == 400
    assert w.call("inventory", "GET", f"/jobs/{job['id']}/photos/{ok.json()['id']}").status_code in (403, 404)
    assert w.call("manager", "GET", f"/jobs/{job['id']}/photos/{ok.json()['id']}").status_code == 200


def test_mechanics_do_not_sign_in_and_work_is_credited_to_them(w):
    r = w.client.post("/api/auth/login", json={"email": "mechanic@test.local", "password": PASSWORD})
    assert r.status_code == 403 and "Service Manager records" in r.json()["detail"]
    job = flow.to_billing(w)
    assert job["inspection"] is not None
    with SessionLocal() as db:
        from app.models import Inspection, WorkCompletion

        assert db.scalar(select(Inspection.mechanic_id)) == w.ids["mechanic"]
        assert db.scalar(select(WorkCompletion.mechanic_id)) == w.ids["mechanic"]
    # Work needs a mechanic assigned first.
    unassigned = flow.open_job(w, flow.new_vehicle(w, reg="MH12ZZ0001", mobile="9822011111")["id"], assign=False)
    r = w.call("manager", "PUT", f"/jobs/{unassigned['id']}/inspection", json={"recommended_repairs": "x"})
    assert r.status_code in (409, 422)
