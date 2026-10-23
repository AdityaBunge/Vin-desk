"""Parts catalogue, stock, parts-request fulfilment and purchase requests."""
from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.api.helpers import PageNum, PageSize, like, paginate
from app.core.deps import DB, CurrentUser, require
from app.core.errors import DomainError, bad_request, not_found
from app.core.utils import ZERO
from app.models import (
    Inspection,
    InventoryMovement,
    InventoryStock,
    Part,
    PartsRequest,
    PartsRequestLine,
    PurchaseRequest,
    ServiceJob,
    Supplier,
    VehicleModel,
    part_compatibility,
)
from app.models.enums import CLOSED_JOB_STATUSES, PartsRequestStatus
from app.schemas.common import Page
from app.schemas.inventory import (
    AdjustIn,
    AlternativeIn,
    DecisionIn,
    MovementOut,
    PartIn,
    PartMechanicOut,
    PartOut,
    PartsRequestQueueOut,
    PurchaseRequestIn,
    PurchaseRequestOut,
    QtyIn,
    ReceiveIn,
    StockOut,
    SupplierIn,
    SupplierOut,
    UnavailableIn,
    WriteOffIn,
)
from app.schemas.workshop import (
    CancelLineIn,
    PartsLineOut,
    PartsLineUpdate,
    SparePartsAvailableIn,
    SparePartsListOut,
    SparePartsUnavailableIn,
)
from app.services import jobs as jobs_service
from app.services import inventory
from app.services.common import audit

router = APIRouter(tags=["inventory"])


# --- Catalogue --------------------------------------------------------------------------


@router.get("/parts")
def list_parts(
    db: DB, user: CurrentUser, q: str | None = None, category_id: int | None = None,
    model_id: int | None = None, low_stock: bool = False, include_inactive: bool = False,
    page: PageNum = 1, page_size: PageSize = 25, _=require("parts.read"),
):
    stmt = select(Part).join(InventoryStock, InventoryStock.part_id == Part.id).order_by(Part.sku)
    if q and q.strip():
        term = like(q)
        stmt = stmt.where(or_(Part.sku.ilike(term), Part.name.ilike(term), Part.description.ilike(term)))
    if category_id:
        stmt = stmt.where(Part.category_id == category_id)
    if model_id:
        stmt = stmt.where(
            Part.id.in_(select(part_compatibility.c.part_id).where(part_compatibility.c.vehicle_model_id == model_id))
        )
    if low_stock:
        stmt = stmt.where(InventoryStock.qty_on_hand - InventoryStock.qty_reserved <= Part.reorder_threshold)
    if not include_inactive:
        stmt = stmt.where(Part.is_active)
    data = paginate(db, stmt, page, page_size)
    # Purchase cost and supplier are not exposed to roles that only read the catalogue.
    full = bool(user.permissions & {"parts.manage", "inventory.read"})
    schema = PartOut if full else PartMechanicOut
    data["items"] = [schema.model_validate(p) for p in data["items"]]
    return data


def _apply_part(db, part: Part, body: PartIn) -> None:
    data = body.model_dump(exclude={"compatible_model_ids"})
    for key, value in data.items():
        setattr(part, key, value)
    models = db.scalars(select(VehicleModel).where(VehicleModel.id.in_(body.compatible_model_ids))).all() if body.compatible_model_ids else []
    if len(models) != len(set(body.compatible_model_ids)):
        raise bad_request("Unknown vehicle model in compatibility list")
    part.compatible_models = list(models)


@router.post("/parts", response_model=PartOut, status_code=201)
def create_part(body: PartIn, db: DB, user=require("parts.manage")):
    if db.scalar(select(Part.id).where(Part.sku == body.sku)):
        raise DomainError(f"Part number {body.sku} already exists")
    part = Part(stock=InventoryStock(qty_on_hand=ZERO, qty_reserved=ZERO))
    _apply_part(db, part, body)
    db.add(part)
    db.flush()
    audit(db, user, "part.create", "part", part.id, f"Created part {part.sku}")
    db.commit()
    db.refresh(part)
    return part


