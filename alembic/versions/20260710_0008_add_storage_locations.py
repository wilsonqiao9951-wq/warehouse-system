"""add warehouse codes and storage locations

Revision ID: 20260710_0008
Revises: 20260710_0007
"""

from alembic import op
import sqlalchemy as sa


revision = "20260710_0008"
down_revision = "20260710_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("warehouses") as batch:
        batch.add_column(sa.Column("code", sa.String(length=50), nullable=True))
        batch.add_column(sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.execute("UPDATE warehouses SET code = UPPER(REPLACE(name, ' ', '-')) WHERE code IS NULL")
    with op.batch_alter_table("warehouses") as batch:
        batch.alter_column("code", nullable=False)
        batch.create_unique_constraint("uq_warehouses_org_code", ["organization_id", "code"])

    op.create_table(
        "storage_locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column("zone", sa.String(length=80), nullable=True),
        sa.Column("location_type", sa.String(length=30), nullable=False, server_default="bin"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("warehouse_id", "code", name="uq_storage_locations_warehouse_code"),
    )
    op.create_index("ix_storage_locations_id", "storage_locations", ["id"])
    op.create_index("ix_storage_locations_organization_id", "storage_locations", ["organization_id"])
    op.create_index("ix_storage_locations_warehouse_id", "storage_locations", ["warehouse_id"])


def downgrade() -> None:
    op.drop_table("storage_locations")
    with op.batch_alter_table("warehouses") as batch:
        batch.drop_constraint("uq_warehouses_org_code", type_="unique")
        batch.drop_column("is_active")
        batch.drop_column("code")
