"""Reports and dashboard figures, computed with database aggregations.

Each report returns {"title", "columns": [{"key","label","type"}], "rows": [...], "summary": {...}}
so the API can serve it as JSON or CSV. Days are bucketed in the service centre's time zone.
"""
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Date, and_, case, cast, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.utils import ZERO, utcnow
from app.models import (
    DeliveryJob,
    Inspection,
    InventoryMovement,
    InventoryStock,
    Invoice,
    InvoiceLine,
    JobLabour,
    Part,
    PartsRequest,
    PartsRequestLine,
    Payment,
    PurchaseRequest,
    Role,
    ServiceJob,
    User,
    Vehicle,
    VehicleModel,
    WorkCompletion,
    Customer,
    AuditLog,
    LabourOperation,
    TaxRate,
)
from app.models.enums import (
    MECHANIC_DONE_STATUSES,
    ACTIVE_DELIVERY_STATUSES,
    CLOSED_JOB_STATUSES,
    ApprovalStatus,
    Channel,
    DeliveryKind,
    DeliveryStatus,
    InvoiceStatus,
    JobStatus,
    LineType,
    PartsLineStatus,
    PartsRequestStatus,
    PaymentStatus,
    PurchaseRequestStatus,
    RoleCode,
)

TZ_NAME = "Asia/Kolkata"
TZ = ZoneInfo(TZ_NAME)


def local_day(column):
    return cast(func.timezone(TZ_NAME, column), Date)


def day_range(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(date_from, time.min, TZ),
        datetime.combine(date_to + timedelta(days=1), time.min, TZ),
    )


def today_local() -> date:
    return utcnow().astimezone(TZ).date()


def col(key: str, label: str, type_: str = "text") -> dict:
    return {"key": key, "label": label, "type": type_}


def _count(db: Session, model, *conditions) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0


FINAL = Invoice.status == InvoiceStatus.FINALISED
OPEN_JOB = ServiceJob.status.notin_(CLOSED_JOB_STATUSES)
OPEN_LINE = and_(
    PartsRequestLine.status.notin_((PartsLineStatus.CANCELLED, PartsLineStatus.ISSUED)),
    PartsRequestLine.approval_status != ApprovalStatus.REJECTED,
)


# --- Reports ----------------------------------------------------------------------------


def jobs_by_period(db: Session, start: datetime, end: datetime, monthly: bool) -> dict:
    bucket = func.to_char(func.timezone(TZ_NAME, ServiceJob.visit_at), "YYYY-MM" if monthly else "YYYY-MM-DD")
    rows = db.execute(
        select(
            bucket.label("period"),
            func.count().label("opened"),
            func.count().filter(ServiceJob.status == JobStatus.COMPLETED).label("completed"),
            func.count().filter(ServiceJob.status == JobStatus.CANCELLED).label("cancelled"),
            func.count().filter(OPEN_JOB).label("still_open"),
        )
        .where(ServiceJob.visit_at >= start, ServiceJob.visit_at < end)
        .group_by(bucket).order_by(bucket)
    ).mappings().all()
    return {
        "title": "Monthly service jobs" if monthly else "Daily service jobs",
        "columns": [col("period", "Month" if monthly else "Date"), col("opened", "Jobs opened", "number"),
                    col("completed", "Completed", "number"), col("cancelled", "Cancelled", "number"),
                    col("still_open", "Still open", "number")],
        "rows": [dict(r) for r in rows],
        "summary": {"jobs_opened": sum(r["opened"] for r in rows)},
        "chart": {"x": "period", "series": ["opened", "completed"]},
    }


