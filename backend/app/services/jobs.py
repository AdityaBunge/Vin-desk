"""Service-job lifecycle: reception, assignment, inspection, completion, billing hand-off, handover.

Every status change goes through `transition`, which validates it against TRANSITIONS and
writes a timeline event.
"""
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError, bad_request, forbidden, not_found
from app.core.utils import utcnow
from app.models import (
    Inspection,
    JobAssignment,
    JobEvent,
    JobLabour,
    JobManualPart,
    LabourOperation,
    Part,
    PartsRequest,
    PartsRequestLine,
    ServiceJob,
    TaxRate,
    User,
    Vehicle,
    WorkCompletion,
)
from app.models.enums import (
    CLOSED_JOB_STATUSES,
    ApprovalStatus,
    EstimateStatus,
    InvoiceStatus,
    PartsLineStatus,
    RoleCode,
)
from app.models.enums import JobStatus as S
from app.services import settings as settings_service
from app.services.common import audit, next_number, notify_role, notify_user

INDIA = ZoneInfo("Asia/Kolkata")

TRANSITIONS: dict[str, set[str]] = {
    # READY_FOR_BILLING from the early stages is "direct billing" (bill_directly).
    S.RECEIVED: {S.AWAITING_ASSIGNMENT, S.READY_FOR_BILLING},
    S.AWAITING_ASSIGNMENT: {S.INSPECTION_IN_PROGRESS, S.READY_FOR_BILLING},
    S.INSPECTION_IN_PROGRESS: {S.AWAITING_PARTS, S.READY_FOR_SERVICE, S.READY_FOR_BILLING},
    S.AWAITING_ESTIMATE_APPROVAL: {S.AWAITING_PARTS, S.READY_FOR_SERVICE, S.INSPECTION_IN_PROGRESS},
    S.AWAITING_PARTS: {S.READY_FOR_SERVICE, S.READY_FOR_BILLING},
    S.READY_FOR_SERVICE: {S.IN_SERVICE, S.READY_FOR_BILLING},
    # No quality-inspection step: completed work goes straight to the Service Manager for billing.
    S.IN_SERVICE: {S.READY_FOR_BILLING},
    S.AWAITING_QUALITY_CHECK: {S.READY_FOR_BILLING, S.IN_SERVICE},  # old records only
    S.AWAITING_MANAGER_REVIEW: {S.READY_FOR_BILLING, S.IN_SERVICE},
    S.READY_FOR_BILLING: {S.READY_FOR_DELIVERY, S.IN_SERVICE},
    S.READY_FOR_DELIVERY: {S.COMPLETED, S.READY_FOR_BILLING},
    S.ON_HOLD: set(),  # resumes only to the status recorded before the hold
    S.COMPLETED: set(),
    S.CANCELLED: set(),
}
# Any job that has not reached delivery can be put on hold or cancelled.
_INTERRUPTIBLE = set(TRANSITIONS) - {S.READY_FOR_DELIVERY, S.COMPLETED, S.CANCELLED, S.ON_HOLD}
for _status in _INTERRUPTIBLE:
    TRANSITIONS[_status] |= {S.ON_HOLD, S.CANCELLED}
TRANSITIONS[S.ON_HOLD] |= {S.CANCELLED}

LABEL = {s: s.replace("_", " ").title() for s in S}


def add_event(
    db: Session,
    job: ServiceJob,
    event_type: str,
    message: str,
    actor: User | None,
    from_status: str | None = None,
    to_status: str | None = None,
) -> None:
    db.add(
        JobEvent(
            job_id=job.id,
            event_type=event_type,
            message=message,
            from_status=from_status,
            to_status=to_status,
            actor_id=actor.id if actor else None,
        )
    )


def transition(db: Session, job: ServiceJob, to: str, actor: User | None, message: str = "") -> None:
    current = job.status
    allowed = set(TRANSITIONS.get(current, set()))
    if current == S.ON_HOLD and job.status_before_hold:
        allowed.add(job.status_before_hold)
    if to not in allowed:
        raise DomainError(f"A job in status {LABEL[S(current)]} cannot move to {LABEL[S(to)]}")
    job.status = to
    add_event(db, job, "STATUS_CHANGE", message or f"Status changed to {LABEL[S(to)]}", actor, current, to)


def get_job(db: Session, job_id: int, lock: bool = False) -> ServiceJob:
    if lock:
        # Lock only the job row (it is joined-loaded with other tables).
        db.execute(select(ServiceJob.id).where(ServiceJob.id == job_id).with_for_update())
    job = db.get(ServiceJob, job_id, populate_existing=lock)
    if job is None:
        raise not_found("Job card")
    return job


