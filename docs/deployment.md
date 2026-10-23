# Deployment, integrations, backup and restore

## Quick deployment with Docker (recommended)

One server runs everything: PostgreSQL, the API, the email worker and Caddy (web server with automatic HTTPS). A 2 CPU / 4 GB VM is plenty; an Oracle Cloud "Always Free" Ampere VM in Mumbai or Hyderabad works at no cost.

1. **Server.** Ubuntu 22.04/24.04. Open ports 80 and 443 (in the cloud firewall / security list *and* `ufw`). Install Docker: `curl -fsSL https://get.docker.com | sh`.
2. **Domain.** Point a DNS `A` record (e.g. `service.yourcentre.in`) at the server's public IP.
3. **Code.** Copy this repository to the server (e.g. `git clone`), then:
   ```bash
   cp .env.production.example .env.production
   nano .env.production        # DOMAIN, PUBLIC_BASE_URL, CORS_ORIGINS, POSTGRES_PASSWORD, JWT_SECRET, Gmail settings
   docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
   ```
   The API applies database migrations and syncs roles and permissions on every start. It refuses to start if a production setting is missing or unsafe; read `docker compose -f docker-compose.prod.yml logs api` if it does not come up.
4. **First administrator.**
   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.production exec api python -m app.seed --create-admin you@yourcentre.in "Your Name"
   ```
   Sign in at `https://service.yourcentre.in`, create the other users (Users & Roles), then fill in **Admin > Settings**: centre name, address, GSTIN, PAN, state, invoice declaration.
5. **Check email.** `docker compose -f docker-compose.prod.yml --env-file .env.production exec api python scripts/send_test_email.py you@yourcentre.in`
6. **Backups.** `chmod +x scripts/backup-docker.sh` and add its nightly cron line (shown at the top of that script). Copy the backups off the server as well; a backup on the same server is lost with it.

Upgrading: `git pull && docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build` (migrations run automatically; take a backup first).

The sections below describe the same steps for a manual (non-Docker) installation.

## Production checklist

The API refuses to start with `APP_ENV=production` unless all of these hold:

- `JWT_SECRET` is set to at least 32 random characters.
- `PUBLIC_BASE_URL` starts with `https://`.
- `CORS_ORIGINS` lists explicit origins (no `*`).
- `EMAIL_PROVIDER` is a real provider (not `dev`) with its settings; `SMS_PROVIDER` is `msg91` (with `MSG91_AUTH_KEY`) or `disabled`; `WHATSAPP_PROVIDER` is `meta` (with `WHATSAPP_ACCESS_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID`) or `disabled`.

Also do the following yourself:

1. Create a dedicated PostgreSQL role and database; set `DATABASE_URL`.
2. `alembic upgrade head`, then `python -m app.seed --reference-only` (roles, permissions, vehicle models, tax rates; the API also does this on every start). Do **not** run the demo seed; it refuses to run in production, and demo accounts cannot sign in there.
3. `python -m app.seed --create-admin you@yourdomain "Your Name"` and sign in to create the other users.
4. Fill in Admin > Settings (service-centre name, address, GSTIN, prefixes, SMS sender and template IDs, WhatsApp template names and reminder timings, public URL).
5. Build the frontend (`npm run build`) and serve `frontend/dist` from the same origin as the API, with `/api` proxied to the backend. Same-origin matters: the refresh cookie is `SameSite=Strict`.
6. Terminate TLS at the reverse proxy. Add request rate limits there too (the built-in limiter is per process).
7. Run the delivery worker as its own service: set `RUN_WORKER_IN_API=false` and run `python -m app.workers.delivery_worker` under a process supervisor. Several workers may run at once. The worker also queues WhatsApp reminders, so with WhatsApp on at least one worker must be running.
8. Keep `backend/var/uploads` (job photographs) on persistent storage and include it in backups.

### Example reverse proxy (nginx)

```nginx
server {
    listen 443 ssl http2;
    server_name service.example.in;
    # ssl_certificate ...; ssl_certificate_key ...;

    root /srv/fsc/frontend/dist;
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        client_max_body_size 6m;
    }
    location / { try_files $uri /index.html; }
}
```

