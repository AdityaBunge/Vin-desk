"""Non-secret application settings stored in the database, with defaults.

Credentials (SMTP password, SMS auth key, webhook secret, JWT secret) are environment-only and
are reported by the API solely as "configured: true/false".
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.utils import financial_year_suffix
from app.models import Setting, User

INDIA = ZoneInfo("Asia/Kolkata")

DEFAULTS: dict[str, object] = {
    # Service centre
    # The business's own details, exactly as on its invoices. Change them in Admin > Settings.
    "centre_name": "Positive Sales",
    "centre_name_with_fy": True,  # print " F.Y:26-27 - (from 1-Apr-26)" after the name, for the invoice's date
    "centre_address": "AUTHORISED DEALR FORCE MOTORS\nPlot number 350/2/2\nChhatrapati Sambhaji Nagar Road\nOpposite infra,market mirchi hotel signal, panchvati Nashik422003\nGST No.: 27FDCPB5213C1Z8",
    "centre_phone": "",
    "centre_email": "gurkhanashik@gmail.com",
    "centre_gstin": "27FDCPB5213C1Z8",
    "centre_other_registration": "",
    "centre_pan": "AAVFB6252C",
    "centre_state_name": "Maharashtra",
    "centre_state_code": "27",
    # Numbering
    "job_number_prefix": "SC",
    "invoice_number_prefix": "INV",
    # Billing
    "gst_split_intra_state": True,  # show GST as CGST + SGST halves
    "max_discount_percent": 10,
    "invoice_terms": "",  # the business's invoices carry only the declaration
    "invoice_declaration": "We declare that this invoice shows the actual price of the goods described and that all particulars are true and correct.",
    "default_labour_sac": "998714",  # SAC for maintenance and repair of motor vehicles
    "estimate_terms": "This is an estimate; the final amount may vary with actual parts and labour used.",
    # Communication (non-secret)
    "email_sender_name": "",
    "sms_sender_id": "",
    "sms_template_id": "",
    "sms_dlt_entity_id": "",
    "public_base_url": "",
    "invoice_link_expiry_days": 30,
    "delivery_max_attempts": 5,
    "delivery_backoff_base_seconds": 60,
    "manual_resend_limit_per_hour": 3,
    # WhatsApp templates: names exactly as approved in WhatsApp Manager (see docs/deployment.md
    # for the variables each one must take, in order).
    "whatsapp_invoice_template": "invoice_ready",
    "whatsapp_payment_reminder_template": "payment_reminder",
    "whatsapp_service_reminder_template": "service_reminder",
    "whatsapp_template_language": "en",
    # Payment-due reminders on WhatsApp for finalised invoices with an outstanding balance.
    "payment_reminder_enabled": True,
    "payment_reminder_after_days": 3,  # first reminder this long after the invoice
    "payment_reminder_every_days": 7,  # then again this often
    "payment_reminder_max": 3,  # automatic reminders per invoice
    # Service-due reminders on WhatsApp, `service_interval_days` after the last visit.
    "service_reminder_enabled": True,
    "service_reminder_days_before": 7,
    # Dealer dashboard
    "monthly_revenue_target": 0,  # rupees incl. GST; 0 = no target
    "monthly_vehicles_target": 0,  # vehicles delivered; 0 = no target
    "service_interval_days": 180,  # a vehicle is due for service this long after its last visit
}


def get_all(db: Session) -> dict[str, object]:
    values = dict(DEFAULTS)
    for row in db.query(Setting).all():
        if row.key in DEFAULTS:
            values[row.key] = row.value
    return values


def get(db: Session, key: str):
    row = db.get(Setting, key)
    return row.value if row is not None else DEFAULTS[key]


def set_many(db: Session, values: dict[str, object], user: User | None) -> dict[str, list]:
    """Returns {key: [old, new]} for changed keys (for the audit trail)."""
    changes: dict[str, list] = {}
    current = get_all(db)
    for key, value in values.items():
        if key not in DEFAULTS or current[key] == value:
            continue
        row = db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value=value, updated_by_id=user.id if user else None))
        else:
            row.value = value
            row.updated_by_id = user.id if user else None
        changes[key] = [current[key], value]
    return changes


def public_base_url(db: Session) -> str:
    return (get(db, "public_base_url") or get_settings().public_base_url).rstrip("/")


def centre_display_name(values: dict, on: date | None = None) -> str:
    """The business name as printed, with the financial year of `on` (default: today in India)."""
    name = str(values["centre_name"]).strip()
    if values.get("centre_name_with_fy"):
        name = f"{name} {financial_year_suffix(on or datetime.now(INDIA).date())}"
    return name


def centre_snapshot(db: Session, on: date | None = None) -> dict:
    """Centre details frozen onto an invoice; the financial year is that of the invoice date."""
    s = get_all(db)
    return {
        "name": centre_display_name(s, on),
        "address": s["centre_address"],
        "phone": s["centre_phone"],
        "email": s["centre_email"],
        "gstin": s["centre_gstin"],
        "other_registration": s["centre_other_registration"],
        "pan": s["centre_pan"],
        "state_name": s["centre_state_name"],
        "state_code": s["centre_state_code"],
        "declaration": s["invoice_declaration"],
        "default_labour_sac": s["default_labour_sac"],
        "gst_split_intra_state": s["gst_split_intra_state"],
    }
