from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.utils import utcnow
from app.models.base import Base, TimestampMixin, created_ts, intpk, opt_ts, user_fk
from app.models.enums import DeliveryKind, DeliveryStatus


class InvoiceLink(Base):
    """Customer-facing invoice link. The URL token is `public_id.signature`; the signature is an
    HMAC with a server-side secret, so database contents alone cannot be used to open an invoice."""

    __tablename__ = "invoice_links"
    id: Mapped[intpk]
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[opt_ts]
    created_by_id: Mapped[int | None] = user_fk()
    created_at: Mapped[created_ts]
    last_accessed_at: Mapped[opt_ts]
    access_count: Mapped[int] = mapped_column(Integer, default=0)

    invoice = relationship("Invoice", back_populates="links")

    def is_usable(self, now: datetime | None = None) -> bool:
        return self.revoked_at is None and self.expires_at > (now or utcnow())

    @property
    def usable(self) -> bool:
        return self.is_usable()


class DeliveryJob(Base, TimestampMixin):
    """Durable outbox row: one message to a customer on one channel.

    `kind` INVOICE and PAYMENT_REMINDER belong to an invoice (and carry its secure link);
    SERVICE_REMINDER belongs to a vehicle, anchored on the visit it counts from."""

    __tablename__ = "delivery_jobs"
    id: Mapped[intpk]
    kind: Mapped[str] = mapped_column(String(20), default=DeliveryKind.INVOICE, server_default=DeliveryKind.INVOICE, index=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), index=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"), index=True)
    service_job_id: Mapped[int | None] = mapped_column(ForeignKey("service_jobs.id"), index=True)
    link_id: Mapped[int | None] = mapped_column(ForeignKey("invoice_links.id"))
    channel: Mapped[str] = mapped_column(String(10), index=True)
    destination: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20), default=DeliveryStatus.PENDING, index=True)
    trigger: Mapped[str] = mapped_column(String(10), default="AUTO")  # AUTO | MANUAL
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    locked_until: Mapped[opt_ts]
    provider: Mapped[str] = mapped_column(String(40), default="")
    provider_message_id: Mapped[str | None] = mapped_column(String(120), index=True)
    # False when the provider cannot confirm delivery: SENT then means "delivery status unknown".
    receipts_supported: Mapped[bool] = mapped_column(Boolean, default=False)
    # True when handled by the development simulator (no real message left the system).
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_attempt_at: Mapped[opt_ts]
    sent_at: Mapped[opt_ts]
    delivered_at: Mapped[opt_ts]
    # Passed to the provider on every attempt of this job so retries are de-duplicated there.
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    requested_by_id: Mapped[int | None] = user_fk()

    invoice = relationship("Invoice", back_populates="delivery_jobs")
    vehicle = relationship("Vehicle")
    service_job = relationship("ServiceJob")
    link = relationship("InvoiceLink")
    attempts: Mapped[list["CommunicationAttempt"]] = relationship(
        order_by="CommunicationAttempt.id", back_populates="delivery_job"
    )

    @property
    def display_status(self) -> str:
        """SENT is shown as-is only when a receipt can still upgrade it to DELIVERED."""
        if self.status == DeliveryStatus.SENT:
            if self.simulated:
                return "SIMULATED"
            if not self.receipts_supported:
                return "DELIVERY_STATUS_UNKNOWN"
        return self.status


class CommunicationAttempt(Base):
    """Append-only history of provider calls (UPDATE/DELETE blocked by a database trigger)."""

    __tablename__ = "communication_attempts"
    id: Mapped[intpk]
    delivery_job_id: Mapped[int] = mapped_column(ForeignKey("delivery_jobs.id"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    outcome: Mapped[str] = mapped_column(String(30))
    provider: Mapped[str] = mapped_column(String(40), default="")
    provider_message_id: Mapped[str | None] = mapped_column(String(120))
    error: Mapped[str | None] = mapped_column(Text)

    delivery_job: Mapped[DeliveryJob] = relationship(back_populates="attempts")


class WebhookEvent(Base):
    """Processed provider callbacks, for duplicate-callback protection."""

    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("provider", "event_id"),)
    id: Mapped[intpk]
    provider: Mapped[str] = mapped_column(String(40))
    event_id: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    received_at: Mapped[created_ts]


class Notification(Base):
    """Internal staff notification (distinct from customer email/SMS/WhatsApp deliveries)."""

    __tablename__ = "notifications"
    id: Mapped[intpk]
    recipient_id: Mapped[int] = user_fk(nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(Text, default="")
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    read_at: Mapped[opt_ts]
    created_at: Mapped[created_ts]
