# Vin Desk API and delivery worker (same image, different command).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UPLOAD_DIR=/data/uploads

# DejaVu fonts give invoice PDFs the rupee sign; tzdata for Indian dates.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts

RUN useradd --system --uid 10001 vindesk \
    && mkdir -p /data/uploads \
    && chown -R vindesk /data
USER vindesk

EXPOSE 8000
# Migrations and role/permission sync are idempotent; run them on every start.
CMD ["sh", "-c", "alembic upgrade head && python -m app.seed --reference-only && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --proxy-headers --forwarded-allow-ips='*'"]
