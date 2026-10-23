"""Invoices, payments and customer delivery (Service Manager only)."""
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import Response
from sqlalchemy import or_, select

from app.api.helpers import PageNum, PageSize, like, paginate
from app.core.deps import DB, require
from app.core.errors import not_found
from app.core.utils import normalise_registration
from app.models import DeliveryJob, Invoice, Vehicle
from app.models.enums import InvoiceStatus
from app.schemas.billing import (
    DeliveryOut,
    DraftUpdateIn,
    InvoiceLineEdit,
    InvoiceLineIn,
    InvoiceOut,
    InvoiceSummary,
    PaymentIn,
    PaymentOut,
    ResendIn,
)
from app.schemas.common import Page, ReasonIn
from app.schemas.workshop import DirectBillIn, DirectBillNewIn
from app.services import billing, delivery
from app.services import jobs as jobs_service
from app.services.common import audit
from app.services.invoice_pdf import render_invoice_pdf

router = APIRouter(tags=["billing"])


@router.get("/invoices", response_model=Page[InvoiceSummary])
def list_invoices(
    db: DB, q: str | None = None, status: str | None = None, payment_status: str | None = None,
    outstanding_only: bool = False, date_from: datetime | None = None, date_to: datetime | None = None,
    page: PageNum = 1, page_size: PageSize = 25, _=require("invoice.read"),
):
    stmt = select(Invoice).order_by(Invoice.id.desc())
    if q and q.strip():
        term = like(q)
        conds = [Invoice.invoice_number.ilike(term), Invoice.job_number.ilike(term), Invoice.customer_name.ilike(term)]
        reg = normalise_registration(q)
        if reg:
            conds.append(Invoice.vehicle_registration.like(f"%{reg}%"))
        digits = "".join(c for c in q if c.isdigit())
        if len(digits) >= 4:
            conds.append(Invoice.customer_mobile.like(f"%{digits}%"))
        stmt = stmt.where(or_(*conds))
    if status:
        stmt = stmt.where(Invoice.status.in_(status.split(",")))
    if payment_status:
        stmt = stmt.where(Invoice.payment_status.in_(payment_status.split(",")))
    if outstanding_only:
        stmt = stmt.where(Invoice.status == InvoiceStatus.FINALISED, Invoice.total > Invoice.amount_paid)
    if date_from:
        stmt = stmt.where(Invoice.created_at >= date_from)
    if date_to:
        stmt = stmt.where(Invoice.created_at <= date_to)
    return paginate(db, stmt, page, page_size)


@router.post("/jobs/{job_id}/direct-bill", response_model=InvoiceOut)
def direct_bill_job(job_id: int, body: DirectBillIn, db: DB, user=require("invoice.manage", "job.manage")):
    """Send an open job straight to billing and create its draft invoice."""
    job = jobs_service.get_job(db, job_id, lock=True)
    jobs_service.bill_directly(db, job, user, body.description)
    inv = billing.prepare_draft(db, job, user)
    db.commit()
    db.refresh(inv)
    return inv


@router.post("/vehicles/{vehicle_id}/direct-bill", response_model=InvoiceOut, status_code=201)
def direct_bill_vehicle(vehicle_id: int, body: DirectBillNewIn, db: DB, user=require("invoice.manage", "reception.manage")):
    """Open a job card for the vehicle and bill it at once (no inspection or workshop steps)."""
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise not_found("Vehicle")
    job = jobs_service.create_job(
        db, user, vehicle=vehicle, odometer=body.odometer, fuel_level=body.fuel_level, complaints=body.description,
        override_reason=body.override_reason,
    )
    db.flush()
    jobs_service.bill_directly(db, job, user, body.description)
    inv = billing.prepare_draft(db, job, user)
    db.commit()
    db.refresh(inv)
    return inv


@router.post("/jobs/{job_id}/invoice", response_model=InvoiceOut)
def prepare_invoice(job_id: int, db: DB, user=require("invoice.manage")):
    """Create the draft invoice, or rebuild the existing draft from current job data."""
    job = jobs_service.get_job(db, job_id, lock=True)
    inv = billing.prepare_draft(db, job, user)
    db.commit()
    db.refresh(inv)
    return inv


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut)
def get_invoice(invoice_id: int, db: DB, _=require("invoice.read")):
    return billing.get_invoice(db, invoice_id)


@router.patch("/invoices/{invoice_id}", response_model=InvoiceOut)
def update_invoice(invoice_id: int, body: DraftUpdateIn, db: DB, user=require("invoice.manage")):
    inv = billing.get_invoice(db, invoice_id, lock=True)
    billing.update_draft(db, inv, user, body.notes, body.terms, [d.model_dump() for d in body.discounts])
    if body.discounts:
        audit(db, user, "invoice.discount", "invoice", inv.id, "Updated draft invoice discounts",
              {"discount_total": str(inv.discount_total)})
    db.commit()
    db.refresh(inv)
    return inv


@router.post("/invoices/{invoice_id}/lines", response_model=InvoiceOut, status_code=201)
def add_invoice_line(invoice_id: int, body: InvoiceLineIn, db: DB, user=require("invoice.manage")):
    """Add an item to the draft bill by hand."""
    inv = billing.get_invoice(db, invoice_id, lock=True)
    billing.add_custom_line(db, inv, user, body.model_dump())
    db.commit()
    db.refresh(inv)
    return inv


