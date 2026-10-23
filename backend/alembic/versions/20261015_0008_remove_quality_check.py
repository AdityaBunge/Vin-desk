"""Remove the quality-inspection step

Data only: jobs waiting for a quality check (or held while waiting) move to READY_FOR_BILLING.
quality_inspections and the checklist tables are kept for history.

Revision ID: 0008
Revises: 0007
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in ("status", "status_before_hold"):
        op.execute(f"""
            UPDATE service_jobs SET {column} = 'READY_FOR_BILLING'
            WHERE {column} IN ('AWAITING_QUALITY_CHECK', 'AWAITING_MANAGER_REVIEW')
        """)


def downgrade() -> None:
    pass  # the step no longer exists; nothing to restore
