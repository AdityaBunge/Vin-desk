"""Unauthenticated endpoints: the customer invoice link and provider delivery-receipt webhooks."""
import hashlib
import hmac
import json
from decimal import Decimal

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field, StringConstraints, ValidationError
from sqlalchemy import select

from app.core.config import get_settings
from app.core.deps import DB
from app.core.rate_limit import client_ip, limiter
from app.core.security import sign_webhook, verify_link_token
from app.core.utils import utcnow
from app.integrations.whatsapp import MetaWhatsAppProvider
from app.models import CustomerFeedback, Invoice, InvoiceLink
from app.models.enums import InvoiceStatus
from app.services import delivery
from app.services.invoice_pdf import render_invoice_pdf

router = APIRouter(tags=["public"])

# One generic message for every failure, so a caller cannot tell a wrong token from a revoked one.
UNAVAILABLE = HTTPException(404, "This invoice link is not valid. Please contact the service centre.")
EXPIRED = HTTPException(410, "This invoice link has expired. Please contact the service centre for a new link.")


def _money_as_text(value):
    """Amounts leave the API as exact decimal strings, never binary floats."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _money_as_text(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_money_as_text(v) for v in value]
    return value


def _resolve(db, token: str, request: Request) -> Invoice:
    limiter.check(f"public-link:{client_ip(request)}", get_settings().public_link_rate_limit_per_minute)
    public_id = verify_link_token(token)
    if public_id is None:
        raise UNAVAILABLE
    link = db.scalar(select(InvoiceLink).where(InvoiceLink.public_id == public_id))
    if link is None or link.revoked_at is not None:
        raise UNAVAILABLE
    if link.expires_at <= utcnow():
        raise EXPIRED
    invoice = link.invoice
    if invoice.status != InvoiceStatus.FINALISED:
        raise UNAVAILABLE
    link.access_count += 1
    link.last_accessed_at = utcnow()
    db.commit()
    return invoice


@router.get("/public/invoices/{token}")
def public_invoice(token: str, request: Request, db: DB):
    """Protected invoice view for the customer. Returns only what the invoice itself shows;
    no internal IDs, no contact details."""
    inv = _resolve(db, token, request)
    centre = inv.centre or {}
    return _money_as_text({
        "centre": {k: centre.get(k, "") for k in ("name", "address", "phone", "email", "gstin", "pan", "state_name", "state_code", "declaration")},
        "invoice_number": inv.invoice_number,
        "invoice_date": inv.finalised_at,
        "job_number": inv.job_number,
        "customer_name": inv.customer_name,
        "billing_address": inv.billing_address,
        "customer_gstin": inv.customer_gstin,
        "vehicle_registration": inv.vehicle_registration,
        "vehicle_model": inv.vehicle_model,
        "lines": [
            {
                "line_type": l.line_type, "code": l.code, "description": l.description, "hsn_code": l.hsn_code,
                "unit": l.unit, "quantity": l.quantity,
                "unit_price": l.unit_price, "discount_amount": l.discount_amount, "tax_rate": l.tax_rate,
                "tax_amount": l.tax_amount, "line_total": l.line_total,
            }
            for l in inv.lines
        ],
        "subtotal_labour": inv.subtotal_labour,
        "subtotal_parts": inv.subtotal_parts,
        "discount_total": inv.discount_total,
        "tax_total": inv.tax_total,
        "tax_breakdown": inv.tax_breakdown,
        "hsn_summary": inv.hsn_summary,
        "round_off": inv.round_off,
        "total_in_words": inv.total_in_words,
        "tax_in_words": inv.tax_in_words,
        "total": inv.total,
        "amount_paid": inv.amount_paid,
        "outstanding": inv.outstanding,
        "payment_status": inv.payment_status,
        "terms": inv.terms,
        "feedback": _feedback(db, inv),
    })


class FeedbackIn(BaseModel):
    rating: Annotated[int, Field(ge=1, le=5)]
    comment: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ""


def _feedback(db, inv: Invoice) -> dict | None:
    fb = db.scalar(select(CustomerFeedback).where(CustomerFeedback.invoice_id == inv.id))
    return {"rating": fb.rating, "comment": fb.comment} if fb else None


@router.post("/public/invoices/{token}/feedback")
def public_feedback(token: str, body: FeedbackIn, request: Request, db: DB):
    """The customer rates the visit (1-5 stars, optional comment); a later rating replaces it."""
    inv = _resolve(db, token, request)
    fb = db.scalar(select(CustomerFeedback).where(CustomerFeedback.invoice_id == inv.id))
    if fb is None:
        fb = CustomerFeedback(invoice_id=inv.id, job_id=inv.job_id, rating=body.rating, comment=body.comment)
        db.add(fb)
    else:
        fb.rating, fb.comment = body.rating, body.comment
    db.commit()
    return {"rating": fb.rating, "comment": fb.comment}


@router.get("/public/invoices/{token}/pdf")
def public_invoice_pdf(token: str, request: Request, db: DB):
    inv = _resolve(db, token, request)
    return Response(
        render_invoice_pdf(inv), media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{inv.invoice_number}.pdf"',
            "Cache-Control": "private, no-store",
            "X-Robots-Tag": "noindex",
        },
    )


class ReceiptIn(BaseModel):
    event_id: str
    message_id: str
    status: str  # delivered | failed
    error: str | None = None


@router.post("/webhooks/delivery/{provider}")
async def delivery_receipt(
    provider: str, request: Request, db: DB, x_webhook_signature: str | None = Header(default=None)
):
    """Delivery-receipt callback in the application's normalised format:

        {"event_id": "...", "message_id": "<provider message id>", "status": "delivered|failed"}

    signed with `X-Webhook-Signature: hex(HMAC-SHA256(WEBHOOK_SECRET, raw body))`.
    A provider whose native callback differs needs a small adapter that re-signs into this shape.
    """
    if not get_settings().webhook_secret:
        raise HTTPException(503, "Webhooks are not configured")
    raw = await request.body()
    if not x_webhook_signature or not hmac.compare_digest(x_webhook_signature.lower(), sign_webhook(raw)):
        raise HTTPException(401, "Invalid webhook signature")
    try:
        body = ReceiptIn.model_validate(json.loads(raw))
    except (ValueError, ValidationError):
        raise HTTPException(400, "Malformed webhook payload") from None
    result = delivery.handle_receipt(
        db, provider, body.event_id, body.message_id, body.status.lower(), body.error,
        {"event_id": body.event_id, "message_id": body.message_id, "status": body.status},
    )
    db.commit()
    return {"result": result}


# Meta's message statuses, mapped onto the outbox's receipt vocabulary. "sent" adds nothing to
# what the send call already recorded.
WHATSAPP_STATUSES = {"delivered": "delivered", "read": "delivered", "failed": "failed"}


@router.get("/webhooks/whatsapp")
def whatsapp_webhook_verify(
    mode: str = Query("", alias="hub.mode"), token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
):
    """Meta calls this once when the webhook is registered in the app dashboard."""
    expected = get_settings().whatsapp_verify_token
    if not expected or mode != "subscribe" or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(403, "Webhook verification failed")
    return PlainTextResponse(challenge)


@router.post("/webhooks/whatsapp")
async def whatsapp_webhook(request: Request, db: DB, x_hub_signature_256: str | None = Header(default=None)):
    """Message status callbacks from the WhatsApp Cloud API, signed by Meta with the app secret:
    `X-Hub-Signature-256: sha256=hex(HMAC-SHA256(WHATSAPP_APP_SECRET, raw body))`."""
    secret = get_settings().whatsapp_app_secret
    if not secret:
        raise HTTPException(503, "WhatsApp webhooks are not configured")
    raw = await request.body()
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not x_hub_signature_256 or not hmac.compare_digest(x_hub_signature_256.lower(), expected):
        raise HTTPException(401, "Invalid webhook signature")
    try:
        body = json.loads(raw)
        statuses = [st for entry in body.get("entry", []) for change in entry.get("changes", [])
                    for st in change.get("value", {}).get("statuses", [])]
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(400, "Malformed webhook payload") from None
    results = []
    for st in statuses:
        status = WHATSAPP_STATUSES.get(str(st.get("status", "")))
        if not status or not st.get("id"):
            continue
        errors = st.get("errors") or [{}]
        error = (errors[0].get("error_data") or {}).get("details") or errors[0].get("title")
        results.append(delivery.handle_receipt(
            db, MetaWhatsAppProvider.name, f"{st['id']}:{st['status']}", str(st["id"]), status, error, st,
        ))
    db.commit()
    return {"results": results}