def revenue(db: Session, start: datetime, end: datetime, **_) -> dict:
    day = local_day(Invoice.finalised_at)
    rows = db.execute(
        select(
            day.label("date"), func.count().label("invoices"),
            func.sum(Invoice.subtotal_labour).label("labour"), func.sum(Invoice.subtotal_parts).label("parts"),
            func.sum(Invoice.discount_total).label("discount"), func.sum(Invoice.tax_total).label("tax"),
            func.sum(Invoice.total).label("total"),
        )
        .where(FINAL, Invoice.finalised_at >= start, Invoice.finalised_at < end)
        .group_by(day).order_by(day)
    ).mappings().all()
    collected = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.voided_at.is_(None), Payment.paid_at >= start, Payment.paid_at < end)
    )
    outstanding = db.scalar(select(func.coalesce(func.sum(Invoice.total - Invoice.amount_paid), 0)).where(FINAL))
    return {
        "title": "Revenue",
        "columns": [col("date", "Date", "date"), col("invoices", "Invoices", "number"), col("labour", "Labour", "money"),
                    col("parts", "Parts", "money"), col("discount", "Discounts", "money"), col("tax", "Tax", "money"),
                    col("total", "Invoiced total", "money")],
        "rows": [dict(r) for r in rows],
        "summary": {
            "invoiced_total": sum((r["total"] for r in rows), ZERO),
            "labour_revenue": sum((r["labour"] for r in rows), ZERO),
            "parts_revenue": sum((r["parts"] for r in rows), ZERO),
            "tax_total": sum((r["tax"] for r in rows), ZERO),
            "payments_collected": collected,
            "outstanding_all_invoices": outstanding,
        },
        "chart": {"x": "date", "series": ["labour", "parts"]},
    }


def outstanding_invoices(db: Session, **_) -> dict:
    rows = db.execute(
        select(
            Invoice.invoice_number, local_day(Invoice.finalised_at).label("date"), Invoice.customer_name,
            Invoice.customer_mobile, Invoice.vehicle_registration, Invoice.total, Invoice.amount_paid,
            (Invoice.total - Invoice.amount_paid).label("outstanding"), Invoice.payment_status,
        )
        .where(FINAL, Invoice.total > Invoice.amount_paid).order_by(Invoice.finalised_at)
    ).mappings().all()
    return {
        "title": "Outstanding invoices",
        "columns": [col("invoice_number", "Invoice"), col("date", "Date", "date"), col("customer_name", "Customer"),
                    col("customer_mobile", "Mobile"), col("vehicle_registration", "Vehicle"), col("total", "Total", "money"),
                    col("amount_paid", "Paid", "money"), col("outstanding", "Outstanding", "money"), col("payment_status", "Status", "status")],
        "rows": [dict(r) for r in rows],
        "summary": {"outstanding_total": sum((r["outstanding"] for r in rows), ZERO), "invoices": len(rows)},
    }


def parts_consumption(db: Session, start: datetime, end: datetime, **_) -> dict:
    rows = db.execute(
        select(
            InvoiceLine.code.label("sku"), func.max(InvoiceLine.description).label("name"),
            func.sum(InvoiceLine.quantity).label("quantity"),
            func.sum(InvoiceLine.line_total - InvoiceLine.tax_amount).label("revenue"),
        )
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .where(FINAL, InvoiceLine.line_type == LineType.PART, Invoice.finalised_at >= start, Invoice.finalised_at < end)
        .group_by(InvoiceLine.code).order_by(func.sum(InvoiceLine.quantity).desc())
    ).mappings().all()
    return {
        "title": "Parts consumption (invoiced)",
        "columns": [col("sku", "Part number"), col("name", "Part"), col("quantity", "Quantity used", "number"),
                    col("revenue", "Revenue (ex tax)", "money")],
        "rows": [dict(r) for r in rows],
        "summary": {"parts_revenue": sum((r["revenue"] for r in rows), ZERO)},
        "chart": {"x": "sku", "series": ["quantity"]},
    }


def low_stock(db: Session, **_) -> dict:
    available = InventoryStock.qty_on_hand - InventoryStock.qty_reserved
    rows = db.execute(
        select(Part.sku, Part.name, InventoryStock.qty_on_hand.label("on_hand"), InventoryStock.qty_reserved.label("reserved"),
               available.label("available"), Part.reorder_threshold, Part.storage_location)
        .join(InventoryStock, InventoryStock.part_id == Part.id)
        .where(Part.is_active, available <= Part.reorder_threshold).order_by(available)
    ).mappings().all()
    return {
        "title": "Low-stock items",
        "columns": [col("sku", "Part number"), col("name", "Part"), col("on_hand", "On hand", "number"),
                    col("reserved", "Reserved", "number"), col("available", "Available", "number"),
                    col("reorder_threshold", "Reorder at", "number"), col("storage_location", "Location")],
        "rows": [dict(r) for r in rows], "summary": {"items": len(rows)},
    }


