"""Administrator endpoints: users, master data, settings, audit log; plus read-only master
data for the other roles. Every change made here is written to the audit trail."""
from datetime import datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.api.helpers import PageNum, PageSize, like, paginate
from app.core.deps import DB, require
from app.core.errors import DomainError, not_found
from app.core.security import hash_password
from app.integrations.registry import provider_status
from app.models import (
    AuditLog,
    DeliveryJob,
    LabourOperation,
    PartCategory,
    RefreshToken,
    Role,
    TaxRate,
    User,
    VehicleModel,
)
from app.models.enums import ACTIVE_DELIVERY_STATUSES, RoleCode
from app.schemas.admin import (
    AuditOut,
    CategoryIn,
    CategoryOut,
    LabourOpIn,
    LabourOpOut,
    SettingsIn,
    TaxRateIn,
    TaxRateOut,
    UserCreate,
    UserOut,
    UserUpdate,
    VehicleModelIn,
    VehicleModelOut,
)
from app.schemas.common import Page, UserRef
from app.services import settings as settings_service
from app.services.common import audit
from app.core.utils import utcnow

router = APIRouter(tags=["admin & master data"])


def _commit(db, what: str):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DomainError(f"{what} already exists or is still referenced by other records") from exc


# --- Users ------------------------------------------------------------------------------


@router.get("/users", response_model=list[UserOut])
def list_users(db: DB, _=require("user.manage")):
    return db.scalars(select(User).order_by(User.full_name)).all()


@router.get("/mechanics", response_model=list[UserRef])
def list_mechanics(db: DB, _=require("staff.read")):
    return db.scalars(
        select(User).join(Role).where(Role.code == RoleCode.MECHANIC, User.is_active).order_by(User.full_name)
    ).all()


def _role(db, code: str) -> Role:
    return db.scalar(select(Role).where(Role.code == code))


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: DB, actor=require("user.manage")):
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise DomainError("A user with this email already exists")
    user = User(
        email=email, full_name=body.full_name, phone=body.phone, role_id=_role(db, body.role_code).id,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.flush()
    audit(db, actor, "user.create", "user", user.id, f"Created user {email}", {"role": body.role_code})
    _commit(db, "User")
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, db: DB, actor=require("user.manage")):
    user = db.get(User, user_id)
    if user is None:
        raise not_found("User")
    changes: dict = {}
    if body.is_active is False and user.id == actor.id:
        raise DomainError("You cannot deactivate your own account")
    if body.role_code and body.role_code != user.role_code:
        if user.id == actor.id:
            raise DomainError("You cannot change your own role")
        changes["role"] = [user.role_code, body.role_code]
        user.role = _role(db, body.role_code)
        user.role_id = user.role.id
    for field in ("full_name", "phone", "is_active"):
        value = getattr(body, field)
        if value is not None and value != getattr(user, field):
            changes[field] = [getattr(user, field), value]
            setattr(user, field, value)
    if body.password:
        user.password_hash = hash_password(body.password)
        changes["password"] = "changed"
    if "password" in changes or changes.get("is_active", [None, True])[1] is False or "role" in changes:
        # Force existing sessions to sign in again.
        for token in db.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))):
            token.revoked_at = utcnow()
    if changes:
        audit(db, actor, "user.update", "user", user.id, f"Updated user {user.email}", changes)
    db.commit()
    return user


# --- Master data ------------------------------------------------------------------------


