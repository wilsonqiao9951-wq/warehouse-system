"""add organization ownership foundation

Revision ID: 20260709_0002
Revises: 20260427_0001
Create Date: 2026-07-09 23:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260709_0002"
down_revision: Union[str, None] = "20260427_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TENANT_TABLES = (
    "users",
    "warehouses",
    "parts",
    "work_orders",
    "inventory_transactions",
    "work_order_parts",
    "qc_pictures",
    "job_status",
    "return_equipments",
    "audit_logs",
)


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "organizations" not in tables:
        op.create_table(
            "organizations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("slug", sa.String(length=120), nullable=False, unique=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_organizations_id", "organizations", ["id"])

    organization_count = bind.execute(sa.text("SELECT COUNT(*) FROM organizations")).scalar_one()
    if organization_count == 0:
        bind.execute(
            sa.text(
                "INSERT INTO organizations (id, name, slug, is_active) "
                "VALUES (1, 'Default Organization', 'default', 1)"
            )
        )

    tables = set(sa.inspect(bind).get_table_names())
    for table_name in TENANT_TABLES:
        if table_name not in tables:
            continue
        columns = {column["name"] for column in sa.inspect(bind).get_columns(table_name)}
        if "organization_id" in columns:
            continue
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(sa.Column("organization_id", sa.Integer(), nullable=True))
            batch_op.create_index(f"ix_{table_name}_organization_id", ["organization_id"])
            batch_op.create_foreign_key(
                f"fk_{table_name}_organization_id_organizations",
                "organizations",
                ["organization_id"],
                ["id"],
            )
        bind.execute(sa.text(f"UPDATE {table_name} SET organization_id = 1 WHERE organization_id IS NULL"))
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column("organization_id", existing_type=sa.Integer(), nullable=False)


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table_name in reversed(TENANT_TABLES):
        if table_name not in tables:
            continue
        columns = {column["name"] for column in sa.inspect(bind).get_columns(table_name)}
        if "organization_id" not in columns:
            continue
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_constraint(
                f"fk_{table_name}_organization_id_organizations",
                type_="foreignkey",
            )
            batch_op.drop_index(f"ix_{table_name}_organization_id")
            batch_op.drop_column("organization_id")

    if "organizations" in set(sa.inspect(bind).get_table_names()):
        op.drop_index("ix_organizations_id", table_name="organizations")
        op.drop_table("organizations")
