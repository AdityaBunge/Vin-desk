"""Service Manager bill edits; mechanics type additional parts

- invoice_lines.is_custom: an item the Service Manager added to the draft bill by hand.
- invoice_lines.price_override: a rate the Service Manager changed on the draft bill.
  Both survive rebuilding the draft from the job.
- inspections.spare_parts_unconfirmed: parts text the mechanic added (at inspection or as
  additional parts during service) that inventory has not yet checked.

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("invoice_lines", sa.Column("is_custom", sa.Boolean, nullable=False, server_default=sa.false()))
    op.add_column("invoice_lines", sa.Column("price_override", sa.Numeric(14, 2), nullable=True))
    op.add_column("inspections", sa.Column("spare_parts_unconfirmed", sa.Text, nullable=False, server_default=""))
    op.execute("""
        UPDATE inspections SET spare_parts_unconfirmed = spare_parts_notes
        WHERE spare_parts_status IN ('PENDING', 'UNAVAILABLE')
    """)


def downgrade() -> None:
    op.drop_column("inspections", "spare_parts_unconfirmed")
    op.drop_column("invoice_lines", "price_override")
    op.drop_column("invoice_lines", "is_custom")
