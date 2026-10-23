from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.utils import utcnow
from app.models.base import Base, Money, Qty, TimestampMixin, created_ts, intpk, opt_ts, user_fk
from app.models.enums import (
    ApprovalStatus,
    PartsLineStatus,
    PartsRequestStatus,
    PurchaseRequestStatus,
    Urgency,
)

part_compatibility = Table(
    "part_compatibility",
    Base.metadata,
    Column("part_id", ForeignKey("parts.id", ondelete="CASCADE"), primary_key=True),
    Column("vehicle_model_id", ForeignKey("vehicle_models.id", ondelete="CASCADE"), primary_key=True),
)


class PartCategory(Base):
    __tablename__ = "part_categories"
    id: Mapped[intpk]
    name: Mapped[str] = mapped_column(String(80), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[intpk]
    name: Mapped[str] = mapped_column(String(160), unique=True)
    contact_name: Mapped[str] = mapped_column(String(120), default="")
    phone: Mapped[str] = mapped_column(String(20), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Part(Base, TimestampMixin):
    __tablename__ = "parts"
    id: Mapped[intpk]
    sku: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category_id: Mapped[int | None] = mapped_column(ForeignKey("part_categories.id"), index=True)
    purchase_cost: Mapped[Money]
    selling_price: Mapped[Money]
    tax_rate_id: Mapped[int | None] = mapped_column(ForeignKey("tax_rates.id"))
    reorder_threshold: Mapped[Qty]
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    storage_location: Mapped[str] = mapped_column(String(60), default="")
    hsn_code: Mapped[str] = mapped_column(String(20), default="")  # GST HSN code printed on invoices
    unit: Mapped[str] = mapped_column(String(10), default="NO")  # "per" column on invoices: NO, Nos, Ltr...
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Columns of the workshop's closing-stock sheet, as last synced (see app.import_parts).
    dms_bin: Mapped[str] = mapped_column(String(30), default="", server_default="")
    dms_category: Mapped[str] = mapped_column(String(30), default="", server_default="")
    movement_class: Mapped[str] = mapped_column(String(10), default="", server_default="")
    abc_class: Mapped[str] = mapped_column(String(10), default="", server_default="")
    hml_class: Mapped[str] = mapped_column(String(10), default="", server_default="")
    ris_class: Mapped[str] = mapped_column(String(10), default="", server_default="")
    sheet_closing_qty: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    sheet_closing_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    sheet_actual_qty: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    category = relationship("PartCategory", lazy="joined")
    supplier = relationship("Supplier", lazy="joined")
    tax_rate = relationship("TaxRate", lazy="joined")
    stock: Mapped["InventoryStock"] = relationship(
        back_populates="part", uselist=False, lazy="joined", cascade="all, delete-orphan"
    )
    compatible_models = relationship("VehicleModel", secondary=part_compatibility, lazy="selectin")


class InventoryStock(Base):
    """Stock levels, one row per part. The row is locked FOR UPDATE for every change."""

    __tablename__ = "inventory_stock"
    __table_args__ = (
        CheckConstraint("qty_on_hand >= 0", name="on_hand_non_negative"),
        CheckConstraint("qty_reserved >= 0", name="reserved_non_negative"),
        CheckConstraint("qty_reserved <= qty_on_hand", name="reserved_within_on_hand"),
    )
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id", ondelete="CASCADE"), primary_key=True)
    qty_on_hand: Mapped[Qty]
    qty_reserved: Mapped[Qty]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    part: Mapped[Part] = relationship(back_populates="stock")

    @property
    def qty_available(self) -> Decimal:
        return self.qty_on_hand - self.qty_reserved


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"
    id: Mapped[intpk]
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), index=True)
    movement_type: Mapped[str] = mapped_column(String(30), index=True)
    quantity: Mapped[Qty]  # signed only for ADJUSTMENT; otherwise positive
    on_hand_after: Mapped[Qty]
    reserved_after: Mapped[Qty]
    job_id: Mapped[int | None] = mapped_column(ForeignKey("service_jobs.id"), index=True)
    parts_request_line_id: Mapped[int | None] = mapped_column(ForeignKey("parts_request_lines.id"))
    purchase_request_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_requests.id"))
    reason: Mapped[str] = mapped_column(Text, default="")
    performed_by_id: Mapped[int] = user_fk(nullable=False)
    created_at: Mapped[created_ts]

    part = relationship("Part")
    performed_by = relationship("User")
    job = relationship("ServiceJob")

    @property
    def job_number(self) -> str | None:
        return self.job.job_number if self.job else None


