from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.utils import utcnow
from app.models.base import Base, created_ts, intpk, user_fk


class AuditLog(Base):
    """Append-only audit trail (UPDATE/DELETE blocked by a database trigger)."""

    __tablename__ = "audit_logs"
    id: Mapped[intpk]
    actor_id: Mapped[int | None] = user_fk(index=True)
    actor_email: Mapped[str] = mapped_column(String(255), default="system")
    actor_role: Mapped[str] = mapped_column(String(40), default="SYSTEM")
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(40), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[created_ts]


class Setting(Base):
    """Service-centre and application settings (non-secret)."""

    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    updated_by_id: Mapped[int | None] = user_fk()


class DocumentCounter(Base):
    """Per-year running numbers for job cards, invoices, etc."""

    __tablename__ = "document_counters"
    scope: Mapped[str] = mapped_column(String(30), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer, default=0)
