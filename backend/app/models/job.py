from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.utils import utcnow
from app.models.base import Base, Money, Qty, TimestampMixin, created_ts, intpk, opt_ts, user_fk
from app.models.enums import ApprovalStatus, JobStatus, JobType, Urgency


class ServiceJob(Base, TimestampMixin):
    """One job card per vehicle visit."""

    __tablename__ = "service_jobs"
    id: Mapped[intpk]
    job_number: Mapped[str] = mapped_column(String(20), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    visit_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    odometer: Mapped[int] = mapped_column(Integer)
    fuel_level: Mapped[str] = mapped_column(String(20))
    complaints: Mapped[str] = mapped_column(Text)
    condition_notes: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(10), default=Urgency.NORMAL)
    job_type: Mapped[str] = mapped_column(String(20), default=JobType.PAID, server_default=JobType.PAID, index=True)
    status: Mapped[str] = mapped_column(String(40), default=JobStatus.RECEIVED, index=True)
    status_before_hold: Mapped[str | None] = mapped_column(String(40))
    assigned_mechanic_id: Mapped[int | None] = user_fk(index=True)
    estimated_completion_at: Mapped[opt_ts]
    created_by_id: Mapped[int] = user_fk(nullable=False)
    active_job_override_reason: Mapped[str | None] = mapped_column(Text)
    hold_reason: Mapped[str | None] = mapped_column(Text)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    rework_count: Mapped[int] = mapped_column(Integer, default=0)
    returned_for_rework: Mapped[bool] = mapped_column(Boolean, default=False)
    ready_for_delivery_at: Mapped[opt_ts]
    delivered_at: Mapped[opt_ts]
    handover_to: Mapped[str | None] = mapped_column(String(120))
    handover_notes: Mapped[str | None] = mapped_column(Text)
    handover_by_id: Mapped[int | None] = user_fk()

    customer = relationship("Customer", lazy="joined")
    vehicle = relationship("Vehicle", lazy="joined")
    assigned_mechanic = relationship("User", foreign_keys=[assigned_mechanic_id], lazy="joined")
    events: Mapped[list["JobEvent"]] = relationship(back_populates="job", order_by="JobEvent.id")
    assignments: Mapped[list["JobAssignment"]] = relationship(order_by="JobAssignment.id")
    photos: Mapped[list["JobPhoto"]] = relationship(order_by="JobPhoto.id")
    inspection: Mapped["Inspection | None"] = relationship(back_populates="job", uselist=False)
    labour: Mapped[list["JobLabour"]] = relationship(back_populates="job", order_by="JobLabour.id")
    parts_requests = relationship("PartsRequest", back_populates="job", order_by="PartsRequest.id")
    manual_parts: Mapped[list["JobManualPart"]] = relationship(order_by="JobManualPart.id", cascade="all, delete-orphan")
    estimates = relationship("Estimate", back_populates="job", order_by="Estimate.version")
    completions: Mapped[list["WorkCompletion"]] = relationship(order_by="WorkCompletion.id")
    quality_inspections: Mapped[list["QualityInspection"]] = relationship(
        order_by="QualityInspection.id"
    )
    invoices = relationship("Invoice", back_populates="job", order_by="Invoice.id")

    @property
    def registration_number(self) -> str:
        return self.vehicle.registration_number

    @property
    def model_name(self) -> str:
        return self.vehicle.model.name

    @property
    def mechanic_name(self) -> str | None:
        return self.assigned_mechanic.full_name if self.assigned_mechanic else None


class JobAssignment(Base):
    __tablename__ = "job_assignments"
    id: Mapped[intpk]
    job_id: Mapped[int] = mapped_column(ForeignKey("service_jobs.id"), index=True)
    mechanic_id: Mapped[int] = user_fk(nullable=False, index=True)
    assigned_by_id: Mapped[int] = user_fk(nullable=False)
    assigned_at: Mapped[created_ts]
    unassigned_at: Mapped[opt_ts]
    notes: Mapped[str] = mapped_column(Text, default="")

    mechanic = relationship("User", foreign_keys=[mechanic_id])