def ensure_can_view(job: ServiceJob, user: User) -> None:
    perms = user.permissions
    if "job.read_all" in perms:
        return
    if "job.read_assigned" in perms and job.assigned_mechanic_id == user.id:
        return
    # 404 rather than 403 so job numbers cannot be probed.
    raise not_found("Job card")


def ensure_assigned_mechanic(job: ServiceJob, user: User) -> None:
    """Work is recorded by the Service Manager on behalf of the assigned mechanic (mechanics do not
    sign in). The permission check is done by the API; here a mechanic must be assigned."""
    if job.assigned_mechanic_id is None:
        raise DomainError("Assign a mechanic to this job first")


def _require_status(job: ServiceJob, *statuses: str, action: str) -> None:
    if job.status not in statuses:
        raise DomainError(f"Cannot {action} while the job is {LABEL[S(job.status)]}")


def _require_open(job: ServiceJob, action: str) -> None:
    if job.status in CLOSED_JOB_STATUSES:
        raise DomainError(f"Cannot {action}: the job is {LABEL[S(job.status)]} and its records are locked")


JOB_DETAIL_FIELDS = ("odometer", "fuel_level", "complaints", "condition_notes", "priority", "job_type", "estimated_completion_at")


def update_job_details(db: Session, job: ServiceJob, user: User, data: dict) -> None:
    """Service Manager corrections to the job card, allowed at any stage while the job is open."""
    _require_open(job, "edit the job card")
    changes = {}
    for key in JOB_DETAIL_FIELDS:
        if key in data and data[key] is not None and getattr(job, key) != data[key]:
            changes[key] = [str(getattr(job, key)), str(data[key])]
            setattr(job, key, data[key])
    if "estimated_completion_at" in data and data["estimated_completion_at"] is None and job.estimated_completion_at is not None:
        changes["estimated_completion_at"] = [str(job.estimated_completion_at), None]
        job.estimated_completion_at = None
    if not changes:
        return
    if "odometer" in changes:
        job.vehicle.odometer = max(job.vehicle.odometer or 0, job.odometer)
    add_event(db, job, "JOB_EDITED", "Job card edited: " + ", ".join(changes), user)
    audit(db, user, "job.edit", "service_job", job.id, f"Edited job card {job.job_number}", changes)


# Labour can be changed until the mechanic starts the service; after that it is fixed.
WORK_STATUSES = (S.INSPECTION_IN_PROGRESS, S.AWAITING_PARTS, S.READY_FOR_SERVICE)


def update_labour(db: Session, job: ServiceJob, user: User, labour_id: int, estimated_hours, notes) -> None:
    ensure_assigned_mechanic(job, user)
    _require_open(job, "edit labour")
    row = db.get(JobLabour, labour_id)
    if row is None or row.job_id != job.id:
        raise not_found("Labour operation")
    if estimated_hours is not None and estimated_hours != row.estimated_hours:
        # Billed hours are fixed once the service has started.
        _require_status(job, *WORK_STATUSES, action="change labour hours")
        add_event(db, job, "LABOUR_EDITED", f"{row.description}: hours changed {row.estimated_hours} -> {estimated_hours}", user)
        row.estimated_hours = estimated_hours
    if notes is not None:
        row.notes = notes


def update_completion(db: Session, job: ServiceJob, user: User, completion_id: int, data: dict) -> None:
    ensure_assigned_mechanic(job, user)
    _require_open(job, "edit the completion report")
    completion = db.get(WorkCompletion, completion_id)
    if completion is None or completion.job_id != job.id:
        raise not_found("Completion record")
    changed = [k for k, v in data.items() if v is not None and getattr(completion, k) != v]
    for key in changed:
        setattr(completion, key, data[key])
    if changed:
        add_event(db, job, "COMPLETION_EDITED", "Completion report edited: " + ", ".join(changed), user)
        audit(db, user, "completion.edit", "service_job", job.id, f"Edited completion report of {job.job_number}", {"fields": changed})


def active_jobs_for_vehicle(db: Session, vehicle_id: int) -> list[ServiceJob]:
    return list(
        db.scalars(
            select(ServiceJob).where(
                ServiceJob.vehicle_id == vehicle_id, ServiceJob.status.notin_(CLOSED_JOB_STATUSES)
            )
        )
    )


# --- Reception -------------------------------------------------------------------------


