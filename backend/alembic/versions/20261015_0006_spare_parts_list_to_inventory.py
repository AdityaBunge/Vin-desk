"""Route the mechanic's hand-written spare parts list to inventory

inspections.spare_parts_status: "" (nothing to do), PENDING (inventory has not handled it), DONE.
Existing submitted lists on jobs that have not started work become PENDING, and those jobs wait
in AWAITING_PARTS again until inventory handles the list.

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("inspections", sa.Column("spare_parts_status", sa.String(10), nullable=False, server_default=""))
    op.add_column("inspections", sa.Column("spare_parts_done_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True))
    op.add_column("inspections", sa.Column("spare_parts_done_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("inspections", sa.Column("spare_parts_done_note", sa.Text, nullable=False, server_default=""))
    op.execute("""
        UPDATE inspections i SET spare_parts_status = 'PENDING'
        FROM service_jobs j
        WHERE j.id = i.job_id AND i.submitted_at IS NOT NULL AND btrim(i.spare_parts_notes) <> ''
          AND j.status NOT IN ('COMPLETED', 'CANCELLED')
    """)
    op.execute("""
        UPDATE service_jobs j SET status = 'AWAITING_PARTS'
        FROM inspections i
        WHERE i.job_id = j.id AND i.spare_parts_status = 'PENDING' AND j.status = 'READY_FOR_SERVICE'
    """)


def downgrade() -> None:
    op.drop_column("inspections", "spare_parts_done_note")
    op.drop_column("inspections", "spare_parts_done_at")
    op.drop_column("inspections", "spare_parts_done_by_id")
    op.drop_column("inspections", "spare_parts_status")
