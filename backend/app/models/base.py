from datetime import datetime
from decimal import Decimal
from typing import Annotated

from sqlalchemy import DateTime, ForeignKey, MetaData, Numeric
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.utils import utcnow

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

Money = Annotated[Decimal, mapped_column(Numeric(14, 2), default=Decimal("0"))]
Qty = Annotated[Decimal, mapped_column(Numeric(12, 2), default=Decimal("0"))]
intpk = Annotated[int, mapped_column(primary_key=True)]
created_ts = Annotated[datetime, mapped_column(DateTime(timezone=True), default=utcnow, index=True)]
opt_ts = Annotated[datetime | None, mapped_column(DateTime(timezone=True))]


def user_fk(nullable: bool = True, index: bool = False):
    return mapped_column(ForeignKey("users.id"), nullable=nullable, index=index)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class TimestampMixin:
    created_at: Mapped[created_ts]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