def create_job(
    db: Session,
    user: User,
    *,
    vehicle: Vehicle,
    odometer: int,
    fuel_level: str,
    complaints: str,
    condition_notes: str = "",
    priority: str = "NORMAL",
    job_type: str = "PAID",
    estimated_completion_at: datetime | None = None,
    mechanic_id: int | None = None,
    override_reason: str | None = None,
) -> ServiceJob:
    # Serialise concurrent receptions of the same vehicle so the active-job check is reliable.
    db.execute(select(Vehicle.id).where(Vehicle.id == vehicle.id).with_for_update())
    if not vehicle.is_active:
        raise DomainError("This vehicle record is inactive")
    active = active_jobs_for_vehicle(db, vehicle.id)
    if active and not (override_reason and override_reason.strip()):
        raise DomainError(
            {
                "code": "ACTIVE_JOB_EXISTS",
                "message": "This vehicle already has an active job card. "
                "Provide an override reason to open another.",
                "active_jobs": [
                    {"id": j.id, "job_number": j.job_number, "status": j.status} for j in active
                ],
            }
        )
    prefix = settings_service.get(db, "job_number_prefix")
    job = ServiceJob(
        job_number=next_number(db, "job", prefix),
        customer_id=vehicle.customer_id,
        vehicle_id=vehicle.id,
        odometer=odometer,
        fuel_level=fuel_level,
        complaints=complaints.strip(),
        condition_notes=condition_notes.strip(),
        priority=priority,
        job_type=job_type,
        estimated_completion_at=estimated_completion_at,
        created_by_id=user.id,
        status=S.RECEIVED,
        active_job_override_reason=override_reason.strip() if active and override_reason else None,
    )
    db.add(job)
    db.flush()
    add_event(db, job, "RECEIVED", f"Vehicle received, job card {job.job_number} opened", user, None, S.RECEIVED)
    if active:
        add_event(db, job, "OVERRIDE", f"Opened despite active job(s): {override_reason}", user)
    transition(db, job, S.AWAITING_ASSIGNMENT, user, "Awaiting mechanic assignment")
    vehicle.odometer = max(vehicle.odometer or 0, odometer)
    audit(
        db, user, "job.create", "service_job", job.id, f"Created job card {job.job_number}",
        {"vehicle": vehicle.registration_number, "override_reason": job.active_job_override_reason},
    )
    if mechanic_id:
        assign_mechanic(db, job, mechanic_id, user)
    return job


def assign_mechanic(db: Session, job: ServiceJob, mechanic_id: int, user: User, notes: str = "") -> None:
    if job.status in (*CLOSED_JOB_STATUSES, S.READY_FOR_DELIVERY, S.READY_FOR_BILLING):
        raise DomainError(f"Cannot assign a mechanic while the job is {LABEL[S(job.status)]}")
    mechanic = db.get(User, mechanic_id)
    if mechanic is None or not mechanic.is_active or mechanic.role_code != RoleCode.MECHANIC:
        raise bad_request("Select an active mechanic")
    if job.assigned_mechanic_id == mechanic.id:
        raise DomainError("The job is already assigned to this mechanic")
    for a in job.assignments:
        if a.unassigned_at is None:
            a.unassigned_at = utcnow()
    db.add(JobAssignment(job_id=job.id, mechanic_id=mechanic.id, assigned_by_id=user.id, notes=notes))
    job.assigned_mechanic_id = mechanic.id
    job.assigned_mechanic = mechanic
    add_event(db, job, "ASSIGNED", f"Assigned to {mechanic.full_name}", user)
    if job.status == S.AWAITING_ASSIGNMENT:
        transition(db, job, S.INSPECTION_IN_PROGRESS, user, "Inspection in progress")
    audit(db, user, "job.assign", "service_job", job.id, f"Assigned {job.job_number} to {mechanic.email}")


# --- Mechanic: inspection, labour, parts requests ---------------------------------------


