"""add van inventory planning indexes

Revision ID: 20260807_0060
Revises: 20260807_0059
Create Date: 2026-08-07
"""

from alembic import op


revision = "20260807_0060"
down_revision = "20260807_0059"
branch_labels = None
depends_on = None


INDEXES = (
    (
        "ix_inventory_tx_org_from_wh_type_created",
        "inventory_transactions",
        ["organization_id", "from_warehouse_id", "transaction_type", "created_at"],
    ),
    (
        "ix_replenishment_org_destination_status",
        "replenishment_requests",
        ["organization_id", "destination_warehouse_id", "status"],
    ),
    (
        "ix_vehicle_return_org_source_status",
        "vehicle_return_requests",
        ["organization_id", "source_warehouse_id", "status"],
    ),
)


def upgrade() -> None:
    for name, table_name, columns in INDEXES:
        op.create_index(name, table_name, columns, unique=False)


def downgrade() -> None:
    for name, table_name, _columns in reversed(INDEXES):
        op.drop_index(name, table_name=table_name)
