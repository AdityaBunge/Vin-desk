"""Stock control. Every stock change:

* locks the part's inventory_stock row (SELECT ... FOR UPDATE) for the whole transaction, so two
  concurrent issues of the same part are serialised and the second sees the reduced quantity;
* is validated so stock can never go negative (also enforced by CHECK constraints);
* writes an inventory_movements row recording who did it and when.

Lock order is always: parts-request line, then stock row.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError, bad_request, forbidden, not_found
from app.core.utils import ZERO, utcnow
from app.models import (
    InventoryMovement,
    InventoryStock,
    Part,
    PartsRequest,
    PartsRequestLine,
    PurchaseRequest,
    PurchaseRequestLine,
    ServiceJob,
    User,
)
from app.models.enums import (
    CLOSED_JOB_STATUSES,
    AlternativeStatus,
    ApprovalStatus,
    MovementType,
    PartsLineStatus,
    PartsRequestStatus,
    PurchaseRequestStatus,
    RoleCode,
)
from app.services import jobs as jobs_service
from app.services.common import audit, next_number, notify_role, notify_user


def lock_stock(db: Session, part_id: int) -> InventoryStock:
    stock = db.execute(
        select(InventoryStock)
        .where(InventoryStock.part_id == part_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if stock is None:
        stock = InventoryStock(part_id=part_id, qty_on_hand=ZERO, qty_reserved=ZERO)
        db.add(stock)
        db.flush()
    return stock


def lock_line(db: Session, line_id: int) -> PartsRequestLine:
    db.execute(select(PartsRequestLine.id).where(PartsRequestLine.id == line_id).with_for_update())
    line = db.get(PartsRequestLine, line_id, populate_existing=True)
    if line is None:
        raise not_found("Parts request line")
    return line


def _move(
    db: Session, stock: InventoryStock, movement_type: str, quantity: Decimal, user: User,
    *, line: PartsRequestLine | None = None, job_id: int | None = None,
    purchase_request_id: int | None = None, reason: str = "",
) -> InventoryMovement:
    movement = InventoryMovement(
        part_id=stock.part_id,
        movement_type=movement_type,
        quantity=quantity,
        on_hand_after=stock.qty_on_hand,
        reserved_after=stock.qty_reserved,
        job_id=job_id if job_id is not None else (line.request.job_id if line else None),
        parts_request_line_id=line.id if line else None,
        purchase_request_id=purchase_request_id,
        reason=reason,
        performed_by_id=user.id,
    )
    db.add(movement)
    return movement


def _positive(quantity: Decimal) -> None:
    if quantity is None or quantity <= 0:
        raise bad_request("Quantity must be greater than zero")


def refresh_line_status(line: PartsRequestLine) -> None:
    if line.status == PartsLineStatus.CANCELLED:
        return
    remaining = line.qty_requested - line.qty_issued
    if remaining <= 0:
        line.status, line.is_short = PartsLineStatus.ISSUED, False
    elif line.qty_issued > 0:
        line.status = PartsLineStatus.PARTIALLY_ISSUED
    elif line.qty_reserved >= remaining:
        line.status, line.is_short = PartsLineStatus.RESERVED, False
    elif line.qty_reserved > 0:
        line.status = PartsLineStatus.PARTIALLY_RESERVED
    elif line.is_short:
        line.status = PartsLineStatus.UNAVAILABLE
    else:
        line.status = PartsLineStatus.PENDING
    line.qty_approved = line.qty_reserved + line.qty_issued
    refresh_request_status(line.request)


def refresh_request_status(req: PartsRequest) -> None:
    live = [l for l in req.lines if l.status != PartsLineStatus.CANCELLED]
    if not live:
        req.status = PartsRequestStatus.CANCELLED
    elif all(l.status == PartsLineStatus.ISSUED for l in live):
        req.status = PartsRequestStatus.FULFILLED
    elif any(l.qty_issued > 0 or l.qty_reserved > 0 for l in live):
        req.status = PartsRequestStatus.PARTIALLY_FULFILLED
    elif all(l.status == PartsLineStatus.UNAVAILABLE for l in live):
        req.status = PartsRequestStatus.UNAVAILABLE
    else:
        req.status = PartsRequestStatus.PENDING


def _line_open(line: PartsRequestLine) -> ServiceJob:
    if line.status == PartsLineStatus.CANCELLED:
        raise DomainError("This parts request line has been cancelled")
    job = line.request.job
    if job.status in CLOSED_JOB_STATUSES:
        raise DomainError("The job for this parts request is closed")
    return job


# --- Fulfilment against job cards -------------------------------------------------------


def reserve(db: Session, line_id: int, quantity: Decimal, user: User) -> PartsRequestLine:
    _positive(quantity)
    line = lock_line(db, line_id)
    _line_open(line)
    remaining = line.qty_requested - line.qty_issued - line.qty_reserved
    if quantity > remaining:
        raise DomainError(f"Only {remaining} more can be reserved for this line")
    stock = lock_stock(db, line.part_id)
    if quantity > stock.qty_available:
        raise DomainError(
            f"Insufficient stock for {line.part.sku}: {stock.qty_available} available, {quantity} requested"
        )
    stock.qty_reserved += quantity
    line.qty_reserved += quantity
    _move(db, stock, MovementType.RESERVED, quantity, user, line=line)
    refresh_line_status(line)
    return line


def issue(db: Session, line_id: int, quantity: Decimal, user: User) -> PartsRequestLine:
    _positive(quantity)
    line = lock_line(db, line_id)
    job = _line_open(line)
    if line.approval_status != ApprovalStatus.APPROVED:
        raise DomainError("Parts can be issued only after the customer has approved the estimate for them")
    if quantity > line.qty_requested - line.qty_issued:
        raise DomainError(f"Only {line.qty_requested - line.qty_issued} remain to be issued for this line")
    stock = lock_stock(db, line.part_id)
    from_reservation = min(quantity, line.qty_reserved)
    from_free_stock = quantity - from_reservation
    if from_free_stock > stock.qty_available:
        raise DomainError(
            f"Insufficient stock for {line.part.sku}: {stock.qty_available + from_reservation} can be issued, "
            f"{quantity} requested"
        )
    stock.qty_on_hand -= quantity
    stock.qty_reserved -= from_reservation
    line.qty_reserved -= from_reservation
    line.qty_issued += quantity
    _move(db, stock, MovementType.ISSUED, quantity, user, line=line)
    refresh_line_status(line)
    jobs_service.add_event(
        db, job, "PARTS_ISSUED", f"Issued {quantity} x {line.part.sku} ({line.part.name})", user
    )
    if line.qty_outstanding > 0:
        notify_role(
            db, RoleCode.SERVICE_MANAGER, "PARTS_PARTIAL", f"Partial issue: {job.job_number}",
            f"{line.part.sku}: {line.qty_issued} of {line.qty_requested} issued", "service_job", job.id,
        )
    jobs_service.sync_parts_state(db, job, user)
    _check_low_stock(db, stock)
    return line


def release_reservation(db: Session, line: PartsRequestLine, user: User, reason: str) -> None:
    if line.qty_reserved <= 0:
        return
    stock = lock_stock(db, line.part_id)
    quantity = line.qty_reserved
    stock.qty_reserved -= quantity
    line.qty_reserved = ZERO
    _move(db, stock, MovementType.RESERVATION_RELEASED, quantity, user, line=line, reason=reason)


def return_unused(db: Session, line_id: int, quantity: Decimal, user: User, reason: str = "") -> PartsRequestLine:
    """Unused issued parts come back into stock."""
    _positive(quantity)
    line = lock_line(db, line_id)
    returnable = line.qty_unreconciled
    if quantity > returnable:
        raise DomainError(
            f"Only {returnable} of {line.part.sku} can be returned (issued less consumed and already returned)"
        )
    stock = lock_stock(db, line.part_id)
    stock.qty_on_hand += quantity
    line.qty_returned += quantity
    _move(db, stock, MovementType.RETURNED, quantity, user, line=line, reason=reason)
    jobs_service.add_event(
        db, line.request.job, "PARTS_RETURNED", f"Returned {quantity} x {line.part.sku} to stock", user
    )
    return line


def mark_unavailable(
    db: Session, line_id: int, user: User, expected_restock_date: date | None, notes: str
) -> PartsRequestLine:
    line = lock_line(db, line_id)
    job = _line_open(line)
    if line.qty_outstanding <= 0:
        raise DomainError("Nothing is outstanding on this line")
    line.is_short = True
    line.expected_restock_date = expected_restock_date
    line.inventory_notes = notes
    refresh_line_status(line)
    missing = line.qty_outstanding - line.qty_reserved
    jobs_service.add_event(
        db, job, "PARTS_SHORTAGE", f"Shortage: {missing} x {line.part.sku} unavailable", user
    )
    notify_role(
        db, RoleCode.SERVICE_MANAGER, "PARTS_UNAVAILABLE",
        f"Part unavailable for {job.job_number}",
        f"{line.part.sku} {line.part.name}: {missing} short"
        + (f", restock expected {expected_restock_date:%d %b %Y}" if expected_restock_date else ""),
        "service_job", job.id,
    )
    return line


def propose_alternative(db: Session, line_id: int, alt_part_id: int, user: User, notes: str) -> PartsRequestLine:
    line = lock_line(db, line_id)
    job = _line_open(line)
    if line.qty_issued > 0:
        raise DomainError("An alternative cannot be proposed after stock has been issued on this line")
    alt = db.get(Part, alt_part_id)
    if alt is None or not alt.is_active or alt.id == line.part_id:
        raise bad_request("Select a different, active part as the alternative")
    line.alt_part_id, line.alt_status, line.alt_notes = alt.id, AlternativeStatus.PROPOSED, notes
    notify_role(
        db, RoleCode.SERVICE_MANAGER, "ALTERNATIVE_PROPOSED",
        f"Alternative part proposed for {job.job_number}",
        f"{line.part.sku} -> {alt.sku} {alt.name}", "service_job", job.id,
    )
    return line


def decide_alternative(db: Session, line_id: int, approve: bool, user: User, notes: str = "") -> PartsRequestLine:
    line = lock_line(db, line_id)
    job = _line_open(line)
    if line.alt_status != AlternativeStatus.PROPOSED:
        raise DomainError("There is no pending alternative proposal on this line")
    alt = db.get(Part, line.alt_part_id)
    if approve:
        if line.qty_issued > 0:
            raise DomainError("Stock has already been issued on this line")
        release_reservation(db, line, user, "Alternative part approved")
        old_sku = line.part.sku
        line.original_part_id = line.original_part_id or line.part_id
        line.part_id, line.part = alt.id, alt
        line.description = alt.name
        line.alt_status = AlternativeStatus.APPROVED
        line.is_short, line.expected_restock_date = False, None
        refresh_line_status(line)
        jobs_service.add_event(db, job, "ALTERNATIVE_APPROVED", f"Alternative approved: {old_sku} -> {alt.sku}", user)
    else:
        line.alt_status = AlternativeStatus.REJECTED
    if notes:
        line.alt_notes = f"{line.alt_notes}\nDecision: {notes}".strip()
    notify_role(
        db, RoleCode.INVENTORY_STAFF, "ALTERNATIVE_DECISION",
        f"Alternative {'approved' if approve else 'rejected'}: {job.job_number}",
        f"{alt.sku} {alt.name}", "parts_request", line.request_id,
    )
    audit(
        db, user, "parts.alternative_decision", "parts_request_line", line.id,
        f"Alternative {alt.sku} {'approved' if approve else 'rejected'} for {job.job_number}",
    )
    return line


def cancel_line(db: Session, line: PartsRequestLine, user: User, reason: str) -> None:
    if line.qty_issued - line.qty_returned > 0:
        raise DomainError("Issued parts must be returned before the line can be cancelled")
    release_reservation(db, line, user, reason)
    line.status = PartsLineStatus.CANCELLED
    line.cancel_reason = reason
    refresh_request_status(line.request)


def cancel_line_by_id(db: Session, line_id: int, user: User, reason: str) -> PartsRequestLine:
    line = lock_line(db, line_id)
    job = _line_open(line)
    if "job.manage" not in user.permissions:
        # A mechanic may withdraw only lines on their own job (cancel_line refuses issued stock).
        if job.assigned_mechanic_id != user.id:
            raise forbidden()
    cancel_line(db, line, user, reason)
    jobs_service.add_event(db, job, "PARTS_LINE_CANCELLED", f"Cancelled request for {line.part.sku}: {reason}", user)
    jobs_service.sync_parts_state(db, job, user)
    return line


def update_line(db: Session, line_id: int, user: User, quantity, urgency, notes) -> PartsRequestLine:
    """The requesting mechanic corrects a request line. Quantity can change only while nothing
    has been reserved or issued against it."""
    line = lock_line(db, line_id)
    job = _line_open(line)
    jobs_service.ensure_assigned_mechanic(job, user)
    if quantity is not None and quantity != line.qty_requested:
        if line.qty_reserved > 0 or line.qty_issued > 0:
            raise DomainError("Stock is already reserved or issued for this line; its quantity can no longer be changed")
        _positive(quantity)
        jobs_service.add_event(db, job, "PARTS_LINE_EDITED", f"{line.part.sku}: quantity changed {line.qty_requested} -> {quantity}", user)
        line.qty_requested = quantity
    if urgency is not None:
        line.urgency = urgency
    if notes is not None:
        line.notes = notes
    refresh_line_status(line)
    return line


def update_purchase_request(db: Session, pr_id: int, user: User, lines: list[dict], supplier_id, notes: str) -> PurchaseRequest:
    pr = _lock_pr(db, pr_id)
    if pr.status != PurchaseRequestStatus.PENDING_APPROVAL:
        raise DomainError("A purchase request can be edited only while it is awaiting approval")
    if not lines:
        raise bad_request("Add at least one part to the purchase request")
    pr.supplier_id, pr.notes = supplier_id, notes
    pr.lines.clear()
    db.flush()
    for item in lines:
        part = db.get(Part, item["part_id"])
        if part is None:
            raise bad_request("One of the selected parts does not exist")
        _positive(item["quantity"])
        pr.lines.append(PurchaseRequestLine(
            part_id=part.id, quantity=item["quantity"],
            unit_cost=item.get("unit_cost") if item.get("unit_cost") is not None else part.purchase_cost,
            parts_request_line_id=item.get("parts_request_line_id"),
        ))
    audit(db, user, "purchase.edit", "purchase_request", pr.id, f"Edited {pr.pr_number} before approval")
    return pr


# --- Stock receipts, adjustments, write-offs --------------------------------------------


def _check_low_stock(db: Session, stock: InventoryStock) -> None:
    part = db.get(Part, stock.part_id)
    before = stock.qty_available
    if part and part.is_active and before <= part.reorder_threshold:
        notify_role(
            db, RoleCode.INVENTORY_STAFF, "LOW_STOCK", f"Low stock: {part.sku}",
            f"{part.name}: {before} available (reorder at {part.reorder_threshold})", "part", part.id,
        )


def receive_stock(
    db: Session, part_id: int, quantity: Decimal, user: User, reason: str = "",
    purchase_request_id: int | None = None,
) -> InventoryStock:
    _positive(quantity)
    if db.get(Part, part_id) is None:
        raise not_found("Part")
    stock = lock_stock(db, part_id)
    stock.qty_on_hand += quantity
    _move(db, stock, MovementType.RECEIVED, quantity, user, reason=reason, purchase_request_id=purchase_request_id)
    return stock


def adjust_stock(db: Session, part_id: int, delta: Decimal, user: User, reason: str) -> InventoryStock:
    """Authorised correction after a stock count. `delta` may be negative."""
    if delta == 0:
        raise bad_request("Adjustment quantity cannot be zero")
    if not reason.strip():
        raise bad_request("A reason is required for stock adjustments")
    if db.get(Part, part_id) is None:
        raise not_found("Part")
    stock = lock_stock(db, part_id)
    if stock.qty_on_hand + delta < stock.qty_reserved:
        raise DomainError(
            f"Adjustment would leave {stock.qty_on_hand + delta} on hand, below the {stock.qty_reserved} reserved"
        )
    stock.qty_on_hand += delta
    _move(db, stock, MovementType.ADJUSTMENT, delta, user, reason=reason)
    audit(db, user, "inventory.adjust", "part", part_id, f"Stock adjusted by {delta}", {"reason": reason})
    return stock


def write_off(db: Session, part_id: int, quantity: Decimal, user: User, reason: str) -> InventoryStock:
    _positive(quantity)
    if not reason.strip():
        raise bad_request("A reason is required for write-offs")
    if db.get(Part, part_id) is None:
        raise not_found("Part")
    stock = lock_stock(db, part_id)
    if quantity > stock.qty_available:
        raise DomainError(f"Only {stock.qty_available} unreserved units can be written off")
    stock.qty_on_hand -= quantity
    _move(db, stock, MovementType.WRITE_OFF, quantity, user, reason=reason)
    audit(db, user, "inventory.write_off", "part", part_id, f"Wrote off {quantity}", {"reason": reason})
    return stock


# --- Purchase requests ------------------------------------------------------------------


def create_purchase_request(
    db: Session, user: User, lines: list[dict], supplier_id: int | None, notes: str
) -> PurchaseRequest:
    if not lines:
        raise bad_request("Add at least one part to the purchase request")
    pr = PurchaseRequest(
        pr_number=next_number(db, "purchase_request", "PUR"),
        supplier_id=supplier_id,
        notes=notes,
        created_by_id=user.id,
    )
    for item in lines:
        part = db.get(Part, item["part_id"])
        if part is None:
            raise bad_request("One of the selected parts does not exist")
        _positive(item["quantity"])
        pr.lines.append(
            PurchaseRequestLine(
                part_id=part.id,
                quantity=item["quantity"],
                unit_cost=item.get("unit_cost") if item.get("unit_cost") is not None else part.purchase_cost,
                parts_request_line_id=item.get("parts_request_line_id"),
            )
        )
    db.add(pr)
    db.flush()
    notify_role(
        db, RoleCode.SERVICE_MANAGER, "PURCHASE_REQUEST", f"Purchase request {pr.pr_number} needs approval",
        f"{len(pr.lines)} line(s)", "purchase_request", pr.id,
    )
    audit(db, user, "purchase.create", "purchase_request", pr.id, f"Created {pr.pr_number}")
    return pr


def _lock_pr(db: Session, pr_id: int) -> PurchaseRequest:
    db.execute(select(PurchaseRequest.id).where(PurchaseRequest.id == pr_id).with_for_update())
    pr = db.get(PurchaseRequest, pr_id, populate_existing=True)
    if pr is None:
        raise not_found("Purchase request")
    return pr


def decide_purchase_request(db: Session, pr_id: int, approve: bool, user: User, notes: str) -> PurchaseRequest:
    pr = _lock_pr(db, pr_id)
    if pr.status != PurchaseRequestStatus.PENDING_APPROVAL:
        raise DomainError("This purchase request has already been decided")
    if pr.created_by_id == user.id:
        raise forbidden("You cannot approve a purchase request you created")
    pr.status = PurchaseRequestStatus.APPROVED if approve else PurchaseRequestStatus.REJECTED
    pr.decided_by_id, pr.decided_at, pr.decision_notes = user.id, utcnow(), notes
    notify_user(
        db, pr.created_by_id, "PURCHASE_DECISION",
        f"Purchase request {pr.pr_number} {'approved' if approve else 'rejected'}", notes,
        "purchase_request", pr.id,
    )
    audit(
        db, user, "purchase.approve" if approve else "purchase.reject", "purchase_request", pr.id,
        f"{pr.pr_number} {'approved' if approve else 'rejected'}", {"notes": notes},
    )
    return pr


def receive_purchase_request(db: Session, pr_id: int, user: User, received: list[dict] | None) -> PurchaseRequest:
    """Record goods received against an approved purchase request (all lines in full by default)."""
    pr = _lock_pr(db, pr_id)
    if pr.status not in (PurchaseRequestStatus.APPROVED, PurchaseRequestStatus.PARTIALLY_RECEIVED):
        raise DomainError("Stock can be received only against an approved purchase request")
    wanted = {r["line_id"]: r["quantity"] for r in received} if received else None
    # Lock stock rows in a stable order to avoid deadlocks between concurrent receipts.
    for line in sorted(pr.lines, key=lambda l: l.part_id):
        quantity = line.quantity - line.qty_received if wanted is None else wanted.get(line.id, ZERO)
        if quantity <= 0:
            continue
        if quantity > line.quantity - line.qty_received:
            raise DomainError("Received quantity exceeds the quantity ordered")
        receive_stock(db, line.part_id, quantity, user, f"Received against {pr.pr_number}", pr.id)
        line.qty_received += quantity
    if all(l.qty_received >= l.quantity for l in pr.lines):
        pr.status, pr.received_at = PurchaseRequestStatus.RECEIVED, utcnow()
    else:
        pr.status = PurchaseRequestStatus.PARTIALLY_RECEIVED
    notify_role(
        db, RoleCode.SERVICE_MANAGER, "STOCK_RECEIVED", f"Stock received: {pr.pr_number}", "",
        "purchase_request", pr.id,
    )
    audit(db, user, "purchase.receive", "purchase_request", pr.id, f"Received stock against {pr.pr_number}")
    return pr
