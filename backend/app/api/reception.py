"""Customers, vehicles, job cards and the Service Manager's job-level actions."""
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import exists, or_, select
from sqlalchemy.exc import IntegrityError

from app.api.helpers import PageNum, PageSize, like, paginate
from app.core.config import get_settings
from app.core.deps import DB, CurrentUser, require
from app.core.errors import DomainError, bad_request, forbidden, not_found
from app.core.utils import normalise_registration
from app.models import (
    Customer,
    CustomerConsent,
    Invoice,
    JobPhoto,
    Part,
    PartsRequest,
    PartsRequestLine,
    ServiceJob,
    User,
    Vehicle,
    VehicleModel,
)
from app.models.enums import CLOSED_JOB_STATUSES, InvoiceStatus, JobStatus, MECHANIC_DONE_STATUSES
from app.schemas.billing import EstimateOut, InvoiceSummary
from app.schemas.common import Page, ReasonIn
from app.schemas.workshop import (
    AssignIn,
    CompletionOut,
    CustomerDetail,
    CustomerIn,
    CustomerOut,
    CustomerUpdate,
    EventOut,
    HandoverIn,
    InspectionOut,
    JobCreate,
    JobSummary,
    JobUpdate,
    LabourOut,
    ManualPartOut,
    PartsRequestOut,
    PhotoOut,
    QualityOut,
    VehicleIn,
    VehicleOut,
    VehicleUpdate,
)
from app.services import billing
from app.services import jobs as jobs_service
from app.services.common import audit, next_number

router = APIRouter(tags=["reception & jobs"])


class JobDetail(JobSummary):
    fuel_level: str
    condition_notes: str
    hold_reason: str | None
    cancel_reason: str | None
    active_job_override_reason: str | None
    ready_for_delivery_at: datetime | None
    delivered_at: datetime | None
    handover_to: str | None
    handover_notes: str | None
    created_at: datetime
    events: list[EventOut]
    photos: list[PhotoOut]
    inspection: InspectionOut | None
    labour: list[LabourOut]
    parts_requests: list[PartsRequestOut]
    manual_parts: list[ManualPartOut] = []
    completions: list[CompletionOut]
    quality_inspections: list[QualityOut]
    estimates: list[EstimateOut] = []
    invoices: list[InvoiceSummary] = []
    billing_blockers: list[str] = []
    pending_approvals: list[str] = []


class LookupOut(BaseModel):
    registration_number: str
    found: bool
    vehicle: VehicleOut | None = None
    active_jobs: list[JobSummary] = []
    history: list[dict] = []


# --- Customers --------------------------------------------------------------------------


def _record_consent(db, customer: Customer, channel: str, granted: bool, user: User, source: str) -> None:
    db.add(CustomerConsent(customer_id=customer.id, channel=channel, granted=granted, source=source, recorded_by_id=user.id))


@router.get("/customers", response_model=Page[CustomerOut])
def list_customers(db: DB, q: str | None = None, page: PageNum = 1, page_size: PageSize = 25, _=require("customer.read")):
    stmt = select(Customer).order_by(Customer.name)
    if q and q.strip():
        term = like(q)
        digits = "".join(c for c in q if c.isdigit())
        conds = [Customer.name.ilike(term), Customer.email.ilike(term), Customer.code.ilike(term)]
        if len(digits) >= 4:
            conds.append(Customer.mobile.like(f"%{digits}%"))
        stmt = stmt.where(or_(*conds))
    return paginate(db, stmt, page, page_size)


@router.post("/customers", response_model=CustomerOut, status_code=201)
def create_customer(body: CustomerIn, db: DB, user=require("reception.manage")):
    customer = Customer(code=next_number(db, "customer", "CUST", width=6, yearly=False), **body.model_dump())
    db.add(customer)
    db.flush()
    _record_consent(db, customer, "EMAIL", body.email_opt_in, user, "Recorded at reception")
    _record_consent(db, customer, "SMS", body.sms_opt_in, user, "Recorded at reception")
    _record_consent(db, customer, "WHATSAPP", body.whatsapp_opt_in, user, "Recorded at reception")
    audit(db, user, "customer.create", "customer", customer.id, f"Registered customer {customer.code}")
    db.commit()
    return customer