def _shortage_rows(db: Session, only_flagged: bool):
    stmt = (
        select(
            ServiceJob.job_number, Vehicle.registration_number.label("vehicle"), ServiceJob.status.label("job_status"),
            Part.sku, Part.name, PartsRequestLine.qty_requested.label("requested"), PartsRequestLine.qty_issued.label("issued"),
            (PartsRequestLine.qty_requested - PartsRequestLine.qty_issued).label("outstanding"),
            PartsRequestLine.expected_restock_date,
        )
        .join(PartsRequest, PartsRequest.id == PartsRequestLine.request_id)
        .join(ServiceJob, ServiceJob.id == PartsRequest.job_id)
        .join(Vehicle, Vehicle.id == ServiceJob.vehicle_id)
        .join(Part, Part.id == PartsRequestLine.part_id)
        .where(OPEN_JOB, OPEN_LINE)
        .order_by(ServiceJob.visit_at)
    )
    stmt = stmt.where(PartsRequestLine.is_short) if only_flagged else stmt.where(ServiceJob.status == JobStatus.AWAITING_PARTS)
    return db.execute(stmt).mappings().all()


_SHORT_COLS = [col("job_number", "Job card"), col("vehicle", "Vehicle"), col("job_status", "Job status", "status"),
               col("sku", "Part number"), col("name", "Part"), col("requested", "Requested", "number"),
               col("issued", "Issued", "number"), col("outstanding", "Outstanding", "number"),
               col("expected_restock_date", "Restock expected", "date")]


def unavailable_parts(db: Session, **_) -> dict:
    rows = _shortage_rows(db, only_flagged=True)
    return {"title": "Unavailable parts", "columns": _SHORT_COLS, "rows": [dict(r) for r in rows], "summary": {"lines": len(rows)}}


def jobs_waiting_parts(db: Session, **_) -> dict:
    rows = _shortage_rows(db, only_flagged=False)
    return {"title": "Jobs waiting for parts", "columns": _SHORT_COLS, "rows": [dict(r) for r in rows],
            "summary": {"jobs": len({r["job_number"] for r in rows})}}


def technician_workload(db: Session, start: datetime, end: datetime, **_) -> dict:
    hours = (
        select(func.coalesce(func.sum(JobLabour.estimated_hours), 0))
        .join(ServiceJob, ServiceJob.id == JobLabour.job_id)
        .where(ServiceJob.assigned_mechanic_id == User.id, JobLabour.approval_status == ApprovalStatus.APPROVED,
               ServiceJob.visit_at >= start, ServiceJob.visit_at < end)
        .correlate(User).scalar_subquery()
    )
    rows = db.execute(
        select(
            User.full_name.label("mechanic"),
            func.count(ServiceJob.id).filter(OPEN_JOB).label("active_jobs"),
            func.count(ServiceJob.id).filter(ServiceJob.status == JobStatus.IN_SERVICE).label("in_service"),
            func.count(ServiceJob.id).filter(
                ServiceJob.status == JobStatus.COMPLETED, ServiceJob.delivered_at >= start, ServiceJob.delivered_at < end
            ).label("completed_in_period"),
            func.coalesce(func.sum(ServiceJob.rework_count).filter(ServiceJob.visit_at >= start, ServiceJob.visit_at < end), 0).label("reworks"),
            hours.label("approved_hours"),
        )
        .join(Role, Role.id == User.role_id)
        .outerjoin(ServiceJob, ServiceJob.assigned_mechanic_id == User.id)
        .where(Role.code == RoleCode.MECHANIC, User.is_active)
        .group_by(User.id, User.full_name).order_by(User.full_name)
    ).mappings().all()
    return {
        "title": "Technician workload",
        "columns": [col("mechanic", "Mechanic"), col("active_jobs", "Active jobs", "number"), col("in_service", "In service", "number"),
                    col("completed_in_period", "Completed in period", "number"), col("reworks", "Reworks", "number"),
                    col("approved_hours", "Approved labour hours", "number")],
        "rows": [dict(r) for r in rows], "summary": {},
        "chart": {"x": "mechanic", "series": ["active_jobs", "completed_in_period"]},
    }


