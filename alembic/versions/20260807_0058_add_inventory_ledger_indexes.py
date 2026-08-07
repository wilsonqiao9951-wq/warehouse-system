"""add inventory ledger query indexes

Revision ID: 20260807_0058
Revises: 20260807_0057
Create Date: 2026-08-07
"""

from alembic import op


revision = "20260807_0058"
down_revision = "20260807_0057"
branch_labels = None
depends_on = None


INDEXES = (
    (
        "ix_inventory_tx_org_type_created",
        ["organization_id", "transaction_type", "created_at"],
    ),
    (
        "ix_inventory_tx_org_part_created",
        ["organization_id", "part_id", "created_at"],
    ),
    (
        "ix_inventory_tx_org_from_wh_created",
        ["organization_id", "from_warehouse_id", "created_at"],
    ),
    (
        "ix_inventory_tx_org_to_wh_created",
        ["organization_id", "to_warehouse_id", "created_at"],
    ),
    (
        "ix_inventory_tx_org_user_created",
        ["organization_id", "user_id", "created_at"],
    ),
    (
        "ix_inventory_tx_org_work_order_created",
        ["organization_id", "work_order_id", "created_at"],
    ),
)


def upgrade() -> None:
    for name, columns in INDEXES:
        op.create_index(
            name,
            "inventory_transactions",
            columns,
            unique=False,
        )


def downgrade() -> None:
    for name, _columns in reversed(INDEXES):
        op.drop_index(name, table_name="inventory_transactions")
