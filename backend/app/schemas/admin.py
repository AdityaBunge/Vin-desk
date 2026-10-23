from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, StringConstraints

from app.models.enums import RoleCode
from app.schemas.common import ORM, HsnCode, Name, NonNegMoney, Str

Password = Annotated[str, StringConstraints(min_length=10, max_length=72)]
# WhatsApp Manager allows only lower-case letters, digits and underscores in template names.
WhatsAppTemplate = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9_]{1,512}$")]


class LoginIn(BaseModel):
    # Plain string: sign-in must work for any stored address (e.g. *.local demo accounts).
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=72)]


class UserOut(ORM):
    id: int
    email: str
    full_name: str
    phone: str | None
    role_code: str
    is_active: bool
    is_demo: bool
    last_login_at: datetime | None
    created_at: datetime


class MeOut(UserOut):
    permissions: list[str]


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: MeOut


class UserCreate(BaseModel):
    email: EmailStr
    full_name: Name
    phone: Str | None = None
    role_code: RoleCode
    password: Password


class UserUpdate(BaseModel):
    full_name: Name | None = None
    phone: Str | None = None
    role_code: RoleCode | None = None
    is_active: bool | None = None
    password: Password | None = None


class VehicleModelOut(ORM):
    id: int
    name: str
    is_active: bool
    sort_order: int


class VehicleModelIn(BaseModel):
    name: Name
    is_active: bool = True
    sort_order: int = 0


class TaxRateOut(ORM):
    id: int
    name: str
    rate: Decimal
    is_active: bool


class TaxRateIn(BaseModel):
    name: Name
    rate: Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]
    is_active: bool = True


class CategoryOut(ORM):
    id: int
    name: str
    is_active: bool


class CategoryIn(BaseModel):
    name: Name
    is_active: bool = True


class LabourOpOut(ORM):
    id: int
    code: str
    name: str
    description: str
    default_hours: Decimal
    hourly_rate: Decimal
    tax_rate_id: int | None
    tax_rate: TaxRateOut | None
    sac_code: str
    is_active: bool


class LabourOpIn(BaseModel):
    code: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=2, max_length=30)]
    name: Name
    description: Str = ""
    default_hours: Annotated[Decimal, Field(gt=0, le=200, max_digits=6, decimal_places=2)]
    hourly_rate: NonNegMoney
    tax_rate_id: int | None = None
    sac_code: HsnCode = ""
    is_active: bool = True


class ChecklistItemOut(ORM):
    id: int
    label: str
    category: str
    is_active: bool
    sort_order: int


class ChecklistItemIn(BaseModel):
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
    category: Str = "GENERAL"
    is_active: bool = True
    sort_order: int = 0


class SettingsIn(BaseModel):
    centre_name: Name | None = None
    centre_name_with_fy: bool | None = None
    centre_address: Str | None = None
    centre_phone: Str | None = None
    centre_email: Str | None = None
    centre_gstin: Str | None = None
    centre_other_registration: Str | None = None
    centre_pan: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^([A-Za-z]{5}[0-9]{4}[A-Za-z])?$")] | None = None
    centre_state_name: Str | None = None
    centre_state_code: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^([0-9]{2})?$")] | None = None
    invoice_declaration: Str | None = None
    default_labour_sac: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^([0-9]{4,8})?$")] | None = None
    job_number_prefix: Annotated[str, StringConstraints(pattern=r"^[A-Z]{1,6}$")] | None = None
    invoice_number_prefix: Annotated[str, StringConstraints(pattern=r"^[A-Z]{1,6}$")] | None = None
    gst_split_intra_state: bool | None = None
    max_discount_percent: Annotated[float, Field(ge=0, le=100)] | None = None
    invoice_terms: Str | None = None
    estimate_terms: Str | None = None
    email_sender_name: Str | None = None
    sms_sender_id: Annotated[str, StringConstraints(strip_whitespace=True, max_length=11)] | None = None
    sms_template_id: Str | None = None
    sms_dlt_entity_id: Str | None = None
    public_base_url: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^(https?://\S+)?$")] | None = None
    invoice_link_expiry_days: Annotated[int, Field(ge=1, le=365)] | None = None
    delivery_max_attempts: Annotated[int, Field(ge=1, le=10)] | None = None
    delivery_backoff_base_seconds: Annotated[int, Field(ge=5, le=3600)] | None = None
    manual_resend_limit_per_hour: Annotated[int, Field(ge=1, le=20)] | None = None
    whatsapp_invoice_template: WhatsAppTemplate | None = None
    whatsapp_payment_reminder_template: WhatsAppTemplate | None = None
    whatsapp_service_reminder_template: WhatsAppTemplate | None = None
    whatsapp_template_language: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z]{2,3}(_[A-Z]{2})?$")] | None = None
    payment_reminder_enabled: bool | None = None
    payment_reminder_after_days: Annotated[int, Field(ge=0, le=90)] | None = None
    payment_reminder_every_days: Annotated[int, Field(ge=1, le=90)] | None = None
    payment_reminder_max: Annotated[int, Field(ge=1, le=10)] | None = None
    service_reminder_enabled: bool | None = None
    service_reminder_days_before: Annotated[int, Field(ge=0, le=60)] | None = None
    monthly_revenue_target: Annotated[float, Field(ge=0, le=1e10)] | None = None
    monthly_vehicles_target: Annotated[int, Field(ge=0, le=100000)] | None = None
    service_interval_days: Annotated[int, Field(ge=30, le=730)] | None = None


class DealerTargetsIn(BaseModel):
    monthly_revenue_target: Annotated[float, Field(ge=0, le=1e10)]
    monthly_vehicles_target: Annotated[int, Field(ge=0, le=100000)]
    service_interval_days: Annotated[int, Field(ge=30, le=730)]


class AuditOut(ORM):
    id: int
    actor_email: str
    actor_role: str
    action: str
    entity_type: str
    entity_id: str | None
    summary: str
    details: dict | None
    created_at: datetime


class NotificationOut(ORM):
    id: int
    type: str
    title: str
    message: str
    entity_type: str | None
    entity_id: int | None
    is_read: bool
    created_at: datetime
