from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.utils import utcnow
from app.models.base import Base, Money, Qty, TimestampMixin, created_ts, intpk, opt_ts, user_fk
from app.models.enums import EstimateStatus, InvoiceStatus, PaymentStatus


class TaxRate(Base):
    """Configurable tax treatment; each labour operation and part references one."""

    __tablename__ = "tax_rates"
    id: Mapped[intpk]
    name: Mapped[str] = mapped_column(String(60), unique=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))  # percent
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Estimate(Base, TimestampMixin):
    """Each row is one estimate version for a job; older versions are kept as SUPERSEDED."""

    __tablename__ = "estimates"
    __table_args__ = (UniqueConstraint("job_id", "version"),)
    id: Mapped[intpk]
    job_id: Mapped[int] = mapped_column(ForeignKey("service_jobs.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default=EstimateStatus.DRAFT, index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    terms: Mapped[str] = mapped_column(Text, default="")
    subtotal_labour: Mapped[Money]
    subtotal_parts: Mapped[Money]
    discount_total: Mapped[Money]
    tax_total: Mapped[Money]
    total: Mapped[Money]
    created_by_id: Mapped[int] = user_fk(nullable=False)
    sent_at: Mapped[opt_ts]
    decided_at: Mapped[opt_ts]

    job = relationship("ServiceJob", back_populates="estimates")
    lines: Mapped[list["EstimateLine"]] = relationship(
        order_by="EstimateLine.id", cascade="all, delete-orphan"
    )
    approvals: Mapped[list["CustomerApproval"]] = relationship(order_by="CustomerApproval.id")


class EstimateLine(Base):
    __tablename__ = "estimate_lines"
    id: Mapped[intpk]
    estimate_id: Mapped[int] = mapped_column(ForeignKey("estimates.id"), index=True)
    line_type: Mapped[str] = mapped_column(String(10))
    job_labour_id: Mapped[int | None] = mapped_column(ForeignKey("job_labour.id"))
    parts_request_line_id: Mapped[int | None] = mapped_column(ForeignKey("parts_request_lines.id"))
    code: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[Qty]
    unit_price: Mapped[Money]
    discount_amount: Mapped[Money]
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    tax_amount: Mapped[Money]
    line_total: Mapped[Money]


class CustomerApproval(Base):
    __tablename__ = "customer_approvals"
    id: Mapped[intpk]
    job_id: Mapped[int] = mapped_column(ForeignKey("service_jobs.id"), index=True)
    estimate_id: Mapped[int] = mapped_column(ForeignKey("estimates.id"), index=True)
    decision: Mapped[str] = mapped_column(String(10))
    method: Mapped[str] = mapped_column(String(20))
    notes: Mapped[str] = mapped_column(Text, default="")
    recorded_by_id: Mapped[int] = user_fk(nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Invoice(Base, TimestampMixin):
    __tablename__ = "invoices"
    __table_args__ = (
        # At most one live (non-cancelled) invoice per job.
        Index(
            "uq_invoices_job_live",
            "job_id",
            unique=True,
            postgresql_where=text("status <> 'CANCELLED'"),
        ),
    )
    id: Mapped[intpk]
    invoice_number: Mapped[str | None] = mapped_column(String(20), unique=True)  # set on finalise
    job_id: Mapped[int] = mapped_column(ForeignKey("service_jobs.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default=InvoiceStatus.DRAFT, index=True)
    payment_status: Mapped[str] = mapped_column(String(20), default=PaymentStatus.UNPAID, index=True)
    # Snapshots frozen at finalisation so later master-data edits never alter the invoice.
    customer_name: Mapped[str] = mapped_column(String(120), default="")
    customer_email: Mapped[str | None] = mapped_column(String(255))
    customer_mobile: Mapped[str | None] = mapped_column(String(20))
    billing_address: Mapped[str] = mapped_column(Text, default="")
    customer_gstin: Mapped[str | None] = mapped_column(String(15))
    vehicle_registration: Mapped[str] = mapped_column(String(20), default="")
    vehicle_model: Mapped[str] = mapped_column(String(80), default="")
    job_number: Mapped[str] = mapped_column(String(20), default="")
    centre: Mapped[dict] = mapped_column(JSON, default=dict)
    subtotal_labour: Mapped[Money]
    subtotal_parts: Mapped[Money]
    discount_total: Mapped[Money]
    taxable_total: Mapped[Money]
    tax_total: Mapped[Money]
    round_off: Mapped[Money]  # total is rounded to the nearest rupee; this is the adjustment
    total: Mapped[Money]
    amount_paid: Mapped[Money]
    notes: Mapped[str] = mapped_column(Text, default="")
    terms: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[int] = user_fk(nullable=False)
    finalised_at: Mapped[opt_ts] = mapped_column(index=True)
    finalised_by_id: Mapped[int | None] = user_fk()
    cancelled_at: Mapped[opt_ts]
    cancelled_by_id: Mapped[int | None] = user_fk()
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    replaces_invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"))

    job = relationship("ServiceJob", back_populates="invoices")
    customer = relationship("Customer")
    lines: Mapped[list["InvoiceLine"]] = relationship(
        order_by="InvoiceLine.sort_order", cascade="all, delete-orphan"
    )
    payments: Mapped[list["Payment"]] = relationship(order_by="Payment.id")
    delivery_jobs = relationship("DeliveryJob", order_by="DeliveryJob.id", back_populates="invoice")
    links = relationship("InvoiceLink", order_by="InvoiceLink.id", back_populates="invoice")

    @property
    def outstanding(self) -> Decimal:
        return self.total - self.amount_paid

    @property
    def tax_breakdown(self) -> list[dict]:
        from app.services.billing import tax_breakdown

        return tax_breakdown(self)

    @property
    def hsn_summary(self) -> list[dict]:
        from app.services.billing import hsn_summary

        return hsn_summary(self)

    @property
    def total_in_words(self) -> str:
        from app.core.utils import rupees_in_words

        return rupees_in_words(self.total)

    @property
    def tax_in_words(self) -> str:
        from app.core.utils import rupees_in_words

        return rupees_in_words(self.tax_total)


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    id: Mapped[intpk]
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    line_type: Mapped[str] = mapped_column(String(10))
    job_labour_id: Mapped[int | None] = mapped_column(ForeignKey("job_labour.id"))
    parts_request_line_id: Mapped[int | None] = mapped_column(ForeignKey("parts_request_lines.id"))
    manual_part_id: Mapped[int | None] = mapped_column(ForeignKey("job_manual_parts.id"))
    # Service Manager edits on the draft bill; both survive rebuilding the draft from the job.
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    price_override: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    code: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(255))
    hsn_code: Mapped[str] = mapped_column(String(20), default="")
    unit: Mapped[str] = mapped_column(String(10), default="")
    quantity: Mapped[Qty]
    unit_price: Mapped[Money]
    discount_amount: Mapped[Money]
    tax_name: Mapped[str] = mapped_column(String(60), default="")
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    tax_amount: Mapped[Money]
    line_total: Mapped[Money]


class CustomerFeedback(Base):
    """The customer's rating of a visit, given on the invoice link (one per invoice, changeable)."""

    __tablename__ = "customer_feedback"
    __table_args__ = (CheckConstraint("rating BETWEEN 1 AND 5", name="ck_customer_feedback_rating"),)
    id: Mapped[intpk]
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), unique=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("service_jobs.id"), index=True)
    rating: Mapped[int] = mapped_column(SmallInteger)
    comment: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Payment(Base):
    """A payment record (not a gateway transaction)."""

    __tablename__ = "payments"
    id: Mapped[intpk]
    reference: Mapped[str] = mapped_column(String(20), unique=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    amount: Mapped[Money]
    method: Mapped[str] = mapped_column(String(20))
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    external_reference: Mapped[str] = mapped_column(String(80), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    recorded_by_id: Mapped[int] = user_fk(nullable=False)
    # Client-supplied key so a double-submitted form cannot record the payment twice.
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    voided_at: Mapped[opt_ts]
    voided_by_id: Mapped[int | None] = user_fk()
    void_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[created_ts]

    recorded_by = relationship("User", foreign_keys=[recorded_by_id])