@router.get("/customers/{customer_id}", response_model=CustomerDetail)
def get_customer(customer_id: int, db: DB, _=require("customer.read")):
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise not_found("Customer")
    return customer


@router.patch("/customers/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: int, body: CustomerUpdate, db: DB, user=require("reception.manage")):
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise not_found("Customer")
    data = body.model_dump(exclude_unset=True)
    for key in ("name", "mobile"):
        if key in data and data[key] is None:
            raise bad_request(f"{key} cannot be empty")
    changed = [k for k, v in data.items() if getattr(customer, k) != v]
    for channel, field in (("EMAIL", "email_opt_in"), ("SMS", "sms_opt_in"), ("WHATSAPP", "whatsapp_opt_in")):
        if field in changed:
            _record_consent(db, customer, channel, data[field], user, "Updated by service manager")
    for key in changed:
        setattr(customer, key, data[key])
    if changed:
        # Field names only: contact details themselves are not copied into the audit log.
        audit(db, user, "customer.update", "customer", customer.id, f"Updated customer {customer.code}", {"fields": changed})
    db.commit()
    return customer


# --- Vehicles ---------------------------------------------------------------------------


def _history(db, vehicle_id: int, include_billing: bool, exclude_job_id: int | None = None) -> list[dict]:
    jobs = db.scalars(
        select(ServiceJob).where(ServiceJob.vehicle_id == vehicle_id).order_by(ServiceJob.visit_at.desc())
    ).unique().all()
    history = []
    for job in jobs:
        if job.id == exclude_job_id:
            continue
        invoice = next((i for i in job.invoices if i.status == InvoiceStatus.FINALISED), None)
        entry = {
            "job_id": job.id,
            "job_number": job.job_number,
            "visit_at": job.visit_at,
            "status": job.status,
            "odometer": job.odometer,
            "complaints": job.complaints,
            "diagnostic_findings": job.inspection.diagnostic_findings if job.inspection else "",
            "recommended_repairs": job.inspection.recommended_repairs if job.inspection else "",
            "spare_parts_notes": job.inspection.spare_parts_notes if job.inspection else "",
            "repairs_completed": job.completions[-1].repairs_completed if job.completions else "",
            "labour": [l.description for l in job.labour if l.approval_status == "APPROVED"],
            "parts": [
                {"sku": l.part.sku, "name": l.part.name, "quantity": l.qty_consumed}
                for l in jobs_service.active_part_lines(job)
                if (l.qty_consumed or 0) > 0
            ],
            "mechanic": job.mechanic_name,
        }
        if include_billing:
            entry["invoice_number"] = invoice.invoice_number if invoice else None
            entry["invoice_total"] = invoice.total if invoice else None
        history.append(entry)
    return history


@router.get("/vehicles/lookup", response_model=LookupOut)
def lookup_vehicle(registration: str, db: DB, _=require("customer.read")):
    """Reception search: returns the vehicle, its owner, open jobs and full service history."""
    reg = normalise_registration(registration)
    vehicle = db.scalar(select(Vehicle).where(Vehicle.registration_number == reg)) if reg else None
    if vehicle is None:
        return LookupOut(registration_number=reg, found=False)
    return LookupOut(
        registration_number=reg, found=True, vehicle=vehicle,
        active_jobs=jobs_service.active_jobs_for_vehicle(db, vehicle.id),
        history=_history(db, vehicle.id, include_billing=True),
    )


@router.get("/vehicles", response_model=Page[VehicleOut])
def list_vehicles(
    db: DB, q: str | None = None, model_id: int | None = None, customer_id: int | None = None,
    page: PageNum = 1, page_size: PageSize = 25, _=require("customer.read"),
):
    stmt = select(Vehicle).join(Vehicle.customer).order_by(Vehicle.registration_number)
    if q and q.strip():
        term = like(q)
        reg = normalise_registration(q)
        conds = [Customer.name.ilike(term), Vehicle.vin.ilike(term)]
        if reg:
            conds.append(Vehicle.registration_number.like(f"%{reg}%"))
        digits = "".join(c for c in q if c.isdigit())
        if len(digits) >= 4:
            conds.append(Customer.mobile.like(f"%{digits}%"))
        stmt = stmt.where(or_(*conds))
    if model_id:
        stmt = stmt.where(Vehicle.model_id == model_id)
    if customer_id:
        stmt = stmt.where(Vehicle.customer_id == customer_id)
    return paginate(db, stmt, page, page_size)


@router.post("/vehicles", response_model=VehicleOut, status_code=201)
def create_vehicle(body: VehicleIn, db: DB, user=require("reception.manage")):
    existing = db.scalar(select(Vehicle).where(Vehicle.registration_number == body.registration_number))
    if existing is not None:
        raise DomainError(
            {"code": "DUPLICATE_REGISTRATION", "message": f"Vehicle {existing.registration_number} is already registered",
             "vehicle_id": existing.id}
        )
    model = db.get(VehicleModel, body.model_id)
    if model is None or not model.is_active:
        raise bad_request("Select an active vehicle model")
    if db.get(Customer, body.customer_id) is None:
        raise bad_request("Customer not found")
    vehicle = Vehicle(**body.model_dump())
    db.add(vehicle)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DomainError("A vehicle with this registration or chassis number already exists") from exc
    audit(db, user, "vehicle.create", "vehicle", vehicle.id, f"Registered vehicle {vehicle.registration_number}")
    db.commit()
    return vehicle


@router.patch("/vehicles/{vehicle_id}", response_model=VehicleOut)
def update_vehicle(vehicle_id: int, body: VehicleUpdate, db: DB, user=require("reception.manage")):
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise not_found("Vehicle")
    data = body.model_dump(exclude_unset=True)
    if data.get("customer_id") and db.get(Customer, data["customer_id"]) is None:
        raise bad_request("Customer not found")
    if data.get("model_id") and db.get(VehicleModel, data["model_id"]) is None:
        raise bad_request("Vehicle model not found")
    for key, value in data.items():
        if value is not None or key in ("vin", "engine_number"):
            setattr(vehicle, key, value)
    audit(db, user, "vehicle.update", "vehicle", vehicle.id, f"Updated vehicle {vehicle.registration_number}", {"fields": list(data)})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DomainError("Another vehicle already uses this chassis number") from exc
    db.refresh(vehicle)
    return vehicle


@router.get("/vehicles/{vehicle_id}/history")
def vehicle_history(vehicle_id: int, db: DB, _=require("customer.read")):
    if db.get(Vehicle, vehicle_id) is None:
        raise not_found("Vehicle")
    return _history(db, vehicle_id, include_billing=True)


# --- Jobs -------------------------------------------------------------------------------

SORTS = {"visit_at": ServiceJob.visit_at, "job_number": ServiceJob.job_number, "status": ServiceJob.status}


@router.get("/jobs", response_model=Page[JobSummary])
def list_jobs(
    db: DB, user: CurrentUser, q: str | None = None, status: str | None = None, mechanic_id: int | None = None,
    model_id: int | None = None, date_from: datetime | None = None, date_to: datetime | None = None,
    active_only: bool = False, returned_only: bool = False, sort: str = "visit_at", order: str = "desc",
    page: PageNum = 1, page_size: PageSize = 25,
):
    perms = user.permissions
    if not perms & {"job.read_all", "job.read_assigned"}:
        raise forbidden()
    stmt = select(ServiceJob).join(ServiceJob.vehicle).join(ServiceJob.customer)
    if "job.read_all" not in perms:
        stmt = stmt.where(ServiceJob.assigned_mechanic_id == user.id)  # mechanics: own jobs only
    elif mechanic_id:
        stmt = stmt.where(ServiceJob.assigned_mechanic_id == mechanic_id)
    if q and q.strip():
        term = like(q)
        reg = normalise_registration(q)
        digits = "".join(c for c in q if c.isdigit())
        conds = [ServiceJob.job_number.ilike(term), Customer.name.ilike(term)]
        if reg:
            conds.append(Vehicle.registration_number.like(f"%{reg}%"))
        if len(digits) >= 4:
            conds.append(Customer.mobile.like(f"%{digits}%"))
        conds.append(
            exists().where(Invoice.job_id == ServiceJob.id, Invoice.invoice_number.ilike(term))
        )
        conds.append(  # part number search
            exists().where(
                PartsRequest.job_id == ServiceJob.id, PartsRequestLine.request_id == PartsRequest.id,
                Part.id == PartsRequestLine.part_id, Part.sku.ilike(term),
            )
        )
        stmt = stmt.where(or_(*conds))
    if status:
        stmt = stmt.where(ServiceJob.status.in_(status.split(",")))
    if active_only:
        if "job.read_all" in perms:
            stmt = stmt.where(ServiceJob.status.notin_(CLOSED_JOB_STATUSES))
        else:  # mechanics: work handed to the Service Manager counts as done
            stmt = stmt.where(ServiceJob.status.notin_((*MECHANIC_DONE_STATUSES, JobStatus.CANCELLED)))
    if returned_only:
        stmt = stmt.where(ServiceJob.returned_for_rework.is_(True), ServiceJob.status == JobStatus.IN_SERVICE)
    if model_id:
        stmt = stmt.where(Vehicle.model_id == model_id)
    if date_from:
        stmt = stmt.where(ServiceJob.visit_at >= date_from)
    if date_to:
        stmt = stmt.where(ServiceJob.visit_at <= date_to)
    column = SORTS.get(sort, ServiceJob.visit_at)
    stmt = stmt.order_by(column.asc() if order == "asc" else column.desc(), ServiceJob.id.desc())
    return paginate(db, stmt, page, page_size)


def job_detail(job: ServiceJob, user: User) -> JobDetail:
    detail = JobDetail.model_validate(job)
    if "estimate.manage" in user.permissions:
        detail.billing_blockers = billing.billing_blockers(job)
    else:
        # Mechanics see the work, not the commercial documents.
        detail.estimates, detail.invoices = [], []
    detail.pending_approvals = jobs_service.pending_approval_items(job)
    return detail


@router.post("/jobs", response_model=JobDetail, status_code=201)
def create_job(body: JobCreate, db: DB, user=require("reception.manage")):
    vehicle = db.get(Vehicle, body.vehicle_id)
    if vehicle is None:
        raise bad_request("Vehicle not found")
    job = jobs_service.create_job(
        db, user, vehicle=vehicle, odometer=body.odometer, fuel_level=body.fuel_level, complaints=body.complaints,
        condition_notes=body.condition_notes, priority=body.priority, job_type=body.job_type,
        estimated_completion_at=body.estimated_completion_at, mechanic_id=body.mechanic_id,
        override_reason=body.override_reason,
    )
    db.commit()
    db.refresh(job)
    return job_detail(job, user)


def _load(db, job_id: int, user: User, lock: bool = False) -> ServiceJob:
    job = jobs_service.get_job(db, job_id, lock=lock)
    jobs_service.ensure_can_view(job, user)
    return job


def _done(db, job: ServiceJob, user: User) -> JobDetail:
    db.commit()
    db.refresh(job)
    return job_detail(job, user)


@router.get("/jobs/{job_id}", response_model=JobDetail)
def get_job(job_id: int, db: DB, user: CurrentUser):
    return job_detail(_load(db, job_id, user), user)


@router.patch("/jobs/{job_id}", response_model=JobDetail)
def update_job(job_id: int, body: JobUpdate, db: DB, user=require("reception.manage")):
    """Correct job-card details at any stage while the job is open. Changes are audited."""
    job = _load(db, job_id, user, lock=True)
    jobs_service.update_job_details(db, job, user, body.model_dump(exclude_unset=True))
    return _done(db, job, user)


@router.get("/jobs/{job_id}/history")
def job_vehicle_history(job_id: int, db: DB, user: CurrentUser):
    """Previous visits of this job's vehicle (mechanics see it for their assigned jobs)."""
    job = _load(db, job_id, user)
    return _history(db, job.vehicle_id, include_billing="invoice.read" in user.permissions, exclude_job_id=job.id)


@router.post("/jobs/{job_id}/assign", response_model=JobDetail)
def assign(job_id: int, body: AssignIn, db: DB, user=require("job.assign")):
    job = _load(db, job_id, user, lock=True)
    jobs_service.assign_mechanic(db, job, body.mechanic_id, user, body.notes)
    return _done(db, job, user)


@router.post("/jobs/{job_id}/hold", response_model=JobDetail)
def hold(job_id: int, body: ReasonIn, db: DB, user=require("job.manage")):
    job = _load(db, job_id, user, lock=True)
    jobs_service.hold_job(db, job, user, body.reason)
    return _done(db, job, user)


@router.post("/jobs/{job_id}/resume", response_model=JobDetail)
def resume(job_id: int, db: DB, user=require("job.manage")):
    job = _load(db, job_id, user, lock=True)
    jobs_service.resume_job(db, job, user)
    return _done(db, job, user)


@router.post("/jobs/{job_id}/cancel", response_model=JobDetail)
def cancel(job_id: int, body: ReasonIn, db: DB, user=require("job.manage")):
    job = _load(db, job_id, user, lock=True)
    jobs_service.cancel_job(db, job, user, body.reason)
    return _done(db, job, user)


@router.post("/jobs/{job_id}/return-to-mechanic", response_model=JobDetail)
def return_to_mechanic(job_id: int, body: ReasonIn, db: DB, user=require("job.manage")):
    job = _load(db, job_id, user, lock=True)
    jobs_service.return_to_mechanic(db, job, user, body.reason)
    return _done(db, job, user)


@router.post("/jobs/{job_id}/ready-for-delivery", response_model=JobDetail)
def ready_for_delivery(job_id: int, db: DB, user=require("job.manage")):
    job = _load(db, job_id, user, lock=True)
    jobs_service.mark_ready_for_delivery(db, job, user)
    return _done(db, job, user)


@router.post("/jobs/{job_id}/handover", response_model=JobDetail)
def handover(job_id: int, body: HandoverIn, db: DB, user=require("job.manage")):
    job = _load(db, job_id, user, lock=True)
    jobs_service.record_handover(db, job, user, body.received_by, body.notes, body.allow_outstanding)
    return _done(db, job, user)


# --- Photographs ------------------------------------------------------------------------

IMAGE_SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff", ".jpg"),
    "image/png": (b"\x89PNG\r\n\x1a\n", ".png"),
}


