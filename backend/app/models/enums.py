"""Status vocabularies. Stored as plain strings so adding a value needs no enum migration."""
from enum import StrEnum


class RoleCode(StrEnum):
    SERVICE_MANAGER = "SERVICE_MANAGER"
    MECHANIC = "MECHANIC"
    INVENTORY_STAFF = "INVENTORY_STAFF"
    ADMIN = "ADMIN"


class JobStatus(StrEnum):
    RECEIVED = "RECEIVED"
    AWAITING_ASSIGNMENT = "AWAITING_ASSIGNMENT"
    INSPECTION_IN_PROGRESS = "INSPECTION_IN_PROGRESS"
    AWAITING_ESTIMATE_APPROVAL = "AWAITING_ESTIMATE_APPROVAL"
    AWAITING_PARTS = "AWAITING_PARTS"
    READY_FOR_SERVICE = "READY_FOR_SERVICE"
    IN_SERVICE = "IN_SERVICE"
    AWAITING_QUALITY_CHECK = "AWAITING_QUALITY_CHECK"
    AWAITING_MANAGER_REVIEW = "AWAITING_MANAGER_REVIEW"
    READY_FOR_BILLING = "READY_FOR_BILLING"
    READY_FOR_DELIVERY = "READY_FOR_DELIVERY"
    COMPLETED = "COMPLETED"
    ON_HOLD = "ON_HOLD"
    CANCELLED = "CANCELLED"


CLOSED_JOB_STATUSES = (JobStatus.COMPLETED, JobStatus.CANCELLED)
# From the mechanic's point of view the job is done once the work is handed to the Service Manager.
MECHANIC_DONE_STATUSES = (JobStatus.READY_FOR_BILLING, JobStatus.READY_FOR_DELIVERY, JobStatus.COMPLETED)


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class JobType(StrEnum):
    PAID = "PAID"
    FREE_SERVICE = "FREE_SERVICE"
    WARRANTY = "WARRANTY"
    ACCIDENT = "ACCIDENT"  # accident / insurance repair


class Urgency(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class PartsRequestStatus(StrEnum):
    PENDING = "PENDING"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    FULFILLED = "FULFILLED"
    UNAVAILABLE = "UNAVAILABLE"
    CANCELLED = "CANCELLED"


class PartsLineStatus(StrEnum):
    PENDING = "PENDING"
    PARTIALLY_RESERVED = "PARTIALLY_RESERVED"
    RESERVED = "RESERVED"
    PARTIALLY_ISSUED = "PARTIALLY_ISSUED"
    ISSUED = "ISSUED"
    UNAVAILABLE = "UNAVAILABLE"
    CANCELLED = "CANCELLED"


class AlternativeStatus(StrEnum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class MovementType(StrEnum):
    RECEIVED = "RECEIVED"
    RESERVED = "RESERVED"
    ISSUED = "ISSUED"
    RETURNED = "RETURNED"
    RESERVATION_RELEASED = "RESERVATION_RELEASED"
    ADJUSTMENT = "ADJUSTMENT"
    WRITE_OFF = "WRITE_OFF"


class PurchaseRequestStatus(StrEnum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"


class EstimateStatus(StrEnum):
    DRAFT = "DRAFT"
    AWAITING_CUSTOMER_APPROVAL = "AWAITING_CUSTOMER_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class LineType(StrEnum):
    LABOUR = "LABOUR"
    PART = "PART"


class QualityResult(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class InvoiceStatus(StrEnum):
    DRAFT = "DRAFT"
    FINALISED = "FINALISED"
    CANCELLED = "CANCELLED"


class PaymentStatus(StrEnum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


class PaymentMethod(StrEnum):
    CASH = "CASH"
    CARD = "CARD"
    UPI = "UPI"
    BANK_TRANSFER = "BANK_TRANSFER"


class Channel(StrEnum):
    EMAIL = "EMAIL"
    SMS = "SMS"
    WHATSAPP = "WHATSAPP"


class DeliveryKind(StrEnum):
    """What a delivery job sends. Reminders go by WhatsApp only."""

    INVOICE = "INVOICE"
    PAYMENT_REMINDER = "PAYMENT_REMINDER"  # finalised invoice with an outstanding balance
    SERVICE_REMINDER = "SERVICE_REMINDER"  # vehicle approaching its next periodic service


class DeliveryStatus(StrEnum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


ACTIVE_DELIVERY_STATUSES = (
    DeliveryStatus.PENDING,
    DeliveryStatus.QUEUED,
    DeliveryStatus.RETRY_SCHEDULED,
)


class AttemptOutcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    TEMPORARY_FAILURE = "TEMPORARY_FAILURE"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"
