from datetime import datetime
from decimal import Decimal
from typing import Annotated, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints

from app.core.utils import GSTIN_RE

T = TypeVar("T")

Str = Annotated[str, StringConstraints(strip_whitespace=True)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]
PositiveQty = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
NonNegMoney = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
# GST HSN (goods) or SAC (services) code: 4-8 digits, or blank.
HsnCode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^([0-9]{4,8})?$")]


def _gstin(value: str | None) -> str | None:
    if value is not None and not GSTIN_RE.match(value):
        raise ValueError("Enter a valid 15-character GSTIN, e.g. 27AAALM4691H1ZS")
    return value


# Blank means "no GSTIN" (individual customers).
Gstin = Annotated[
    str | None,
    BeforeValidator(lambda v: (v.strip().upper() or None) if isinstance(v, str) else v),
    AfterValidator(_gstin),
]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


class In(BaseModel):
    model_config = ConfigDict(protected_namespaces=())


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class UserRef(ORM):
    id: int
    full_name: str


class ReasonIn(BaseModel):
    reason: Reason


class Stamp(ORM):
    created_at: datetime
