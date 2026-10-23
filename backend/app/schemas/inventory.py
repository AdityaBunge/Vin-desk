from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.admin import CategoryOut, TaxRateOut, VehicleModelOut
from app.schemas.common import ORM, HsnCode, Name, NonNegMoney, PositiveQty, Reason, Str, Text, UserRef
from app.schemas.workshop import PartsRequestOut

Sku = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=2, max_length=40)]
NonNegQty = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]


class SupplierOut(ORM):
    id: int
    name: str
    contact_name: str
    phone: str
    email: str
    address: str
    is_active: bool


class SupplierIn(BaseModel):
    name: Name
    contact_name: Str = ""
    phone: Str = ""
    email: Str = ""
    address: Str = ""
    is_active: bool = True


class StockOut(ORM):
    qty_on_hand: Decimal
    qty_reserved: Decimal
    qty_available: Decimal


class PartOut(ORM):
    id: int
    sku: str
    name: str
    description: str
    category: CategoryOut | None
    purchase_cost: Decimal
    selling_price: Decimal
    tax_rate: TaxRateOut | None
    reorder_threshold: Decimal
    supplier: SupplierOut | None
    storage_location: str
    hsn_code: str
    unit: str
    is_active: bool
    stock: StockOut
    compatible_models: list[VehicleModelOut]
    dms_bin: str
    dms_category: str
    movement_class: str
    abc_class: str
    hml_class: str
    ris_class: str
    sheet_closing_qty: Decimal | None
    sheet_closing_value: Decimal | None
    sheet_actual_qty: Decimal | None


class PartMechanicOut(ORM):
    """Catalogue view without purchase cost or supplier (for mechanics)."""

    id: int
    sku: str
    name: str
    description: str
    category: CategoryOut | None
    selling_price: Decimal
    storage_location: str
    is_active: bool
    stock: StockOut
    compatible_models: list[VehicleModelOut]


class PartIn(BaseModel):
    sku: Sku
    name: Name
    description: Str = ""
    category_id: int | None = None
    purchase_cost: NonNegMoney = Decimal("0")
    selling_price: NonNegMoney
    tax_rate_id: int | None = None
    reorder_threshold: NonNegQty = Decimal("0")
    supplier_id: int | None = None
    storage_location: Str = ""
    hsn_code: HsnCode = ""
    unit: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10)] = "NO"
    is_active: bool = True
    compatible_model_ids: list[int] = []


class QtyIn(BaseModel):
    quantity: PositiveQty
    reason: Text = ""


class AdjustIn(BaseModel):
    delta: Annotated[Decimal, Field(max_digits=12, decimal_places=2)]
    reason: Reason


class WriteOffIn(BaseModel):
    quantity: PositiveQty
    reason: Reason


class UnavailableIn(BaseModel):
    expected_restock_date: date | None = None
    notes: Text = ""


class AlternativeIn(BaseModel):
    part_id: int
    notes: Text = ""


class DecisionIn(BaseModel):
    approve: bool
    notes: Text = ""


class MovementOut(ORM):
    id: int
    part: "MovementPart"
    movement_type: str
    quantity: Decimal
    on_hand_after: Decimal
    reserved_after: Decimal
    job_id: int | None
    job_number: str | None = None
    reason: str
    performed_by: UserRef
    created_at: datetime


class MovementPart(ORM):
    id: int
    sku: str
    name: str


class JobRef(ORM):
    id: int
    job_number: str
    status: str
    registration_number: str
    model_name: str
    mechanic_name: str | None


class PartsRequestQueueOut(PartsRequestOut):
    job: JobRef


class PurchaseLineIn(BaseModel):
    part_id: int
    quantity: PositiveQty
    unit_cost: NonNegMoney | None = None
    parts_request_line_id: int | None = None


class PurchaseRequestIn(BaseModel):
    supplier_id: int | None = None
    notes: Text = ""
    lines: Annotated[list[PurchaseLineIn], Field(min_length=1, max_length=100)]


class PurchaseLineOut(ORM):
    id: int
    part: MovementPart
    quantity: Decimal
    qty_received: Decimal
    unit_cost: Decimal
    parts_request_line_id: int | None


class PurchaseRequestOut(ORM):
    id: int
    pr_number: str
    status: str
    notes: str
    supplier: SupplierOut | None
    created_by: UserRef
    decided_by: UserRef | None
    decided_at: datetime | None
    decision_notes: str
    received_at: datetime | None
    created_at: datetime
    lines: list[PurchaseLineOut]


class ReceiveLineIn(BaseModel):
    line_id: int
    quantity: PositiveQty


class ReceiveIn(BaseModel):
    lines: list[ReceiveLineIn] | None = None


MovementOut.model_rebuild()