@router.patch("/invoices/{invoice_id}/lines/{line_id}", response_model=InvoiceOut)
def edit_invoice_line(invoice_id: int, line_id: int, body: InvoiceLineEdit, db: DB, user=require("invoice.manage")):
    """Change a draft line's rate (any line) or description / quantity (items added by hand)."""
    inv = billing.get_invoice(db, invoice_id, lock=True)
    billing.edit_line(db, inv, user, line_id, body.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(inv)
    return inv


@router.delete("/invoices/{invoice_id}/lines/{line_id}", response_model=InvoiceOut)
def remove_invoice_line(invoice_id: int, line_id: int, db: DB, user=require("invoice.manage")):
    inv = billing.get_invoice(db, invoice_id, lock=True)
    billing.remove_custom_line(db, inv, user, line_id)
    db.commit()
    db.refresh(inv)
    return inv


@router.get("/invoices/{invoice_id}/pdf")
def invoice_pdf(invoice_id: int, db: DB, _=require("invoice.read")):
    """PDF of the invoice. Drafts and cancelled invoices are watermarked."""
    inv = billing.get_invoice(db, invoice_id)
    name = inv.invoice_number or f"draft-{inv.job_number}"
    return Response(
        render_invoice_pdf(inv), media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{name}.pdf"', "Cache-Control": "no-store"},
    )


@router.post("/invoices/{invoice_id}/finalise", response_model=InvoiceOut)
def finalise(invoice_id: int, db: DB, user=require("invoice.manage")):
    """Finalise the invoice and queue email / SMS / WhatsApp delivery in the same transaction.
    The response returns as soon as the outbox rows are committed; sending is asynchronous."""
    inv = billing.finalise(db, invoice_id, user)
    db.commit()
    db.refresh(inv)
    return inv


@router.post("/invoices/{invoice_id}/cancel", response_model=InvoiceOut)
def cancel(invoice_id: int, body: ReasonIn, db: DB, user=require("invoice.manage")):
    inv = billing.cancel_invoice(db, invoice_id, user, body.reason)
    db.commit()
    db.refresh(inv)
    return inv


# --- Payments ---------------------------------------------------------------------------


@router.post("/invoices/{invoice_id}/payments", response_model=PaymentOut, status_code=201)
def record_payment(invoice_id: int, body: PaymentIn, db: DB, user=require("payment.record")):
    payment = billing.record_payment(db, invoice_id, user, **body.model_dump())
    db.commit()
    return payment


@router.post("/payments/{payment_id}/void", response_model=PaymentOut)
def void_payment(payment_id: int, body: ReasonIn, db: DB, user=require("payment.record")):
    payment = billing.void_payment(db, payment_id, user, body.reason)
    db.commit()
    return payment


# --- Delivery ---------------------------------------------------------------------------


@router.get("/deliveries", response_model=Page[DeliveryOut])
def list_deliveries(
    db: DB, status: str | None = None, channel: str | None = None, invoice_id: int | None = None,
    kind: str | None = None, page: PageNum = 1, page_size: PageSize = 25, _=require("delivery.manage"),
):
    stmt = select(DeliveryJob).order_by(DeliveryJob.id.desc())
    if kind:
        stmt = stmt.where(DeliveryJob.kind == kind)
    if status:
        stmt = stmt.where(DeliveryJob.status.in_(status.split(",")))
    if channel:
        stmt = stmt.where(DeliveryJob.channel == channel)
    if invoice_id:
        stmt = stmt.where(DeliveryJob.invoice_id == invoice_id)
    return paginate(db, stmt, page, page_size)


@router.post("/invoices/{invoice_id}/resend", response_model=DeliveryOut, status_code=201)
def resend(invoice_id: int, body: ResendIn, db: DB, user=require("delivery.manage")):
    """Send again on ONE channel. Requires confirm=true; rate-limited per invoice and channel."""
    job = delivery.resend(db, invoice_id, body.channel, user, body.confirm)
    db.commit()
    db.refresh(job)
    return job


@router.post("/invoices/{invoice_id}/payment-reminder", response_model=DeliveryOut, status_code=201)
def payment_reminder(invoice_id: int, db: DB, user=require("delivery.manage")):
    """Send a WhatsApp payment reminder now. Only for an outstanding balance; rate-limited per invoice."""
    job = delivery.send_payment_reminder(db, invoice_id, user)
    db.commit()
    db.refresh(job)
    return job


@router.post("/deliveries/{delivery_id}/retry", response_model=DeliveryOut)
def retry(delivery_id: int, db: DB, user=require("delivery.manage")):
    job = delivery.retry(db, delivery_id, user)
    db.commit()
    db.refresh(job)
    return job


@router.post("/invoices/{invoice_id}/link")
def reissue_link(invoice_id: int, db: DB, user=require("delivery.manage")):
    """Revoke existing customer links and issue a fresh one (e.g. after expiry or a wrong recipient)."""
    inv = billing.get_invoice(db, invoice_id, lock=True)
    link = delivery.reissue_link(db, inv, user)
    url = delivery.link_url(db, link)
    db.commit()
    return {"url": url, "expires_at": link.expires_at}
