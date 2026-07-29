"""add replenishment approval decisions

Revision ID: 20260712_0022
Revises: 20260712_0021
"""
from alembic import op
import sqlalchemy as sa


revision = "20260712_0022"
down_revision = "20260712_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("replenishment_requests") as batch:
        batch.drop_constraint("ck_replenishment_status", type_="check")
        batch.add_column(sa.Column("approval_status", sa.String(length=20), nullable=False, server_default="pending"))
        batch.add_column(sa.Column("approved_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("approved_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("rejected_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("rejected_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("rejection_reason", sa.Text(), nullable=True))
        batch.create_foreign_key("fk_replenishment_approved_by", "users", ["approved_by"], ["id"])
        batch.create_foreign_key("fk_replenishment_rejected_by", "users", ["rejected_by"], ["id"])
        batch.create_check_constraint(
            "ck_replenishment_status",
            "status IN ('requested', 'picking', 'shipped', 'received', 'completed', 'cancelled', 'rejected')",
        )
        batch.create_check_constraint(
            "ck_replenishment_approval_status",
            "approval_status IN ('pending', 'approved', 'rejected')",
        )
    op.execute(sa.text(
        "UPDATE replenishment_requests SET approval_status = 'approved' "
        "WHERE status IN ('picking', 'shipped', 'received', 'completed')"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "UPDATE replenishment_requests SET status = 'cancelled', "
        "cancellation_reason = COALESCE(cancellation_reason, rejection_reason, 'Rejected before downgrade') "
        "WHERE status = 'rejected'"
    ))
    with op.batch_alter_table("replenishment_requests") as batch:
        batch.drop_constraint("ck_replenishment_approval_status", type_="check")
        batch.drop_constraint("ck_replenishment_status", type_="check")
        batch.drop_constraint("fk_replenishment_rejected_by", type_="foreignkey")
        batch.drop_constraint("fk_replenishment_approved_by", type_="foreignkey")
        batch.drop_column("rejection_reason")
        batch.drop_column("rejected_at")
        batch.drop_column("rejected_by")
        batch.drop_column("approved_at")
        batch.drop_column("approved_by")
        batch.drop_column("approval_status")
        batch.create_check_constraint(
            "ck_replenishment_status",
            "status IN ('requested', 'picking', 'shipped', 'received', 'completed', 'cancelled')",
        )
