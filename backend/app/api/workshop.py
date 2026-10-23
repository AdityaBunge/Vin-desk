"""Mechanic work on a job (inspection, labour, parts requests, completion), quality inspection
and estimates. Mechanic endpoints additionally check that the job is assigned to the caller."""
from fastapi import APIRouter

from app.api.reception import JobDetail, _done, _load
from app.core.deps import DB, require
from app.schemas.billing import DraftUpdateIn, EstimateOut
from app.schemas.workshop import (
    AdditionalPartsIn,
    CompletionIn,
    CompletionUpdate,
    InspectionIn,
    LabourIn,
    LabourUpdate,
    PartsRequestIn,
)
from app.services import estimates
from app.services import jobs as jobs_service

router = APIRouter(tags=["workshop"])


@router.put("/jobs/{job_id}/inspection", response_model=JobDetail)
def save_inspection(job_id: int, body: InspectionIn, db: DB, user=require("job.work")):
    job = _load(db, job_id, user, lock=True)
    jobs_service.save_inspection(db, job, user, body.model_dump(exclude_unset=True))
    return _done(db, job, user)


@router.post("/jobs/{job_id}/inspection/submit", response_model=JobDetail)
def submit_inspection(job_id: int, db: DB, user=require("job.work")):
    job = _load(db, job_id, user, lock=True)
    jobs_service.submit_inspection(db, job, user)
    return _done(db, job, user)


@router.post("/jobs/{job_id}/labour", response_model=JobDetail, status_code=201)
def add_labour(job_id: int, body: LabourIn, db: DB, user=require("job.work")):
    job = _load(db, job_id, user, lock=True)
    jobs_service.add_labour(db, job, user, body.labour_operation_id, body.estimated_hours, body.notes)
    return _done(db, job, user)


@router.patch("/jobs/{job_id}/labour/{labour_id}", response_model=JobDetail)
def update_labour(job_id: int, labour_id: int, body: LabourUpdate, db: DB, user=require("job.work")):
    job = _load(db, job_id, user, lock=True)
    jobs_service.update_labour(db, job, user, labour_id, body.estimated_hours, body.notes)
    return _done(db, job, user)


@router.patch("/jobs/{job_id}/completions/{completion_id}", response_model=JobDetail)
def update_completion(job_id: int, completion_id: int, body: CompletionUpdate, db: DB, user=require("job.work")):
    job = _load(db, job_id, user, lock=True)
    jobs_service.update_completion(db, job, user, completion_id, body.model_dump(exclude_unset=True))
    return _done(db, job, user)


@router.delete("/jobs/{job_id}/labour/{labour_id}", response_model=JobDetail)
def remove_labour(job_id: int, labour_id: int, db: DB, user=require("job.work")):
    job = _load(db, job_id, user, lock=True)
    jobs_service.remove_labour(db, job, user, labour_id)
    return _done(db, job, user)


@router.post("/jobs/{job_id}/parts-requests", response_model=JobDetail, status_code=201)
def create_parts_request(job_id: int, body: PartsRequestIn, db: DB, user=require("job.work")):
    job = _load(db, job_id, user, lock=True)
    jobs_service.create_parts_request(db, job, user, [l.model_dump() for l in body.lines], body.notes)
    return _done(db, job, user)


@router.post("/jobs/{job_id}/additional-parts", response_model=JobDetail)
def additional_parts(job_id: int, body: AdditionalPartsIn, db: DB, user=require("job.work")):
    """The mechanic types extra parts needed during service; inventory checks them by hand."""
    job = _load(db, job_id, user, lock=True)
    jobs_service.request_additional_parts(db, job, user, body.text)
    return _done(db, job, user)


@router.post("/jobs/{job_id}/start-service", response_model=JobDetail)
def start_service(job_id: int, db: DB, user=require("job.work")):
    job = _load(db, job_id, user, lock=True)
    jobs_service.start_service(db, job, user)
    return _done(db, job, user)


@router.post("/jobs/{job_id}/complete", response_model=JobDetail)
def complete_work(job_id: int, body: CompletionIn, db: DB, user=require("job.work")):
    job = _load(db, job_id, user, lock=True)
    jobs_service.complete_work(db, job, user, body.model_dump())
    return _done(db, job, user)


# --- Estimates --------------------------------------------------------------------------


@router.post("/jobs/{job_id}/estimates", response_model=EstimateOut, status_code=201)
def create_estimate(job_id: int, db: DB, user=require("estimate.manage")):
    """Creates a new estimate version; any earlier open version is kept as SUPERSEDED."""
    job = _load(db, job_id, user, lock=True)
    est = estimates.create_estimate(db, job, user)
    db.commit()
    return est


@router.patch("/estimates/{estimate_id}", response_model=EstimateOut)
def update_estimate(estimate_id: int, body: DraftUpdateIn, db: DB, user=require("estimate.manage")):
    est = estimates.get_estimate(db, estimate_id)
    estimates.update_estimate(db, est, user, body.notes, body.terms, [d.model_dump() for d in body.discounts])
    db.commit()
    return est
