"""Customer messages: invoice delivery (secure links, the durable outbox and its processing) and
WhatsApp payment-due / service-due reminders, which use the same outbox.

Flow
----
1. `billing.finalise` calls `issue_link` + `enqueue` inside the finalisation transaction, which
   writes one delivery_jobs row per channel (the outbox). No provider is contacted there.
2. A worker calls `run_once`, which claims due rows (FOR UPDATE SKIP LOCKED), marks them QUEUED
   and commits, then sends each one outside any lock and records the outcome.
3. Email, SMS and WhatsApp are separate rows processed independently: one failing never affects
   the others. Reminders (queued by app.services.reminders) are further rows with their own `kind`.

Statuses: provider acceptance => SENT. DELIVERED is set only by a verified receipt callback.
"""
import logging
import uuid
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.errors import DomainError, bad_request, not_found
from app.core.security import new_public_id, sign_link_token
from app.core.utils import format_inr, is_valid_email, normalise_indian_mobile, utcnow
from app.integrations import registry
from app.integrations.base import EmailContent, ProviderConfigError, SendResult, SmsContent, WhatsAppContent
from app.models import (
    CommunicationAttempt,
    Customer,
    DeliveryJob,
    Invoice,
    InvoiceLink,
    ServiceJob,
    User,
    WebhookEvent,
)
from app.models.enums import (
    ACTIVE_DELIVERY_STATUSES,
    AttemptOutcome,
    Channel,
    DeliveryKind,
    DeliveryStatus,
    InvoiceStatus,
    JobStatus,
    RoleCode,
)
from app.services import settings as settings_service
from app.services.common import audit, notify_role
from app.services.invoice_pdf import render_invoice_pdf

log = logging.getLogger("fsc.delivery")
CLAIM_TIMEOUT = timedelta(minutes=5)
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
CHANNEL_NAMES = {Channel.EMAIL: "email", Channel.SMS: "sms", Channel.WHATSAPP: "WhatsApp"}

# Suggested texts for the WhatsApp templates to submit in WhatsApp Manager, with {{n}} = the n-th
# value this module sends. The real text is whatever Meta approved; the simulator renders these so
# a developer can see roughly what the customer will read. The invoice template also needs a
# DOCUMENT header, which carries the PDF.
WHATSAPP_TEMPLATE_TEXT = {
    DeliveryKind.INVOICE: (
        "Hello {{1}}, thank you for choosing {{6}}. Your service invoice {{2}} for vehicle {{3}} is attached "
        "(total Rs. {{4}}). You can also view it online: {{5}} For any questions, please call the service centre."
    ),
    DeliveryKind.PAYMENT_REMINDER: (
        "Hello {{1}}, this is a reminder from {{6}}: a balance of Rs. {{4}} is due on invoice {{2}} for vehicle {{3}}. "
        "View the invoice: {{5}} Please ignore this message if you have already paid."
    ),
    DeliveryKind.SERVICE_REMINDER: (
        "Hello {{1}}, your vehicle {{2}} ({{3}}) is due for its next periodic service on {{4}}. "
        "Please contact {{5}} to book a convenient time."
    ),
}


@lru_cache
def _templates() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html"]), keep_trailing_newline=True
    )


# --- Secure links -----------------------------------------------------------------------


def issue_link(db: Session, inv: Invoice, user: User | None) -> InvoiceLink:
    days = int(settings_service.get(db, "invoice_link_expiry_days"))
    link = InvoiceLink(
        public_id=new_public_id(), expires_at=utcnow() + timedelta(days=days),
        created_by_id=user.id if user else None,
    )
    inv.links.append(link)  # the relationship sets invoice_id and adds it to the session
    db.flush()
    return link


def revoke_links(db: Session, inv: Invoice) -> int:
    count = 0
    for link in inv.links:
        if link.revoked_at is None:
            link.revoked_at = utcnow()
            count += 1
    return count


def usable_link(inv: Invoice) -> InvoiceLink | None:
    return next((l for l in reversed(inv.links) if l.is_usable()), None)


def link_url(db: Session, link: InvoiceLink) -> str:
    return f"{settings_service.public_base_url(db)}/i/{sign_link_token(link.public_id)}"


def reissue_link(db: Session, inv: Invoice, user: User) -> InvoiceLink:
    if inv.status != InvoiceStatus.FINALISED:
        raise DomainError("Links can be issued only for finalised invoices")
    revoked = revoke_links(db, inv)
    link = issue_link(db, inv, user)
    audit(db, user, "invoice.link_reissue", "invoice", inv.id, f"Reissued link for {inv.invoice_number}", {"revoked": revoked})
    return link


