"""Dealer dashboard: the business at a glance for a date range.

Money comes from finalised invoices (totals include GST; the parts/labour split and margin are
before GST) and recorded payments. Parts figures use the parts sheet's columns as last synced
(Closing Qty., Closing Value, ACTUAL QUANTITY, ABC, Movement) and parts sales from finalised
invoices, because parts billed from inventory's checked list do not move stock in the app.
"""
from datetime import date, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models import (
    Customer,
    CustomerFeedback,
    Inspection,
    Invoice,
    InvoiceLine,
    Part,
    PartsRequestLine,
    Payment,
    PurchaseRequest,
    ServiceJob,
    User,
    Vehicle,
    VehicleModel,
)
from app.models.enums import (
    CLOSED_JOB_STATUSES,
    InvoiceStatus,
    JobStatus,
    JobType,
    LineType,
    PartsLineStatus,
    PaymentStatus,
    PurchaseRequestStatus,
)
from app.models.job import JobManualPart
from app.services import settings as settings_service
from app.services.reports import TZ_NAME, day_range, today_local

FINAL = Invoice.status == InvoiceStatus.FINALISED
OPEN_JOB = ServiceJob.status.notin_(CLOSED_JOB_STATUSES)
DEAD_STOCK_DAYS = 90
STUCK_JOB_DAYS = 7
REPEAT_VISIT_DAYS = 30

STAGES: list[tuple[str, tuple[str, ...]]] = [
    ("Waiting to start", (JobStatus.RECEIVED, JobStatus.AWAITING_ASSIGNMENT)),
    ("Inspection", (JobStatus.INSPECTION_IN_PROGRESS, JobStatus.AWAITING_ESTIMATE_APPROVAL)),
    ("Waiting for parts", (JobStatus.AWAITING_PARTS,)),
    ("In service", (JobStatus.READY_FOR_SERVICE, JobStatus.IN_SERVICE, JobStatus.AWAITING_QUALITY_CHECK, JobStatus.AWAITING_MANAGER_REVIEW)),
    ("Billing", (JobStatus.READY_FOR_BILLING,)),
    ("Ready for delivery", (JobStatus.READY_FOR_DELIVERY,)),
    ("On hold", (JobStatus.ON_HOLD,)),
]


def _num(value) -> float:
    return float(value or 0)


def _sum(db: Session, expr, *where) -> float:
    return _num(db.scalar(select(func.coalesce(func.sum(expr), 0)).where(*where)))


