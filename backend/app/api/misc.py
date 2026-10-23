"""Dashboards, reports (JSON or CSV) and in-app staff notifications."""
import re
from datetime import date, timedelta

from fastapi import APIRouter
from sqlalchemy import func, select, update

from app.api.helpers import PageNum, PageSize, csv_response, paginate
from app.core.deps import DB, CurrentUser, require
from app.core.errors import bad_request, forbidden, not_found
from app.core.utils import utcnow
from app.models import Notification
from app.schemas.admin import DealerTargetsIn, NotificationOut
from app.schemas.common import Page
from app.services import reports
from app.services.common import audit

router = APIRouter(tags=["dashboard, reports & notifications"])


@router.get("/features")
def features(_: CurrentUser):
    """Optional features switched on by configuration, so screens can hide what is off."""
    from app.core.config import get_settings

    s = get_settings()
    return {"sms": s.sms_enabled, "whatsapp": s.whatsapp_enabled, "parts_sheet": bool(s.parts_sheet_url)}


@router.get("/parts-sheet")
def parts_sheet(_=require("inventory.read", "parts.manage")):
    """The Google Sheet the parts catalogue is synced from, for the embedded sheet page."""
    from app.core.config import get_settings

    s = get_settings()
    match = re.search(r"docs\.google\.com/spreadsheets/d/([\w-]+)", s.parts_sheet_url)
    if not match:
        raise not_found("Parts sheet (PARTS_SHEET_URL)")
    return {"url": f"https://docs.google.com/spreadsheets/d/{match.group(1)}/edit", "sync_seconds": max(s.parts_sheet_sync_seconds, 10.0)}


@router.get("/dealer-dashboard")
def dealer_dashboard(db: DB, date_from: date | None = None, date_to: date | None = None, _=require("dealer.dashboard")):
    """Business overview for a date range (default: this month to today)."""
    from app.services.dealer_dashboard import dealer_dashboard as build

    today = reports.today_local()
    date_to = date_to or today
    date_from = date_from or date_to.replace(day=1)
    if date_from > date_to:
        raise bad_request("The start date must be on or before the end date")
    if (date_to - date_from).days > 366 * 3:
        raise bad_request("Choose a range of at most three years")
    return build(db, date_from, date_to)


@router.put("/dealer-dashboard/targets")
def dealer_targets(body: DealerTargetsIn, db: DB, user=require("dealer.dashboard")):
    """Monthly targets and the service interval shown on the dealer dashboard."""
    from app.services import settings as settings_service

    changes = settings_service.set_many(db, body.model_dump(), user)
    if changes:
        audit(db, user, "settings.update", "settings", None, "Updated dealer targets: " + ", ".join(changes), changes)
    db.commit()
    return body


@router.get("/dashboard")
def dashboard(db: DB, user: CurrentUser):
    """Live figures for the caller's role, computed from the database on each request."""
    return reports.dashboard(db, user)


@router.get("/reports")
def list_reports(user: CurrentUser):
    perms = user.permissions
    return [
        {"name": name, "uses_date_range": uses_range}
        for name, (_, allowed, uses_range) in reports.REPORTS.items()
        if perms.intersection(allowed)
    ]


@router.get("/reports/{name}")
def run_report(
    name: str, db: DB, user: CurrentUser, date_from: date | None = None, date_to: date | None = None,
    format: str = "json",
):
    entry = reports.REPORTS.get(name)
    if entry is None:
        raise not_found("Report")
    fn, allowed, _ = entry
    if not user.permissions.intersection(allowed):
        raise forbidden()
    today = reports.today_local()
    date_to = date_to or today
    date_from = date_from or (date_to - timedelta(days=29))
    if date_from > date_to:
        raise bad_request("The start date must not be after the end date")
    if (date_to - date_from).days > 731:
        raise bad_request("Choose a date range of at most two years")
    start, end = reports.day_range(date_from, date_to)
    result = fn(db, start=start, end=end)
    result["date_from"], result["date_to"] = date_from, date_to
    if format == "csv":
        keys = [c["key"] for c in result["columns"]]
        audit(db, user, "report.export", "report", name, f"Exported report {name} as CSV",
              {"date_from": str(date_from), "date_to": str(date_to)})
        db.commit()
        return csv_response(
            f"{name}_{date_from}_{date_to}.csv", [c["label"] for c in result["columns"]],
            [[row.get(k) for k in keys] for row in result["rows"]],
        )
    return result


@router.get("/notifications", response_model=Page[NotificationOut])
def list_notifications(db: DB, user: CurrentUser, unread_only: bool = False, page: PageNum = 1, page_size: PageSize = 20):
    stmt = select(Notification).where(Notification.recipient_id == user.id).order_by(Notification.id.desc())
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    return paginate(db, stmt, page, page_size)


@router.get("/notifications/unread-count")
def unread_count(db: DB, user: CurrentUser):
    count = db.scalar(
        select(func.count()).select_from(Notification).where(Notification.recipient_id == user.id, Notification.is_read.is_(False))
    )
    return {"unread": count or 0}


@router.post("/notifications/{notification_id}/read", status_code=204)
def mark_read(notification_id: int, db: DB, user: CurrentUser):
    note = db.get(Notification, notification_id)
    if note is None or note.recipient_id != user.id:
        raise not_found("Notification")
    note.is_read, note.read_at = True, utcnow()
    db.commit()


@router.post("/notifications/read-all", status_code=204)
def mark_all_read(db: DB, user: CurrentUser):
    db.execute(
        update(Notification).where(Notification.recipient_id == user.id, Notification.is_read.is_(False))
        .values(is_read=True, read_at=utcnow())
    )
    db.commit()
