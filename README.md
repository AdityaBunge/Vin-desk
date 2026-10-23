# Vin Desk - Service Centre Management System

A full-stack application for a Force Motors service centre covering the whole vehicle visit: reception and job cards, mechanic inspection, spare-parts requests and inventory, optional estimates (quotes), repair, invoicing with PDF, automatic invoice delivery by email and SMS with a secure customer link, payments, and vehicle handover.

- **Backend:** Python, FastAPI, SQLAlchemy 2, Alembic, Pydantic, PostgreSQL, JWT
- **Frontend:** React, TypeScript, Vite, Tailwind CSS, React Router, React Hook Form + Zod, TanStack Query and Table, Recharts
- **Tests:** Pytest (API and concurrency tests on a real PostgreSQL database), Vitest + Testing Library

Roles: **Service Manager**, **Mechanic**, **Inventory Staff**, **Administrator**. All permissions are enforced by the API.

## Quick start (development)

Prerequisites: Python 3.12+, Node 20+, PostgreSQL 15+ (or Docker).

### One command

```bash
python run.py --setup     # first time only: Python env, packages, database, demo data; then starts
python run.py             # every other time: starts the database, backend and frontend, opens the browser
```

Logs from both servers appear in that window; press Ctrl+C to stop them (`--stop-db` also stops the database). `python run.py --help` lists the options. The manual steps below do the same thing by hand.

### 1. Database

Windows with PostgreSQL installed (runs a separate development cluster on port 5544; your existing PostgreSQL is not touched):

```powershell
.\scripts\dev-db.ps1 start
```

Or with Docker: `docker compose up -d`, and set `DATABASE_URL` / `TEST_DATABASE_URL` as shown in `.env.example`.

### 2. Backend

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head                  # create the schema
python -m app.seed                    # reference data + demo users, parts, customers, two sample jobs
uvicorn app.main:app --reload --port 8000
```

No `.env` is needed for development: the defaults match the cluster from step 1 and use the email/SMS simulators. To change anything, copy `.env.example` to `.env`.

- API documentation (OpenAPI): http://localhost:8000/api/docs
- The invoice-delivery worker runs inside the API process in development.

### 3. Frontend

```powershell
cd frontend
npm install
npm run dev                           # http://localhost:5173 (proxies /api to port 8000)
```

### Development sign-in

| Role | Email | Password |
|---|---|---|
| Service Manager | `manager@demo.local` | `Demo@12345` |
| Mechanic | `mechanic@demo.local` (also `mechanic2@demo.local`) | `Demo@12345` |
| Inventory Staff | `inventory@demo.local` | `Demo@12345` |
| Administrator | `admin@demo.local` | `Demo@12345` |

These accounts are flagged as demo accounts. The demo seed refuses to run when `APP_ENV=production`, and demo accounts are refused at sign-in in production even if they exist in the database.

### Email, SMS and WhatsApp in development

With the default `EMAIL_PROVIDER=dev` and `SMS_PROVIDER=dev`, **no real messages are sent**. Each invoice email is written to `backend/var/dev_outbox/email-<id>.eml` (open it in a mail client to see the HTML, text and PDF attachment) and each SMS is appended to `backend/var/dev_outbox/sms.log`. With `WHATSAPP_PROVIDER=dev` in `.env` (WhatsApp is off by default), WhatsApp messages - invoices with their PDF, payment reminders and service reminders - are appended to `backend/var/dev_outbox/whatsapp.log`, with each PDF saved next to it. The UI labels these deliveries "Simulated (not sent)". Real provider setup is in [docs/deployment.md](docs/deployment.md).

## Importing the spare-parts sheet

The parts catalogue and opening stock can be loaded from the workshop's closing-stock sheet (Google Sheets shared as "anyone with the link can view", or a downloaded CSV):

```powershell
cd backend
python -m app.import_parts "<sheet link>" --dry-run   # show what would change
python -m app.import_parts "<sheet link>"             # import
```

- New part numbers are created with their stock recorded as a `RECEIVED` movement. The quantity is the physical count (`ACTUAL QUANTITY`) when present, otherwise `Closing Qty.`. The landed unit cost is `Closing Value ÷ Closing Qty.`, the selling price is cost + 20% (`--markup`), and the tax is GST 18% (`--tax`).
- Re-running is safe: existing parts get the sheet's name, cost and bin, but their selling price, tax and stock are left alone. Add `--update-stock` after a stock count to adjust on-hand stock to the sheet (an audited `ADJUSTMENT`).
- The command lists rows it skipped (no part number) and new parts with no cost in the sheet, whose price must be set on the Parts screen.

### Automatic sync

Set `PARTS_SHEET_URL` in `.env` to the sheet link and restart the backend. Every `PARTS_SHEET_SYNC_SECONDS` (default 30) the backend downloads the sheet and, when it has changed, runs the same import: new part numbers are added with their opening stock, and existing parts take the sheet's name, landed cost and bin. Staff only edit the sheet.

- The sheet's own columns (BIN, Category, Movement, ABC, HML, RIS, Closing Qty., Closing Value, ACTUAL QUANTITY) are copied to each part on every sync and shown in the Parts Catalogue for the Service Manager, Inventory and Admin. They are for reference; live stock is the On hand / Available columns.
- Stock of existing parts is never taken from the sheet: it is maintained in the app by issues, receipts and returns. Use `--update-stock` above after a physical stock count.
- Deleting a row from the sheet does not delete the part.
- If the sheet cannot be read (not shared, offline), the app keeps its current data and logs a `Parts sheet sync skipped` warning.

## Tests

```powershell
cd backend
pytest                                 # 65 tests, about 3 minutes; needs the fsc_test database

