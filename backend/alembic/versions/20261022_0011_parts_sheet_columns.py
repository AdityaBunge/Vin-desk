"""Parts keep the closing-stock sheet's own columns

- parts.dms_bin, dms_category, movement_class, abc_class, hml_class, ris_class: the dealer
  system's BIN, Category, Movement, ABC, HML and RIS codes from the sheet.
- parts.sheet_closing_qty, sheet_closing_value, sheet_actual_qty: the sheet's Closing Qty.,
  Closing Value and ACTUAL QUANTITY as last synced. Shown for reference only; stock in the app
  is still inventory_stock.

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

TEXT_COLUMNS = (("dms_bin", 30), ("dms_category", 30), ("movement_class", 10), ("abc_class", 10), ("hml_class", 10), ("ris_class", 10))
NUMBER_COLUMNS = (("sheet_closing_qty", 12), ("sheet_closing_value", 14), ("sheet_actual_qty", 12))


def upgrade() -> None:
    for name, length in TEXT_COLUMNS:
        op.add_column("parts", sa.Column(name, sa.String(length), nullable=False, server_default=""))
    for name, precision in NUMBER_COLUMNS:
        op.add_column("parts", sa.Column(name, sa.Numeric(precision, 2), nullable=True))


def downgrade() -> None:
    for name, _ in NUMBER_COLUMNS + TEXT_COLUMNS:
        op.drop_column("parts", name)
