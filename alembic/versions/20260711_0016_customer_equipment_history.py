"""add customer and equipment service history foundation

Revision ID: 20260711_0016
Revises: 20260711_0015
"""
from alembic import op
import sqlalchemy as sa

revision = "20260711_0016"
down_revision = "20260711_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Older deployments received these workflow columns through the application's
    # compatibility bootstrap rather than Alembic. Make the migration chain
    # self-contained before creating history indexes that depend on them.
    work_order_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("work_orders")}
    if "started_at" not in work_order_columns:
        op.add_column("work_orders", sa.Column("started_at", sa.DateTime(), nullable=True))
    if "completed_at" not in work_order_columns:
        op.add_column("work_orders", sa.Column("completed_at", sa.DateTime(), nullable=True))
    if "is_locked" not in work_order_columns:
        op.add_column("work_orders", sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("account_number", sa.String(length=120), nullable=True),
        sa.Column("contact_name", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("state", sa.String(length=120), nullable=True),
        sa.Column("zip", sa.String(length=20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "account_number", name="uq_customers_org_account"),
    )
    op.create_index("ix_customers_organization_id", "customers", ["organization_id"])
    op.create_table(
        "equipment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("asset_tag", sa.String(length=120), nullable=True),
        sa.Column("manufacturer", sa.String(length=160), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("serial_number", sa.String(length=160), nullable=True),
        sa.Column("equipment_type", sa.String(length=160), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("install_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "asset_tag", name="uq_equipment_org_asset_tag"),
    )
    op.create_index("ix_equipment_organization_id", "equipment", ["organization_id"])
    op.create_index("ix_equipment_customer_id", "equipment", ["customer_id"])
    with op.batch_alter_table("work_orders") as batch:
        batch.add_column(sa.Column("customer_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("equipment_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_work_orders_customer_id", "customers", ["customer_id"], ["id"])
        batch.create_foreign_key("fk_work_orders_equipment_id", "equipment", ["equipment_id"], ["id"])
        batch.create_index("ix_work_orders_customer_id", ["customer_id"])
        batch.create_index("ix_work_orders_equipment_id", ["equipment_id"])
        batch.create_index("ix_work_orders_org_equipment_completed", ["organization_id", "equipment_id", "completed_at"])
        batch.create_index("ix_work_orders_org_customer_completed", ["organization_id", "customer_id", "completed_at"])


def downgrade() -> None:
    with op.batch_alter_table("work_orders") as batch:
        batch.drop_index("ix_work_orders_equipment_id")
        batch.drop_index("ix_work_orders_customer_id")
        batch.drop_index("ix_work_orders_org_equipment_completed")
        batch.drop_index("ix_work_orders_org_customer_completed")
        batch.drop_constraint("fk_work_orders_equipment_id", type_="foreignkey")
        batch.drop_constraint("fk_work_orders_customer_id", type_="foreignkey")
        batch.drop_column("equipment_id")
        batch.drop_column("customer_id")
    op.drop_table("equipment")
    op.drop_table("customers")