# --- Outbox -----------------------------------------------------------------------------


def _customer(job: DeliveryJob) -> Customer:
    return job.invoice.customer if job.invoice is not None else job.vehicle.customer


def _destination(customer: Customer, channel: str) -> tuple[str, str | None, bool]:
    """Returns (destination, problem, skipped). Uses the customer's current contact details so a
    corrected address is picked up by retries and resends."""
    if channel == Channel.EMAIL:
        if not customer.email_opt_in:
            return customer.email or "", "Customer has opted out of email", True
        if not customer.email:
            return "", "Customer has no email address on record", False
        if not is_valid_email(customer.email):
            return customer.email, "Customer email address is invalid", False
        return customer.email.strip(), None, False
    if channel == Channel.WHATSAPP and not customer.whatsapp_opt_in:
        return customer.mobile or "", "Customer has opted out of WhatsApp", True
    if channel == Channel.SMS and not customer.sms_opt_in:
        return customer.mobile or "", "Customer has opted out of SMS", True
    mobile = normalise_indian_mobile(customer.mobile)
    if mobile is None:
        return customer.mobile or "", "Customer mobile number is missing or not a valid Indian mobile number", False
    return mobile, None, False


def _notify_failure(db: Session, job: DeliveryJob) -> None:
    if job.kind == DeliveryKind.SERVICE_REMINDER:
        vehicle = job.vehicle
        notify_role(
            db, RoleCode.SERVICE_MANAGER, "SERVICE_REMINDER_FAILED",
            f"Service reminder failed: {vehicle.registration_number}", job.last_error or "", "vehicle", vehicle.id,
        )
        return
    inv = job.invoice
    if job.kind == DeliveryKind.PAYMENT_REMINDER:
        kind, title = "PAYMENT_REMINDER_FAILED", f"Payment reminder failed: {inv.invoice_number}"
    else:
        kind, title = f"INVOICE_{job.channel}_FAILED", f"Invoice {CHANNEL_NAMES[job.channel]} failed: {inv.invoice_number}"
    notify_role(db, RoleCode.SERVICE_MANAGER, kind, title, job.last_error or "", "invoice", inv.id)


def enabled_channels() -> tuple[str, ...]:
    from app.core.config import get_settings

    s = get_settings()
    return (Channel.EMAIL,) + ((Channel.SMS,) if s.sms_enabled else ()) + ((Channel.WHATSAPP,) if s.whatsapp_enabled else ())


def _require_enabled(channel: str) -> None:
    if channel not in enabled_channels():
        if channel == Channel.WHATSAPP:
            raise DomainError("WhatsApp is turned off for this service centre")
        raise DomainError("SMS is turned off for this service centre; invoices are sent by email only")


def _add_job(
    db: Session, customer: Customer, channel: str, kind: str, trigger: str, user: User | None, **subject
) -> DeliveryJob:
    """One outbox row. `subject` is invoice + link, or vehicle + service_job for a service reminder."""
    destination, problem, skipped = _destination(customer, channel)
    job = DeliveryJob(
        kind=kind, channel=channel, destination=destination, trigger=trigger,
        max_attempts=int(settings_service.get(db, "delivery_max_attempts")),
        idempotency_key=uuid.uuid4().hex, requested_by_id=user.id if user else None,
        next_attempt_at=utcnow(), **subject,
    )
    if problem:
        job.status = DeliveryStatus.SKIPPED if skipped else DeliveryStatus.FAILED
        job.last_error = problem
    db.add(job)
    db.flush()
    if problem and not skipped:
        _notify_failure(db, job)
    return job


def enqueue(
    db: Session, inv: Invoice, link: InvoiceLink, user: User | None, trigger: str,
    channels: tuple[str, ...] | None = None,
) -> list[DeliveryJob]:
    return [
        _add_job(db, inv.customer, channel, DeliveryKind.INVOICE, trigger, user, invoice=inv, link=link)
        for channel in channels or enabled_channels()
    ]


def enqueue_payment_reminder(db: Session, inv: Invoice, user: User | None, trigger: str) -> DeliveryJob:
    link = usable_link(inv) or issue_link(db, inv, user)
    return _add_job(db, inv.customer, Channel.WHATSAPP, DeliveryKind.PAYMENT_REMINDER, trigger, user, invoice=inv, link=link)