def _shift_year(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 February
        return d.replace(year=d.year + years, day=28)


def _days_since(column):
    return func.date_part("day", func.now() - column)


# Invoice part lines with their catalogue part (from a parts request or inventory's checked list).
_PART_ID = func.coalesce(PartsRequestLine.part_id, JobManualPart.part_id)


def _part_lines(*columns):
    return (
        select(*columns)
        .select_from(InvoiceLine)
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .outerjoin(PartsRequestLine, PartsRequestLine.id == InvoiceLine.parts_request_line_id)
        .outerjoin(JobManualPart, JobManualPart.id == InvoiceLine.manual_part_id)
        .where(FINAL, InvoiceLine.line_type == LineType.PART)
    )


def _sales_by_part(start, end):
    """Subquery: part_id, quantity and before-GST value sold on invoices finalised in [start, end)."""
    return (
        _part_lines(_PART_ID.label("part_id"), func.sum(InvoiceLine.quantity).label("qty"),
                    func.sum(InvoiceLine.line_total - InvoiceLine.tax_amount).label("value"))
        .where(_PART_ID.is_not(None), Invoice.finalised_at >= start, Invoice.finalised_at < end)
        .group_by(_PART_ID)
        .subquery()
    )


# --- Money ---------------------------------------------------------------------------------


def _revenue(db: Session, start, end) -> float:
    return _sum(db, Invoice.total, FINAL, Invoice.finalised_at >= start, Invoice.finalised_at < end)


def money_section(db: Session, d_from: date, d_to: date) -> dict:
    start, end = day_range(d_from, d_to)
    today = today_local()
    days = (d_to - d_from).days + 1
    prev_start, prev_end = day_range(d_from - timedelta(days=days), d_from - timedelta(days=1))
    ly_start, ly_end = day_range(_shift_year(d_from, -1), _shift_year(d_to, -1))
    fy_first = date(today.year if today.month >= 4 else today.year - 1, 4, 1)
    in_period = (FINAL, Invoice.finalised_at >= start, Invoice.finalised_at < end)

    invoices = db.scalar(select(func.count()).select_from(Invoice).where(*in_period)) or 0
    revenue = _revenue(db, start, end)
    split = dict(db.execute(
        select(InvoiceLine.line_type, func.sum(InvoiceLine.line_total - InvoiceLine.tax_amount))
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id).where(*in_period).group_by(InvoiceLine.line_type)
    ).all())

    unpaid = (FINAL, Invoice.payment_status != PaymentStatus.PAID)
    age = _days_since(Invoice.finalised_at)
    ageing = [
        {"bucket": label, "amount": _sum(db, Invoice.total - Invoice.amount_paid, *unpaid, cond)}
        for label, cond in (("0-30 days", age <= 30), ("31-60 days", and_(age > 30, age <= 60)),
                            ("61-90 days", and_(age > 60, age <= 90)), ("Over 90 days", age > 90))
    ]
    dues = db.execute(
        select(Invoice.invoice_number, Invoice.customer_name, Invoice.customer_mobile, Invoice.vehicle_registration,
               (Invoice.total - Invoice.amount_paid).label("outstanding"), age.label("days"))
        .where(*unpaid).order_by((Invoice.total - Invoice.amount_paid).desc()).limit(10)
    ).mappings().all()

    # Last 12 months to the end of the period, parts and labour before GST.
    first_month = date(d_to.year, d_to.month, 1)
    for _ in range(11):
        first_month = (first_month - timedelta(days=1)).replace(day=1)
    t_start, t_end = day_range(first_month, d_to)
    month = func.to_char(func.timezone(TZ_NAME, Invoice.finalised_at), "YYYY-MM")
    rows = db.execute(
        select(month.label("month"), InvoiceLine.line_type, func.sum(InvoiceLine.line_total - InvoiceLine.tax_amount))
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .where(FINAL, Invoice.finalised_at >= t_start, Invoice.finalised_at < t_end)
        .group_by(month, InvoiceLine.line_type)
    ).all()
    trend: dict[str, dict] = {}
    m = first_month
    while m <= d_to:
        key = m.strftime("%Y-%m")
        trend[key] = {"month": key, "parts": 0.0, "labour": 0.0}
        m = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
    for key, line_type, value in rows:
        if key in trend:
            trend[key]["parts" if line_type == LineType.PART else "labour"] += _num(value)

    return {
        "revenue": revenue,
        "revenue_previous_period": _revenue(db, prev_start, prev_end),
        "revenue_last_year": _revenue(db, ly_start, ly_end),
        "revenue_today": _revenue(db, *day_range(today, today)),
        "revenue_month": _revenue(db, *day_range(today.replace(day=1), today)),
        "revenue_financial_year": _revenue(db, *day_range(fy_first, today)),
        "invoices": invoices,
        "average_bill": revenue / invoices if invoices else 0,
        "parts_sales": _num(split.get(LineType.PART)),
        "labour_sales": _num(split.get(LineType.LABOUR)),
        "gst_collected": _sum(db, Invoice.tax_total, *in_period),
        "collected": _sum(db, Payment.amount, Payment.voided_at.is_(None), Payment.paid_at >= start, Payment.paid_at < end),
        "outstanding": sum(a["amount"] for a in ageing),
        "ageing": ageing,
        "top_dues": [{**r, "outstanding": _num(r["outstanding"]), "days": int(r["days"] or 0)} for r in dues],
        "trend": list(trend.values()),
    }