def save_inspection(db: Session, job: ServiceJob, user: User, data: dict) -> Inspection:
    ensure_assigned_mechanic(job, user)
    _require_open(job, "edit the inspection")
    insp = job.inspection
    if insp is None:
        insp = Inspection(job_id=job.id, mechanic_id=job.assigned_mechanic_id)
        db.add(insp)
        job.inspection = insp
    changed = [k for k, v in data.items() if getattr(insp, k, None) != v]
    for key, value in data.items():
        setattr(insp, key, value)
    if changed and job.status != S.INSPECTION_IN_PROGRESS:
        # Corrections after submission stay possible, but leave a visible trail.
        add_event(db, job, "INSPECTION_EDITED", "Inspection findings edited: " + ", ".join(changed), user)
        audit(db, user, "inspection.edit", "service_job", job.id, f"Edited inspection of {job.job_number} after submission", {"fields": changed})
        if "spare_parts_notes" in changed and insp.submitted_at is not None:
            if insp.spare_parts_notes.strip():
                _send_spare_parts_list(db, job, user, updated=True)
            elif insp.spare_parts_status == "PENDING":
                insp.spare_parts_status = ""  # list cleared: nothing left for inventory
                sync_parts_state(db, job, user)
    insp.mechanic_id = job.assigned_mechanic_id
    db.flush()
    return insp


def add_labour(
    db: Session, job: ServiceJob, user: User, labour_operation_id: int,
    estimated_hours: Decimal | None, notes: str = "",
) -> JobLabour:
    ensure_assigned_mechanic(job, user)
    _require_status(job, *WORK_STATUSES, action="add labour")
    op = db.get(LabourOperation, labour_operation_id)
    if op is None or not op.is_active:
        raise bad_request("Select an active labour operation")
    additional = job.status == S.IN_SERVICE
    row = JobLabour(
        job_id=job.id,
        labour_operation_id=op.id,
        code=op.code,
        description=op.name,
        estimated_hours=estimated_hours if estimated_hours is not None else op.default_hours,
        hourly_rate=op.hourly_rate,
        tax_rate_id=op.tax_rate_id,
        is_additional=additional,
        approval_status=ApprovalStatus.APPROVED,  # no customer-approval step
        added_by_id=user.id,
        notes=notes,
    )
    db.add(row)
    db.flush()
    if additional:
        _flag_additional_work(db, job, user, f"Additional labour added: {op.name}")
    return row


def remove_labour(db: Session, job: ServiceJob, user: User, labour_id: int) -> None:
    ensure_assigned_mechanic(job, user)
    _require_status(job, *WORK_STATUSES, action="remove labour")
    row = db.get(JobLabour, labour_id)
    if row is None or row.job_id != job.id:
        raise not_found("Labour operation")
    add_event(db, job, "LABOUR_REMOVED", f"Labour removed: {row.description}", user)
    db.delete(row)


def _flag_additional_work(db: Session, job: ServiceJob, user: User, message: str) -> None:
    add_event(db, job, "ADDITIONAL_WORK", message, user)
    notify_role(
        db, RoleCode.SERVICE_MANAGER, "ADDITIONAL_WORK",
        f"Additional work added: {job.job_number}", message, "service_job", job.id,
    )


def create_parts_request(
    db: Session, job: ServiceJob, user: User, lines: list[dict], notes: str = ""
) -> PartsRequest:
    ensure_assigned_mechanic(job, user)
    _require_status(job, S.INSPECTION_IN_PROGRESS, S.IN_SERVICE, action="request parts")
    return _new_parts_request(db, job, user, lines, notes)


def _new_parts_request(db: Session, job: ServiceJob, user: User, lines: list[dict], notes: str) -> PartsRequest:
    if not lines:
        raise bad_request("Add at least one part to the request")
    additional = job.status == S.IN_SERVICE
    req = PartsRequest(
        request_number=next_number(db, "parts_request", "REQ"),
        job_id=job.id,
        requested_by_id=user.id,
        is_additional=additional,
        notes=notes,
    )
    seen: set[int] = set()
    for item in lines:
        part = db.get(Part, item["part_id"])
        if part is None or not part.is_active:
            raise bad_request("One of the selected parts does not exist or is inactive")
        if part.id in seen:
            raise bad_request(f"{part.sku} is listed twice; combine the quantities")
        seen.add(part.id)
        req.lines.append(
            PartsRequestLine(
                part_id=part.id,
                description=part.name,
                qty_requested=item["quantity"],
                urgency=item.get("urgency", "NORMAL"),
                notes=item.get("notes", ""),
                approval_status=ApprovalStatus.APPROVED,  # inventory may issue straight away
            )
        )
    db.add(req)
    db.flush()
    # Requesting never touches stock: quantities move only when inventory reserves or issues.
    add_event(db, job, "PARTS_REQUESTED", f"Parts request {req.request_number} ({len(req.lines)} line(s))", user)
    notify_role(
        db, RoleCode.INVENTORY_STAFF, "PARTS_REQUEST",
        f"New parts request {req.request_number}",
        f"{len(req.lines)} line(s) for job {job.job_number}", "parts_request", req.id,
    )
    if additional:
        _flag_additional_work(db, job, user, f"Additional parts requested ({req.request_number})")
    return req