def enqueue_service_reminder(db: Session, visit: ServiceJob) -> DeliveryJob:
    """Reminder that the vehicle's next service is due, counted from `visit` (its latest visit)."""
    vehicle = visit.vehicle
    return _add_job(
        db, vehicle.customer, Channel.WHATSAPP, DeliveryKind.SERVICE_REMINDER, "AUTO", None, vehicle=vehicle, service_job=visit,
    )


def service_due_on(db: Session, visit: ServiceJob) -> date:
    interval = int(settings_service.get(db, "service_interval_days"))
    return visit.visit_at.astimezone(settings_service.INDIA).date() + timedelta(days=interval)


def _build_email(db: Session, job: DeliveryJob) -> EmailContent:
    from app.core.config import get_settings

    inv, link = job.invoice, job.link
    centre = inv.centre or {}
    context = {
        "centre_name": centre.get("name", ""), "centre_address": centre.get("address", ""),
        "centre_phone": centre.get("phone", ""), "centre_email": centre.get("email", ""),
        "customer_name": inv.customer_name, "registration": inv.vehicle_registration,
        "vehicle_model": inv.vehicle_model, "job_number": inv.job_number,
        "invoice_number": inv.invoice_number, "total": format_inr(inv.total),
        "amount_paid": format_inr(inv.amount_paid), "outstanding": format_inr(inv.outstanding),
        "link_url": link_url(db, link), "link_expires": f"{link.expires_at:%d %b %Y}",
    }
    env = _templates()
    return EmailContent(
        to_address=job.destination, to_name=inv.customer_name,
        subject=f"Your Vehicle Service Invoice - {inv.job_number}",
        text_body=env.get_template("invoice_email.txt").render(**context),
        html_body=env.get_template("invoice_email.html").render(**context),
        sender_address=get_settings().email_sender_address or centre.get("email", "") or "no-reply@localhost",
        sender_name=settings_service.get(db, "email_sender_name") or centre.get("name", ""),
        attachments=[(f"{inv.invoice_number}.pdf", render_invoice_pdf(inv), "application/pdf")],
    )


def _build_sms(db: Session, job: DeliveryJob) -> SmsContent:
    inv = job.invoice
    centre_name = (inv.centre or {}).get("name", "")
    url = link_url(db, job.link)
    amount = format_inr(inv.total)
    body = (
        f"Your vehicle service invoice {inv.invoice_number} for vehicle {inv.vehicle_registration} "
        f"has been generated. Total: INR {amount}. View your invoice securely: {url} "
        f"Thank you for choosing {centre_name}."
    )
    s = settings_service.get_all(db)
    return SmsContent(
        to_e164=job.destination, body=body,
        variables={"invoice_number": inv.invoice_number, "registration": inv.vehicle_registration,
                   "amount": amount, "url": url, "centre": centre_name},
        sender_id=s["sms_sender_id"], template_id=s["sms_template_id"], dlt_entity_id=s["sms_dlt_entity_id"],
    )


def _whatsapp_param(value) -> str:
    """WhatsApp rejects empty template values and ones with new lines, tabs or runs of spaces."""
    return " ".join(str(value or "").split())[:1000] or "-"


def _build_whatsapp(db: Session, job: DeliveryJob) -> WhatsAppContent:
    s = settings_service.get_all(db)
    centre = str(s["centre_name"]).strip()
    document = None
    if job.kind == DeliveryKind.SERVICE_REMINDER:
        vehicle = job.vehicle
        template = s["whatsapp_service_reminder_template"]
        due = service_due_on(db, job.service_job)
        params = [vehicle.customer.name, vehicle.registration_number, vehicle.model.name, f"{due:%d %b %Y}", centre]
    else:
        inv = job.invoice
        if job.kind == DeliveryKind.PAYMENT_REMINDER:
            template, amount = s["whatsapp_payment_reminder_template"], inv.outstanding
        else:
            template, amount = s["whatsapp_invoice_template"], inv.total
            document = (f"{inv.invoice_number}.pdf", render_invoice_pdf(inv))
        params = [inv.customer_name, inv.invoice_number, inv.vehicle_registration, format_inr(amount), link_url(db, job.link), centre]
    params = [_whatsapp_param(p) for p in params]
    body = WHATSAPP_TEMPLATE_TEXT[job.kind]
    for n, value in enumerate(params, 1):
        body = body.replace("{{%d}}" % n, value)
    return WhatsAppContent(
        to_e164=job.destination, template_name=str(template), language=str(s["whatsapp_template_language"]),
        body_params=params, body=body, document=document,
    )