# --- Workshop ------------------------------------------------------------------------------


def workshop_section(db: Session, d_from: date, d_to: date) -> dict:
    start, end = day_range(d_from, d_to)
    today_start, today_end = day_range(today_local(), today_local())
    J = ServiceJob
    delivered = (J.status == JobStatus.COMPLETED, J.delivered_at >= start, J.delivered_at < end)
    turnaround = func.extract("epoch", J.delivered_at - J.visit_at) / 86400

    def count(*where) -> int:
        return db.scalar(select(func.count()).select_from(J).where(*where)) or 0

    by_status = dict(db.execute(select(J.status, func.count()).where(OPEN_JOB).group_by(J.status)).all())
    stuck = db.execute(
        select(J.job_number, Vehicle.registration_number, VehicleModel.name.label("model"), J.status,
               _days_since(J.visit_at).label("days"))
        .join(Vehicle, Vehicle.id == J.vehicle_id).join(VehicleModel, VehicleModel.id == Vehicle.model_id)
        .where(OPEN_JOB, J.status != JobStatus.READY_FOR_DELIVERY,
               or_(J.status == JobStatus.ON_HOLD, J.visit_at < func.now() - timedelta(days=STUCK_JOB_DAYS)))
        .order_by(J.visit_at).limit(10)
    ).mappings().all()
    mechanics = db.execute(
        select(User.full_name.label("mechanic"),
               func.count(J.id).filter(OPEN_JOB).label("open_jobs"),
               func.count(J.id).filter(*delivered).label("delivered"),
               func.avg(turnaround).filter(*delivered).label("avg_days"))
        .join(J, J.assigned_mechanic_id == User.id).group_by(User.id, User.full_name).order_by(User.full_name)
    ).mappings().all()

    earlier = aliased(ServiceJob)
    repeats = db.execute(
        select(J.job_number, Vehicle.registration_number, J.visit_at, func.max(earlier.visit_at).label("previous_visit"))
        .join(Vehicle, Vehicle.id == J.vehicle_id)
        .join(earlier, and_(earlier.vehicle_id == J.vehicle_id, earlier.id != J.id, earlier.visit_at < J.visit_at,
                            earlier.visit_at >= J.visit_at - timedelta(days=REPEAT_VISIT_DAYS),
                            earlier.status != JobStatus.CANCELLED))
        .where(J.visit_at >= start, J.visit_at < end, J.status != JobStatus.CANCELLED)
        .group_by(J.id, J.job_number, Vehicle.registration_number, J.visit_at).order_by(J.visit_at.desc())
    ).mappings().all()

    jobs_by_type = dict(db.execute(
        select(J.job_type, func.count()).where(J.visit_at >= start, J.visit_at < end, J.status != JobStatus.CANCELLED).group_by(J.job_type)
    ).all())
    revenue_by_type = dict(db.execute(
        select(J.job_type, func.sum(Invoice.total)).join(Invoice, Invoice.job_id == J.id)
        .where(FINAL, Invoice.finalised_at >= start, Invoice.finalised_at < end).group_by(J.job_type)
    ).all())

    return {
        "by_type": [{"type": t.value, "jobs": jobs_by_type.get(t, 0), "revenue": _num(revenue_by_type.get(t))} for t in JobType],
        "arrivals_today": count(J.visit_at >= today_start, J.visit_at < today_end),
        "arrivals": count(J.visit_at >= start, J.visit_at < end),
        "in_workshop": count(OPEN_JOB),
        "ready_for_delivery": by_status.get(JobStatus.READY_FOR_DELIVERY, 0),
        "delivered": count(*delivered),
        "average_turnaround_days": _num(db.scalar(select(func.avg(turnaround)).where(*delivered))),
        "stages": [{"stage": name, "jobs": sum(by_status.get(s, 0) for s in statuses)} for name, statuses in STAGES],
        "stuck_jobs": [{**r, "days": int(r["days"] or 0)} for r in stuck],
        "mechanics": [{**r, "avg_days": _num(r["avg_days"])} for r in mechanics],
        "repeat_visits": [{**r, "visit_at": r["visit_at"].isoformat(), "previous_visit": r["previous_visit"].isoformat()} for r in repeats[:10]],
        "repeat_visit_count": len(repeats),
    }


