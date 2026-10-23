"""Reference data and development demo data.

    python -m app.seed --reference-only                 # roles, permissions, models, tax, checklist
    python -m app.seed                                  # + demo users, parts, customers, sample jobs
    python -m app.seed --create-admin EMAIL "Full Name" # first administrator (prompts for password)

Demo accounts use published passwords, so demo seeding is refused when APP_ENV=production and
demo accounts cannot sign in there.
"""
import argparse
import getpass
import sys
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import (
    Customer,
    CustomerConsent,
    InventoryStock,
    LabourOperation,
    Part,
    PartCategory,
    Role,
    Supplier,
    TaxRate,
    User,
    Vehicle,
    VehicleModel,
)
from app.models.enums import RoleCode
from app.services import inventory
from app.services import jobs as jobs_service
from app.services import settings as settings_service
from app.services.bootstrap import ensure_reference_data
from app.services.common import next_number

DEMO_PASSWORD = "Demo@12345"
DEMO_USERS = [
    ("manager@demo.local", "Meera Kulkarni", RoleCode.SERVICE_MANAGER),
    ("mechanic@demo.local", "Ravi Patil", RoleCode.MECHANIC),
    ("mechanic2@demo.local", "Imran Shaikh", RoleCode.MECHANIC),
    ("inventory@demo.local", "Sunita Joshi", RoleCode.INVENTORY_STAFF),
    ("admin@demo.local", "Arjun Deshmukh", RoleCode.ADMIN),
]
LABOUR = [  # code, name, hours, rate, tax
    ("LAB-GS", "General service (oil and filters)", "2.0", "650", "GST 18%"),
    ("LAB-BRK-F", "Front brake pad replacement", "1.5", "650", "GST 18%"),
    ("LAB-BRK-R", "Rear brake shoe replacement", "2.0", "650", "GST 18%"),
    ("LAB-CLU", "Clutch plate replacement", "5.0", "750", "GST 18%"),
    ("LAB-SUS", "Suspension inspection and repair", "3.0", "700", "GST 18%"),
    ("LAB-AC", "AC service and gas top-up", "1.5", "800", "GST 18%"),
    ("LAB-WA", "Wheel alignment and balancing", "1.0", "600", "GST 18%"),
    ("LAB-DIAG", "Electrical / ECU diagnosis", "1.0", "900", "GST 18%"),
    ("LAB-INJ", "Injector cleaning and calibration", "3.0", "850", "GST 18%"),
]
PARTS = [  # sku, name, category, cost, price, tax, on hand, reorder, location, models ("*" = all)
    ("FM-OIL-15W40-5L", "Engine oil 15W-40 (5 L)", "Lubricants", "1450", "1950", "GST 18%", 24, 6, "A1-01", "*"),
    ("FM-FLT-OIL-01", "Oil filter", "Filters", "210", "340", "GST 18%", 30, 8, "A1-02", "*"),
    ("FM-FLT-AIR-01", "Air filter element", "Filters", "380", "590", "GST 18%", 18, 5, "A1-03", "*"),
    ("FM-FLT-FUEL-01", "Fuel filter", "Filters", "420", "650", "GST 18%", 2, 5, "A1-04", "*"),
    ("FM-BRK-PAD-TRV", "Front brake pad set - Traveller", "Brakes", "1650", "2400", "GST 28%", 6, 3, "B2-01", "Force Traveller,Force Urbania"),
    ("FM-BRK-PAD-TRV-HD", "Front brake pad set - Traveller (heavy duty)", "Brakes", "1950", "2850", "GST 28%", 4, 2, "B2-02", "Force Traveller,Force Urbania,Force Monobus"),
    ("FM-BRK-SHOE-TRX", "Rear brake shoe set - Trax", "Brakes", "1250", "1850", "GST 28%", 5, 2, "B2-03", "Force Trax Cruiser,Force Trax Toofan"),
    ("FM-BRK-FLD-DOT4", "Brake fluid DOT 4 (500 ml)", "Lubricants", "190", "320", "GST 18%", 20, 5, "A1-05", "*"),
    ("FM-CLU-KIT-TRV", "Clutch kit - Traveller", "Transmission", "7800", "10900", "GST 28%", 0, 1, "C3-01", "Force Traveller"),
    ("FM-CLU-KIT-GRK", "Clutch kit - Gurkha", "Transmission", "8200", "11500", "GST 28%", 2, 1, "C3-02", "Force Gurkha"),
    ("FM-BLT-FAN-01", "Fan belt", "Engine", "340", "560", "GST 28%", 10, 3, "C3-05", "*"),
    ("FM-WPR-BLD-22", "Wiper blade 22 inch", "Body & electrical", "180", "320", "GST 18%", 12, 4, "D4-01", "*"),
    ("FM-BAT-12V-80", "Battery 12V 80Ah", "Body & electrical", "5600", "7400", "GST 28%", 3, 2, "D4-05", "*"),
    ("FM-CLT-5L", "Coolant concentrate (5 L)", "Lubricants", "780", "1150", "GST 18%", 8, 3, "A1-06", "*"),
    ("FM-SHK-FRT-TRV", "Front shock absorber - Traveller", "Suspension", "2300", "3350", "GST 28%", 4, 2, "E5-01", "Force Traveller,Force Monobus"),
]
# GST HSN code and invoice unit per demo part ("Nos" for fluids, as dealers commonly print).
PART_GST = {
    "FM-OIL-15W40-5L": ("27101980", "Nos"), "FM-FLT-OIL-01": ("84212300", "NO"), "FM-FLT-AIR-01": ("84213100", "NO"),
    "FM-FLT-FUEL-01": ("84212300", "NO"), "FM-BRK-PAD-TRV": ("87083000", "SET"), "FM-BRK-PAD-TRV-HD": ("87083000", "SET"),
    "FM-BRK-SHOE-TRX": ("87083000", "SET"), "FM-BRK-FLD-DOT4": ("38190010", "Nos"), "FM-CLU-KIT-TRV": ("87089300", "SET"),
    "FM-CLU-KIT-GRK": ("87089300", "SET"), "FM-BLT-FAN-01": ("40103999", "NO"), "FM-WPR-BLD-22": ("85129000", "NO"),
    "FM-BAT-12V-80": ("85071000", "NO"), "FM-CLT-5L": ("38200000", "Nos"), "FM-SHK-FRT-TRV": ("87088000", "NO"),
}