@router.put("/parts/{part_id}", response_model=PartOut)
def update_part(part_id: int, body: PartIn, db: DB, user=require("parts.manage")):
    part = db.get(Part, part_id)
    if part is None:
        raise not_found("Part")
    before = {"selling_price": str(part.selling_price), "purchase_cost": str(part.purchase_cost), "is_active": part.is_active}
    _apply_part(db, part, body)
    audit(db, user, "part.update", "part", part.id, f"Updated part {part.sku}",
          {"before": before, "after": {"selling_price": str(body.selling_price), "purchase_cost": str(body.purchase_cost), "is_active": body.is_active}})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DomainError("Another part already uses this part number") from exc
    db.refresh(part)
    return part


@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(db: DB, _=require("parts.manage", "inventory.read")):
    return db.scalars(select(Supplier).order_by(Supplier.name)).all()


@router.post("/suppliers", response_model=SupplierOut, status_code=201)
def create_supplier(body: SupplierIn, db: DB, user=require("parts.manage")):
    supplier = Supplier(**body.model_dump())
    db.add(supplier)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DomainError("A supplier with this name already exists") from exc
    audit(db, user, "supplier.create", "supplier", supplier.id, f"Created supplier {supplier.name}")
    db.commit()
    return supplier


# --- Stock operations -------------------------------------------------------------------


@router.post("/parts/{part_id}/receive", response_model=StockOut)
def receive(part_id: int, body: QtyIn, db: DB, user=require("inventory.adjust")):
    stock = inventory.receive_stock(db, part_id, body.quantity, user, body.reason or "Stock received")
    db.commit()
    return stock


@router.post("/parts/{part_id}/adjust", response_model=StockOut)
def adjust(part_id: int, body: AdjustIn, db: DB, user=require("inventory.adjust")):
    stock = inventory.adjust_stock(db, part_id, body.delta, user, body.reason)
    db.commit()
    return stock


@router.post("/parts/{part_id}/write-off", response_model=StockOut)
def write_off(part_id: int, body: WriteOffIn, db: DB, user=require("inventory.adjust")):
    stock = inventory.write_off(db, part_id, body.quantity, user, body.reason)
    db.commit()
    return stock


@router.get("/inventory/movements", response_model=Page[MovementOut])
def movements(
    db: DB, part_id: int | None = None, job_id: int | None = None, movement_type: str | None = None,
    q: str | None = None, date_from: datetime | None = None, date_to: datetime | None = None,
    page: PageNum = 1, page_size: PageSize = 50, _=require("inventory.read"),
):
    stmt = select(InventoryMovement).join(InventoryMovement.part).order_by(InventoryMovement.id.desc())
    if part_id:
        stmt = stmt.where(InventoryMovement.part_id == part_id)
    if job_id:
        stmt = stmt.where(InventoryMovement.job_id == job_id)
    if movement_type:
        stmt = stmt.where(InventoryMovement.movement_type == movement_type)
    if q and q.strip():
        stmt = stmt.where(or_(Part.sku.ilike(like(q)), Part.name.ilike(like(q))))
    if date_from:
        stmt = stmt.where(InventoryMovement.created_at >= date_from)
    if date_to:
        stmt = stmt.where(InventoryMovement.created_at <= date_to)
    return paginate(db, stmt, page, page_size)


# --- Parts requests ---------------------------------------------------------------------


