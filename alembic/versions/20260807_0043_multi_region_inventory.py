"""add multi-region inventory ownership

Revision ID: 20260807_0043
Revises: 20260807_0042
Create Date: 2026-08-07
"""

from datetime import datetime

import sqlalchemy as sa
from alembic import op


revision = "20260807_0043"
down_revision = "20260807_0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_regions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "NOT is_default OR is_active",
            name="ck_inventory_regions_default_active",
        ),
        sa.CheckConstraint(
            "version >= 0",
            name="ck_inventory_regions_version_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "code",
            name="uq_inventory_regions_org_code",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "name",
            name="uq_inventory_regions_org_name",
        ),
    )
    op.create_index(
        "ix_inventory_regions_id",
        "inventory_regions",
        ["id"],
    )
    op.create_index(
        "ix_inventory_regions_organization_id",
        "inventory_regions",
        ["organization_id"],
    )
    op.create_index(
        "uq_inventory_regions_org_default",
        "inventory_regions",
        ["organization_id"],
        unique=True,
        sqlite_where=sa.text("is_default = 1"),
        postgresql_where=sa.text("is_default"),
    )
    with op.batch_alter_table("warehouses") as batch_op:
        batch_op.add_column(sa.Column("region_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_warehouses_region_id_inventory_regions",
            "inventory_regions",
            ["region_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_warehouses_region_id", ["region_id"])

    connection = op.get_bind()
    now = datetime.utcnow()
    organization_ids = connection.execute(
        sa.text("SELECT id FROM organizations ORDER BY id")
    ).scalars()
    for organization_id in organization_ids:
        connection.execute(
            sa.text(
                "INSERT INTO inventory_regions "
                "(organization_id, code, name, timezone, is_default, is_active, "
                "version, created_at, updated_at) "
                "VALUES (:organization_id, 'PRIMARY', 'Primary region', 'UTC', "
                ":is_default, :is_active, 0, :created_at, :updated_at)"
            ),
            {
                "organization_id": organization_id,
                "is_default": True,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
        )
    connection.execute(
        sa.text(
            "UPDATE warehouses SET region_id = ("
            "SELECT inventory_regions.id FROM inventory_regions "
            "WHERE inventory_regions.organization_id = warehouses.organization_id "
            "AND inventory_regions.is_default LIMIT 1"
            ") WHERE region_id IS NULL"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("warehouses") as batch_op:
        batch_op.drop_index("ix_warehouses_region_id")
        batch_op.drop_constraint(
            "fk_warehouses_region_id_inventory_regions",
            type_="foreignkey",
        )
        batch_op.drop_column("region_id")
    op.drop_index(
        "uq_inventory_regions_org_default",
        table_name="inventory_regions",
    )
    op.drop_index(
        "ix_inventory_regions_organization_id",
        table_name="inventory_regions",
    )
    op.drop_index("ix_inventory_regions_id", table_name="inventory_regions")
    op.drop_table("inventory_regions")