# --- Customers -----------------------------------------------------------------------------


def customers_section(db: Session, d_from: date, d_to: date) -> dict:
    start, end = day_range(d_from, d_to)
    J = ServiceJob
    served = select(J.customer_id).where(J.visit_at >= start, J.visit_at < end, J.status != JobStatus.CANCELLED).distinct()
    served_ids = set(db.scalars(served))
    returning = set(db.scalars(select(J.customer_id).where(J.customer_id.in_(served_ids), J.visit_at < start).distinct())) if served_ids else set()
    models = db.execute(
        select(VehicleModel.name.label("model"), func.count(J.id).label("jobs"))
        .join(Vehicle, Vehicle.model_id == VehicleModel.id).join(J, J.vehicle_id == Vehicle.id)
        .where(J.visit_at >= start, J.visit_at < end, J.status != JobStatus.CANCELLED)
        .group_by(VehicleModel.name).order_by(func.count(J.id).desc())
    ).mappings().all()
    top = db.execute(
        select(Customer.name, Customer.mobile, func.count(Invoice.id).label("invoices"), func.sum(Invoice.total).label("spend"))
        .join(Invoice, Invoice.customer_id == Customer.id)
        .where(FINAL, Invoice.finalised_at >= start, Invoice.finalised_at < end)
        .group_by(Customer.id, Customer.name, Customer.mobile).order_by(func.sum(Invoice.total).desc()).limit(10)
    ).mappings().all()
    F = CustomerFeedback
    rated = (F.created_at >= start, F.created_at < end)
    ratings = dict(db.execute(select(F.rating, func.count()).where(*rated).group_by(F.rating)).all())
    rated_count = sum(ratings.values())
    low = db.execute(
        select(J.job_number, Invoice.customer_name, Invoice.customer_mobile, F.rating, F.comment, F.created_at)
        .join(J, J.id == F.job_id).join(Invoice, Invoice.id == F.invoice_id)
        .where(*rated, F.rating <= 3).order_by(F.created_at.desc()).limit(10)
    ).mappings().all()

    return {
        "feedback": {
            "count": rated_count,
            "average": sum(r * n for r, n in ratings.items()) / rated_count if rated_count else 0,
            "distribution": [{"rating": r, "count": ratings.get(r, 0)} for r in (5, 4, 3, 2, 1)],
            "low": [{**r, "created_at": r["created_at"].isoformat()} for r in low],
        },
        "customers_served": len(served_ids),
        "new_customers": len(served_ids - returning),
        "returning_customers": len(returning),
        "by_model": [dict(r) for r in models],
        "top_customers": [{**r, "spend": _num(r["spend"])} for r in top],
    }


# --- Parts and stock -----------------------------------------------------------------------