@router.get("/parts-requests", response_model=Page[PartsRequestQueueOut])
def parts_requests(
    db: DB, status: str | None = None, open_only: bool = False, q: str | None = None,
    page: PageNum = 1, page_size: PageSize = 25, _=require("inventory.read"),
):
    stmt = select(PartsRequest).join(PartsRequest.job).order_by(PartsRequest.id.desc())
    if status:
        stmt = stmt.where(PartsRequest.status.in_(status.split(",")))
    if open_only:
        stmt = stmt.where(
            PartsRequest.status.notin_((PartsRequestStatus.FULFILLED, PartsRequestStatus.CANCELLED)),
            ServiceJob.status.notin_(CLOSED_JOB_STATUSES),
        )
    if q and q.strip():
        stmt = stmt.where(or_(PartsRequest.request_number.ilike(like(q)), ServiceJob.job_number.ilike(like(q))))
    return paginate(db, stmt, page, page_size)


def _list_out(insp: Inspection) -> SparePartsListOut:
    job = insp.job
    done_by = insp.spare_parts_done_by.full_name if insp.spare_parts_done_by else None
    return SparePartsListOut(
        job_id=job.id, job_number=job.job_number, job_status=job.status,
        registration_number=job.vehicle.registration_number, model_name=job.vehicle.model.name,
        mechanic_name=job.assigned_mechanic.full_name if job.assigned_mechanic else None,
        notes=insp.spare_parts_notes, status=insp.spare_parts_status, submitted_at=insp.submitted_at,
        done_by_name=done_by, done_at=insp.spare_parts_done_at, done_note=insp.spare_parts_done_note,
        unconfirmed=insp.spare_parts_unconfirmed, parts=list(job.manual_parts),
    )


@router.get("/spare-parts-lists", response_model=list[SparePartsListOut])
def spare_parts_lists(db: DB, pending_only: bool = True, _=require("inventory.read")):
    """Mechanics' hand-written spare parts lists from submitted inspections."""
    stmt = (
        select(Inspection).join(Inspection.job)
        .where(Inspection.spare_parts_status != "", ServiceJob.status.notin_(CLOSED_JOB_STATUSES))
        .order_by(Inspection.submitted_at.desc()).limit(50)
    )
    if pending_only:  # not yet checked, or checked and not available
        stmt = stmt.where(Inspection.spare_parts_status.in_(("PENDING", "UNAVAILABLE")))
    return [_list_out(i) for i in db.scalars(stmt)]


@router.post("/jobs/{job_id}/spare-parts-list/available", response_model=SparePartsListOut)
def spare_parts_available(job_id: int, body: SparePartsAvailableIn, db: DB, user=require("inventory.fulfil")):
    """Inventory checked the shelf: the written parts are available. The entered lines are billed."""
    job = jobs_service.get_job(db, job_id, lock=True)
    jobs_service.mark_spare_parts_available(db, job, user, [l.model_dump() for l in body.lines], body.note)
    db.commit()
    db.refresh(job)
    return _list_out(job.inspection)


@router.post("/jobs/{job_id}/spare-parts-list/unavailable", response_model=SparePartsListOut)
def spare_parts_unavailable(job_id: int, body: SparePartsUnavailableIn, db: DB, user=require("inventory.fulfil")):
    """Inventory checked the shelf: not available. The job keeps waiting for parts."""
    job = jobs_service.get_job(db, job_id, lock=True)
    jobs_service.mark_spare_parts_unavailable(db, job, user, body.note)
    db.commit()
    db.refresh(job)
    return _list_out(job.inspection)


def _line_done(db, line: PartsRequestLine) -> PartsRequestLine:
    db.commit()
    db.refresh(line)
    return line


@router.patch("/parts-request-lines/{line_id}", response_model=PartsLineOut)
def update_line(line_id: int, body: PartsLineUpdate, db: DB, user=require("job.work")):
    return _line_done(db, inventory.update_line(db, line_id, user, body.quantity, body.urgency, body.notes))


@router.post("/parts-request-lines/{line_id}/reserve", response_model=PartsLineOut)
def reserve(line_id: int, body: QtyIn, db: DB, user=require("inventory.fulfil")):
    return _line_done(db, inventory.reserve(db, line_id, body.quantity, user))