Start the API with `uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2 --proxy-headers` and hide `/api/docs` at the proxy if you do not want the OpenAPI UI exposed.

## Email setup

Email goes through any SMTP relay.

```
EMAIL_PROVIDER=smtp
SMTP_HOST=smtp.your-provider.example
SMTP_PORT=587
SMTP_SECURITY=starttls        # or ssl (port 465)
SMTP_USERNAME=...
SMTP_PASSWORD=...
EMAIL_SENDER_ADDRESS=service@yourdomain.in
```

- Use a sender address on a domain you control and publish SPF, DKIM and DMARC records for it, or invoices will land in spam.
- The display name comes from Admin > Settings > "Email sender display name" (falls back to the service-centre name).
- SMTP gives no delivery receipts. A successfully handed-over message is shown as **Sent (delivery unconfirmed)**, never Delivered.

### Testing email

1. Without a real provider: `docker compose --profile mail up -d`, then set `EMAIL_PROVIDER=smtp`, `SMTP_HOST=localhost`, `SMTP_PORT=1025`, `SMTP_SECURITY=none`, `EMAIL_SENDER_ADDRESS=service@example.test`. Finalise an invoice and open the inbox at http://localhost:8025 to see the HTML email, the plain-text part and the PDF attachment.
2. With the real provider: create a test customer with your own email address, finalise an invoice, and check the message, the attachment, the link and the spam score. Check Invoice > Delivery for the attempt history.

**Status of this integration:** the SMTP adapter has been exercised only by automated tests with mocked providers and by the development simulator. It has not been run against a live mail server in this project. Do step 1 or 2 before relying on it.

## SMS setup (India)

Transactional SMS in India must be sent through a DLT-registered principal entity, with an approved header (sender ID) and an approved content template. The application sends through MSG91's Flow API.

1. Complete DLT registration with a telecom operator: principal entity ID, a 6-character header, and a **transactional** (service-implicit) template such as:

   `Your vehicle service invoice {#var#} for vehicle {#var#} has been generated. Total: INR {#var#}. View your invoice securely: {#var#} Thank you for choosing {#var#}.`

2. In MSG91, add the approved template and map its variables to these names, which the adapter sends: `invoice_number`, `registration`, `amount`, `url`, `centre`. Note the MSG91 template ID. Whitelist your `PUBLIC_BASE_URL` domain for the URL variable if your operator requires it.
3. Configure the server:

   ```
   SMS_PROVIDER=msg91
   MSG91_AUTH_KEY=...
   ```

4. In Admin > Settings set "SMS template ID", "SMS sender ID" and "DLT principal entity ID". With MSG91 the sender ID and entity are bound to the template inside the MSG91 account; the two extra fields are stored for reference and for other gateways.

Only transactional messages are sent: invoices, and on WhatsApp payment-due and service-due reminders. Customers can be opted out per channel on their record; an opted-out channel is recorded as `SKIPPED`.

### Testing SMS

Create a test customer with your own mobile number, finalise an invoice, and confirm the text, the link and the Delivery panel status. A rejected request (wrong template ID, unapproved content, bad auth key) appears as `FAILED` with the gateway's reason.

**Status of this integration:** the MSG91 adapter is written from MSG91's published Flow API format and has **not** been run against the live service; no credentials or approved template were available. Treat it as unverified until step "Testing SMS" succeeds. To use a different gateway, add a class with the same `send()` method in `app/integrations/sms.py` and select it in `registry.py`; billing code does not change.

## WhatsApp setup

WhatsApp sends three kinds of message, each through the same outbox as email and SMS (retries, failure notifications, history on the invoice, the Invoice Delivery page):

| Message | When | Template setting (Admin > Settings > WhatsApp) |
|---|---|---|
| Invoice, with the PDF attached | When the invoice is finalised, and on "Resend WhatsApp" | `whatsapp_invoice_template` (default `invoice_ready`) |
| Payment reminder | Automatically for finalised invoices with a balance: first after `payment_reminder_after_days` (3), then every `payment_reminder_every_days` (7), at most `payment_reminder_max` (3) times; and on "Send payment reminder" on the invoice | `whatsapp_payment_reminder_template` (default `payment_reminder`) |
| Service-due reminder | Automatically `service_reminder_days_before` (7) days before the vehicle is due, which is `service_interval_days` (180) after its latest visit - the dealer dashboard's rule. Once per visit; never while the vehicle has an open job | `whatsapp_service_reminder_template` (default `service_reminder`) |