def parts_section(db: Session, d_from: date, d_to: date) -> dict:
    start, end = day_range(d_from, d_to)
    today = today_local()
    active = Part.is_active.is_(True)
    in_stock = and_(active, Part.sheet_closing_qty > 0)
    shelf_qty = func.coalesce(Part.sheet_actual_qty, Part.sheet_closing_qty, 0)

    def grouped(column) -> list[dict]:
        label = func.coalesce(func.nullif(column, ""), "Not set")
        rows = db.execute(
            select(label.label("group"), func.count(Part.id).label("parts"), func.coalesce(func.sum(Part.sheet_closing_value), 0).label("value"))
            .where(in_stock).group_by(label).order_by(label)
        ).mappings().all()
        return [{**r, "value": _num(r["value"])} for r in rows]

    last_sold = (
        _part_lines(_PART_ID.label("part_id"), func.max(Invoice.finalised_at).label("last_sold"))
        .where(_PART_ID.is_not(None)).group_by(_PART_ID).subquery()
    )
    dead_cutoff = day_range(today - timedelta(days=DEAD_STOCK_DAYS), today)[0]
    dead = and_(in_stock, or_(last_sold.c.last_sold.is_(None), last_sold.c.last_sold < dead_cutoff))
    dead_rows = db.execute(
        select(Part.sku, Part.name, Part.sheet_closing_qty.label("qty"), Part.sheet_closing_value.label("value"), last_sold.c.last_sold)
        .outerjoin(last_sold, last_sold.c.part_id == Part.id).where(dead)
        .order_by(Part.sheet_closing_value.desc().nulls_last()).limit(10)
    ).mappings().all()
    dead_total = db.execute(
        select(func.count(Part.id), func.coalesce(func.sum(Part.sheet_closing_value), 0))
        .outerjoin(last_sold, last_sold.c.part_id == Part.id).where(dead)
    ).one()

    unit_cost = func.coalesce(Part.sheet_closing_value / func.nullif(Part.sheet_closing_qty, 0), Part.purchase_cost)
    diff = Part.sheet_actual_qty - func.coalesce(Part.sheet_closing_qty, 0)
    differs = and_(active, Part.sheet_actual_qty.is_not(None), diff != 0)
    count_rows = db.execute(
        select(Part.sku, Part.name, Part.sheet_closing_qty.label("closing_qty"), Part.sheet_actual_qty.label("actual_qty"),
               diff.label("difference"), (diff * unit_cost).label("value"))
        .where(differs).order_by(func.abs(diff * unit_cost).desc()).limit(15)
    ).mappings().all()

    month_start = day_range(today - timedelta(days=29), today)[0]
    sold_30 = _sales_by_part(month_start, day_range(today, today)[1])
    low = db.execute(
        select(Part.sku, Part.name, shelf_qty.label("qty"), sold_30.c.qty.label("sold_30_days"))
        .join(sold_30, sold_30.c.part_id == Part.id).where(active, shelf_qty < sold_30.c.qty)
        .order_by((sold_30.c.qty - shelf_qty).desc()).limit(15)
    ).mappings().all()

    sales = _sales_by_part(start, end)

    def top(order) -> list[dict]:
        rows = db.execute(
            select(Part.sku, Part.name, sales.c.qty, sales.c.value).join(sales, sales.c.part_id == Part.id).order_by(order.desc()).limit(10)
        ).mappings().all()
        return [{**r, "qty": _num(r["qty"]), "value": _num(r["value"])} for r in rows]

    open_job_ids = select(ServiceJob.id).where(OPEN_JOB)
    return {
        "stock_value": _sum(db, Part.sheet_closing_value, in_stock),
        "parts_in_stock": db.scalar(select(func.count()).select_from(Part).where(in_stock)) or 0,
        "by_abc": grouped(Part.abc_class),
        "by_movement": grouped(Part.movement_class),
        "dead_stock_days": DEAD_STOCK_DAYS,
        "dead_stock_parts": dead_total[0],
        "dead_stock_value": _num(dead_total[1]),
        "dead_stock": [{**r, "qty": _num(r["qty"]), "value": _num(r["value"]),
                        "last_sold": r["last_sold"].isoformat() if r["last_sold"] else None} for r in dead_rows],
        "count_difference_parts": db.scalar(select(func.count()).select_from(Part).where(differs)) or 0,
        "count_differences": [{k: (_num(v) if k in ("closing_qty", "actual_qty", "difference", "value") else v) for k, v in r.items()} for r in count_rows],
        "running_low": [{**r, "qty": _num(r["qty"]), "sold_30_days": _num(r["sold_30_days"])} for r in low],
        "top_by_value": top(sales.c.value),
        "top_by_qty": top(sales.c.qty),
        "shortage_lines": db.scalar(select(func.count()).select_from(PartsRequestLine).where(PartsRequestLine.status == PartsLineStatus.UNAVAILABLE)) or 0,
        "unavailable_lists": db.scalar(select(func.count()).select_from(Inspection).where(
            Inspection.spare_parts_status == "UNAVAILABLE", Inspection.job_id.in_(open_job_ids))) or 0,
        "pending_purchase_requests": db.scalar(select(func.count()).select_from(PurchaseRequest).where(
            PurchaseRequest.status == PurchaseRequestStatus.PENDING_APPROVAL)) or 0,
    }