@router.post("/parts-request-lines/{line_id}/issue", response_model=PartsLineOut)
def issue(line_id: int, body: QtyIn, db: DB, user=require("inventory.fulfil")):
    return _line_done(db, inventory.issue(db, line_id, body.quantity, user))


@router.post("/parts-request-lines/{line_id}/return", response_model=PartsLineOut)
def return_unused(line_id: int, body: QtyIn, db: DB, user=require("inventory.fulfil")):
    return _line_done(db, inventory.return_unused(db, line_id, body.quantity, user, body.reason))


@router.post("/parts-request-lines/{line_id}/unavailable", response_model=PartsLineOut)
def mark_unavailable(line_id: int, body: UnavailableIn, db: DB, user=require("inventory.fulfil")):
    return _line_done(db, inventory.mark_unavailable(db, line_id, user, body.expected_restock_date, body.notes))


@router.post("/parts-request-lines/{line_id}/alternative", response_model=PartsLineOut)
def propose_alternative(line_id: int, body: AlternativeIn, db: DB, user=require("inventory.fulfil")):
    return _line_done(db, inventory.propose_alternative(db, line_id, body.part_id, user, body.notes))


@router.post("/parts-request-lines/{line_id}/alternative-decision", response_model=PartsLineOut)
def decide_alternative(line_id: int, body: DecisionIn, db: DB, user=require("alternative.approve")):
    return _line_done(db, inventory.decide_alternative(db, line_id, body.approve, user, body.notes))


@router.post("/parts-request-lines/{line_id}/cancel", response_model=PartsLineOut)
def cancel_line(line_id: int, body: CancelLineIn, db: DB, user=require("job.manage", "job.work")):
    return _line_done(db, inventory.cancel_line_by_id(db, line_id, user, body.reason))


# --- Purchase requests ------------------------------------------------------------------


@router.get("/purchase-requests", response_model=Page[PurchaseRequestOut])
def purchase_requests(
    db: DB, status: str | None = None, page: PageNum = 1, page_size: PageSize = 25,
    _=require("inventory.read"),
):
    stmt = select(PurchaseRequest).order_by(PurchaseRequest.id.desc())
    if status:
        stmt = stmt.where(PurchaseRequest.status.in_(status.split(",")))
    return paginate(db, stmt, page, page_size)


@router.post("/purchase-requests", response_model=PurchaseRequestOut, status_code=201)
def create_purchase_request(body: PurchaseRequestIn, db: DB, user=require("purchase.create")):
    pr = inventory.create_purchase_request(db, user, [l.model_dump() for l in body.lines], body.supplier_id, body.notes)
    db.commit()
    db.refresh(pr)
    return pr


@router.put("/purchase-requests/{pr_id}", response_model=PurchaseRequestOut)
def update_purchase_request(pr_id: int, body: PurchaseRequestIn, db: DB, user=require("purchase.create")):
    pr = inventory.update_purchase_request(db, pr_id, user, [l.model_dump() for l in body.lines], body.supplier_id, body.notes)
    db.commit()
    db.refresh(pr)
    return pr


@router.post("/purchase-requests/{pr_id}/decision", response_model=PurchaseRequestOut)
def decide_purchase_request(pr_id: int, body: DecisionIn, db: DB, user=require("purchase.approve")):
    pr = inventory.decide_purchase_request(db, pr_id, body.approve, user, body.notes)
    db.commit()
    db.refresh(pr)
    return pr


@router.post("/purchase-requests/{pr_id}/receive", response_model=PurchaseRequestOut)
def receive_purchase_request(pr_id: int, body: ReceiveIn, db: DB, user=require("purchase.receive", "inventory.adjust")):
    pr = inventory.receive_purchase_request(db, pr_id, user, [l.model_dump() for l in body.lines] if body.lines else None)
    db.commit()
    db.refresh(pr)
    return pr
