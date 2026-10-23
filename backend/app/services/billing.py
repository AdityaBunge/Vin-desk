"""Invoices and payments.

A draft invoice is built from *approved labour* and *parts actually consumed* (never from the
quantities originally requested). Finalisation is one transaction that freezes the invoice,
allocates its number, issues the customer link and writes the email + SMS outbox rows; no
provider is contacted inside it.
"""
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError, bad_request, not_found
from app.core.utils import ZERO, money, utcnow
from app.models import Invoice, InvoiceLine, Payment, ServiceJob, TaxRate, User
from app.models.enums import (
    ApprovalStatus,
    DeliveryStatus,
    InvoiceStatus,
    JobStatus,
    LineType,
    PaymentStatus,
)
from app.services import jobs as jobs_service
from app.services import settings as settings_service
from app.services.common import audit, next_number
from app.services.estimates import calc_line, check_discount


def billing_blockers(job: ServiceJob) -> list[str]:
    """Reasons the job cannot be invoiced yet (empty list = ready)."""
    blockers: list[str] = []
    if job.status != JobStatus.READY_FOR_BILLING:
        blockers.append(f"Job status is {jobs_service.LABEL[JobStatus(job.status)]}, not Ready For Billing")
    if not job.completions:
        blockers.append("The mechanic has not recorded work completion")
    if jobs_service.spare_parts_list_pending(job):
        blockers.append("The mechanic's spare parts list has not been confirmed as available by inventory")
    pending = jobs_service.pending_approval_items(job)
    if pending:
        blockers.append("Customer approval is pending for: " + ", ".join(pending))
    for line in jobs_service.active_part_lines(job):
        if line.qty_outstanding > 0:
            blockers.append(f"{line.part.sku}: {line.qty_outstanding} still outstanding")
        if line.qty_issued > 0 and line.qty_consumed is None:
            blockers.append(f"{line.part.sku}: quantity consumed has not been recorded")
        elif line.qty_unreconciled != 0:
            blockers.append(
                f"{line.part.sku}: {line.qty_unreconciled} issued but neither used nor returned to stock"
            )
        if line.qty_reserved > 0:
            blockers.append(f"{line.part.sku}: {line.qty_reserved} still reserved")
    return blockers