# --- Margin, targets, service due ----------------------------------------------------------


def growth_section(db: Session, d_from: date, d_to: date) -> dict:
    start, end = day_range(d_from, d_to)
    today = today_local()
    sales, cost = db.execute(
        _part_lines(func.coalesce(func.sum(InvoiceLine.line_total - InvoiceLine.tax_amount), 0),
                    func.coalesce(func.sum(InvoiceLine.quantity * Part.purchase_cost), 0))
        .join(Part, Part.id == _PART_ID)
        .where(Invoice.finalised_at >= start, Invoice.finalised_at < end)
    ).one()
    sales, cost = _num(sales), _num(cost)

    month_start, month_end = day_range(today.replace(day=1), today)
    targets = {
        "revenue_target": _num(settings_service.get(db, "monthly_revenue_target")),
        "revenue_month": _revenue(db, month_start, month_end),
        "vehicles_target": int(settings_service.get(db, "monthly_vehicles_target") or 0),
        "vehicles_month": db.scalar(select(func.count()).select_from(ServiceJob).where(
            ServiceJob.status == JobStatus.COMPLETED, ServiceJob.delivered_at >= month_start, ServiceJob.delivered_at < month_end)) or 0,
    }

    interval = int(settings_service.get(db, "service_interval_days") or 180)
    J = ServiceJob
    last = (
        select(J.vehicle_id, func.max(J.visit_at).label("last_visit"),
               func.count(J.id).filter(OPEN_JOB).label("open_jobs"))
        .where(J.status != JobStatus.CANCELLED).group_by(J.vehicle_id).subquery()
    )
    cutoff = day_range(today - timedelta(days=interval), today)[0]
    due = and_(last.c.open_jobs == 0, last.c.last_visit < cutoff, Vehicle.is_active.is_(True))
    due_rows = db.execute(
        select(Vehicle.registration_number, VehicleModel.name.label("model"), Customer.name.label("customer"),
               Customer.mobile, last.c.last_visit, _days_since(last.c.last_visit).label("days"))
        .join(last, last.c.vehicle_id == Vehicle.id).join(VehicleModel, VehicleModel.id == Vehicle.model_id)
        .join(Customer, Customer.id == Vehicle.customer_id).where(due).order_by(last.c.last_visit.desc()).limit(20)
    ).mappings().all()

    return {
        "parts_sales": sales,
        "parts_cost": cost,
        "parts_margin": sales - cost,
        "parts_margin_percent": (sales - cost) / sales * 100 if sales else 0,
        "targets": targets,
        "service_interval_days": interval,
        "service_due_count": db.scalar(select(func.count()).select_from(Vehicle).join(last, last.c.vehicle_id == Vehicle.id).where(due)) or 0,
        "service_due": [{**r, "last_visit": r["last_visit"].isoformat(), "days": int(r["days"] or 0)} for r in due_rows],
    }


def dealer_dashboard(db: Session, d_from: date, d_to: date) -> dict:
    return {
        "date_from": d_from.isoformat(),
        "date_to": d_to.isoformat(),
        "money": money_section(db, d_from, d_to),
        "workshop": workshop_section(db, d_from, d_to),
        "customers": customers_section(db, d_from, d_to),
        "parts": parts_section(db, d_from, d_to),
        "growth": growth_section(db, d_from, d_to),
    }