class JobEvent(Base):
    """Timestamped job timeline."""

    __tablename__ = "job_events"
    id: Mapped[intpk]
    job_id: Mapped[int] = mapped_column(ForeignKey("service_jobs.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    from_status: Mapped[str | None] = mapped_column(String(40))
    to_status: Mapped[str | None] = mapped_column(String(40))
    actor_id: Mapped[int | None] = user_fk()
    created_at: Mapped[created_ts]

    job: Mapped[ServiceJob] = relationship(back_populates="events")
    actor = relationship("User")


class JobPhoto(Base):
    __tablename__ = "job_photos"
    id: Mapped[intpk]
    job_id: Mapped[int] = mapped_column(ForeignKey("service_jobs.id"), index=True)
    stored_name: Mapped[str] = mapped_column(String(80), unique=True)
    original_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(40))
    size_bytes: Mapped[int] = mapped_column(Integer)
    uploaded_by_id: Mapped[int] = user_fk(nullable=False)
    created_at: Mapped[created_ts]


class Inspection(Base, TimestampMixin):
    __tablename__ = "inspections"
    id: Mapped[intpk]
    job_id: Mapped[int] = mapped_column(ForeignKey("service_jobs.id"), unique=True)
    mechanic_id: Mapped[int] = user_fk(nullable=False)
    initial_observations: Mapped[str] = mapped_column(Text, default="")
    diagnostic_findings: Mapped[str] = mapped_column(Text, default="")
    recommended_repairs: Mapped[str] = mapped_column(Text, default="")
    # Parts the mechanic writes by hand on the inspection. Free text only: not linked to the
    # parts catalogue or stock (catalogue parts requests are a separate step on the Parts tab).
    spare_parts_notes: Mapped[str] = mapped_column(Text, default="")
    # Inventory's handling of that written list: "" (nothing to do), PENDING (not yet checked),
    # AVAILABLE / UNAVAILABLE (checked by hand on the shelf), or DONE (older catalogue flow).
    spare_parts_status: Mapped[str] = mapped_column(String(20), default="")
    spare_parts_done_by_id: Mapped[int | None] = user_fk()
    spare_parts_done_at: Mapped[opt_ts]
    spare_parts_done_note: Mapped[str] = mapped_column(Text, default="")
    # Parts text added (at inspection or as additional parts) that inventory has not yet checked.
    spare_parts_unconfirmed: Mapped[str] = mapped_column(Text, default="")
    safety_observations: Mapped[str] = mapped_column(Text, default="")
    additional_recommendations: Mapped[str] = mapped_column(Text, default="")
    mechanic_notes: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(10), default=Urgency.NORMAL)
    submitted_at: Mapped[opt_ts]

    job: Mapped[ServiceJob] = relationship(back_populates="inspection")
    spare_parts_done_by = relationship("User", foreign_keys=[spare_parts_done_by_id])


class JobManualPart(Base, TimestampMixin):
    """A part from the mechanic's written list that inventory staff confirmed as available by
    checking the shelf themselves. When matched to a catalogue part it is billed at the catalogue
    rate; otherwise at the price entered. Stock levels are not changed."""

    __tablename__ = "job_manual_parts"
    id: Mapped[intpk]
    job_id: Mapped[int] = mapped_column(ForeignKey("service_jobs.id"), index=True)
    part_id: Mapped[int | None] = mapped_column(ForeignKey("parts.id"))
    description: Mapped[str] = mapped_column(String(160))
    hsn_code: Mapped[str] = mapped_column(String(20), default="")
    unit: Mapped[str] = mapped_column(String(10), default="NO")
    quantity: Mapped[Qty]
    unit_price: Mapped[Money]
    tax_rate_id: Mapped[int | None] = mapped_column(ForeignKey("tax_rates.id"))
    added_by_id: Mapped[int] = user_fk(nullable=False)

    part = relationship("Part", lazy="joined")
    tax_rate = relationship("TaxRate", lazy="joined")