def submit_inspection(db: Session, job: ServiceJob, user: User) -> None:
    ensure_assigned_mechanic(job, user)
    _require_status(job, S.INSPECTION_IN_PROGRESS, action="submit the inspection")
    insp = job.inspection
    if insp is None or not insp.recommended_repairs.strip():
        raise DomainError("Record the recommended repairs before submitting the inspection")
    insp.submitted_at = utcnow()
    if insp.spare_parts_notes.strip():
        _send_spare_parts_list(db, job, user)
    # There is no customer-approval step: the inspected work goes straight ahead.
    if has_outstanding_parts(job):
        transition(db, job, S.AWAITING_PARTS, user, "Inspection submitted; awaiting parts")
    else:
        transition(db, job, S.READY_FOR_SERVICE, user, "Inspection submitted; ready for service")
    notify_role(
        db, RoleCode.SERVICE_MANAGER, "INSPECTION_SUBMITTED",
        f"Inspection complete: {job.job_number}", insp.recommended_repairs[:200], "service_job", job.id,
    )


# --- Parts state ------------------------------------------------------------------------


def active_part_lines(job: ServiceJob) -> list[PartsRequestLine]:
    return [
        line
        for req in job.parts_requests
        for line in req.lines
        if line.status != PartsLineStatus.CANCELLED and line.approval_status != ApprovalStatus.REJECTED
    ]


def request_additional_parts(db: Session, job: ServiceJob, user: User, text: str) -> None:
    """During service the mechanic types the extra parts needed; they go to inventory to check by
    hand, like the inspection list. Work cannot be completed until inventory confirms them."""
    ensure_assigned_mechanic(job, user)
    _require_status(job, S.READY_FOR_SERVICE, S.IN_SERVICE, action="request additional parts")
    text = text.strip()
    if len(text) < 2:
        raise bad_request("Type the parts needed, one per line")
    insp = job.inspection
    if insp is None:
        raise DomainError("Submit the inspection first")
    stamp = utcnow().astimezone(INDIA).strftime("%d %b %H:%M")
    insp.spare_parts_notes = f"{insp.spare_parts_notes.rstrip()}\n\nAdditional parts ({stamp}):\n{text}".strip()
    if insp.spare_parts_status in ("PENDING", "UNAVAILABLE"):
        insp.spare_parts_unconfirmed = f"{insp.spare_parts_unconfirmed.rstrip()}\n{text}".strip()
    else:
        insp.spare_parts_unconfirmed = text
    insp.spare_parts_status = "PENDING"
    insp.spare_parts_done_by_id, insp.spare_parts_done_at, insp.spare_parts_done_note = None, None, ""
    add_event(db, job, "SPARE_PARTS_LIST", f"Additional parts requested: {text[:200]}", user)
    notify_role(db, RoleCode.INVENTORY_STAFF, "PARTS_REQUEST", f"Additional parts for {job.job_number}", text[:200], "service_job", job.id)
    _flag_additional_work(db, job, user, f"Additional parts requested: {text[:120]}")


def spare_parts_list_pending(job: ServiceJob) -> bool:
    """The written list still needs inventory: not yet checked, or checked and not available."""
    return job.inspection is not None and job.inspection.spare_parts_status in ("PENDING", "UNAVAILABLE")


def has_outstanding_parts(job: ServiceJob) -> bool:
    return spare_parts_list_pending(job) or any(line.qty_outstanding > 0 for line in active_part_lines(job))


def _send_spare_parts_list(db: Session, job: ServiceJob, user: User, updated: bool = False) -> None:
    """Hand the mechanic's written spare parts list to inventory staff."""
    insp = job.inspection
    insp.spare_parts_status = "PENDING"
    insp.spare_parts_unconfirmed = insp.spare_parts_notes.strip()
    insp.spare_parts_done_by_id, insp.spare_parts_done_at, insp.spare_parts_done_note = None, None, ""
    verb = "updated" if updated else "sent"
    add_event(db, job, "SPARE_PARTS_LIST", f"Spare parts list {verb} to inventory", user)
    notify_role(
        db, RoleCode.INVENTORY_STAFF, "PARTS_REQUEST",
        f"Spare parts list {'updated' if updated else 'for'} {job.job_number}",
        insp.spare_parts_notes.strip()[:200], "service_job", job.id,
    )


