"""add enterprise analytics query indexes

Revision ID: 20260807_0044
Revises: 20260807_0043
Create Date: 2026-08-07
"""

from alembic import op


revision = "20260807_0044"
down_revision = "20260807_0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_work_orders_org_created_at",
        "work_orders",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "ix_work_orders_org_completed_at",
        "work_orders",
        ["organization_id", "completed_at"],
    )
    op.create_index(
        "ix_work_orders_org_completed_by_at",
        "work_orders",
        ["organization_id", "completed_by_id", "completed_at"],
    )
    op.create_index(
        "ix_work_orders_org_job_type_completed",
        "work_orders",
        ["organization_id", "job_type", "completed_at"],
    )
    op.create_index(
        "ix_work_order_parts_org_work_order",
        "work_order_parts",
        ["organization_id", "work_order_id"],
    )
    op.create_index(
        "ix_inventory_transactions_org_created_at",
        "inventory_transactions",
        ["organization_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inventory_transactions_org_created_at",
        table_name="inventory_transactions",
    )
    op.drop_index(
        "ix_work_order_parts_org_work_order",
        table_name="work_order_parts",
    )
    op.drop_index(
        "ix_work_orders_org_job_type_completed",
        table_name="work_orders",
    )
    op.drop_index(
        "ix_work_orders_org_completed_by_at",
        table_name="work_orders",
    )
    op.drop_index(
        "ix_work_orders_org_completed_at",
        table_name="work_orders",
    )
    op.drop_index(
        "ix_work_orders_org_created_at",
        table_name="work_orders",
    )
