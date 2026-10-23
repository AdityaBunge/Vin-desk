from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.models.enums import Channel, PaymentMethod
from app.schemas.common import ORM, HsnCode, NonNegMoney, Text, UserRef


class DiscountIn(BaseModel):
    line_id: int
    discount_amount: NonNegMoney


class InvoiceLineIn(BaseModel):
    """An item the Service Manager adds to the draft bill."""

    line_type: Literal["PART", "LABOUR"] = "PART"
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    hsn_code: HsnCode = ""
    unit: Annotated[str, StringConstraints(strip_whitespace=True, max_length=10)] = "NO"
    quantity: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
    unit_price: NonNegMoney
    tax_rate_id: int | None = None


class InvoiceLineEdit(BaseModel):
    unit_price: NonNegMoney | None = None
    quantity: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)] | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)] | None = None


class DraftUpdateIn(BaseModel):
    notes: Text | None = None
    terms: Text | None = None
    discounts: list[DiscountIn] = []


class EstimateLineOut(ORM):
    id: int
    line_type: str
    code: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    line_total: Decimal


class ApprovalOut(ORM):
    id: int
    decision: str
    method: str
    notes: str
    decided_at: datetime


class EstimateOut(ORM):
    id: int
    job_id: int
    version: int
    status: str
    notes: str
    terms: str
    subtotal_labour: Decimal
    subtotal_parts: Decimal
    discount_total: Decimal
    tax_total: Decimal
    total: Decimal
    sent_at: datetime | None
    decided_at: datetime | None
    created_at: datetime
    lines: list[EstimateLineOut]
    approvals: list[ApprovalOut]


class InvoiceLineOut(ORM):
    id: int
    line_type: str
    is_custom: bool
    price_override: Decimal | None
    code: str
    description: str
    hsn_code: str
    unit: str
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal
    tax_name: str
    tax_rate: Decimal
    tax_amount: Decimal
    line_total: Decimal


class PaymentOut(ORM):
    id: int
    reference: str
    amount: Decimal
    method: str
    paid_at: datetime
    external_reference: str
    notes: str
    recorded_by: UserRef
    voided_at: datetime | None
    void_reason: str | None


class PaymentIn(BaseModel):
    amount: Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2)]
    method: PaymentMethod
    paid_at: datetime | None = None
    external_reference: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] = ""
    notes: Text = ""
    idempotency_key: Annotated[str, StringConstraints(min_length=8, max_length=64)] | None = None


class AttemptOut(ORM):
    id: int
    attempt_number: int
    started_at: datetime
    finished_at: datetime
    outcome: str
    provider: str
    error: str | None


class DeliveryOut(ORM):
    id: int
    kind: str
    invoice_id: int | None
    vehicle_id: int | None
    channel: str
    destination: str
    status: str
    display_status: str
    trigger: str
    attempt_count: int
    max_attempts: int
    next_attempt_at: datetime
    provider: str
    receipts_supported: bool
    simulated: bool
    last_error: str | None
    last_attempt_at: datetime | None
    sent_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime
    attempts: list[AttemptOut]


class LinkOut(ORM):
    id: int
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime
    last_accessed_at: datetime | None
    access_count: int
    usable: bool


class InvoiceSummary(ORM):
    id: int
    invoice_number: str | None
    job_id: int
    job_number: str
    status: str
    payment_status: str
    customer_name: str
    customer_mobile: str | None
    vehicle_registration: str
    vehicle_model: str
    total: Decimal
    amount_paid: Decimal
    outstanding: Decimal
    finalised_at: datetime | None
    created_at: datetime


class InvoiceOut(InvoiceSummary):
    customer_id: int
    customer_email: str | None
    billing_address: str
    customer_gstin: str | None
    centre: dict
    subtotal_labour: Decimal
    subtotal_parts: Decimal
    discount_total: Decimal
    taxable_total: Decimal
    tax_total: Decimal
    round_off: Decimal
    notes: str
    terms: str
    cancel_reason: str | None
    cancelled_at: datetime | None
    lines: list[InvoiceLineOut]
    payments: list[PaymentOut]
    tax_breakdown: list[dict]
    hsn_summary: list[dict]
    total_in_words: str
    tax_in_words: str
    delivery_jobs: list[DeliveryOut]
    links: list[LinkOut]


class ResendIn(BaseModel):
    channel: Channel
    confirm: bool = False
