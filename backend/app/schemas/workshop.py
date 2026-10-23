from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, StringConstraints, field_validator, model_validator

from app.core.utils import normalise_indian_mobile, normalise_registration
from app.models.enums import JobType, QualityResult, Urgency
from app.schemas.admin import VehicleModelOut
from app.schemas.common import ORM, Gstin, HsnCode, In, NonNegMoney, Name, PositiveQty, Reason, Str, Text, UserRef

FuelLevel = Literal["EMPTY", "QUARTER", "HALF", "THREE_QUARTER", "FULL"]
Mobile = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=20)]


def _mobile(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    normalised = normalise_indian_mobile(value)
    if normalised is None:
        raise ValueError("Enter a valid 10-digit Indian mobile number")
    return normalised


# --- Customers & vehicles ---------------------------------------------------------------


class CustomerIn(BaseModel):
    name: Name
    mobile: Mobile
    email: EmailStr  # required: invoices are sent by email
    alternate_mobile: str | None = None
    billing_address: Text = ""
    gstin: Gstin | None = None
    email_opt_in: bool = True
    sms_opt_in: bool = True
    whatsapp_opt_in: bool = True

    _m = field_validator("mobile", "alternate_mobile")(_mobile)

    @field_validator("email", mode="before")
    @classmethod
    def _blank_email(cls, v):
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError("Email address is required")
        return v


class CustomerUpdate(BaseModel):
    name: Name | None = None
    mobile: Mobile | None = None
    email: EmailStr | None = None
    alternate_mobile: str | None = None
    billing_address: Text | None = None
    gstin: Gstin | None = None
    email_opt_in: bool | None = None
    sms_opt_in: bool | None = None
    whatsapp_opt_in: bool | None = None

    _m = field_validator("mobile", "alternate_mobile")(_mobile)

    @field_validator("email", mode="before")
    @classmethod
    def _blank_email(cls, v):
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError("Email address is required")
        return v


class ConsentOut(ORM):
    id: int
    channel: str
    purpose: str
    granted: bool
    source: str
    recorded_at: datetime


class CustomerOut(ORM):
    id: int
    code: str
    name: str
    mobile: str
    email: str | None
    alternate_mobile: str | None
    billing_address: str
    gstin: str | None
    email_opt_in: bool
    sms_opt_in: bool
    whatsapp_opt_in: bool
    created_at: datetime


class CustomerDetail(CustomerOut):
    vehicles: list["VehicleBrief"]
    consents: list[ConsentOut]


class VehicleBrief(ORM):
    id: int
    registration_number: str
    model: VehicleModelOut
    vin: str | None
    engine_number: str | None
    odometer: int
    is_active: bool


class VehicleOut(VehicleBrief):
    customer: CustomerOut
    created_at: datetime


class VehicleIn(In):
    registration_number: Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=20)]
    model_id: int
    customer_id: int
    vin: Str | None = None
    engine_number: Str | None = None
    odometer: Annotated[int, Field(ge=0, le=5_000_000)] = 0

    @field_validator("registration_number")
    @classmethod
    def _reg(cls, v: str) -> str:
        v = normalise_registration(v)
        if len(v) < 4:
            raise ValueError("Enter a valid registration number")
        return v

    @field_validator("vin", "engine_number")
    @classmethod
    def _upper(cls, v):
        return v.upper() if v else None


class VehicleUpdate(In):
    model_id: int | None = None
    customer_id: int | None = None
    vin: Str | None = None
    engine_number: Str | None = None
    is_active: bool | None = None


# --- Jobs -------------------------------------------------------------------------------


class JobCreate(BaseModel):
    vehicle_id: int
    odometer: Annotated[int, Field(ge=0, le=5_000_000)]
    fuel_level: FuelLevel
    complaints: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=4000)]
    condition_notes: Text = ""
    priority: Urgency = Urgency.NORMAL
    job_type: JobType = JobType.PAID
    estimated_completion_at: datetime | None = None
    mechanic_id: int | None = None
    override_reason: Text | None = None


class DirectBillIn(BaseModel):
    """What was done, for the job card and the invoice record."""

    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=4000)]


class DirectBillNewIn(DirectBillIn):
    """Direct billing for a vehicle without an open job: a job card is created first."""

    odometer: Annotated[int, Field(ge=0, le=5_000_000)]
    fuel_level: FuelLevel = "HALF"
    override_reason: Text | None = None


class JobUpdate(BaseModel):
    odometer: Annotated[int, Field(ge=0, le=5_000_000)] | None = None
    fuel_level: FuelLevel | None = None
    complaints: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=4000)] | None = None
    condition_notes: Text | None = None
    priority: Urgency | None = None
    job_type: JobType | None = None
    estimated_completion_at: datetime | None = None


class LabourUpdate(BaseModel):
    estimated_hours: Annotated[Decimal, Field(gt=0, le=200, max_digits=6, decimal_places=2)] | None = None
    notes: Text | None = None


class CompletionUpdate(BaseModel):
    repairs_completed: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=4000)] | None = None
    outstanding_issues: Text | None = None
    final_observations: Text | None = None


class PartsLineUpdate(BaseModel):
    quantity: PositiveQty | None = None
    urgency: Urgency | None = None
    notes: Text | None = None


class JobSummary(ORM):
    id: int
    job_number: str
    status: str
    priority: str
    job_type: str
    visit_at: datetime
    odometer: int
    complaints: str
    estimated_completion_at: datetime | None
    rework_count: int
    returned_for_rework: bool
    customer: CustomerOut
    vehicle: VehicleBrief
    assigned_mechanic: UserRef | None


class EventOut(ORM):
    id: int
    event_type: str
    message: str
    from_status: str | None
    to_status: str | None
    actor: UserRef | None
    created_at: datetime


