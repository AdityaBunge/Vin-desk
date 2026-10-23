"""The permission matrix. Synced into the roles/permissions tables by `ensure_reference_data`;
request-time checks read the database rows, so this file is the single place to change access."""
from app.models.enums import RoleCode

SM, MECH, INV, ADMIN = (
    RoleCode.SERVICE_MANAGER,
    RoleCode.MECHANIC,
    RoleCode.INVENTORY_STAFF,
    RoleCode.ADMIN,
)

ROLES = {
    SM: ("Service Manager", "Reception, workshop coordination, billing and reports"),
    MECH: ("Mechanic", "Inspection, diagnosis and repair of assigned jobs"),
    INV: ("Inventory Staff", "Spare-parts stock, fulfilment and purchase requests"),
    ADMIN: ("Administrator", "Users, master data, settings and audit logs"),
}

# permission code -> (description, roles)
PERMISSIONS: dict[str, tuple[str, tuple[RoleCode, ...]]] = {
    "masterdata.read": ("Read vehicle models, labour catalogue, tax rates", (SM, MECH, INV, ADMIN)),
    "masterdata.manage": ("Manage vehicle models, categories, labour, tax, checklist", (ADMIN,)),
    "user.manage": ("Create, deactivate and assign roles to users", (ADMIN,)),
    "settings.manage": ("Manage service-centre and communication settings", (ADMIN,)),
    "audit.read": ("View audit logs", (ADMIN,)),
    "staff.read": ("List mechanics for assignment", (SM, ADMIN)),
    "reception.manage": ("Register customers, vehicles and service visits", (SM,)),
    "customer.read": ("Search customers and vehicles", (SM,)),
    "job.read_all": ("View all job cards", (SM,)),
    "job.read_assigned": ("View job cards assigned to self", (MECH,)),
    "job.assign": ("Assign jobs to mechanics", (SM,)),
    # Mechanics do not sign in: the Service Manager records the inspection and work for them.
    "job.work": ("Record inspection, labour, parts requests and completion", (SM,)),
    "job.manage": ("Hold, cancel, return, mark ready and hand over jobs", (SM,)),
    "parts.read": ("Search the parts catalogue and availability", (SM, MECH, INV, ADMIN)),
    "parts.manage": ("Maintain the parts catalogue and suppliers", (INV, ADMIN)),
    "inventory.read": ("View parts requests and stock movements", (SM, INV)),
    "inventory.fulfil": ("Reserve, issue and return parts against job cards", (INV,)),
    "inventory.adjust": ("Record stock receipts, adjustments and write-offs", (INV,)),
    "purchase.create": ("Create purchase requests", (INV,)),
    "purchase.approve": ("Approve or reject purchase requests", (SM,)),
    "alternative.approve": ("Approve alternative parts", (SM,)),
    "estimate.manage": ("Prepare estimates (quotes)", (SM,)),
    "invoice.read": ("View invoices", (SM,)),
    "invoice.manage": ("Prepare, finalise and cancel invoices", (SM,)),
    "payment.record": ("Record and void payments", (SM,)),
    "delivery.manage": ("View, retry and resend invoice deliveries", (SM,)),
    "report.view": ("View business reports", (SM,)),
    "report.inventory": ("View inventory reports", (SM, INV)),
    "dealer.dashboard": ("View the dealer dashboard (sales, dues, stock value, margins)", (SM, ADMIN)),
}
