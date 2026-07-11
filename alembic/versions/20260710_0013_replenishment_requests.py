"""add executable replenishment requests

Revision ID: 20260710_0013
Revises: 20260710_0012
"""
from alembic import op
import sqlalchemy as sa
revision = "20260710_0013"
down_revision = "20260710_0012"
branch_labels = None
depends_on = None
def upgrade() -> None:
    op.create_table("replenishment_requests",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("part_id", sa.Integer(), sa.ForeignKey("parts.id"), nullable=False), sa.Column("destination_warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("source_warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=True), sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("work_order_id", sa.Integer(), sa.ForeignKey("work_orders.id"), nullable=True), sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="requested"), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_replenishment_requests_id", "replenishment_requests", ["id"])
    op.create_index("ix_replenishment_requests_organization_id", "replenishment_requests", ["organization_id"])
def downgrade() -> None:
    op.drop_table("replenishment_requests")
