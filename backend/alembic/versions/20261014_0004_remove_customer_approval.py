"""Remove the customer-approval step

Data only: open jobs waiting on customer approval move on, and pending labour / parts on open
jobs become approved. Historical estimates and customer_approvals rows are kept.

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

OPEN = "('COMPLETED', 'CANCELLED')"


def upgrade() -> None:
    op.execute(f"""
        UPDATE job_labour SET approval_status = 'APPROVED'
        WHERE approval_status = 'PENDING'
          AND job_id IN (SELECT id FROM service_jobs WHERE status NOT IN {OPEN})
    """)
    op.execute(f"""
        UPDATE parts_request_lines SET approval_status = 'APPROVED'
        WHERE approval_status = 'PENDING'
          AND request_id IN (SELECT r.id FROM parts_requests r JOIN service_jobs j ON j.id = r.job_id
                             WHERE j.status NOT IN {OPEN})
    """)
    # Jobs (or held jobs) that were waiting for the customer move to the next real step.
    for column in ("status", "status_before_hold"):
        op.execute(f"""
            UPDATE service_jobs j SET {column} = CASE WHEN EXISTS (
                SELECT 1 FROM parts_requests r JOIN parts_request_lines l ON l.request_id = r.id
                WHERE r.job_id = j.id AND l.status <> 'CANCELLED' AND l.approval_status <> 'REJECTED'
                  AND l.qty_requested > l.qty_issued
            ) THEN 'AWAITING_PARTS' ELSE 'READY_FOR_SERVICE' END
            WHERE {column} = 'AWAITING_ESTIMATE_APPROVAL'
        """)
    op.execute("UPDATE estimates SET status = 'DRAFT' WHERE status = 'AWAITING_CUSTOMER_APPROVAL'")


def downgrade() -> None:
    pass  # data-only; previous approval states cannot be reconstructed
