import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import admin, auth, billing, inventory, misc, public, reception, workshop
from app.core.config import get_settings
from app.core.database import SessionLocal

log = logging.getLogger("fsc")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if s.is_production:
        problems = s.production_problems()
        if problems:
            raise RuntimeError("Refusing to start in production:\n - " + "\n - ".join(problems))
    elif "dev" in (s.email_provider, s.sms_provider, s.whatsapp_provider):
        log.warning("Email/SMS/WhatsApp are using the DEVELOPMENT SIMULATOR: no real customer messages are sent.")
    if s.app_env != "test":
        # Keep roles and permissions in step with the code after an upgrade (idempotent).
        from app.services.bootstrap import ensure_reference_data

        with SessionLocal() as db:
            ensure_reference_data(db)
            db.commit()
    stops = []
    if s.run_worker_in_api and s.app_env != "test":
        from app.workers.delivery_worker import start_background_thread

        stops.append(start_background_thread()[1])
    if s.parts_sheet_url and s.app_env != "test":
        from app.workers import sheet_sync_worker

        stops.append(sheet_sync_worker.start_background_thread()[1])
    yield
    for stop in stops:
        stop.set()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Vin Desk - Service Centre Management",
        version="1.0.0",
        description="Reception, job cards, inspection, parts, estimates, invoicing, "
        "invoice delivery, payments and handover.",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if s.is_production:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        # Log the detail server-side; never leak internals to the client.
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "An unexpected error occurred"})

    for module in (auth, admin, reception, workshop, inventory, billing, misc, public):
        app.include_router(module.router, prefix="/api")

    @app.get("/api/health", tags=["public"])
    def health():
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ok"}

    return app


app = create_app()
