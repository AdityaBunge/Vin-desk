"""Inventory picks the written spare parts from the catalogue

- job_manual_parts.part_id: the catalogue part inventory matched the written line to. Its rate,
  HSN, unit and tax come from the catalogue, so inventory no longer types prices. Lines without
  a part (not in the catalogue) keep the price entered by hand.

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_manual_parts", sa.Column("part_id", sa.Integer, sa.ForeignKey("parts.id"), nullable=True))


def downgrade() -> None:
    op.drop_column("job_manual_parts", "part_id")