The worker checks for due reminders every 5 minutes. A reminder that is no longer needed when its turn comes (invoice paid or cancelled, vehicle back in the workshop) is marked `CANCELLED` instead of being sent. When reminders are first switched on, invoices more than two weeks past their first reminder date and vehicles more than 30 days overdue are not messaged; send those by hand. Customers who untick "WhatsApp" on their record get nothing on WhatsApp (recorded as `SKIPPED`).

### 1. Meta account and number

1. Create a Meta Business account (business.facebook.com) and complete **business verification** - needed to message more than a handful of customers.
2. At developers.facebook.com create an app (type **Business**) and add the **WhatsApp** product.
3. Add the service centre's business phone number (WhatsApp > API Setup). The number must not be in use on the WhatsApp phone app. Note its **Phone number ID**.
4. Business Settings > Users > **System users**: add an admin system user, assign the app, and **generate a token** with `whatsapp_business_messaging` and `whatsapp_business_management`. This token does not expire; the one on the API Setup page lasts only 24 hours.
5. WhatsApp Manager > Payment settings: add a payment method. Each business-initiated (template) conversation is charged by Meta.

### 2. Message templates

A business may start a WhatsApp conversation only with a template approved by Meta. In WhatsApp Manager > Message templates create these three, category **Utility**, language English (`en`; set "Template language code" in Admin > Settings if you use another). The application fills the variables **in this order**; the wording is yours, but the variable count and order must match, and a variable may not be the first or last thing in the text.

**`invoice_ready`** - header type **Document** (the application uploads the invoice PDF), body:

> Hello {{1}}, thank you for choosing {{6}}. Your service invoice {{2}} for vehicle {{3}} is attached (total Rs. {{4}}). You can also view it online: {{5}} For any questions, please call the service centre.

**`payment_reminder`** - no header, body:

> Hello {{1}}, this is a reminder from {{6}}: a balance of Rs. {{4}} is due on invoice {{2}} for vehicle {{3}}. View the invoice: {{5}} Please ignore this message if you have already paid.

Variables for both: 1 customer name, 2 invoice number, 3 registration, 4 amount (invoice total / outstanding balance), 5 secure invoice link, 6 service-centre name.

**`service_reminder`** - no header, body:

> Hello {{1}}, your vehicle {{2}} ({{3}}) is due for its next periodic service on {{4}}. Please contact {{5}} to book a convenient time.

Variables: 1 customer name, 2 registration, 3 vehicle model, 4 due date (e.g. 21 Apr 2027), 5 service-centre name.

Approval usually takes minutes to a few hours. If you name a template differently, enter its name in Admin > Settings.

### 3. Configure the application

```
WHATSAPP_PROVIDER=meta
WHATSAPP_ACCESS_TOKEN=<system user token>
WHATSAPP_PHONE_NUMBER_ID=<phone number ID>
WHATSAPP_APP_SECRET=<App settings > Basic > App secret>
WHATSAPP_VERIFY_TOKEN=<any random string>
```

Restart the API and the worker. Admin > Settings shows which values are configured (never the values themselves); the reception and customer screens now show a "WhatsApp" consent tick, and existing customers start with the same choice as their SMS consent.

### 4. Message-status webhook

In the Meta app: WhatsApp > Configuration > Webhook > Edit. Callback URL `https://<your domain>/api/webhooks/whatsapp`, verify token = `WHATSAPP_VERIFY_TOKEN`. Meta calls the URL once to verify it; then **subscribe to the `messages` field**. Meta signs every callback with the app secret (`X-Hub-Signature-256`); unsigned or wrongly signed requests get 401. Statuses `delivered` and `read` mark the message **Delivered**; `failed` marks it **Failed** with Meta's reason and notifies the Service Manager. Without the webhook, WhatsApp messages stay at "Sent (awaiting receipt)". For local testing the URL must be public HTTPS (e.g. an ngrok tunnel to port 8000).