def _sniff(data: bytes) -> tuple[str, str] | None:
    """Identify the image type from its content; the client-supplied type and name are ignored."""
    for mime, (signature, ext) in IMAGE_SIGNATURES.items():
        if data.startswith(signature):
            return mime, ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


@router.post("/jobs/{job_id}/photos", response_model=PhotoOut, status_code=201)
def upload_photo(job_id: int, file: UploadFile, db: DB, user=require("reception.manage", "job.work")):
    job = _load(db, job_id, user)
    if job.status in CLOSED_JOB_STATUSES:
        raise DomainError("Photographs cannot be added to a closed job")
    s = get_settings()
    data = file.file.read(s.max_upload_bytes + 1)
    if len(data) > s.max_upload_bytes:
        raise bad_request(f"Photograph is larger than {s.max_upload_bytes // (1024 * 1024)} MB")
    kind = _sniff(data)
    if kind is None:
        raise bad_request("Only JPEG, PNG or WebP photographs are accepted")
    mime, ext = kind
    stored = f"{uuid.uuid4().hex}{ext}"  # random server-side name; never the uploaded filename
    directory = Path(s.upload_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / stored).write_bytes(data)
    photo = JobPhoto(
        job_id=job.id, stored_name=stored, original_name=Path(file.filename or "photo").name[:255],
        content_type=mime, size_bytes=len(data), uploaded_by_id=user.id,
    )
    db.add(photo)
    jobs_service.add_event(db, job, "PHOTO", "Photograph added", user)
    db.commit()
    return photo


@router.get("/jobs/{job_id}/photos/{photo_id}")
def get_photo(job_id: int, photo_id: int, db: DB, user: CurrentUser):
    _load(db, job_id, user)
    photo = db.get(JobPhoto, photo_id)
    if photo is None or photo.job_id != job_id:
        raise not_found("Photograph")
    path = Path(get_settings().upload_dir) / photo.stored_name
    if not path.is_file():
        raise not_found("Photograph")
    return FileResponse(path, media_type=photo.content_type, headers={"X-Content-Type-Options": "nosniff"})
