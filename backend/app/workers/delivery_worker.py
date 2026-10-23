"""Background worker for the customer-message outbox (invoices and WhatsApp reminders).

Run standalone (recommended in production, one or more processes):

    python -m app.workers.delivery_worker

or inside the API process (default in development, RUN_WORKER_IN_API=true). Multiple workers
are safe: rows are claimed with FOR UPDATE SKIP LOCKED. Every few minutes it also queues the
WhatsApp reminders that have fallen due (app.services.reminders).
"""
import logging
import signal
import threading
import time

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services import delivery, reminders

log = logging.getLogger("fsc.worker")
REMINDER_SCAN_SECONDS = 300


def run_forever(stop: threading.Event) -> None:
    poll = get_settings().worker_poll_seconds
    log.info("Delivery worker started (poll every %ss)", poll)
    next_scan = 0.0
    while not stop.is_set():
        if get_settings().whatsapp_enabled and time.monotonic() >= next_scan:
            next_scan = time.monotonic() + REMINDER_SCAN_SECONDS
            try:
                reminders.run_once(SessionLocal)
            except Exception:  # noqa: BLE001 - try again on the next scan
                log.exception("Reminder scheduling failed")
        try:
            processed = delivery.run_once(SessionLocal)
        except Exception:  # noqa: BLE001 - e.g. database briefly unavailable; keep the worker alive
            log.exception("Delivery worker iteration failed")
            processed = 0
        if processed == 0:
            stop.wait(poll)
    log.info("Delivery worker stopped")


def start_background_thread() -> tuple[threading.Thread, threading.Event]:
    stop = threading.Event()
    thread = threading.Thread(target=run_forever, args=(stop,), name="delivery-worker", daemon=True)
    thread.start()
    return thread, stop


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    run_forever(stop)


if __name__ == "__main__":
    main()
