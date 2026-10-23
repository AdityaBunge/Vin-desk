"""The dealer dashboard: figures from a billed job, targets, and who may see it."""
from decimal import Decimal

from sqlalchemy import select

from app.models import Part
from tests.flow import finalise, to_billing


def test_dealer_dashboard_figures_from_a_billed_job(w):
    job = to_billing(w)  # 2 x OIL at 1000 (cost 1.00, GST 18%) + general service labour 2 h x 650
    invoice = finalise(w, job["id"])
    with w.db() as db:
        oil = db.scalar(select(Part).where(Part.sku == "OIL"))
        oil.sheet_closing_qty, oil.sheet_closing_value, oil.sheet_actual_qty, oil.abc_class = Decimal(10), Decimal(5000), Decimal(8), "A"
        db.commit()

    d = w.ok("manager", "GET", "/dealer-dashboard")
    money = d["money"]
    assert money["revenue"] == float(invoice["total"]) and money["invoices"] == 1
    assert (money["parts_sales"], money["labour_sales"]) == (2000.0, 1300.0)
    assert money["outstanding"] == float(invoice["total"])  # nothing paid yet
    assert money["top_dues"][0]["invoice_number"] == invoice["invoice_number"]
    assert sum(m["parts"] + m["labour"] for m in money["trend"]) == 3300.0

    growth = d["growth"]
    assert (growth["parts_sales"], growth["parts_cost"], growth["parts_margin"]) == (2000.0, 2.0, 1998.0)

    parts = d["parts"]
    assert parts["top_by_value"][0] == {"sku": "OIL", "name": "Engine oil", "qty": 2.0, "value": 2000.0}
    assert parts["stock_value"] == 5000.0 and parts["by_abc"] == [{"group": "A", "parts": 1, "value": 5000.0}]
    assert parts["dead_stock_parts"] == 0  # OIL sold today
    assert parts["count_differences"][0]["difference"] == -2.0
    assert parts["running_low"] == []  # 8 on the shelf, 2 sold in 30 days

    workshop = d["workshop"]
    assert workshop["in_workshop"] == 1 and {"stage": "Billing", "jobs": 1} in workshop["stages"]
    assert d["customers"]["new_customers"] == 1


def test_dealer_targets_and_access(w):
    assert w.call("inventory", "GET", "/dealer-dashboard").status_code == 403
    assert w.call("admin", "GET", "/dealer-dashboard").status_code == 200
    assert w.call("manager", "GET", "/dealer-dashboard", params={"date_from": "2026-02-01", "date_to": "2026-01-01"}).status_code == 400

    w.ok("admin", "PUT", "/dealer-dashboard/targets",
         json={"monthly_revenue_target": 500000, "monthly_vehicles_target": 40, "service_interval_days": 120})
    growth = w.ok("manager", "GET", "/dealer-dashboard")["growth"]
    assert (growth["targets"]["revenue_target"], growth["targets"]["vehicles_target"], growth["service_interval_days"]) == (500000.0, 40, 120)
    assert w.call("manager", "PUT", "/dealer-dashboard/targets",
                  json={"monthly_revenue_target": 1, "monthly_vehicles_target": 1, "service_interval_days": 5}).status_code == 422


def test_job_type_and_customer_feedback_reach_the_dashboard(w):
    from tests import flow
    from tests.test_billing_delivery import _link_from, _token

    job = flow.to_billing(w)
    assert job["job_type"] == "PAID"
    w.ok("manager", "PATCH", f"/jobs/{job['id']}", json={"job_type": "WARRANTY"})
    assert flow.get_job(w, job["id"])["job_type"] == "WARRANTY"
    invoice = flow.finalise(w, job["id"])
    flow.run_worker()
    token = _token(_link_from(w))

    assert w.client.get(f"/api/public/invoices/{token}").json()["feedback"] is None
    assert w.client.post(f"/api/public/invoices/{token}/feedback", json={"rating": 6}).status_code == 422
    assert w.client.post(f"/api/public/invoices/{token}/feedback", json={"rating": 4}).json() == {"rating": 4, "comment": ""}
    w.client.post(f"/api/public/invoices/{token}/feedback", json={"rating": 2, "comment": "Took two days longer than promised"})
    assert w.client.get(f"/api/public/invoices/{token}").json()["feedback"] == {"rating": 2, "comment": "Took two days longer than promised"}
    assert w.client.post("/api/public/invoices/1.abc/feedback", json={"rating": 5}).status_code == 404

    d = w.ok("manager", "GET", "/dealer-dashboard")
    assert {"type": "WARRANTY", "jobs": 1, "revenue": float(invoice["total"])} in d["workshop"]["by_type"]
    feedback = d["customers"]["feedback"]
    assert (feedback["count"], feedback["average"]) == (1, 2.0)
    assert feedback["low"][0]["comment"] == "Took two days longer than promised"