class PhotoOut(ORM):
    id: int
    original_name: str
    content_type: str
    size_bytes: int
    created_at: datetime


class InspectionIn(BaseModel):
    initial_observations: Text = ""
    diagnostic_findings: Text = ""
    recommended_repairs: Text = ""
    spare_parts_notes: Text = ""
    safety_observations: Text = ""
    additional_recommendations: Text = ""
    mechanic_notes: Text = ""
    priority: Urgency = Urgency.NORMAL


class InspectionOut(InspectionIn, ORM):
    id: int
    submitted_at: datetime | None
    updated_at: datetime
    spare_parts_status: str
    spare_parts_done_at: datetime | None
    spare_parts_done_note: str
    spare_parts_unconfirmed: str


class SparePartsListOut(BaseModel):
    """The mechanic's written spare parts list, as inventory sees it."""

    job_id: int
    job_number: str
    job_status: str
    registration_number: str
    model_name: str
    mechanic_name: str | None
    notes: str
    status: str
    submitted_at: datetime | None
    done_by_name: str | None
    done_at: datetime | None
    done_note: str
    unconfirmed: str = ""
    parts: list["ManualPartOut"] = []


class ManualPartIn(BaseModel):
    """A part inventory found on the shelf for the written list. With `part_id` the rate, HSN,
    unit and tax come from the catalogue; otherwise `unit_price` must be entered."""

    part_id: int | None = None
    description: Name
    quantity: PositiveQty
    unit: Annotated[str, StringConstraints(strip_whitespace=True, max_length=10)] = "NO"
    unit_price: NonNegMoney | None = None
    hsn_code: HsnCode = ""
    tax_rate_id: int | None = None

    @model_validator(mode="after")
    def _priced(self):
        if self.part_id is None and self.unit_price is None:
            raise ValueError("Pick the part from the catalogue or enter its rate")
        return self


class PartRef(ORM):
    id: int
    sku: str
    name: str


class TaxRateBrief(ORM):
    id: int
    name: str
    rate: Decimal


class ManualPartOut(ORM):
    id: int
    part_id: int | None
    part: PartRef | None
    description: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    hsn_code: str
    tax_rate_id: int | None
    tax_rate: TaxRateBrief | None


class SparePartsAvailableIn(BaseModel):
    lines: Annotated[list[ManualPartIn], Field(min_length=1)]
    note: Text = ""


class SparePartsUnavailableIn(BaseModel):
    note: Reason


class AdditionalPartsIn(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=4000)]


class LabourIn(BaseModel):
    labour_operation_id: int
    estimated_hours: Annotated[Decimal, Field(gt=0, le=200, max_digits=6, decimal_places=2)] | None = None
    notes: Text = ""


class LabourOut(ORM):
    id: int
    code: str
    description: str
    estimated_hours: Decimal
    actual_hours: Decimal | None
    hourly_rate: Decimal
    approval_status: str
    is_additional: bool
    notes: str


class PartsRequestLineIn(BaseModel):
    part_id: int
    quantity: PositiveQty
    urgency: Urgency = Urgency.NORMAL
    notes: Text = ""


class PartsRequestIn(BaseModel):
    lines: Annotated[list[PartsRequestLineIn], Field(min_length=1, max_length=50)]
    notes: Text = ""


class PartRef(ORM):
    id: int
    sku: str
    name: str
    selling_price: Decimal
    storage_location: str


class PartsLineOut(ORM):
    id: int
    request_id: int
    part: PartRef
    original_part: PartRef | None
    alt_part: PartRef | None
    alt_status: str | None
    alt_notes: str
    qty_requested: Decimal
    qty_approved: Decimal
    qty_reserved: Decimal
    qty_issued: Decimal
    qty_returned: Decimal
    qty_consumed: Decimal | None
    qty_outstanding: Decimal
    qty_unreconciled: Decimal
    urgency: str
    notes: str
    status: str
    approval_status: str
    is_short: bool
    expected_restock_date: date | None
    inventory_notes: str
    cancel_reason: str | None


class PartsRequestOut(ORM):
    id: int
    request_number: str
    job_id: int
    status: str
    is_additional: bool
    notes: str
    created_at: datetime
    requested_by: UserRef
    lines: list[PartsLineOut]


class CompletionLabourIn(BaseModel):
    labour_id: int
    actual_hours: Annotated[Decimal, Field(ge=0, le=500, max_digits=6, decimal_places=2)]


class CompletionPartIn(BaseModel):
    line_id: int
    qty_consumed: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]


class CompletionIn(BaseModel):
    repairs_completed: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=4000)]
    outstanding_issues: Text = ""
    final_observations: Text = ""
    labour: list[CompletionLabourIn] = []
    parts: list[CompletionPartIn] = []


class CompletionOut(ORM):
    id: int
    repairs_completed: str
    outstanding_issues: str
    final_observations: str
    completed_at: datetime
    mechanic: UserRef


class QualityItemIn(BaseModel):
    checklist_item_id: int
    passed: bool | None = None
    notes: Text = ""


class QualityIn(BaseModel):
    result: QualityResult
    reason: Text = ""
    road_test_notes: Text = ""
    items: list[QualityItemIn] = []


class QualityResultOut(ORM):
    checklist_item_id: int
    label: str
    passed: bool | None
    notes: str


class QualityOut(ORM):
    id: int
    result: str
    reason: str
    road_test_notes: str
    created_at: datetime
    inspector: UserRef
    results: list[QualityResultOut]


class AssignIn(BaseModel):
    mechanic_id: int
    notes: Text = ""


class HandoverIn(BaseModel):
    received_by: Name
    notes: Text = ""
    allow_outstanding: bool = False


class CancelLineIn(BaseModel):
    reason: Reason


CustomerDetail.model_rebuild()
