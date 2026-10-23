"""Automatic WhatsApp reminders: payment due on unpaid invoices, and the next periodic service.

`run_once` is called by the delivery worker every few minutes. It only queues delivery_jobs rows
(kind PAYMENT_REMINDER / SERVICE_REMINDER); the outbox then sends them like invoice messages, with
the same retries, failure notifications and history. Just before sending, a reminder that is no
longer needed (invoice paid, vehicle back in the workshop) is cancelled instead.

Several workers are safe: a PostgreSQL advisory lock lets only one of them schedule at a time.

Timings come from Admin > Settings:
- payment: first reminder `payment_reminder_after_days` after the invoice, then every
  `payment_reminder_every_days`, at most `payment_reminder_max` automatic ones per invoice.
- service: `service_reminder_days_before` the vehicle's due date, which is
  `service_interval_days` after its latest visit (the same rule as the dealer dashboard). One
  reminder per visit, and none while the vehicle has an open job.
"""
import logging
from datetime import timedelta

from sqlalchemy import exists, func, or_, select, text
from sqlalchemy.orm import Session, aliased

from app.core.config import get_settings
from app.core.utils import utcnow
from app.models import DeliveryJob, Invoice, ServiceJob, Vehicle
from app.models.enums import CLOSED_JOB_STATUSES, DeliveryKind, DeliveryStatus, InvoiceStatus, JobStatus
from app.services import delivery
from app.services import settings as settings_service

log = logging.getLogger("fsc.reminders")

LOCK_KEY = 7_316_002  # arbitrary, unique to this job
BATCH = 200  # reminders queued per run; the rest follow on the next run
# When reminders are first switched on, invoices and vehicles that were already well past their
# reminder date are left to the staff instead of all being messaged at once.
FIRST_REMINDER_GRACE = timedelta(days=14)
SERVICE_OVERDUE_GRACE = timedelta(days=30)


def schedule(db: Session) -> int:
    """Queue the reminders that are due now. Returns how many were queued. The caller commits."""
    if not get_settings().whatsapp_enabled:
        return 0
    if not db.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": LOCK_KEY}).scalar():
        return 0  # another worker is scheduling
    s = settings_service.get_all(db)
    queued = 0
    if s["payment_reminder_enabled"]:
        queued += _payment_reminders(db, s)
    if s["service_reminder_enabled"]:
        queued += _service_reminders(db, s)
    return queued


def _payment_reminders(db: Session, s: dict) -> int:
    now = utcnow()
    after = timedelta(days=int(s["payment_reminder_after_days"]))
    R = aliased(DeliveryJob)
    mine = (R.invoice_id == Invoice.id, R.kind == DeliveryKind.PAYMENT_REMINDER, R.status != DeliveryStatus.CANCELLED)
    auto_count = select(func.count()).where(*mine, R.trigger == "AUTO").scalar_subquery()
    last_sent = select(func.max(R.created_at)).where(*mine).scalar_subquery()
    invoices = db.scalars(
        select(Invoice).where(
            Invoice.status == InvoiceStatus.FINALISED,
            Invoice.total > Invoice.amount_paid,
            Invoice.finalised_at <= now - after,
            auto_count < int(s["payment_reminder_max"]),
            # Manual reminders also reset the clock, so the customer is not messaged twice in a row.
            or_(last_sent.is_(None), last_sent <= now - timedelta(days=int(s["payment_reminder_every_days"]))),
            or_(auto_count > 0, Invoice.finalised_at >= now - after - FIRST_REMINDER_GRACE),
        ).order_by(Invoice.id).limit(BATCH)
    ).all()
    for inv in invoices:
        delivery.enqueue_payment_reminder(db, inv, None, trigger="AUTO")
    return len(invoices)


def _service_reminders(db: Session, s: dict) -> int:
    now = utcnow()
    interval = timedelta(days=int(s["service_interval_days"]))
    before = timedelta(days=int(s["service_reminder_days_before"]))
    J, Other = ServiceJob, aliased(ServiceJob)
    latest = (
        select(J.id, J.vehicle_id, J.visit_at,
               func.row_number().over(partition_by=J.vehicle_id, order_by=(J.visit_at.desc(), J.id.desc())).label("rn"))
        .where(J.status != JobStatus.CANCELLED).subquery()
    )
    open_job = exists().where(Other.vehicle_id == latest.c.vehicle_id, Other.status.notin_(CLOSED_JOB_STATUSES))
    reminded = exists().where(DeliveryJob.service_job_id == latest.c.id, DeliveryJob.kind == DeliveryKind.SERVICE_REMINDER)
    visit_ids = db.scalars(
        select(latest.c.id).join(Vehicle, Vehicle.id == latest.c.vehicle_id).where(
            latest.c.rn == 1, Vehicle.is_active.is_(True), ~open_job, ~reminded,
            latest.c.visit_at <= now - interval + before,  # due date is within `before` days
            latest.c.visit_at >= now - interval - SERVICE_OVERDUE_GRACE,
        ).order_by(latest.c.id).limit(BATCH)
    ).all()
    for visit in db.scalars(select(ServiceJob).where(ServiceJob.id.in_(visit_ids))):
        delivery.enqueue_service_reminder(db, visit)
    return len(visit_ids)


def run_once(session_factory) -> int:
    with session_factory() as db:
        queued = schedule(db)
        db.commit()
    if queued:
        log.info("Queued %d WhatsApp reminder(s)", queued)
    return queued