cd ..\frontend
npm test                               # unit and component tests (hermetic)
npm run typecheck
npm run build
```

- Backend tests build the schema with the real migrations, truncate between tests, and replace the email and SMS providers with in-memory fakes. A guard fails any test that tries to open SMTP or call an HTTP gateway.
- `backend/tests/test_e2e_workflow.py` runs the complete 19-step scenario through the HTTP API.
- Optional live checks against a running development server:

  ```powershell
  cd backend;  python scripts\dev_walkthrough.py        # drives the full scenario over HTTP with demo data
  cd frontend; $env:VITE_LIVE_API='http://127.0.0.1:8000'; npx vitest run src/test/live-smoke.test.tsx   # renders every page for every role
  ```

## Manual walkthrough

1. Sign in as **manager**. Dashboard > **New Service Visit**, search `MH12CD5678` (a seeded Force Urbania) or type a new registration to register a customer and vehicle. Create the job card and assign `Ravi Patil`. Use **Print job card**.
2. Sign in as **mechanic**. Open the job > **Inspection**: write the recommended repairs, the spare parts needed and the priority, add labour operations; on the **Parts** tab request stock from inventory (try `FM-CLU-KIT-TRV`, which is out of stock); submit the inspection.
3. Optional, as **manager**: job > **Estimate** > Prepare estimate to print a quote for the customer. Nothing waits for it.
4. As **inventory**: **Parts Requests**: issue what is available, Record shortage on the rest, propose an alternative or raise a **Purchase Request**.
5. As **manager**: approve the alternative (job > **Parts**) or the purchase request. As **inventory**: Receive stock, then issue.
6. As **mechanic**: job > **Work** > Start service, record hours and parts used, Complete work and send to Service Manager. As **inventory**: Return unused, if any.
7. As **manager**: job > **Billing** > Prepare invoice; review, optionally discount, **Finalise invoice**. Watch the Delivery panel update; resend one channel; open the customer link.
8. Record payment, **Mark ready for delivery**, **Record handover**.
9. Look at **Reports**, **Stock Movements**, and (as **admin**) the **Audit Log**.

## Project structure

```
backend/
  app/
    api/            HTTP routers (auth, admin, reception, workshop, inventory, billing, misc, public)
    core/           config, database, security, permissions, rate limiting
    models/         SQLAlchemy models
    schemas/        Pydantic schemas
    services/       business rules (jobs, inventory, estimates, billing, delivery, reports, ...)
    integrations/   email and SMS provider adapters and simulators
    workers/        invoice-delivery worker
    templates/      invoice email templates
    seed.py         reference and demo data, create-admin
  alembic/          migrations
  scripts/          dev_walkthrough.py
  tests/
frontend/
  src/              components, layouts, pages, features, services, hooks, types, validation, test
docs/               architecture.md, database-schema.md, workflow.md, deployment.md
scripts/            dev-db.ps1 (local PostgreSQL), docker-init-test-db.sql
legacy/node-prototype/   the earlier Express + MySQL prototype, kept for reference; not used
```

## Documentation

- [Architecture](docs/architecture.md): components, authentication, the delivery outbox, design decisions
- [Database schema](docs/database-schema.md): entity-relationship diagram and table reference
- [Workflow](docs/workflow.md): job status machine, who does what, business rules
- [Deployment](docs/deployment.md): production checklist, email and SMS setup and testing, webhooks, backup and restore

## Status and known limits

Working and covered by automated tests: authentication and role permissions, customers and vehicles, job cards, assignment, inspection, parts requests, reservation / issue / return with concurrency protection, shortages, alternatives, purchase requests, estimates and approvals, additional-work control, completion, invoice calculation and finalisation, PDF, payments, the delivery outbox with retries and manual resend, receipt webhooks, secure links, notifications, reports with CSV export, audit log.

Not done, or needing you:

- **Email** has been tested live through Gmail SMTP (App Password). **SMS is switched off** (`SMS_PROVIDER=disabled`); the MSG91 adapter has only been exercised with mocks and needs DLT registration, an approved template and a live test before use. See [docs/deployment.md](docs/deployment.md).
- **MSG91 delivery receipts** need a small adapter to translate MSG91's callback into the signed webhook format; it is not included.
- **Provider choice, SMTP endpoint and credentials are set through environment variables**, not the Administrator screen, which shows them read-only and edits the non-secret settings.
- **Credit notes are not implemented.** Corrections are made by cancelling a finalised invoice (with reason and audit entry) and issuing a new one.
- **No browser end-to-end tests** (Playwright or similar). The UI is covered by component tests and a live render check of every page, and the workflow by API-level end-to-end tests; nobody has clicked through it in a real browser as part of this build.
- **No quality-inspection step.** Completed work goes straight to the Service Manager (`READY_FOR_BILLING`), who can return it to the mechanic. `AWAITING_QUALITY_CHECK` and `AWAITING_MANAGER_REVIEW` remain only for old records; past inspection records are kept.
- Job photographs are stored on local disk (`backend/var/uploads`); use shared or object storage if you run more than one API host.
- The rate limiter is per process; add proxy-level limits in production.
