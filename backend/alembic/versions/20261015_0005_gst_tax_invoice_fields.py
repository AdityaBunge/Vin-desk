"""GST tax-invoice fields: HSN/SAC codes, units, customer GSTIN, round-off

- parts.hsn_code, parts.unit           (e.g. 27101980, "Nos")
- labour_operations.sac_code           (e.g. 998714)
- customers.gstin                      (optional, for business customers)
- invoices.customer_gstin, round_off   (snapshot / rupee rounding)
- invoice_lines.hsn_code, unit         (snapshot per line)

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("parts", sa.Column("hsn_code", sa.String(20), nullable=False, server_default=""))
    op.add_column("parts", sa.Column("unit", sa.String(10), nullable=False, server_default="NO"))
    op.add_column("labour_operations", sa.Column("sac_code", sa.String(20), nullable=False, server_default=""))
    op.add_column("customers", sa.Column("gstin", sa.String(15), nullable=True))
    op.add_column("invoices", sa.Column("customer_gstin", sa.String(15), nullable=True))
    op.add_column("invoices", sa.Column("round_off", sa.Numeric(14, 2), nullable=False, server_default="0"))
    op.add_column("invoice_lines", sa.Column("hsn_code", sa.String(20), nullable=False, server_default=""))
    op.add_column("invoice_lines", sa.Column("unit", sa.String(10), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("invoice_lines", "unit")
    op.drop_column("invoice_lines", "hsn_code")
    op.drop_column("invoices", "round_off")
    op.drop_column("invoices", "customer_gstin")
    op.drop_column("customers", "gstin")
    op.drop_column("labour_operations", "sac_code")
    op.drop_column("parts", "unit")
    op.drop_column("parts", "hsn_code")