def turnaround(db: Session, start: datetime, end: datetime, **_) -> dict:
    hours = func.extract("epoch", ServiceJob.delivered_at - ServiceJob.visit_at) / 3600.0
    base = (ServiceJob.status == JobStatus.COMPLETED, ServiceJob.delivered_at >= start, ServiceJob.delivered_at < end)
    rows = db.execute(
        select(VehicleModel.name.label("model"), func.count().label("jobs"),
               func.round(cast(func.avg(hours), type_=InvoiceLine.quantity.type), 1).label("avg_hours"),
               func.round(cast(func.max(hours), type_=InvoiceLine.quantity.type), 1).label("max_hours"))
        .join(Vehicle, Vehicle.id == ServiceJob.vehicle_id).join(VehicleModel, VehicleModel.id == Vehicle.model_id)
        .where(*base).group_by(VehicleModel.name).order_by(VehicleModel.name)
    ).mappings().all()
    overall = db.scalar(select(func.avg(hours)).where(*base))
    return {
        "title": "Average turnaround time (reception to handover)",
        "columns": [col("model", "Vehicle model"), col("jobs", "Jobs delivered", "number"),
                    col("avg_hours", "Average hours", "number"), col("max_hours", "Longest (hours)", "number")],
        "rows": [dict(r) for r in rows],
        "summary": {"average_hours": round(float(overall), 1) if overall is not None else None},
        "chart": {"x": "model", "series": ["avg_hours"]},
    }


def repeat_visits(db: Session, start: datetime, end: datetime, **_) -> dict:
    rows = db.execute(
        select(Vehicle.registration_number.label("vehicle"), VehicleModel.name.label("model"),
               Customer.name.label("customer"), func.count().label("visits"),
               local_day(func.min(ServiceJob.visit_at)).label("first_visit"),
               local_day(func.max(ServiceJob.visit_at)).label("last_visit"))
        .join(Vehicle, Vehicle.id == ServiceJob.vehicle_id).join(VehicleModel, VehicleModel.id == Vehicle.model_id)
        .join(Customer, Customer.id == Vehicle.customer_id)
        .where(ServiceJob.visit_at >= start, ServiceJob.visit_at < end, ServiceJob.status != JobStatus.CANCELLED)
        .group_by(Vehicle.registration_number, VehicleModel.name, Customer.name)
        .having(func.count() > 1).order_by(func.count().desc())
    ).mappings().all()
    return {
        "title": "Repeat visits",
        "columns": [col("vehicle", "Vehicle"), col("model", "Model"), col("customer", "Customer"),
                    col("visits", "Visits", "number"), col("first_visit", "First visit", "date"), col("last_visit", "Last visit", "date")],
        "rows": [dict(r) for r in rows], "summary": {"vehicles": len(rows)},
    }


def delivery_rates(db: Session, start: datetime, end: datetime, **_) -> dict:
    ok = DeliveryJob.status.in_((DeliveryStatus.SENT, DeliveryStatus.DELIVERED))
    rows = db.execute(
        select(
            DeliveryJob.channel, func.count().label("total"),
            func.count().filter(ok).label("accepted"),
            func.count().filter(DeliveryJob.status == DeliveryStatus.DELIVERED).label("confirmed_delivered"),
            func.count().filter(DeliveryJob.status == DeliveryStatus.FAILED).label("failed"),
            func.count().filter(DeliveryJob.status.in_(ACTIVE_DELIVERY_STATUSES)).label("in_progress"),
            func.count().filter(DeliveryJob.status == DeliveryStatus.SKIPPED).label("skipped"),
            func.count().filter(DeliveryJob.simulated).label("simulated"),
        )
        .where(DeliveryJob.kind == DeliveryKind.INVOICE, DeliveryJob.created_at >= start, DeliveryJob.created_at < end)
        .group_by(DeliveryJob.channel).order_by(DeliveryJob.channel)
    ).mappings().all()
    out = []
    for r in rows:
        row = dict(r)
        finished = row["accepted"] + row["failed"]
        row["success_rate"] = round(100 * row["accepted"] / finished, 1) if finished else None
        out.append(row)
    return {
        "title": "Invoice delivery success and failure rates",
        "columns": [col("channel", "Channel"), col("total", "Deliveries", "number"), col("accepted", "Accepted by provider", "number"),
                    col("confirmed_delivered", "Confirmed delivered", "number"), col("failed", "Failed", "number"),
                    col("in_progress", "In progress", "number"), col("skipped", "Skipped (opt-out)", "number"),
                    col("simulated", "Simulated (dev)", "number"), col("success_rate", "Acceptance rate %", "number")],
        "rows": out, "summary": {},
    }