class LabourOperation(Base):
    """Labour catalogue (master data)."""

    __tablename__ = "labour_operations"
    id: Mapped[intpk]
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    default_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("1"))
    hourly_rate: Mapped[Money]
    tax_rate_id: Mapped[int | None] = mapped_column(ForeignKey("tax_rates.id"))
    sac_code: Mapped[str] = mapped_column(String(20), default="")  # GST SAC code printed on invoices
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    tax_rate = relationship("TaxRate", lazy="joined")


class JobLabour(Base, TimestampMixin):
    __tablename__ = "job_labour"
    id: Mapped[intpk]
    job_id: Mapped[int] = mapped_column(ForeignKey("service_jobs.id"), index=True)
    labour_operation_id: Mapped[int | None] = mapped_column(ForeignKey("labour_operations.id"))
    code: Mapped[str] = mapped_column(String(30), default="LAB-CUSTOM")
    description: Mapped[str] = mapped_column(String(255))
    estimated_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    actual_hours: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    hourly_rate: Mapped[Money]  # snapshot of the catalogue rate when added
    tax_rate_id: Mapped[int | None] = mapped_column(ForeignKey("tax_rates.id"))
    approval_status: Mapped[str] = mapped_column(String(10), default=ApprovalStatus.APPROVED)  # no approval step
    is_additional: Mapped[bool] = mapped_column(Boolean, default=False)
    added_by_id: Mapped[int] = user_fk(nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="")

    job: Mapped[ServiceJob] = relationship(back_populates="labour")
    tax_rate = relationship("TaxRate", lazy="joined")
    labour_operation = relationship("LabourOperation", lazy="joined")


class WorkCompletion(Base):
    __tablename__ = "work_completions"
    id: Mapped[intpk]
    job_id: Mapped[int] = mapped_column(ForeignKey("service_jobs.id"), index=True)
    mechanic_id: Mapped[int] = user_fk(nullable=False)
    repairs_completed: Mapped[str] = mapped_column(Text)
    outstanding_issues: Mapped[str] = mapped_column(Text, default="")
    final_observations: Mapped[str] = mapped_column(Text, default="")
    completed_at: Mapped[created_ts]

    mechanic = relationship("User")


class QualityChecklistItem(Base):
    """Configurable quality-inspection checklist."""

    __tablename__ = "quality_checklist_items"
    id: Mapped[intpk]
    label: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(40), default="GENERAL")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class QualityInspection(Base):
    __tablename__ = "quality_inspections"
    id: Mapped[intpk]
    job_id: Mapped[int] = mapped_column(ForeignKey("service_jobs.id"), index=True)
    inspector_id: Mapped[int] = user_fk(nullable=False)
    result: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str] = mapped_column(Text, default="")
    road_test_notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[created_ts]

    inspector = relationship("User")
    results: Mapped[list["QualityInspectionResult"]] = relationship(
        order_by="QualityInspectionResult.id", cascade="all, delete-orphan"
    )


class QualityInspectionResult(Base):
    __tablename__ = "quality_inspection_results"
    __table_args__ = (UniqueConstraint("inspection_id", "checklist_item_id"),)
    id: Mapped[intpk]
    inspection_id: Mapped[int] = mapped_column(ForeignKey("quality_inspections.id"), index=True)
    checklist_item_id: Mapped[int] = mapped_column(ForeignKey("quality_checklist_items.id"))
    label: Mapped[str] = mapped_column(String(200))
    passed: Mapped[bool | None] = mapped_column(Boolean)  # None = not applicable
    notes: Mapped[str] = mapped_column(Text, default="")
