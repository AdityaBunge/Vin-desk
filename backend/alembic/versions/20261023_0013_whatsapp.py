"""WhatsApp delivery: invoices, payment-due and service-due reminders

- customers.whatsapp_opt_in: existing customers take their SMS preference (both are messages
  to the same mobile number about their own vehicle).
- delivery_jobs.kind: INVOICE (all existing rows), PAYMENT_REMINDER or SERVICE_REMINDER.
- delivery_jobs.invoice_id becomes optional: a service reminder belongs to a vehicle
  (vehicle_id) and the visit it counts from (service_job_id) instead of an invoice.

Revision ID: 0013
Revises: 0012
"""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("whatsapp_opt_in", sa.Boolean, nullable=False, server_default=sa.true()))
    op.execute("UPDATE customers SET whatsapp_opt_in = sms_opt_in")
    op.add_column("delivery_jobs", sa.Column("kind", sa.String(20), nullable=False, server_default="INVOICE"))
    op.create_index("ix_delivery_jobs_kind", "delivery_jobs", ["kind"])
    op.add_column("delivery_jobs", sa.Column("vehicle_id", sa.Integer, sa.ForeignKey("vehicles.id"), nullable=True))
    op.create_index("ix_delivery_jobs_vehicle_id", "delivery_jobs", ["vehicle_id"])
    op.add_column("delivery_jobs", sa.Column("service_job_id", sa.Integer, sa.ForeignKey("service_jobs.id"), nullable=True))
    op.create_index("ix_delivery_jobs_service_job_id", "delivery_jobs", ["service_job_id"])
    op.alter_column("delivery_jobs", "invoice_id", existing_type=sa.Integer, nullable=True)
    op.create_check_constraint(
        "ck_delivery_jobs_subject", "delivery_jobs", "invoice_id IS NOT NULL OR vehicle_id IS NOT NULL"
    )


def downgrade() -> None:
    # Service reminders have no invoice and their attempt history is append-only, so they cannot
    # be fitted back into the old schema.
    if op.get_bind().execute(sa.text("SELECT 1 FROM delivery_jobs WHERE invoice_id IS NULL LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade: service reminders have already been sent")
    op.drop_constraint("ck_delivery_jobs_subject", "delivery_jobs")
    op.alter_column("delivery_jobs", "invoice_id", existing_type=sa.Integer, nullable=False)
    op.drop_index("ix_delivery_jobs_service_job_id", "delivery_jobs")
    op.drop_column("delivery_jobs", "service_job_id")
    op.drop_index("ix_delivery_jobs_vehicle_id", "delivery_jobs")
    op.drop_column("delivery_jobs", "vehicle_id")
    op.drop_index("ix_delivery_jobs_kind", "delivery_jobs")
    op.drop_column("delivery_jobs", "kind")
    op.drop_column("customers", "whatsapp_opt_in")
