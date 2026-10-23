"""Make audit and communication logs append-only

Audit entries, communication attempts, inventory movements and consent records may be inserted
but never updated or deleted through the application's database role.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLES = ("audit_logs", "communication_attempts", "inventory_movements", "customer_consents")


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION fsc_forbid_modification() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% rows are append-only and cannot be modified or deleted', TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION fsc_forbid_modification();"
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};")
    op.execute("DROP FUNCTION IF EXISTS fsc_forbid_modification();")
