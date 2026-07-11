"""notify warehouse when field usage needs replenishment

Revision ID: 20260710_0012
Revises: 20260710_0011
"""
from alembic import op
import sqlalchemy as sa
revision = "20260710_0012"
down_revision = "20260710_0011"
branch_labels = None
depends_on = None
def upgrade() -> None:
    op.create_table("inventory_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("part_id", sa.Integer(), sa.ForeignKey("parts.id"), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("work_order_id", sa.Integer(), sa.ForeignKey("work_orders.id"), nullable=True),
        sa.Column("notification_type", sa.String(length=40), nullable=False, server_default="replenishment"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    for name in ("id", "organization_id"):
        op.create_index(f"ix_inventory_notifications_{name}", "inventory_notifications", [name])
def downgrade() -> None:
    op.drop_table("inventory_notifications")
