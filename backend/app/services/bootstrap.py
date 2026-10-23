"""Idempotent reference data: roles, permissions and first-run master data."""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import PERMISSIONS, ROLES
from app.models import Permission, Role, TaxRate, VehicleModel

VEHICLE_MODELS = [
    "Force Gurkha", "Force Urbania", "Force Trax Cruiser", "Force Trax Toofan", "Force Traveller", "Force Monobus",
]
TAX_RATES = [("GST 18%", "18"), ("GST 28%", "28"), ("GST 12%", "12"), ("GST 5%", "5"), ("Exempt", "0")]


def ensure_reference_data(db: Session) -> None:
    roles = {r.code: r for r in db.scalars(select(Role))}
    for code, (name, description) in ROLES.items():
        if code not in roles:
            roles[code] = Role(code=code, name=name, description=description)
            db.add(roles[code])
    perms = {p.code: p for p in db.scalars(select(Permission))}
    for code, (description, _) in PERMISSIONS.items():
        if code not in perms:
            perms[code] = Permission(code=code, description=description)
            db.add(perms[code])
    db.flush()
    for role_code, role in roles.items():
        wanted = [perms[code] for code, (_, allowed) in PERMISSIONS.items() if role_code in allowed]
        if {p.code for p in role.permissions} != {p.code for p in wanted}:
            role.permissions = wanted

    if db.scalar(select(VehicleModel.id).limit(1)) is None:
        for order, name in enumerate(VEHICLE_MODELS, start=1):
            db.add(VehicleModel(name=name, sort_order=order))
    if db.scalar(select(TaxRate.id).limit(1)) is None:
        for name, rate in TAX_RATES:
            db.add(TaxRate(name=name, rate=Decimal(rate)))
    db.flush()
