"""add scale query indexes

Revision ID: 20260808_0067
Revises: 20260808_0066
Create Date: 2026-08-08
"""

from alembic import op


revision = "20260808_0067"
down_revision = "20260808_0066"
branch_labels = None
depends_on = None


INDEXES = (
    ("ix_work_orders_org_id", "work_orders", ["organization_id", "id"]),
    (
        "ix_work_orders_org_schedule_id",
        "work_orders",
        ["organization_id", "schedule_date", "id"],
    ),
    (
        "ix_inventory_transactions_org_id",
        "inventory_transactions",
        ["organization_id", "id"],
    ),
    (
        "ix_work_order_parts_org_id",
        "work_order_parts",
        ["organization_id", "id"],
    ),
    (
        "ix_work_order_parts_org_user_id",
        "work_order_parts",
        ["organization_id", "user_id", "id"],
    ),
)


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _columns in reversed(INDEXES):
        op.drop_index(name, table_name=table)
