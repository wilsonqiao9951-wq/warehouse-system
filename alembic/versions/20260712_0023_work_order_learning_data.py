"""add work order learning data

Revision ID: 20260712_0023
Revises: 20260712_0022
"""
from alembic import op
import sqlalchemy as sa


revision = "20260712_0023"
down_revision = "20260712_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("work_orders") as batch:
        batch.add_column(sa.Column("fault_type", sa.String(length=120), nullable=True))
        batch.add_column(sa.Column("error_code", sa.String(length=120), nullable=True))
        batch.add_column(sa.Column("environment_info", sa.Text(), nullable=True))
        batch.add_column(sa.Column("final_outcome", sa.String(length=120), nullable=True))
        batch.add_column(sa.Column("first_time_fix", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("is_rework", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("repair_duration_minutes", sa.Integer(), nullable=True))
        batch.create_check_constraint(
            "ck_work_order_repair_duration_non_negative",
            "repair_duration_minutes IS NULL OR repair_duration_minutes >= 0",
        )
        batch.create_index("ix_work_orders_fault_type", ["fault_type"])
        batch.create_index("ix_work_orders_error_code", ["error_code"])
        batch.create_index("ix_work_orders_final_outcome", ["final_outcome"])


def downgrade() -> None:
    with op.batch_alter_table("work_orders") as batch:
        batch.drop_index("ix_work_orders_final_outcome")
        batch.drop_index("ix_work_orders_error_code")
        batch.drop_index("ix_work_orders_fault_type")
        batch.drop_constraint("ck_work_order_repair_duration_non_negative", type_="check")
        batch.drop_column("repair_duration_minutes")
        batch.drop_column("is_rework")
        batch.drop_column("first_time_fix")
        batch.drop_column("final_outcome")
        batch.drop_column("environment_info")
        batch.drop_column("error_code")
        batch.drop_column("fault_type")
