"""Inventory confirms written spare parts lists by hand

- job_manual_parts: parts inventory confirmed as available by checking the shelf (not linked to
  the catalogue or stock), with the price they entered; billed on the invoice.
- invoice_lines.manual_part_id links an invoice line to one of those parts.
- inspections.spare_parts_status gains AVAILABLE and UNAVAILABLE ("DONE" stays for lists handled
  under the earlier catalogue flow).

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_manual_parts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("service_jobs.id"), nullable=False, index=True),
        sa.Column("description", sa.String(160), nullable=False),
        sa.Column("hsn_code", sa.String(20), nullable=False, server_default=""),
        sa.Column("unit", sa.String(10), nullable=False, server_default="NO"),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("unit_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("tax_rate_id", sa.Integer, sa.ForeignKey("tax_rates.id"), nullable=True),
        sa.Column("added_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column("invoice_lines", sa.Column("manual_part_id", sa.Integer, sa.ForeignKey("job_manual_parts.id"), nullable=True))
    op.alter_column("inspections", "spare_parts_status", type_=sa.String(20), existing_type=sa.String(10))


def downgrade() -> None:
    op.alter_column("inspections", "spare_parts_status", type_=sa.String(10), existing_type=sa.String(20))
    op.drop_column("invoice_lines", "manual_part_id")
    op.drop_table("job_manual_parts")
