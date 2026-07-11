"""add field service completion data

Revision ID: 20260711_0014
Revises: 20260710_0013
"""
from alembic import op
import sqlalchemy as sa

revision = "20260711_0014"
down_revision = "20260710_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("work_orders", sa.Column("paused_at", sa.DateTime(), nullable=True))
    op.add_column("work_orders", sa.Column("repair_result", sa.Text(), nullable=True))
    op.add_column("work_orders", sa.Column("checklist_json", sa.Text(), nullable=True))
    op.add_column("work_orders", sa.Column("customer_signature_name", sa.String(length=255), nullable=True))
    op.add_column("work_orders", sa.Column("customer_signature_data", sa.Text(), nullable=True))
    op.add_column("work_orders", sa.Column("customer_signed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("work_orders", "customer_signed_at")
    op.drop_column("work_orders", "customer_signature_data")
    op.drop_column("work_orders", "customer_signature_name")
    op.drop_column("work_orders", "checklist_json")
    op.drop_column("work_orders", "repair_result")
    op.drop_column("work_orders", "paused_at")