def _require_list(job: ServiceJob, *allowed: str) -> Inspection:
    _require_open(job, "handle the spare parts list")
    insp = job.inspection
    if insp is None or insp.spare_parts_status not in allowed:
        raise DomainError("There is no spare parts list waiting for inventory on this job")
    from app.services.billing import live_invoice  # local import: billing imports this module

    inv = live_invoice(job)
    if inv is not None and inv.status != "DRAFT":
        raise DomainError(f"Invoice {inv.invoice_number} is already finalised for this job")
    return insp


def _close_list(db: Session, job: ServiceJob, insp: Inspection, user: User, status: str, note: str) -> None:
    insp.spare_parts_status = status
    insp.spare_parts_done_by_id, insp.spare_parts_done_at, insp.spare_parts_done_note = user.id, utcnow(), note.strip()


def mark_spare_parts_available(db: Session, job: ServiceJob, user: User, lines: list[dict], note: str = "") -> None:
    """Inventory checked the shelf and confirms the written parts are available. A part picked
    from the catalogue is billed at its catalogue rate, HSN, unit and tax (whatever the client
    sent); a part not in the catalogue at the price entered. Re-confirming replaces the earlier
    lines (until invoiced)."""
    insp = _require_list(job, "PENDING", "UNAVAILABLE", "AVAILABLE")
    if not lines:
        raise bad_request("Enter at least one part with its quantity")
    job.manual_parts.clear()
    for item in lines:
        if item.get("part_id") is not None:
            part = db.get(Part, item["part_id"])
            if part is None or not part.is_active:
                raise bad_request("One of the selected parts is not in the catalogue")
            job.manual_parts.append(JobManualPart(
                part_id=part.id, description=part.name, hsn_code=part.hsn_code, unit=part.unit,
                quantity=item["quantity"], unit_price=part.selling_price, tax_rate_id=part.tax_rate_id, added_by_id=user.id,
            ))
            item["description"] = part.name  # for the job event below
            continue
        if item.get("unit_price") is None:
            raise bad_request(f"Enter the rate for {item['description']}, or pick it from the catalogue")
        tax_rate_id = item.get("tax_rate_id")
        if tax_rate_id is not None and db.get(TaxRate, tax_rate_id) is None:
            raise bad_request("Unknown tax rate")
        job.manual_parts.append(JobManualPart(
            description=item["description"], hsn_code=item.get("hsn_code", ""), unit=item.get("unit") or "NO",
            quantity=item["quantity"], unit_price=item["unit_price"], tax_rate_id=tax_rate_id, added_by_id=user.id,
        ))
    _close_list(db, job, insp, user, "AVAILABLE", note)
    insp.spare_parts_unconfirmed = ""
    summary = ", ".join(f"{l['description']} x {l['quantity']}" for l in lines)
    add_event(db, job, "SPARE_PARTS_LIST", f"Inventory confirmed spare parts available: {summary}", user)
    notify_role(db, RoleCode.SERVICE_MANAGER, "PARTS_READY", f"Spare parts available: {job.job_number}", summary[:200], "service_job", job.id)
    db.flush()
    sync_parts_state(db, job, user)


def mark_spare_parts_unavailable(db: Session, job: ServiceJob, user: User, note: str) -> None:
    """Inventory checked and the parts are not in stock. The job keeps waiting for parts; the
    list can be marked available later, or the mechanic can change it."""
    insp = _require_list(job, "PENDING", "UNAVAILABLE")
    if len(note.strip()) < 3:
        raise bad_request("Say which parts are not available (and when they are expected, if known)")
    _close_list(db, job, insp, user, "UNAVAILABLE", note)
    add_event(db, job, "SPARE_PARTS_LIST", f"Inventory: spare parts not available - {note.strip()}", user)
    title = f"Spare parts not available: {job.job_number}"
    notify_role(db, RoleCode.SERVICE_MANAGER, "PARTS_UNAVAILABLE", title, note.strip()[:200], "service_job", job.id)


def sync_parts_state(db: Session, job: ServiceJob, actor: User | None) -> None:
    """Move a job out of AWAITING_PARTS once nothing is outstanding."""
    if job.status == S.AWAITING_PARTS and not has_outstanding_parts(job):
        transition(db, job, S.READY_FOR_SERVICE, actor, "All required parts issued; ready for service")
        notify_role(
            db, RoleCode.SERVICE_MANAGER, "PARTS_READY", f"Parts ready: {job.job_number}",
            "All requested parts have been issued.", "service_job", job.id,
        )