def _send(db: Session, job: DeliveryJob) -> tuple[SendResult, str, bool, bool]:
    """Returns (result, provider name, receipts supported, simulated)."""
    if job.kind != DeliveryKind.SERVICE_REMINDER and (job.link is None or not job.link.is_usable()):
        return SendResult(False, error="The invoice link has expired or was revoked; resend to issue a new link", permanent=True), "", False, False
    try:
        if job.channel == Channel.EMAIL:
            provider = registry.get_email_provider()
            content = _build_email(db, job)
        elif job.channel == Channel.SMS:
            provider = registry.get_sms_provider()
            content = _build_sms(db, job)
        else:
            provider = registry.get_whatsapp_provider()
            content = _build_whatsapp(db, job)
    except ProviderConfigError as exc:
        return SendResult(False, error=str(exc), permanent=True), "", False, False
    try:
        result = provider.send(content, job.idempotency_key)
    except ProviderConfigError as exc:
        result = SendResult(False, error=str(exc), permanent=True)
    except Exception as exc:  # noqa: BLE001 - a provider bug must not kill the worker
        log.exception("Provider %s raised while sending delivery job %s", provider.name, job.id)
        result = SendResult(False, error=f"Unexpected provider error ({type(exc).__name__})")
    return result, provider.name, provider.supports_receipts, provider.simulated


def claim_due(db: Session, limit: int = 20) -> list[int]:
    now = utcnow()
    due = db.scalars(
        select(DeliveryJob)
        .where(
            or_(
                and_(
                    DeliveryJob.status.in_((DeliveryStatus.PENDING, DeliveryStatus.RETRY_SCHEDULED)),
                    DeliveryJob.next_attempt_at <= now,
                ),
                # A worker died mid-send: reclaim after the claim times out.
                and_(DeliveryJob.status == DeliveryStatus.QUEUED, DeliveryJob.locked_until < now),
            )
        )
        .order_by(DeliveryJob.next_attempt_at)
        .limit(limit)
        .with_for_update(skip_locked=True, of=DeliveryJob)
    ).all()
    for job in due:
        job.status = DeliveryStatus.QUEUED
        job.locked_until = now + CLAIM_TIMEOUT
    ids = [j.id for j in due]
    db.commit()
    return ids


def _reminder_not_needed(db: Session, job: DeliveryJob) -> str | None:
    """Why a queued reminder should no longer go out, if it should not."""
    if job.kind == DeliveryKind.PAYMENT_REMINDER:
        if job.invoice.status != InvoiceStatus.FINALISED:
            return "Not sent: the invoice was cancelled"
        if job.invoice.outstanding <= 0:
            return "Not sent: the invoice has been paid"
    elif job.kind == DeliveryKind.SERVICE_REMINDER:
        visit = job.service_job
        newer = db.scalar(
            select(ServiceJob.id).where(
                ServiceJob.vehicle_id == job.vehicle_id, ServiceJob.id != visit.id,
                ServiceJob.visit_at >= visit.visit_at, ServiceJob.status != JobStatus.CANCELLED,
            ).limit(1)
        )
        if newer is not None:
            return "Not sent: the vehicle has visited again"
    return None