def _fill_gst_codes(db: Session) -> None:
    """Give demo parts their HSN code and unit if they have none yet (also upgrades older demo data)."""
    for part in db.scalars(select(Part).where(Part.sku.in_(PART_GST), Part.hsn_code == "")):
        part.hsn_code, part.unit = PART_GST[part.sku]


CUSTOMERS = [  # name, mobile, email, address, [(registration, model, vin, odometer)]
    ("Shree Ganesh Tours & Travels", "9822012345", "accounts@ganeshtours.example", "Plot 14, Bhosari MIDC, Pune 411026",
     [("MH12AB1234", "Force Traveller", "MC1TRV26AB0012345", 84250), ("MH12CD5678", "Force Urbania", "MC1URB24CD0056781", 31200)]),
    ("Prakash Jadhav", "9890123456", "prakash.jadhav@example.com", "Flat 6, Sahyadri Apartments, Kothrud, Pune 411038",
     [("MH14GK4321", "Force Gurkha", "MC1GRK25GK0043210", 18900)]),
    ("Sai Krupa School Transport", "9765432109", "", "Near ZP School, Chakan, Pune 410501",
     [("MH14EF9012", "Force Monobus", None, 126400), ("MH14TX7788", "Force Trax Cruiser", None, 98000)]),
]