class PartsRequest(Base, TimestampMixin):
    __tablename__ = "parts_requests"
    id: Mapped[intpk]
    request_number: Mapped[str] = mapped_column(String(20), unique=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("service_jobs.id"), index=True)
    requested_by_id: Mapped[int] = user_fk(nullable=False)
    status: Mapped[str] = mapped_column(String(30), default=PartsRequestStatus.PENDING, index=True)
    is_additional: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")

    job = relationship("ServiceJob", back_populates="parts_requests")
    requested_by = relationship("User")
    lines: Mapped[list["PartsRequestLine"]] = relationship(
        back_populates="request", order_by="PartsRequestLine.id", cascade="all, delete-orphan"
    )


class PartsRequestLine(Base, TimestampMixin):
    __tablename__ = "parts_request_lines"
    __table_args__ = (
        CheckConstraint("qty_requested > 0", name="requested_positive"),
        CheckConstraint("qty_reserved >= 0 AND qty_issued >= 0 AND qty_returned >= 0", name="non_negative"),
        CheckConstraint("qty_issued <= qty_requested", name="issued_within_requested"),
        CheckConstraint("qty_returned <= qty_issued", name="returned_within_issued"),
    )
    id: Mapped[intpk]
    request_id: Mapped[int] = mapped_column(ForeignKey("parts_requests.id"), index=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), index=True)
    original_part_id: Mapped[int | None] = mapped_column(ForeignKey("parts.id"))
    description: Mapped[str] = mapped_column(String(255), default="")
    qty_requested: Mapped[Qty]
    qty_approved: Mapped[Qty]  # quantity inventory has committed (reserved + issued)
    qty_reserved: Mapped[Qty]
    qty_issued: Mapped[Qty]
    qty_returned: Mapped[Qty]
    qty_consumed: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    urgency: Mapped[str] = mapped_column(String(10), default=Urgency.NORMAL)
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default=PartsLineStatus.PENDING, index=True)
    # Kept for history. New lines are APPROVED on creation (there is no customer-approval step).
    approval_status: Mapped[str] = mapped_column(String(10), default=ApprovalStatus.APPROVED)
    is_short: Mapped[bool] = mapped_column(Boolean, default=False)
    expected_restock_date: Mapped[date | None] = mapped_column(Date)
    inventory_notes: Mapped[str] = mapped_column(Text, default="")
    alt_part_id: Mapped[int | None] = mapped_column(ForeignKey("parts.id"))
    alt_status: Mapped[str | None] = mapped_column(String(10))
    alt_notes: Mapped[str] = mapped_column(Text, default="")
    cancel_reason: Mapped[str | None] = mapped_column(Text)

    request: Mapped[PartsRequest] = relationship(back_populates="lines")
    part = relationship("Part", foreign_keys=[part_id], lazy="joined")
    original_part = relationship("Part", foreign_keys=[original_part_id])
    alt_part = relationship("Part", foreign_keys=[alt_part_id])

    @property
    def qty_outstanding(self) -> Decimal:
        if self.status == PartsLineStatus.CANCELLED:
            return Decimal("0")
        return max(self.qty_requested - self.qty_issued, Decimal("0"))

    @property
    def qty_unreconciled(self) -> Decimal:
        """Issued stock neither declared consumed nor returned to stores."""
        return self.qty_issued - self.qty_returned - (self.qty_consumed or Decimal("0"))


class PurchaseRequest(Base, TimestampMixin):
    __tablename__ = "purchase_requests"
    id: Mapped[intpk]
    pr_number: Mapped[str] = mapped_column(String(20), unique=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    status: Mapped[str] = mapped_column(
        String(30), default=PurchaseRequestStatus.PENDING_APPROVAL, index=True
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[int] = user_fk(nullable=False)
    decided_by_id: Mapped[int | None] = user_fk()
    decided_at: Mapped[opt_ts]
    decision_notes: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[opt_ts]

    supplier = relationship("Supplier")
    created_by = relationship("User", foreign_keys=[created_by_id])
    decided_by = relationship("User", foreign_keys=[decided_by_id])
    lines: Mapped[list["PurchaseRequestLine"]] = relationship(
        order_by="PurchaseRequestLine.id", cascade="all, delete-orphan"
    )


class PurchaseRequestLine(Base):
    __tablename__ = "purchase_request_lines"
    id: Mapped[intpk]
    purchase_request_id: Mapped[int] = mapped_column(ForeignKey("purchase_requests.id"), index=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"))
    quantity: Mapped[Qty]
    qty_received: Mapped[Qty]
    unit_cost: Mapped[Money]
    parts_request_line_id: Mapped[int | None] = mapped_column(ForeignKey("parts_request_lines.id"))

    part = relationship("Part")