def recalculate(inv: Invoice) -> None:
    labour = parts = discount = tax = total = ZERO
    for line in inv.lines:
        gross, line.tax_amount, line.line_total = calc_line(
            line.quantity, line.unit_price, line.discount_amount, line.tax_rate
        )
        if line.line_type == LineType.LABOUR:
            labour += gross
        else:
            parts += gross
        discount += line.discount_amount
        tax += line.tax_amount
        total += line.line_total
    inv.subtotal_labour, inv.subtotal_parts, inv.discount_total = labour, parts, discount
    inv.taxable_total = labour + parts - discount
    # Indian tax invoices are payable in whole rupees; the difference is shown as "Round Off".
    rounded = money(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    inv.tax_total, inv.total, inv.round_off = tax, rounded, rounded - total


def tax_breakdown(inv: Invoice) -> list[dict]:
    groups: dict[tuple[str, Decimal], dict] = {}
    for line in inv.lines:
        key = (line.tax_name, line.tax_rate)
        g = groups.setdefault(key, {"name": line.tax_name, "rate": line.tax_rate, "taxable": ZERO, "tax": ZERO})
        g["taxable"] += line.line_total - line.tax_amount
        g["tax"] += line.tax_amount
    split = bool((inv.centre or {}).get("gst_split_intra_state", True))
    rows = []
    for g in sorted(groups.values(), key=lambda r: r["rate"]):
        row = dict(g)
        if split and g["tax"] > 0:
            row["cgst"] = money(g["tax"] / 2)
            row["sgst"] = g["tax"] - row["cgst"]
        rows.append(row)
    return rows


def hsn_summary(inv: Invoice) -> list[dict]:
    """GST summary grouped by HSN/SAC code and rate, as printed on Indian tax invoices."""
    groups: dict[tuple[str, Decimal], dict] = {}
    for line in inv.lines:
        key = (line.hsn_code or "", line.tax_rate)
        g = groups.setdefault(key, {"hsn_code": key[0], "rate": line.tax_rate, "taxable": ZERO, "tax": ZERO})
        g["taxable"] += line.line_total - line.tax_amount
        g["tax"] += line.tax_amount
    split = bool((inv.centre or {}).get("gst_split_intra_state", True))
    rows = []
    for g in sorted(groups.values(), key=lambda r: (r["hsn_code"] != "", r["hsn_code"], r["rate"])):
        row = dict(g)
        if split:
            row["cgst_rate"] = row["sgst_rate"] = g["rate"] / 2
            row["cgst"] = money(g["tax"] / 2)
            row["sgst"] = g["tax"] - row["cgst"]
        rows.append(row)
    return rows


def _snapshot(db: Session, inv: Invoice, job: ServiceJob) -> None:
    customer, vehicle = job.customer, job.vehicle
    inv.customer_name = customer.name
    inv.customer_gstin = customer.gstin
    inv.customer_email = customer.email
    inv.customer_mobile = customer.mobile
    inv.billing_address = customer.billing_address
    inv.vehicle_registration = vehicle.registration_number
    inv.vehicle_model = vehicle.model.name
    inv.job_number = job.job_number
    inv.centre = settings_service.centre_snapshot(db)


def _build_lines(inv: Invoice, job: ServiceJob) -> None:
    key = lambda l: (l.job_labour_id, l.parts_request_line_id, l.manual_part_id)  # noqa: E731
    previous_discounts = {key(l): l.discount_amount for l in inv.lines if not l.is_custom}
    previous_prices = {key(l): l.price_override for l in inv.lines if not l.is_custom and l.price_override is not None}
    custom = [l for l in inv.lines if l.is_custom]  # items the Service Manager added by hand
    # Rebuild only the lines that come from the job; the manager's own items stay attached
    # (detaching them would delete them, as invoice lines are delete-orphan).
    for line in [l for l in inv.lines if not l.is_custom]:
        inv.lines.remove(line)
    default_sac = (inv.centre or {}).get("default_labour_sac", "")
    order = 0
    for lab in job.labour:
        if lab.approval_status != ApprovalStatus.APPROVED:
            continue
        order += 1
        inv.lines.append(
            InvoiceLine(
                sort_order=order, line_type=LineType.LABOUR, job_labour_id=lab.id, code=lab.code,
                description=lab.description,
                hsn_code=(lab.labour_operation.sac_code if lab.labour_operation else "") or default_sac, unit="HRS",
                # Labour is billed at the hours the customer approved, not the hours taken.
                quantity=lab.estimated_hours, unit_price=lab.hourly_rate,
                discount_amount=previous_discounts.get((lab.id, None, None), ZERO),
                tax_name=lab.tax_rate.name if lab.tax_rate else "No tax",
                tax_rate=lab.tax_rate.rate if lab.tax_rate else ZERO,
            )
        )
    for line in jobs_service.active_part_lines(job):
        consumed = line.qty_consumed or ZERO
        if consumed <= 0:
            continue
        order += 1
        part = line.part
        inv.lines.append(
            InvoiceLine(
                sort_order=order, line_type=LineType.PART, parts_request_line_id=line.id, code=part.sku,
                description=part.name, hsn_code=part.hsn_code, unit=part.unit,
                quantity=consumed, unit_price=part.selling_price,
                discount_amount=previous_discounts.get((None, line.id, None), ZERO),
                tax_name=part.tax_rate.name if part.tax_rate else "No tax",
                tax_rate=part.tax_rate.rate if part.tax_rate else ZERO,
            )
        )
    # Parts from the written list that inventory confirmed: catalogue rate, or the price entered by hand.
    for mp in job.manual_parts:
        order += 1
        inv.lines.append(
            InvoiceLine(
                sort_order=order, line_type=LineType.PART, manual_part_id=mp.id, code=mp.part.sku if mp.part else "",
                description=mp.description, hsn_code=mp.hsn_code, unit=mp.unit,
                quantity=mp.quantity, unit_price=mp.unit_price,
                discount_amount=previous_discounts.get((None, None, mp.id), ZERO),
                tax_name=mp.tax_rate.name if mp.tax_rate else "No tax",
                tax_rate=mp.tax_rate.rate if mp.tax_rate else ZERO,
            )
        )
    for line in inv.lines:
        override = previous_prices.get(key(line))
        if override is not None:
            line.unit_price, line.price_override = override, override
    for line in custom:  # keep the manager's items after the job's lines
        order += 1
        line.sort_order = order
    inv.lines.sort(key=lambda l: l.sort_order)
    recalculate(inv)


def _draft(inv: Invoice) -> None:
    if inv.status != InvoiceStatus.DRAFT:
        raise DomainError("A finalised invoice cannot be modified. Cancel it and issue a corrected invoice.")


def add_custom_line(db: Session, inv: Invoice, user: User, data: dict) -> InvoiceLine:
    """The Service Manager adds an item to the draft bill by hand (e.g. a consumable or outside work)."""
    _draft(inv)
    tax = db.get(TaxRate, data["tax_rate_id"]) if data.get("tax_rate_id") else None
    if data.get("tax_rate_id") and tax is None:
        raise bad_request("Unknown tax rate")
    line = InvoiceLine(
        sort_order=max((l.sort_order for l in inv.lines), default=0) + 1, line_type=data["line_type"], code="",
        description=data["description"], hsn_code=data.get("hsn_code", ""), unit=data.get("unit") or "NO",
        quantity=data["quantity"], unit_price=data["unit_price"], discount_amount=ZERO,
        tax_name=tax.name if tax else "No tax", tax_rate=tax.rate if tax else ZERO, is_custom=True,
    )
    inv.lines.append(line)
    recalculate(inv)
    db.flush()
    audit(db, user, "invoice.line_add", "invoice", inv.id, f"Added '{line.description}' to the draft bill",
          {"quantity": str(line.quantity), "unit_price": str(line.unit_price)})
    return line


def edit_line(db: Session, inv: Invoice, user: User, line_id: int, data: dict) -> None:
    """Change the rate of any draft line; custom lines can also change description and quantity."""
    _draft(inv)
    line = next((l for l in inv.lines if l.id == line_id), None)
    if line is None:
        raise not_found("Invoice line")
    before = {"unit_price": str(line.unit_price), "quantity": str(line.quantity), "description": line.description}
    if data.get("unit_price") is not None:
        line.unit_price = money(data["unit_price"])
        if not line.is_custom:
            line.price_override = line.unit_price
    if line.is_custom:
        if data.get("quantity") is not None:
            line.quantity = data["quantity"]
        if data.get("description"):
            line.description = data["description"]
    elif data.get("quantity") is not None or data.get("description"):
        raise DomainError("Only the rate can be changed on items that come from the job")
    gross, _, _ = calc_line(line.quantity, line.unit_price, ZERO, ZERO)
    if line.discount_amount > gross:
        line.discount_amount = ZERO
    recalculate(inv)
    audit(db, user, "invoice.line_edit", "invoice", inv.id, f"Edited '{line.description}' on the draft bill",
          {"before": before, "after": {"unit_price": str(line.unit_price), "quantity": str(line.quantity)}})


def remove_custom_line(db: Session, inv: Invoice, user: User, line_id: int) -> None:
    _draft(inv)
    line = next((l for l in inv.lines if l.id == line_id), None)
    if line is None:
        raise not_found("Invoice line")
    if not line.is_custom:
        raise DomainError("Items that come from the job cannot be removed here; change the job instead")
    inv.lines.remove(line)
    db.delete(line)
    recalculate(inv)
    audit(db, user, "invoice.line_remove", "invoice", inv.id, f"Removed '{line.description}' from the draft bill")


def get_invoice(db: Session, invoice_id: int, lock: bool = False) -> Invoice:
    if lock:
        db.execute(select(Invoice.id).where(Invoice.id == invoice_id).with_for_update())
    inv = db.get(Invoice, invoice_id, populate_existing=lock)
    if inv is None:
        raise not_found("Invoice")
    return inv


def live_invoice(job: ServiceJob) -> Invoice | None:
    return next((i for i in job.invoices if i.status != InvoiceStatus.CANCELLED), None)


def prepare_draft(db: Session, job: ServiceJob, user: User) -> Invoice:
    """Create the draft invoice for a job, or rebuild the existing draft from current job data."""
    blockers = billing_blockers(job)
    if blockers:
        raise DomainError({"code": "BILLING_BLOCKED", "message": "The job is not ready for billing", "blockers": blockers})
    inv = live_invoice(job)
    if inv is not None and inv.status == InvoiceStatus.FINALISED:
        raise DomainError(f"Invoice {inv.invoice_number} is already finalised for this job")
    if inv is None:
        cancelled = [i for i in job.invoices if i.status == InvoiceStatus.CANCELLED]
        inv = Invoice(
            job_id=job.id, customer_id=job.customer_id, created_by_id=user.id,
            terms=settings_service.get(db, "invoice_terms"),
            replaces_invoice_id=cancelled[-1].id if cancelled else None,
        )
        db.add(inv)
        job.invoices.append(inv)
    _snapshot(db, inv, job)
    _build_lines(inv, job)
    db.flush()
    return inv


def update_draft(db: Session, inv: Invoice, user: User, notes, terms, discounts: list[dict] | None) -> Invoice:
    if inv.status != InvoiceStatus.DRAFT:
        raise DomainError("A finalised invoice cannot be modified. Cancel it and issue a corrected invoice.")
    if notes is not None:
        inv.notes = notes
    if terms is not None:
        inv.terms = terms
    by_id = {l.id: l for l in inv.lines}
    for item in discounts or []:
        line = by_id.get(item["line_id"])
        if line is None:
            raise bad_request("Unknown invoice line")
        gross, _, _ = calc_line(line.quantity, line.unit_price, ZERO, ZERO)
        check_discount(db, gross, money(item["discount_amount"]))
        line.discount_amount = money(item["discount_amount"])
    recalculate(inv)
    return inv


def finalise(db: Session, invoice_id: int, user: User) -> Invoice:
    from app.services import delivery  # local import: delivery renders invoices via this module

    inv = get_invoice(db, invoice_id, lock=True)
    if inv.status != InvoiceStatus.DRAFT:
        raise DomainError("Only a draft invoice can be finalised")
    job = jobs_service.get_job(db, inv.job_id, lock=True)
    blockers = billing_blockers(job)
    if blockers:
        raise DomainError({"code": "BILLING_BLOCKED", "message": "The job is not ready for billing", "blockers": blockers})
    # Rebuild from verified job data so the final figures cannot be stale.
    _snapshot(db, inv, job)
    _build_lines(inv, job)
    inv.invoice_number = next_number(db, "invoice", settings_service.get(db, "invoice_number_prefix"))
    inv.status = InvoiceStatus.FINALISED
    inv.finalised_at, inv.finalised_by_id = utcnow(), user.id
    inv.amount_paid = ZERO
    inv.payment_status = PaymentStatus.PAID if inv.total == 0 else PaymentStatus.UNPAID
    db.flush()
    jobs_service.add_event(db, job, "INVOICE", f"Invoice {inv.invoice_number} finalised (INR {inv.total})", user)
    audit(
        db, user, "invoice.finalise", "invoice", inv.id, f"Finalised {inv.invoice_number} for {job.job_number}",
        {"total": str(inv.total), "tax_total": str(inv.tax_total), "discount_total": str(inv.discount_total)},
    )
    # Outbox rows are written in this same transaction: either the invoice and both delivery
    # jobs are committed together, or none of them are.
    link = delivery.issue_link(db, inv, user)
    delivery.enqueue(db, inv, link, user, trigger="AUTO")
    return inv


def cancel_invoice(db: Session, invoice_id: int, user: User, reason: str) -> Invoice:
    from app.services import delivery

    inv = get_invoice(db, invoice_id, lock=True)
    if inv.status != InvoiceStatus.FINALISED:
        raise DomainError("Only a finalised invoice can be cancelled")
    if any(p.voided_at is None for p in inv.payments):
        raise DomainError("Void the recorded payments before cancelling the invoice")
    job = jobs_service.get_job(db, inv.job_id, lock=True)
    if job.status == JobStatus.COMPLETED:
        raise DomainError("The vehicle has been handed over; this invoice can no longer be cancelled")
    inv.status = InvoiceStatus.CANCELLED
    inv.cancelled_at, inv.cancelled_by_id, inv.cancel_reason = utcnow(), user.id, reason
    delivery.revoke_links(db, inv)
    for dj in inv.delivery_jobs:
        if dj.status in (DeliveryStatus.PENDING, DeliveryStatus.RETRY_SCHEDULED):
            dj.status, dj.last_error = DeliveryStatus.CANCELLED, "Invoice cancelled"
    if job.status == JobStatus.READY_FOR_DELIVERY:
        jobs_service.transition(db, job, JobStatus.READY_FOR_BILLING, user, "Invoice cancelled; back to billing")
    jobs_service.add_event(db, job, "INVOICE", f"Invoice {inv.invoice_number} cancelled: {reason}", user)
    audit(db, user, "invoice.cancel", "invoice", inv.id, f"Cancelled {inv.invoice_number}", {"reason": reason})
    return inv


# --- Payments ---------------------------------------------------------------------------


def _refresh_payment_status(inv: Invoice) -> None:
    paid = sum((p.amount for p in inv.payments if p.voided_at is None), ZERO)
    inv.amount_paid = paid
    if paid >= inv.total:
        inv.payment_status = PaymentStatus.PAID
    elif paid > 0:
        inv.payment_status = PaymentStatus.PARTIALLY_PAID
    else:
        inv.payment_status = PaymentStatus.UNPAID


def record_payment(
    db: Session, invoice_id: int, user: User, *, amount: Decimal, method: str, paid_at=None,
    external_reference: str = "", notes: str = "", idempotency_key: str | None = None,
) -> Payment:
    # The invoice row lock serialises concurrent payments, so the outstanding check is reliable.
    inv = get_invoice(db, invoice_id, lock=True)
    if idempotency_key:
        existing = db.scalar(select(Payment).where(Payment.idempotency_key == idempotency_key))
        if existing is not None:
            if existing.invoice_id != inv.id:
                raise DomainError("This payment submission key was already used for another invoice")
            return existing
    if inv.status != InvoiceStatus.FINALISED:
        raise DomainError("Payments can be recorded only against a finalised invoice")
    amount = money(amount)
    if amount <= 0:
        raise bad_request("Payment amount must be greater than zero")
    if amount > inv.outstanding:
        raise DomainError(f"Payment of INR {amount} exceeds the outstanding balance of INR {inv.outstanding}")
    payment = Payment(
        reference=next_number(db, "payment", "PAY"), amount=amount, method=method,
        paid_at=paid_at or utcnow(), external_reference=external_reference, notes=notes,
        recorded_by_id=user.id, idempotency_key=idempotency_key,
    )
    inv.payments.append(payment)  # the relationship sets invoice_id and adds it to the session
    _refresh_payment_status(inv)
    db.flush()
    audit(
        db, user, "payment.record", "payment", payment.id,
        f"{payment.reference}: INR {amount} by {method} against {inv.invoice_number}",
        {"invoice_id": inv.id, "outstanding_after": str(inv.outstanding)},
    )
    return payment


def void_payment(db: Session, payment_id: int, user: User, reason: str) -> Payment:
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise not_found("Payment")
    inv = get_invoice(db, payment.invoice_id, lock=True)
    db.refresh(payment)
    if payment.voided_at is not None:
        raise DomainError("This payment has already been voided")
    payment.voided_at, payment.voided_by_id, payment.void_reason = utcnow(), user.id, reason
    _refresh_payment_status(inv)
    audit(
        db, user, "payment.void", "payment", payment.id,
        f"Voided {payment.reference} (INR {payment.amount}) on {inv.invoice_number}", {"reason": reason},
    )
    return payment