def delivery_failures(db: Session, start: datetime, end: datetime, channel: str | None = None, **_) -> dict:
    stmt = (
        select(Invoice.invoice_number, DeliveryJob.channel, DeliveryJob.destination, DeliveryJob.attempt_count.label("attempts"),
               DeliveryJob.last_error, DeliveryJob.last_attempt_at, Invoice.customer_name)
        .join(Invoice, Invoice.id == DeliveryJob.invoice_id)
        .where(DeliveryJob.kind == DeliveryKind.INVOICE, DeliveryJob.status == DeliveryStatus.FAILED,
               DeliveryJob.created_at >= start, DeliveryJob.created_at < end)
        .order_by(DeliveryJob.id.desc())
    )
    if channel:
        stmt = stmt.where(DeliveryJob.channel == channel)
    rows = db.execute(stmt).mappings().all()
    return {
        "title": f"{'WhatsApp' if channel == Channel.WHATSAPP else channel.title() if channel else 'Invoice'} delivery failures",
        "columns": [col("invoice_number", "Invoice"), col("channel", "Channel"), col("customer_name", "Customer"),
                    col("destination", "Destination"), col("attempts", "Attempts", "number"), col("last_error", "Error"),
                    col("last_attempt_at", "Last attempt", "datetime")],
        "rows": [dict(r) for r in rows], "summary": {"failures": len(rows)},
    }


# name -> (function, permissions that may view it, uses date range)
REPORTS: dict[str, tuple[Callable, tuple[str, ...], bool]] = {
    "jobs-daily": (lambda db, **kw: jobs_by_period(db, kw["start"], kw["end"], monthly=False), ("report.view",), True),
    "jobs-monthly": (lambda db, **kw: jobs_by_period(db, kw["start"], kw["end"], monthly=True), ("report.view",), True),
    "revenue": (revenue, ("report.view",), True),
    "outstanding-invoices": (outstanding_invoices, ("report.view",), False),
    "parts-consumption": (parts_consumption, ("report.view", "report.inventory"), True),
    "low-stock": (low_stock, ("report.view", "report.inventory"), False),
    "unavailable-parts": (unavailable_parts, ("report.view", "report.inventory"), False),
    "jobs-waiting-parts": (jobs_waiting_parts, ("report.view", "report.inventory"), False),
    "technician-workload": (technician_workload, ("report.view",), True),
    "turnaround": (turnaround, ("report.view",), True),
    "repeat-visits": (repeat_visits, ("report.view",), True),
    "delivery-rates": (delivery_rates, ("report.view",), True),
    "email-failures": (lambda db, **kw: delivery_failures(db, kw["start"], kw["end"], Channel.EMAIL), ("report.view",), True),
    "sms-failures": (lambda db, **kw: delivery_failures(db, kw["start"], kw["end"], Channel.SMS), ("report.view",), True),
    "whatsapp-failures": (lambda db, **kw: delivery_failures(db, kw["start"], kw["end"], Channel.WHATSAPP), ("report.view",), True),
}


# --- Dashboards -------------------------------------------------------------------------


def _series(db: Session, ts_col, value, *where, days: int = 7) -> dict:
    """{date: value} for the last `days` local days (missing days are 0)."""
    start, _ = day_range(today_local() - timedelta(days=days - 1), today_local())
    day = local_day(ts_col)
    rows = dict(db.execute(select(day, value).where(ts_col >= start, *where).group_by(day)).all())
    return {d: rows.get(d) or 0 for d in (today_local() - timedelta(days=i) for i in range(days - 1, -1, -1))}