def pending_approval_items(job: ServiceJob) -> list[str]:
    items = [f"labour: {lab.description}" for lab in job.labour if lab.approval_status == ApprovalStatus.PENDING]
    items += [
        f"part: {line.part.sku}"
        for line in active_part_lines(job)
        if line.approval_status == ApprovalStatus.PENDING
    ]
    return items


# --- Service and completion -------------------------------------------------------------


def start_service(db: Session, job: ServiceJob, user: User) -> None:
    ensure_assigned_mechanic(job, user)
    _require_status(job, S.READY_FOR_SERVICE, action="start service")
    transition(db, job, S.IN_SERVICE, user, "Service started")


def complete_work(db: Session, job: ServiceJob, user: User, data: dict) -> WorkCompletion:
    ensure_assigned_mechanic(job, user)
    _require_status(job, S.IN_SERVICE, action="complete the work")
    if has_outstanding_parts(job):
        raise DomainError("Some requested parts are still outstanding; they must be issued or cancelled first")

    hours = {item["labour_id"]: item["actual_hours"] for item in data.get("labour", [])}
    for lab in job.labour:
        if lab.approval_status != ApprovalStatus.APPROVED:
            continue
        if lab.id in hours:
            lab.actual_hours = hours[lab.id]
        if lab.actual_hours is None:
            lab.actual_hours = lab.estimated_hours  # labour is billed at the planned hours anyway

    consumed = {item["line_id"]: item["qty_consumed"] for item in data.get("parts", [])}
    for line in active_part_lines(job):
        if line.id in consumed:
            qty = consumed[line.id]
            if qty > line.qty_issued - line.qty_returned:
                raise bad_request(
                    f"{line.part.sku}: consumed quantity cannot exceed the quantity issued and not returned"
                )
            line.qty_consumed = qty
        if line.qty_issued > 0 and line.qty_consumed is None:
            raise bad_request(f"Record the quantity of {line.part.sku} actually consumed")

    completion = WorkCompletion(
        job_id=job.id,
        mechanic_id=job.assigned_mechanic_id,  # credited to the mechanic, recorded by the manager
        repairs_completed=data["repairs_completed"].strip(),
        outstanding_issues=data.get("outstanding_issues", "").strip(),
        final_observations=data.get("final_observations", "").strip(),
    )
    db.add(completion)
    job.returned_for_rework = False
    transition(db, job, S.READY_FOR_BILLING, user, "Work completed; ready for billing")
    notify_role(
        db, RoleCode.SERVICE_MANAGER, "WORK_COMPLETED", f"Work completed: {job.job_number}",
        "Ready for billing.", "service_job", job.id,
    )
    unused = [l for l in active_part_lines(job) if l.qty_unreconciled > 0]
    if unused:
        notify_role(
            db, RoleCode.INVENTORY_STAFF, "PARTS_RETURN_DUE", f"Unused parts to return: {job.job_number}",
            ", ".join(f"{l.part.sku} x {l.qty_unreconciled}" for l in unused), "service_job", job.id,
        )
    return completion


def _send_back_to_mechanic(db: Session, job: ServiceJob, user: User, reason: str, event: str) -> None:
    job.rework_count += 1
    job.returned_for_rework = True
    transition(db, job, S.IN_SERVICE, user, f"{event}: {reason}")


DIRECT_BILL_FROM = (
    S.RECEIVED, S.AWAITING_ASSIGNMENT, S.INSPECTION_IN_PROGRESS, S.AWAITING_PARTS, S.READY_FOR_SERVICE, S.IN_SERVICE,
)


def bill_directly(db: Session, job: ServiceJob, user: User, description: str) -> None:
    """Skip the remaining workshop steps and send the job straight to billing (quick jobs such as a
    wash, a small fitment or a parts sale). The usual billing checks still apply afterwards, so
    stock issued but not accounted for, or a parts list still waiting for inventory, blocks it."""
    _require_status(job, *DIRECT_BILL_FROM, action="bill directly")
    text = (description or "").strip() or job.complaints
    job.completions.append(WorkCompletion(
        job_id=job.id, mechanic_id=job.assigned_mechanic_id or user.id, repairs_completed=text,
        final_observations="Billed directly by the Service Manager (inspection and workshop steps skipped).",
    ))
    job.returned_for_rework = False
    transition(db, job, S.READY_FOR_BILLING, user, f"Billed directly: {text[:150]}")
    audit(db, user, "job.direct_bill", "service_job", job.id, f"Billed {job.job_number} directly", {"description": text})