def process_job(db: Session, job_id: int) -> None:
    job = db.get(DeliveryJob, job_id)
    if job is None or job.status != DeliveryStatus.QUEUED:
        return
    reason = _reminder_not_needed(db, job)
    if reason:
        job.status, job.locked_until, job.last_error = DeliveryStatus.CANCELLED, None, reason
        db.commit()
        return
    started = utcnow()
    if job.kind == DeliveryKind.INVOICE and job.invoice.status != InvoiceStatus.FINALISED:
        result, provider, receipts, simulated = SendResult(False, error="Invoice is no longer valid", permanent=True), "", False, False
    else:
        result, provider, receipts, simulated = _send(db, job)
    db.rollback()  # nothing to persist from the send phase; start a clean transaction

    job = db.execute(select(DeliveryJob).where(DeliveryJob.id == job_id).with_for_update(of=DeliveryJob)).scalar_one()
    job.attempt_count += 1
    job.last_attempt_at = utcnow()
    job.locked_until = None
    job.provider = provider or job.provider
    if result.accepted:
        outcome = AttemptOutcome.ACCEPTED
        job.status = DeliveryStatus.SENT
        job.sent_at = utcnow()
        job.provider_message_id = result.message_id
        job.receipts_supported, job.simulated = receipts, simulated
        job.last_error = None
    elif result.permanent or job.attempt_count >= job.max_attempts:
        outcome = AttemptOutcome.PERMANENT_FAILURE if result.permanent else AttemptOutcome.TEMPORARY_FAILURE
        job.status = DeliveryStatus.FAILED
        job.last_error = result.error
        if not result.permanent:
            job.last_error = f"{result.error} (gave up after {job.attempt_count} attempts)"
        _notify_failure(db, job)
    else:
        outcome = AttemptOutcome.TEMPORARY_FAILURE
        base = int(settings_service.get(db, "delivery_backoff_base_seconds"))
        delay = min(base * 2 ** (job.attempt_count - 1), 6 * 3600)  # exponential backoff, capped
        job.status = DeliveryStatus.RETRY_SCHEDULED
        job.next_attempt_at = utcnow() + timedelta(seconds=delay)
        job.last_error = result.error
    db.add(
        CommunicationAttempt(
            delivery_job_id=job.id, attempt_number=job.attempt_count, started_at=started, outcome=outcome,
            provider=provider, provider_message_id=result.message_id, error=result.error,
        )
    )
    db.commit()


def run_once(session_factory, limit: int = 20) -> int:
    """Claim and process due delivery jobs. Returns how many were processed."""
    with session_factory() as db:
        ids = claim_due(db, limit)
    for job_id in ids:
        try:
            with session_factory() as db:
                process_job(db, job_id)
        except Exception:  # noqa: BLE001 - keep going; the claim timeout will retry this job
            log.exception("Failed to process delivery job %s", job_id)
    return len(ids)


# --- Manual retry / resend --------------------------------------------------------------


def get_delivery_job(db: Session, job_id: int, lock: bool = False) -> DeliveryJob:
    stmt = select(DeliveryJob).where(DeliveryJob.id == job_id)
    if lock:
        stmt = stmt.with_for_update(of=DeliveryJob).execution_options(populate_existing=True)
    job = db.execute(stmt).scalar_one_or_none()
    if job is None:
        raise not_found("Delivery record")
    return job


def _check_manual_rate(db: Session, inv: Invoice, channel: str, kind: str = DeliveryKind.INVOICE) -> None:
    limit = int(settings_service.get(db, "manual_resend_limit_per_hour"))
    same = (DeliveryJob.invoice_id == inv.id, DeliveryJob.channel == channel, DeliveryJob.kind == kind, DeliveryJob.trigger == "MANUAL")
    recent = db.scalar(
        select(func.count()).select_from(CommunicationAttempt).join(DeliveryJob)
        .where(*same, CommunicationAttempt.started_at > utcnow() - timedelta(hours=1))
    )
    queued = db.scalar(
        select(func.count()).select_from(DeliveryJob).where(*same, DeliveryJob.status.in_(ACTIVE_DELIVERY_STATUSES))
    )
    if recent + queued >= limit:
        what = f"manual {channel} sends" if kind == DeliveryKind.INVOICE else "manual payment reminders"
        raise DomainError(f"Resend limit reached: at most {limit} {what} per invoice per hour", code=429)


def _ensure_no_active(db: Session, inv: Invoice, channel: str, kind: str = DeliveryKind.INVOICE) -> None:
    active = db.scalar(
        select(func.count()).select_from(DeliveryJob).where(
            DeliveryJob.invoice_id == inv.id, DeliveryJob.channel == channel, DeliveryJob.kind == kind,
            DeliveryJob.status.in_(ACTIVE_DELIVERY_STATUSES),
        )
    )
    if active:
        what = f"{channel} delivery" if kind == DeliveryKind.INVOICE else "payment reminder"
        raise DomainError(f"A {what} for this invoice is already in progress")


def resend(db: Session, invoice_id: int, channel: str, user: User, confirm: bool) -> DeliveryJob:
    """Send the invoice again on one channel only. The other channel is untouched."""
    from app.services.billing import get_invoice

    if not confirm:
        raise bad_request("Resending must be explicitly confirmed")
    _require_enabled(channel)
    inv = get_invoice(db, invoice_id, lock=True)  # serialises concurrent resend clicks
    if inv.status != InvoiceStatus.FINALISED:
        raise DomainError("Only finalised invoices can be sent to customers")
    _ensure_no_active(db, inv, channel)
    _check_manual_rate(db, inv, channel)
    link = usable_link(inv) or issue_link(db, inv, user)
    job = enqueue(db, inv, link, user, trigger="MANUAL", channels=(channel,))[0]
    audit(db, user, "delivery.resend", "invoice", inv.id, f"Resent {inv.invoice_number} by {channel}", {"delivery_job_id": job.id})
    return job