def seed_demo(db: Session) -> None:
    if get_settings().is_production:
        raise SystemExit("Demo data cannot be seeded when APP_ENV=production.")
    roles = {r.code: r for r in db.scalars(select(Role))}
    users: dict[str, User] = {}
    for email, name, role in DEMO_USERS:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, full_name=name, role_id=roles[role].id, is_demo=True,
                        password_hash=hash_password(DEMO_PASSWORD))
            db.add(user)
        users[email] = user
    db.flush()
    if db.scalar(select(Part.id).limit(1)) is not None:
        _fill_gst_codes(db)
        db.commit()
        print("Demo master data already present; users ensured.")
        return

    # Business details come from the settings defaults (the real business); the demo does not override them.

    tax = {t.name: t for t in db.scalars(select(TaxRate))}
    models = {m.name: m for m in db.scalars(select(VehicleModel))}
    supplier = Supplier(name="Force Motors Genuine Parts Distributor", contact_name="Parts Desk",
                        phone="+91 20 5550 0199", email="parts@distributor.example", address="Chinchwad, Pune")
    db.add(supplier)
    for code, name, hours, rate, tax_name in LABOUR:
        db.add(LabourOperation(code=code, name=name, default_hours=Decimal(hours), hourly_rate=Decimal(rate), tax_rate=tax[tax_name]))
    categories: dict[str, PartCategory] = {}
    parts: dict[str, Part] = {}
    for sku, name, cat, cost, price, tax_name, _qty, reorder, loc, compat in PARTS:
        if cat not in categories:
            categories[cat] = PartCategory(name=cat)
            db.add(categories[cat])
        part = Part(
            sku=sku, name=name, category=categories[cat], purchase_cost=Decimal(cost), selling_price=Decimal(price),
            tax_rate=tax[tax_name], reorder_threshold=Decimal(reorder), supplier=supplier, storage_location=loc,
            stock=InventoryStock(qty_on_hand=Decimal(0), qty_reserved=Decimal(0)),
            compatible_models=list(models.values()) if compat == "*" else [models[m] for m in compat.split(",")],
        )
        part.hsn_code, part.unit = PART_GST.get(sku, ("", "NO"))
        db.add(part)
        parts[sku] = part
    db.flush()
    inv_user = users["inventory@demo.local"]
    for sku, *_rest in PARTS:
        qty = _rest[5]
        if qty:
            # Opening stock goes through the normal receipt path so it has a movement record.
            inventory.receive_stock(db, parts[sku].id, Decimal(qty), inv_user, "Opening stock (demo data)")

    manager = users["manager@demo.local"]
    vehicles: dict[str, Vehicle] = {}
    for name, mobile, email, address, owned in CUSTOMERS:
        customer = Customer(code=next_number(db, "customer", "CUST", width=6, yearly=False), name=name,
                            mobile=f"+91{mobile}", email=email or None, billing_address=address)
        db.add(customer)
        db.flush()
        for channel in ("EMAIL", "SMS"):
            db.add(CustomerConsent(customer_id=customer.id, channel=channel, granted=True, source="Demo data", recorded_by_id=manager.id))
        for reg, model, vin, odo in owned:
            vehicles[reg] = Vehicle(registration_number=reg, model_id=models[model].id, customer_id=customer.id, vin=vin, odometer=odo)
            db.add(vehicles[reg])
    db.flush()

    # Sample jobs at early stages; walk the rest of the workflow in the UI.
    jobs_service.create_job(
        db, manager, vehicle=vehicles["MH12AB1234"], odometer=84980, fuel_level="HALF",
        complaints="Brake pedal feels spongy and there is a grinding noise from the front while braking. Due for general service.",
        condition_notes="Minor scratch on rear left panel. Spare wheel present.", priority="HIGH",
        mechanic_id=users["mechanic@demo.local"].id,
    )
    jobs_service.create_job(
        db, manager, vehicle=vehicles["MH14GK4321"], odometer=19450, fuel_level="THREE_QUARTER",
        complaints="Clutch slipping on inclines. Customer requests check of 4x4 engagement.",
    )
    db.commit()
    print("Demo data created.")
    print(f"Demo sign-in password for all demo users: {DEMO_PASSWORD}")
    for email, name, role in DEMO_USERS:
        print(f"  {role:<16} {email:<24} {name}")


def create_admin(db: Session, email: str, full_name: str) -> None:
    email = email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise SystemExit(f"User {email} already exists.")
    password = getpass.getpass("Password (min 10 characters): ")
    if len(password) < 10 or password != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match or are too short.")
    role = db.scalar(select(Role).where(Role.code == RoleCode.ADMIN))
    db.add(User(email=email, full_name=full_name, role_id=role.id, password_hash=hash_password(password)))
    db.commit()
    print(f"Administrator {email} created.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reference-only", action="store_true")
    parser.add_argument("--create-admin", nargs=2, metavar=("EMAIL", "FULL_NAME"))
    args = parser.parse_args(argv)
    with SessionLocal() as db:
        ensure_reference_data(db)
        db.commit()
        if args.create_admin:
            create_admin(db, *args.create_admin)
        elif not args.reference_only:
            seed_demo(db)
        else:
            print("Reference data ensured.")


if __name__ == "__main__":
    sys.exit(main())
