from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, created_ts, intpk, user_fk


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"
    id: Mapped[intpk]
    code: Mapped[str] = mapped_column(String(20), unique=True)  # CUST-000001
    name: Mapped[str] = mapped_column(String(120), index=True)
    mobile: Mapped[str] = mapped_column(String(20), index=True)  # stored as +91XXXXXXXXXX
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    alternate_mobile: Mapped[str | None] = mapped_column(String(20))
    billing_address: Mapped[str] = mapped_column(Text, default="")
    gstin: Mapped[str | None] = mapped_column(String(15))  # business customers; printed on tax invoices
    # Contact preferences for transactional messages (invoice delivery).
    email_opt_in: Mapped[bool] = mapped_column(Boolean, default=True)
    sms_opt_in: Mapped[bool] = mapped_column(Boolean, default=True)
    # WhatsApp: invoices plus payment-due and service-due reminders.
    whatsapp_opt_in: Mapped[bool] = mapped_column(Boolean, default=True)

    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="customer")
    consents: Mapped[list["CustomerConsent"]] = relationship(
        back_populates="customer", order_by="CustomerConsent.id"
    )


class CustomerConsent(Base):
    """Append-only record of each consent / preference change."""

    __tablename__ = "customer_consents"
    id: Mapped[intpk]
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    channel: Mapped[str] = mapped_column(String(10))
    purpose: Mapped[str] = mapped_column(String(40), default="TRANSACTIONAL")
    granted: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(120), default="")
    recorded_by_id: Mapped[int | None] = user_fk()
    recorded_at: Mapped[created_ts]

    customer: Mapped[Customer] = relationship(back_populates="consents")


class VehicleModel(Base):
    __tablename__ = "vehicle_models"
    id: Mapped[intpk]
    name: Mapped[str] = mapped_column(String(80), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Vehicle(Base, TimestampMixin):
    __tablename__ = "vehicles"
    id: Mapped[intpk]
    # Normalised (upper-case, alphanumeric only); unique for duplicate detection.
    registration_number: Mapped[str] = mapped_column(String(20), unique=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("vehicle_models.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    vin: Mapped[str | None] = mapped_column(String(40), unique=True)
    engine_number: Mapped[str | None] = mapped_column(String(40))
    odometer: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    model: Mapped[VehicleModel] = relationship(lazy="joined")
    customer: Mapped[Customer] = relationship(back_populates="vehicles", lazy="joined")