def send_payment_reminder(db: Session, invoice_id: int, user: User) -> DeliveryJob:
    """Send a WhatsApp payment reminder now, for an invoice with an outstanding balance."""
    from app.services.billing import get_invoice

    _require_enabled(Channel.WHATSAPP)
    inv = get_invoice(db, invoice_id, lock=True)  # serialises concurrent clicks
    if inv.status != InvoiceStatus.FINALISED:
        raise DomainError("Only finalised invoices can be sent to customers")
    if inv.outstanding <= 0:
        raise DomainError("This invoice has no outstanding balance")
    _ensure_no_active(db, inv, Channel.WHATSAPP, DeliveryKind.PAYMENT_REMINDER)
    _check_manual_rate(db, inv, Channel.WHATSAPP, DeliveryKind.PAYMENT_REMINDER)
    job = enqueue_payment_reminder(db, inv, user, trigger="MANUAL")
    audit(db, user, "delivery.payment_reminder", "invoice", inv.id, f"Sent payment reminder for {inv.invoice_number}", {"delivery_job_id": job.id})
    return job


def retry(db: Session, job_id: int, user: User) -> DeliveryJob:
    """Retry a FAILED delivery. Re-reads the customer's contact details and link first."""
    from app.services.billing import get_invoice

    existing = get_delivery_job(db, job_id)
    _require_enabled(existing.channel)
    inv = get_invoice(db, existing.invoice_id, lock=True) if existing.invoice_id else None
    job = get_delivery_job(db, job_id, lock=True)
    if job.status != DeliveryStatus.FAILED:
        raise DomainError("Only a failed delivery can be retried")
    if inv is not None and inv.status != InvoiceStatus.FINALISED:
        raise DomainError("Only finalised invoices can be sent to customers")
    destination, problem, _ = _destination(_customer(job), job.channel)
    if problem:
        raise DomainError(f"{problem}. Correct the customer's contact details first.")
    if inv is not None and (job.link is None or not job.link.is_usable()):
        job.link = usable_link(inv) or issue_link(db, inv, user)
    job.destination = destination
    job.status = DeliveryStatus.PENDING
    job.next_attempt_at = utcnow()
    job.max_attempts = job.attempt_count + int(settings_service.get(db, "delivery_max_attempts"))
    job.last_error = None
    if inv is not None:
        audit(db, user, "delivery.retry", "invoice", inv.id, f"Retried {job.channel} delivery of {inv.invoice_number}", {"delivery_job_id": job.id})
    else:
        audit(db, user, "delivery.retry", "vehicle", job.vehicle_id, f"Retried service reminder for {job.vehicle.registration_number}", {"delivery_job_id": job.id})
    return job


# --- Provider delivery receipts ---------------------------------------------------------


def handle_receipt(
    db: Session, provider: str, event_id: str, provider_message_id: str, status: str,
    error: str | None, payload: dict,
) -> str:
    """Apply a verified provider callback. Returns 'applied', 'duplicate' or 'ignored'."""
    inserted = db.execute(
        pg_insert(WebhookEvent)
        .values(provider=provider, event_id=event_id, payload=payload, received_at=utcnow())
        .on_conflict_do_nothing(index_elements=["provider", "event_id"])
        .returning(WebhookEvent.id)
    ).scalar_one_or_none()
    if inserted is None:
        return "duplicate"
    job = db.execute(
        select(DeliveryJob)
        .where(DeliveryJob.provider_message_id == provider_message_id, DeliveryJob.provider == provider)
        .with_for_update(of=DeliveryJob)
    ).scalar_one_or_none()
    if job is None:
        return "ignored"
    if status == "delivered":
        if job.status in (DeliveryStatus.SENT, DeliveryStatus.DELIVERED):
            job.status, job.delivered_at, job.last_error = DeliveryStatus.DELIVERED, job.delivered_at or utcnow(), None
    elif status == "failed":
        if job.status == DeliveryStatus.SENT:
            job.status = DeliveryStatus.FAILED
            job.last_error = (error or "The provider reported that delivery failed")[:500]
            _notify_failure(db, job)
    else:
        return "ignored"
    return "applied"