def _crud(path: str, model, schema_in, schema_out, label: str, order_by):
    """Register list (all roles) + create/update (administrator) endpoints for a master table."""

    @router.get(path, response_model=list[schema_out], name=f"list_{label}")
    def list_items(db: DB, include_inactive: bool = False, _=require("masterdata.read")):
        stmt = select(model).order_by(*order_by)
        if not include_inactive:
            stmt = stmt.where(model.is_active)
        return db.scalars(stmt).all()

    @router.post(path, response_model=schema_out, status_code=201, name=f"create_{label}")
    def create_item(body: schema_in, db: DB, actor=require("masterdata.manage")):
        item = model(**body.model_dump())
        db.add(item)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise DomainError(f"This {label.replace('_', ' ')} already exists") from exc
        audit(db, actor, f"{label}.create", label, item.id, f"Created {label.replace('_', ' ')}", body.model_dump(mode="json"))
        db.commit()
        db.refresh(item)
        return item

    @router.put(path + "/{item_id}", response_model=schema_out, name=f"update_{label}")
    def update_item(item_id: int, body: schema_in, db: DB, actor=require("masterdata.manage")):
        item = db.get(model, item_id)
        if item is None:
            raise not_found(label.replace("_", " ").capitalize())
        for key, value in body.model_dump().items():
            setattr(item, key, value)
        audit(db, actor, f"{label}.update", label, item.id, f"Updated {label.replace('_', ' ')}", body.model_dump(mode="json"))
        _commit(db, label.replace("_", " ").capitalize())
        db.refresh(item)
        return item


_crud("/vehicle-models", VehicleModel, VehicleModelIn, VehicleModelOut, "vehicle_model", (VehicleModel.sort_order, VehicleModel.name))
_crud("/tax-rates", TaxRate, TaxRateIn, TaxRateOut, "tax_rate", (TaxRate.rate.desc(),))
_crud("/part-categories", PartCategory, CategoryIn, CategoryOut, "part_category", (PartCategory.name,))
_crud("/labour-operations", LabourOperation, LabourOpIn, LabourOpOut, "labour_operation", (LabourOperation.code,))


# --- Settings ---------------------------------------------------------------------------


@router.get("/settings")
def get_settings_(db: DB, _=require("settings.manage")):
    """Stored settings plus a non-secret provider summary. Credentials are never returned."""
    return {"values": settings_service.get_all(db), "providers": provider_status()}


@router.put("/settings")
def update_settings(body: SettingsIn, db: DB, actor=require("settings.manage")):
    changes = settings_service.set_many(db, body.model_dump(exclude_unset=True, exclude_none=True), actor)
    if changes:
        audit(db, actor, "settings.update", "settings", None, "Updated settings: " + ", ".join(changes), changes)
    db.commit()
    return {"values": settings_service.get_all(db), "providers": provider_status()}


@router.get("/centre")
def centre_details(db: DB, _=require("masterdata.read")):
    """Service-centre header details for printed job cards."""
    return settings_service.centre_snapshot(db)


# --- Audit & health ---------------------------------------------------------------------


@router.get("/audit-logs", response_model=Page[AuditOut])
def audit_logs(
    db: DB, page: PageNum = 1, page_size: PageSize = 50, q: str | None = None, action: str | None = None,
    entity_type: str | None = None, date_from: datetime | None = None, date_to: datetime | None = None,
    _=require("audit.read"),
):
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    if q:
        stmt = stmt.where(AuditLog.summary.ilike(like(q)) | AuditLog.actor_email.ilike(like(q)))
    if action:
        stmt = stmt.where(AuditLog.action.ilike(like(action)))
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= date_to)
    return paginate(db, stmt, page, page_size)


@router.get("/system/health")
def system_health(db: DB, _=require("settings.manage", "audit.read")):
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:  # noqa: BLE001
        raise HTTPException(503, "Database unavailable") from None
    backlog = db.scalar(select(func.count()).select_from(DeliveryJob).where(DeliveryJob.status.in_(ACTIVE_DELIVERY_STATUSES)))
    oldest = db.scalar(select(func.min(DeliveryJob.next_attempt_at)).where(DeliveryJob.status.in_(ACTIVE_DELIVERY_STATUSES)))
    providers = provider_status()
    return {
        "database": database,
        "environment": providers["environment"],
        "delivery_backlog": backlog,
        "oldest_pending_delivery": oldest,
        "email_provider": providers["email"]["provider"],
        "email_simulated": providers["email"]["simulated"],
        "sms_provider": providers["sms"]["provider"],
        "sms_simulated": providers["sms"]["simulated"],
        "whatsapp_provider": providers["whatsapp"]["provider"],
        "whatsapp_simulated": providers["whatsapp"]["simulated"],
        "active_users": db.scalar(select(func.count()).select_from(User).where(User.is_active)),
        "server_time": utcnow(),
    }
