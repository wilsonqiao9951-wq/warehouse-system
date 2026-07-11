"""add authenticated device-bound engineer job claims

Revision ID: 20260711_0018
Revises: 20260711_0017
"""
from alembic import op
import sqlalchemy as sa

revision = "20260711_0018"
down_revision = "20260711_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("device_id", sa.String(length=128), nullable=False),
        sa.Column("device_token_hash", sa.String(length=64), nullable=False),
        sa.Column("device_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "device_id", name="uq_user_devices_org_device"),
    )
    op.create_index("ix_user_devices_organization_id", "user_devices", ["organization_id"])
    op.create_index("ix_user_devices_user_id", "user_devices", ["user_id"])
    with op.batch_alter_table("work_orders") as batch:
        batch.add_column(sa.Column("claimed_by_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("claimed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("claimed_device_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("claim_version", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("completed_by_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("completed_device_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_work_orders_claimed_by_id", "users", ["claimed_by_id"], ["id"])
        batch.create_foreign_key("fk_work_orders_completed_by_id", "users", ["completed_by_id"], ["id"])
        batch.create_foreign_key("fk_work_orders_claimed_device_id", "user_devices", ["claimed_device_id"], ["id"])
        batch.create_foreign_key("fk_work_orders_completed_device_id", "user_devices", ["completed_device_id"], ["id"])
        batch.create_index("ix_work_orders_claimed_by_id", ["claimed_by_id"])
        batch.create_index("ix_work_orders_completed_by_id", ["completed_by_id"])
        batch.create_index("ix_work_orders_org_claim_status", ["organization_id", "claimed_by_id", "status"])


def downgrade() -> None:
    with op.batch_alter_table("work_orders") as batch:
        batch.drop_index("ix_work_orders_org_claim_status")
        batch.drop_index("ix_work_orders_completed_by_id")
        batch.drop_index("ix_work_orders_claimed_by_id")
        batch.drop_constraint("fk_work_orders_completed_by_id", type_="foreignkey")
        batch.drop_constraint("fk_work_orders_claimed_by_id", type_="foreignkey")
        batch.drop_constraint("fk_work_orders_completed_device_id", type_="foreignkey")
        batch.drop_constraint("fk_work_orders_claimed_device_id", type_="foreignkey")
        batch.drop_column("completed_device_id")
        batch.drop_column("completed_by_id")
        batch.drop_column("claim_version")
        batch.drop_column("claimed_device_id")
        batch.drop_column("claimed_at")
        batch.drop_column("claimed_by_id")
    op.drop_table("user_devices")
