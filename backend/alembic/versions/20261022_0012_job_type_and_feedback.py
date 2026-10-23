"""Job type on job cards, and customer feedback on the invoice link

- service_jobs.job_type: PAID, FREE_SERVICE, WARRANTY or ACCIDENT (existing jobs: PAID).
- customer_feedback: one 1-5 star rating and comment per invoice, given by the customer on the
  invoice link; the customer may change it.

Revision ID: 0012
Revises: 0011
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("service_jobs", sa.Column("job_type", sa.String(20), nullable=False, server_default="PAID"))
    op.create_index("ix_service_jobs_job_type", "service_jobs", ["job_type"])
    op.create_table(
        "customer_feedback",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("invoice_id", sa.Integer, sa.ForeignKey("invoices.id"), nullable=False, unique=True),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("service_jobs.id"), nullable=False, index=True),
        sa.Column("rating", sa.SmallInteger, nullable=False),
        sa.Column("comment", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_customer_feedback_rating"),
    )


def downgrade() -> None:
    op.drop_table("customer_feedback")
    op.drop_index("ix_service_jobs_job_type", "service_jobs")
    op.drop_column("service_jobs", "job_type")