def return_to_mechanic(db: Session, job: ServiceJob, user: User, reason: str) -> None:
    _require_status(
        job, S.READY_FOR_BILLING, S.AWAITING_QUALITY_CHECK, S.AWAITING_MANAGER_REVIEW,
        action="return the job to the mechanic",
    )
    for inv in job.invoices:
        if inv.status == InvoiceStatus.FINALISED:
            raise DomainError("Cancel the finalised invoice before returning the job to the mechanic")
        if inv.status == InvoiceStatus.DRAFT:
            db.delete(inv)
    _send_back_to_mechanic(db, job, user, reason, "Returned by Service Manager")
    audit(db, user, "job.return", "service_job", job.id, f"Returned {job.job_number} to mechanic", {"reason": reason})


# --- Hold / cancel / delivery -----------------------------------------------------------


def hold_job(db: Session, job: ServiceJob, user: User, reason: str) -> None:
    previous = job.status
    transition(db, job, S.ON_HOLD, user, f"Put on hold: {reason}")
    job.status_before_hold = previous
    job.hold_reason = reason
    audit(db, user, "job.hold", "service_job", job.id, f"Put {job.job_number} on hold", {"reason": reason})


def resume_job(db: Session, job: ServiceJob, user: User) -> None:
    _require_status(job, S.ON_HOLD, action="resume the job")
    transition(db, job, job.status_before_hold, user, "Resumed from hold")
    job.status_before_hold = None
    job.hold_reason = None
    sync_parts_state(db, job, user)


def cancel_job(db: Session, job: ServiceJob, user: User, reason: str) -> None:
    from app.services import inventory  # local import: inventory depends on this module

    if any(inv.status == InvoiceStatus.FINALISED for inv in job.invoices):
        raise DomainError("A job with a finalised invoice cannot be cancelled; cancel the invoice first")
    lines = [l for r in job.parts_requests for l in r.lines]
    if any(l.qty_issued - l.qty_returned > 0 for l in lines):
        raise DomainError("Issued parts must be returned to inventory before the job can be cancelled")
    transition(db, job, S.CANCELLED, user, f"Cancelled: {reason}")
    for line in lines:
        if line.status != PartsLineStatus.CANCELLED:
            inventory.cancel_line(db, line, user, "Job cancelled")
    for inv in job.invoices:
        if inv.status == InvoiceStatus.DRAFT:
            db.delete(inv)
    job.cancel_reason = reason
    audit(db, user, "job.cancel", "service_job", job.id, f"Cancelled {job.job_number}", {"reason": reason})


def mark_ready_for_delivery(db: Session, job: ServiceJob, user: User) -> None:
    _require_status(job, S.READY_FOR_BILLING, action="mark the vehicle ready for delivery")
    if not any(inv.status == InvoiceStatus.FINALISED for inv in job.invoices):
        raise DomainError("Finalise the invoice before marking the vehicle ready for delivery")
    job.ready_for_delivery_at = utcnow()
    transition(db, job, S.READY_FOR_DELIVERY, user, "Vehicle ready for delivery")
    notify_role(
        db, RoleCode.SERVICE_MANAGER, "READY_FOR_DELIVERY", f"Vehicle ready: {job.job_number}",
        job.vehicle.registration_number, "service_job", job.id,
    )


def record_handover(
    db: Session, job: ServiceJob, user: User, received_by: str, notes: str, allow_outstanding: bool
) -> None:
    _require_status(job, S.READY_FOR_DELIVERY, action="record the handover")
    invoice = next((i for i in job.invoices if i.status == InvoiceStatus.FINALISED), None)
    if invoice is None:
        raise DomainError("No finalised invoice exists for this job")
    if invoice.outstanding > 0 and not allow_outstanding:
        raise DomainError(
            {
                "code": "OUTSTANDING_BALANCE",
                "message": f"Invoice {invoice.invoice_number} has an outstanding balance of "
                f"INR {invoice.outstanding}. Confirm to hand over anyway.",
            }
        )
    job.delivered_at = utcnow()
    job.handover_to = received_by.strip()
    job.handover_notes = notes.strip()
    job.handover_by_id = user.id
    transition(db, job, S.COMPLETED, user, f"Vehicle handed over to {job.handover_to}")
    audit(
        db, user, "job.handover", "service_job", job.id, f"Handed over {job.job_number}",
        {"received_by": job.handover_to, "outstanding": str(invoice.outstanding)},
    )
