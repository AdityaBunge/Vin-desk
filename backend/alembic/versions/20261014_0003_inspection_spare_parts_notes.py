"""Free-text spare parts list on the inspection

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("inspections", sa.Column("spare_parts_notes", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("inspections", "spare_parts_notes")