def _trend(**series: dict) -> list[dict]:
    """Merge several {date: value} series into [{date, name1, name2, ...}]."""
    days = next(iter(series.values())).keys()
    return [{"date": d.isoformat(), **{name: values[d] for name, values in series.items()}} for d in days]


def _pipeline(db: Session, *where) -> dict:
    J = ServiceJob
    return dict(db.execute(select(J.status, func.count()).where(OPEN_JOB, *where).group_by(J.status)).all())


def dashboard(db: Session, user: User) -> dict:
    role = user.role_code
    today_start, today_end = day_range(today_local(), today_local())
    month_start, _ = day_range(today_local().replace(day=1), today_local())
    J = ServiceJob

    if role == RoleCode.SERVICE_MANAGER:
        def invoiced(since):
            return db.scalar(select(func.coalesce(func.sum(Invoice.total), 0)).where(FINAL, Invoice.finalised_at >= since))

        def collected(since):
            return db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.voided_at.is_(None), Payment.paid_at >= since))

        failed = lambda ch: _count(db, DeliveryJob, DeliveryJob.status == DeliveryStatus.FAILED, DeliveryJob.channel == ch)  # noqa: E731
        cards = {
            "todays_arrivals": _count(db, J, J.visit_at >= today_start, J.visit_at < today_end),
            "active_jobs": _count(db, J, OPEN_JOB),
            "awaiting_assignment": _count(db, J, J.status == JobStatus.AWAITING_ASSIGNMENT),
            "awaiting_parts": _count(db, J, J.status == JobStatus.AWAITING_PARTS),
            "ready_for_billing": _count(db, J, J.status == JobStatus.READY_FOR_BILLING),
            "ready_for_delivery": _count(db, J, J.status == JobStatus.READY_FOR_DELIVERY),
            "on_hold": _count(db, J, J.status == JobStatus.ON_HOLD),
            "unpaid_invoices": _count(db, Invoice, FINAL, Invoice.payment_status == PaymentStatus.UNPAID, Invoice.total > 0),
            "partially_paid_invoices": _count(db, Invoice, FINAL, Invoice.payment_status == PaymentStatus.PARTIALLY_PAID),
            "outstanding_total": db.scalar(select(func.coalesce(func.sum(Invoice.total - Invoice.amount_paid), 0)).where(FINAL)),
            "email_failures": failed(Channel.EMAIL),
            **({"sms_failures": failed(Channel.SMS)} if get_settings().sms_enabled else {}),
            "parts_shortages": _count(db, PartsRequestLine, PartsRequestLine.is_short, OPEN_LINE),
            "pending_purchase_requests": _count(db, PurchaseRequest, PurchaseRequest.status == PurchaseRequestStatus.PENDING_APPROVAL),
            "pending_alternatives": _count(db, PartsRequestLine, PartsRequestLine.alt_status == "PROPOSED", OPEN_LINE),
            "revenue_today": invoiced(today_start),
            "revenue_month": invoiced(month_start),
            "collected_today": collected(today_start),
            "collected_month": collected(month_start),
        }
        extras = {
            "pipeline": _pipeline(db),
            "trend": _trend(
                invoiced=_series(db, Invoice.finalised_at, func.sum(Invoice.total), FINAL),
                collected=_series(db, Payment.paid_at, func.sum(Payment.amount), Payment.voided_at.is_(None)),
            ),
        }
    elif role == RoleCode.MECHANIC:
        mine = J.assigned_mechanic_id == user.id
        cards = {
            "assigned_jobs": _count(db, J, mine, J.status.notin_((*MECHANIC_DONE_STATUSES, JobStatus.CANCELLED))),
            "completed_jobs": _count(db, J, mine, J.status.in_(MECHANIC_DONE_STATUSES)),
            "pending_inspections": _count(db, J, mine, J.status == JobStatus.INSPECTION_IN_PROGRESS),
            "awaiting_parts": _count(db, J, mine, J.status == JobStatus.AWAITING_PARTS),
            "ready_for_service": _count(db, J, mine, J.status == JobStatus.READY_FOR_SERVICE),
            "in_service": _count(db, J, mine, J.status == JobStatus.IN_SERVICE),
            "returned_for_rework": _count(db, J, mine, J.status == JobStatus.IN_SERVICE, J.returned_for_rework),
            "open_parts_requests": db.scalar(
                select(func.count()).select_from(PartsRequest).join(J, J.id == PartsRequest.job_id)
                .where(mine, OPEN_JOB, PartsRequest.status.notin_((PartsRequestStatus.FULFILLED, PartsRequestStatus.CANCELLED)))
            ),
        }
        extras = {
            "pipeline": _pipeline(db, mine),
            "trend": _trend(completed=_series(db, WorkCompletion.completed_at, func.count(), WorkCompletion.mechanic_id == user.id)),
        }
    elif role == RoleCode.INVENTORY_STAFF:
        open_req = select(func.count()).select_from(PartsRequest).join(J, J.id == PartsRequest.job_id).where(OPEN_JOB)
        available = InventoryStock.qty_on_hand - InventoryStock.qty_reserved
        unreturned = PartsRequestLine.qty_issued - PartsRequestLine.qty_returned - func.coalesce(PartsRequestLine.qty_consumed, PartsRequestLine.qty_issued - PartsRequestLine.qty_returned)
        cards = {
            "incoming_requests": db.scalar(open_req.where(PartsRequest.status == PartsRequestStatus.PENDING)),
            "spare_parts_lists": db.scalar(
                select(func.count()).select_from(Inspection).join(J, J.id == Inspection.job_id)
                .where(OPEN_JOB, Inspection.spare_parts_status == "PENDING")
            ),
            "partially_fulfilled": db.scalar(open_req.where(PartsRequest.status == PartsRequestStatus.PARTIALLY_FULFILLED)),
            "unavailable_lines": _count(db, PartsRequestLine, PartsRequestLine.is_short, OPEN_LINE),
            "low_stock_items": db.scalar(
                select(func.count()).select_from(Part).join(InventoryStock, InventoryStock.part_id == Part.id)
                .where(Part.is_active, available <= Part.reorder_threshold)
            ),
            "pending_purchase_requests": _count(db, PurchaseRequest, PurchaseRequest.status == PurchaseRequestStatus.PENDING_APPROVAL),
            "approved_awaiting_receipt": _count(db, PurchaseRequest, PurchaseRequest.status.in_((PurchaseRequestStatus.APPROVED, PurchaseRequestStatus.PARTIALLY_RECEIVED))),
            "returns_due": _count(db, PartsRequestLine, PartsRequestLine.status != PartsLineStatus.CANCELLED, unreturned > 0),
        }
        low = db.execute(
            select(Part.id, Part.sku, Part.name, available.label("available"), Part.reorder_threshold)
            .join(InventoryStock, InventoryStock.part_id == Part.id)
            .where(Part.is_active, available <= Part.reorder_threshold)
            .order_by(available.asc(), Part.name).limit(6)
        ).all()
        extras = {
            "low_stock": [{"id": r.id, "sku": r.sku, "name": r.name, "available": r.available, "threshold": r.reorder_threshold} for r in low],
            "trend": _trend(movements=_series(db, InventoryMovement.created_at, func.count())),
        }
    else:
        by_role = dict(db.execute(select(Role.code, func.count(User.id)).outerjoin(User, and_(User.role_id == Role.id, User.is_active)).group_by(Role.code)).all())
        cards = {
            "active_users": sum(by_role.values()),
            "users_by_role": by_role,
            "vehicle_models": _count(db, VehicleModel, VehicleModel.is_active),
            "parts": _count(db, Part, Part.is_active),
            "labour_operations": _count(db, LabourOperation, LabourOperation.is_active),
            "tax_rates": _count(db, TaxRate, TaxRate.is_active),
            "audit_entries_today": _count(db, AuditLog, AuditLog.created_at >= today_start),
            "delivery_backlog": _count(db, DeliveryJob, DeliveryJob.status.in_(ACTIVE_DELIVERY_STATUSES)),
        }
        extras = {"trend": _trend(audit=_series(db, AuditLog.created_at, func.count()))}
    return {"role": role, "generated_at": utcnow(), "cards": cards, **extras}
