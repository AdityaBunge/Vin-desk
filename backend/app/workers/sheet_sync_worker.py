"""Background sync of the parts catalogue from the workshop's Google Sheet (PARTS_SHEET_URL).

Staff edit the sheet; every PARTS_SHEET_SYNC_SECONDS the sheet is downloaded and, when it has
changed, new part numbers are created (with their opening stock) and existing parts get the
sheet's name, landed cost and bin. Stock of existing parts is never changed: it is maintained in
the app by issues, receipts and returns. Rows removed from the sheet do not delete parts.

Runs inside the API process when PARTS_SHEET_URL is set. Several API processes are safe: a
PostgreSQL advisory lock lets only one of them import at a time.
"""
import hashlib
import logging
import threading
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.import_parts import SheetError, actor, find_tax, import_parts, parse_sheet, read_rows

log = logging.getLogger("fsc.sheet_sync")

LOCK_KEY = 7_316_001  # arbitrary, unique to this job


def sync_once(session_factory: sessionmaker[Session], url: str, last_digest: str | None) -> str | None:
    """Import the sheet if its content differs from `last_digest`. Returns the digest now in the app."""
    s = get_settings()
    rows = read_rows(url)
    digest = hashlib.sha256(repr(rows).encode()).hexdigest()
    if digest == last_digest:
        return digest
    parsed = parse_sheet(rows)
    with session_factory() as db:
        if not db.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": LOCK_KEY}).scalar():
            return last_digest  # another process is importing; try again next round
        report = import_parts(
            db, parsed.parts, actor(db, None), markup_percent=Decimal(str(s.parts_sheet_markup_percent)),
            tax=find_tax(db, s.parts_sheet_tax),
        )
        db.commit()
    log.info(
        "Parts sheet synced: %d parts read, %d created, %d updated, %d unchanged, %d rows skipped",
        len(parsed.parts), len(report.created), len(report.updated), report.unchanged, len(parsed.skipped),
    )
    if report.needs_price:
        log.warning("New parts with no cost in the sheet, set their price in Parts: %s", ", ".join(report.needs_price))
    return digest


def run_forever(stop: threading.Event) -> None:
    s = get_settings()
    interval = max(s.parts_sheet_sync_seconds, 10.0)
    log.info("Parts sheet sync started (every %gs)", interval)
    digest = None
    while not stop.is_set():
        try:
            digest = sync_once(SessionLocal, s.parts_sheet_url, digest)
        except SheetError as exc:
            log.warning("Parts sheet sync skipped: %s", exc)
        except Exception:  # noqa: BLE001 - e.g. database briefly unavailable; keep the worker alive
            log.exception("Parts sheet sync failed")
        stop.wait(interval)
    log.info("Parts sheet sync stopped")


def start_background_thread() -> tuple[threading.Thread, threading.Event]:
    stop = threading.Event()
    thread = threading.Thread(target=run_forever, args=(stop,), name="sheet-sync", daemon=True)
    thread.start()
    return thread, stop