### Testing WhatsApp

1. Before business verification, the API Setup page lets you send only to up to five numbers you add there: add your own.
2. Create a test customer with that mobile number (WhatsApp ticked), finalise an invoice and check the message and PDF on your phone and the WhatsApp card on the invoice.
3. Click "Send payment reminder" on the (unpaid) invoice.
4. A rejected request (template not approved, wrong variable count, number not on WhatsApp, expired token) appears as `FAILED` with Meta's reason. Rate-limit and server errors are retried automatically.

**Status of this integration:** the Meta adapter (`app/integrations/whatsapp.py`) is written from Meta's published Cloud API format and is covered by tests with the HTTP calls mocked; it has **not** been run against the live service, as no credentials or approved templates were available. Treat it as unverified until "Testing WhatsApp" succeeds. The Cloud API has no idempotency key, so a send whose response is lost to a network failure can, rarely, reach the customer twice.

## Delivery receipts (webhook)

`POST /api/webhooks/delivery/{provider}` accepts a normalised receipt:

```json
{"event_id": "unique-per-callback", "message_id": "<provider message id>", "status": "delivered"}
```

`status` is `delivered` or `failed` (optional `error`). `{provider}` must equal the provider name stored on the delivery (`msg91`, `smtp`). The request must carry `X-Webhook-Signature: hex(HMAC-SHA256(WEBHOOK_SECRET, raw body))`; unsigned or wrongly signed requests get 401, and a repeated `event_id` is ignored.

MSG91's native delivery-report callback uses its own payload and does not sign requests. To consume it, put a small adapter in front (a serverless function or proxy rule) that verifies the source, maps each report to the shape above and signs it. That adapter is not included.

## Customer invoice links

- Link format: `PUBLIC_BASE_URL/i/<public_id>.<signature>`. The signature is an HMAC with `INVOICE_LINK_SECRET` (or `JWT_SECRET`).
- Validity is set in Admin > Settings ("Invoice link validity", default 30 days). Expired links return a neutral "expired" page.
- "Revoke & reissue link" on an invoice invalidates every earlier link. Resending after expiry issues a new link automatically.
- Rotating `INVOICE_LINK_SECRET` invalidates all links at once.

## Backups

Back up the database and the uploads folder. With PostgreSQL client tools:

```bash
# Nightly logical backup (custom format, compressed)
pg_dump --format=custom --no-owner --file=fsc_$(date +%F).dump "postgresql://USER:PASSWORD@HOST:5432/fsc_prod"

# Job photographs
tar czf fsc_uploads_$(date +%F).tar.gz -C /srv/fsc/backend/var uploads
```

Windows development cluster:

```powershell
& 'C:\Program Files\PostgreSQL\17\bin\pg_dump.exe' -h localhost -p 5544 -U fsc -Fc -f fsc_dev.dump fsc_dev
```

Recommendations: run daily, keep at least 14 daily and 6 monthly copies, store them encrypted and off the server (they contain customer contact details and invoices), and enable WAL archiving or your host's point-in-time recovery if losing a day of invoices is not acceptable.

## Restore

```bash
createdb fsc_restore
pg_restore --no-owner --dbname="postgresql://USER:PASSWORD@HOST:5432/fsc_restore" fsc_2026-10-14.dump
# Check it, then point DATABASE_URL at it (or rename databases during a maintenance window).
alembic upgrade head        # applies any migrations newer than the backup
tar xzf fsc_uploads_2026-10-14.tar.gz -C /srv/fsc/backend/var
```

Rehearse a restore into a scratch database at least once a quarter; a backup that has never been restored is not a backup. After a restore, check the `delivery_jobs` table: rows that were `PENDING` or `RETRY_SCHEDULED` at backup time will be sent again by the worker. If those invoices were already delivered, set them to `CANCELLED` before starting the worker.

## Upgrades

```bash
git pull
cd backend && pip install -r requirements.txt && alembic upgrade head
cd ../frontend && npm ci && npm run build
# restart the API and the worker
```
