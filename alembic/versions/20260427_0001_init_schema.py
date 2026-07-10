"""initial schema

Revision ID: 20260427_0001
Revises:
Create Date: 2026-04-27 14:50:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260427_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _user_role_enum() -> sa.Enum:
    return sa.Enum("ADMIN", "MANAGER", "WAREHOUSE", "ENGINEER", "ASSISTANT", name="userrole")


def _tx_type_enum() -> sa.Enum:
    return sa.Enum(
        "INBOUND",
        "OUTBOUND",
        "TRANSFER",
        "WORK_ORDER_USED",
        "RETURN",
        "ADJUSTMENT",
        "DAMAGE",
        name="transactiontype",
    )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True, unique=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("role", _user_role_enum(), nullable=False, server_default="ENGINEER"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_users_id", "users", ["id"])

    op.create_table(
        "warehouses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False, unique=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("assigned_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_warehouses_id", "warehouses", ["id"])

    op.create_table(
        "parts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("part_number", sa.String(length=120), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("english_name", sa.String(length=255), nullable=True),
        sa.Column("machine_type", sa.String(length=255), nullable=True),
        sa.Column("unit", sa.String(length=50), nullable=False, server_default="pcs"),
        sa.Column("default_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("safety_stock", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("supplier", sa.String(length=255), nullable=True),
        sa.Column("image_url", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_parts_id", "parts", ["id"])

    op.create_table(
        "work_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_number", sa.String(length=120), nullable=False, unique=True),
        sa.Column("store_name", sa.String(length=255), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("machine_type", sa.String(length=255), nullable=True),
        sa.Column("problem_description", sa.Text(), nullable=True),
        sa.Column("assigned_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("engineer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("assistant_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("revenue", sa.Float(), nullable=False, server_default="0"),
        sa.Column("labor_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_work_orders_id", "work_orders", ["id"])

    op.create_table(
        "inventory_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("part_id", sa.Integer(), sa.ForeignKey("parts.id"), nullable=False),
        sa.Column("transaction_type", _tx_type_enum(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("from_warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=True),
        sa.Column("to_warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=True),
        sa.Column("work_order_id", sa.Integer(), sa.ForeignKey("work_orders.id"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("unit_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_inventory_transactions_id", "inventory_transactions", ["id"])

    op.create_table(
        "work_order_parts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("work_order_id", sa.Integer(), sa.ForeignKey("work_orders.id"), nullable=False),
        sa.Column("part_id", sa.Integer(), sa.ForeignKey("parts.id"), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("installed", sa.String(length=20), nullable=False, server_default="yes"),
        sa.Column("old_part_returned", sa.String(length=20), nullable=False, server_default="no"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_work_order_parts_id", "work_order_parts", ["id"])


def downgrade() -> None:
    op.drop_index("ix_work_order_parts_id", table_name="work_order_parts")
    op.drop_table("work_order_parts")
    op.drop_index("ix_inventory_transactions_id", table_name="inventory_transactions")
    op.drop_table("inventory_transactions")
    op.drop_index("ix_work_orders_id", table_name="work_orders")
    op.drop_table("work_orders")
    op.drop_index("ix_parts_id", table_name="parts")
    op.drop_table("parts")
    op.drop_index("ix_warehouses_id", table_name="warehouses")
    op.drop_table("warehouses")
    op.drop_index("ix_users_id", table_name="users")
    op.drop_table("users")
