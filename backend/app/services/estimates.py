"""Estimates (versioned quotes). There is no customer-approval step: an estimate is an
optional document the Service Manager can prepare, discount and print for the customer."""
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import DomainError, bad_request, not_found
from app.core.utils import ZERO, D, money
from app.models import Estimate, EstimateLine, ServiceJob, User
from app.models.enums import ApprovalStatus, EstimateStatus, JobStatus, LineType
from app.services import jobs as jobs_service
from app.services import settings as settings_service
from app.services.common import audit


def calc_line(quantity, unit_price, discount, tax_rate) -> tuple[Decimal, Decimal, Decimal]:
    """Returns (gross, tax_amount, line_total), each rounded to paise."""
    gross = money(D(quantity) * D(unit_price))
    taxable = gross - money(discount)
    tax = money(taxable * D(tax_rate) / Decimal("100"))
    return gross, tax, taxable + tax


def check_discount(db: Session, gross: Decimal, discount: Decimal) -> None:
    if discount < 0:
        raise bad_request("Discount cannot be negative")
    limit_pct = D(settings_service.get(db, "max_discount_percent"))
    if discount > money(gross * limit_pct / Decimal("100")):
        raise DomainError(f"Discount exceeds the authorised limit of {limit_pct}% of the line amount")


def _recalculate(est: Estimate) -> None:
    labour = parts = discount = tax = total = ZERO
    for line in est.lines:
        gross, line.tax_amount, line.line_total = calc_line(
            line.quantity, line.unit_price, line.discount_amount, line.tax_rate
        )
        if line.line_type == LineType.LABOUR:
            labour += gross
        else:
            parts += gross
        discount += line.discount_amount
        tax += line.tax_amount
        total += line.line_total
    est.subtotal_labour, est.subtotal_parts = labour, parts
    est.discount_total, est.tax_total, est.total = discount, tax, total


def get_estimate(db: Session, estimate_id: int) -> Estimate:
    est = db.get(Estimate, estimate_id)
    if est is None:
        raise not_found("Estimate")
    return est


def create_estimate(db: Session, job: ServiceJob, user: User) -> Estimate:
    """Build a new estimate version from the job's current labour and parts.

    Earlier open versions become SUPERSEDED and are kept for history.
    """
    allowed = (
        JobStatus.INSPECTION_IN_PROGRESS, JobStatus.AWAITING_PARTS,
        JobStatus.READY_FOR_SERVICE, JobStatus.IN_SERVICE,
    )
    if job.status not in allowed:
        raise DomainError("An estimate can be prepared only while the job is being inspected or worked on")
    for old in job.estimates:
        if old.status in (EstimateStatus.DRAFT, EstimateStatus.AWAITING_CUSTOMER_APPROVAL, EstimateStatus.APPROVED):
            old.status = EstimateStatus.SUPERSEDED
    est = Estimate(
        job_id=job.id,
        version=max((e.version for e in job.estimates), default=0) + 1,
        terms=settings_service.get(db, "estimate_terms"),
        created_by_id=user.id,
    )
    for lab in job.labour:
        if lab.approval_status == ApprovalStatus.REJECTED:
            continue
        est.lines.append(
            EstimateLine(
                line_type=LineType.LABOUR, job_labour_id=lab.id, code=lab.code,
                description=lab.description, quantity=lab.estimated_hours, unit_price=lab.hourly_rate,
                discount_amount=ZERO, tax_rate=lab.tax_rate.rate if lab.tax_rate else ZERO,
            )
        )
    for line in jobs_service.active_part_lines(job):
        part = line.part
        est.lines.append(
            EstimateLine(
                line_type=LineType.PART, parts_request_line_id=line.id, code=part.sku,
                description=part.name, quantity=line.qty_requested, unit_price=part.selling_price,
                discount_amount=ZERO, tax_rate=part.tax_rate.rate if part.tax_rate else ZERO,
            )
        )
    for mp in job.manual_parts:
        est.lines.append(
            EstimateLine(
                line_type=LineType.PART, code=mp.part.sku if mp.part else "", description=mp.description, quantity=mp.quantity,
                unit_price=mp.unit_price, discount_amount=ZERO, tax_rate=mp.tax_rate.rate if mp.tax_rate else ZERO,
            )
        )
    _recalculate(est)
    db.add(est)
    job.estimates.append(est)
    db.flush()
    jobs_service.add_event(db, job, "ESTIMATE", f"Estimate v{est.version} prepared (INR {est.total})", user)
    audit(db, user, "estimate.create", "estimate", est.id, f"Estimate v{est.version} for {job.job_number}")
    return est


def update_estimate(db: Session, est: Estimate, user: User, notes, terms, discounts: list[dict] | None) -> Estimate:
    if est.status != EstimateStatus.DRAFT:
        raise DomainError("Only a draft estimate can be edited; create a revised estimate instead")
    if notes is not None:
        est.notes = notes
    if terms is not None:
        est.terms = terms
    by_id = {l.id: l for l in est.lines}
    for item in discounts or []:
        line = by_id.get(item["line_id"])
        if line is None:
            raise bad_request("Unknown estimate line")
        gross, _, _ = calc_line(line.quantity, line.unit_price, ZERO, ZERO)
        check_discount(db, gross, money(item["discount_amount"]))
        line.discount_amount = money(item["discount_amount"])
    _recalculate(est)
    return est
