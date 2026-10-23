from app.models.base import Base
from app.models.billing import (
    CustomerApproval,
    CustomerFeedback,
    Estimate,
    EstimateLine,
    Invoice,
    InvoiceLine,
    Payment,
    TaxRate,
)
from app.models.comms import (
    CommunicationAttempt,
    DeliveryJob,
    InvoiceLink,
    Notification,
    WebhookEvent,
)
from app.models.customer import Customer, CustomerConsent, Vehicle, VehicleModel
from app.models.inventory import (
    InventoryMovement,
    InventoryStock,
    Part,
    PartCategory,
    PartsRequest,
    PartsRequestLine,
    PurchaseRequest,
    PurchaseRequestLine,
    Supplier,
    part_compatibility,
)
from app.models.job import (
    Inspection,
    JobAssignment,
    JobEvent,
    JobLabour,
    JobManualPart,
    JobPhoto,
    LabourOperation,
    QualityChecklistItem,
    QualityInspection,
    QualityInspectionResult,
    ServiceJob,
    WorkCompletion,
)
from app.models.system import AuditLog, DocumentCounter, Setting
from app.models.user import Permission, RefreshToken, Role, User, role_permissions

__all__ = [name for name in dir() if not name.startswith("_")]
