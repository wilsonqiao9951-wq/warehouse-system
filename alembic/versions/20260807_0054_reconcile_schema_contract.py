"""reconcile model and database schema contract

Revision ID: 20260807_0054
Revises: 20260807_0053
Create Date: 2026-08-07
"""

from alembic import op
import sqlalchemy as sa


revision = "20260807_0054"
down_revision = "20260807_0053"
branch_labels = None
depends_on = None


TIMESTAMP_TABLES = (
    "machine_knowledge_profiles",
    "machine_knowledge_entries",
    "part_recognition_observations",
    "part_recognition_candidates",
)


def _warehouse_name_constraints() -> tuple[dict | None, dict | None]:
    global_constraint = None
    tenant_constraint = None
    for constraint in sa.inspect(op.get_bind()).get_unique_constraints("warehouses"):
        if constraint.get("column_names") == ["name"]:
            global_constraint = constraint
        elif constraint.get("column_names") == ["organization_id", "name"]:
            tenant_constraint = constraint
    return global_constraint, tenant_constraint


def _replace_warehouse_name_constraint(*, tenant_scoped: bool) -> None:
    bind = op.get_bind()
    global_constraint, tenant_constraint = _warehouse_name_constraints()
    if tenant_scoped and global_constraint is None and tenant_constraint is not None:
        return
    if not tenant_scoped and tenant_constraint is None and global_constraint is not None:
        return

    if bind.dialect.name == "sqlite":
        naming_convention = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
        with op.batch_alter_table(
            "warehouses",
            naming_convention=naming_convention,
        ) as batch:
            if tenant_scoped:
                if global_constraint is not None:
                    batch.drop_constraint(
                        global_constraint.get("name") or "uq_warehouses_name",
                        type_="unique",
                    )
                if tenant_constraint is None:
                    batch.create_unique_constraint(
                        "uq_warehouses_org_name",
                        ["organization_id", "name"],
                    )
            else:
                if tenant_constraint is not None:
                    batch.drop_constraint(
                        tenant_constraint.get("name")
                        or "uq_warehouses_organization_id",
                        type_="unique",
                    )
                if global_constraint is None:
                    batch.create_unique_constraint("uq_warehouses_name", ["name"])
        return

    with op.batch_alter_table("warehouses") as batch:
        if tenant_scoped:
            if global_constraint is not None:
                batch.drop_constraint(global_constraint["name"], type_="unique")
            if tenant_constraint is None:
                batch.create_unique_constraint(
                    "uq_warehouses_org_name",
                    ["organization_id", "name"],
                )
        else:
            if tenant_constraint is not None:
                batch.drop_constraint(tenant_constraint["name"], type_="unique")
            if global_constraint is None:
                batch.create_unique_constraint("uq_warehouses_name", ["name"])


def upgrade() -> None:
    for table in TIMESTAMP_TABLES:
        op.execute(
            sa.text(
                f'UPDATE "{table}" SET created_at = CURRENT_TIMESTAMP '
                "WHERE created_at IS NULL"
            )
        )
        op.execute(
            sa.text(
                f'UPDATE "{table}" SET updated_at = CURRENT_TIMESTAMP '
                "WHERE updated_at IS NULL"
            )
        )
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "created_at",
                existing_type=sa.DateTime(),
                existing_nullable=True,
                nullable=False,
            )
            batch.alter_column(
                "updated_at",
                existing_type=sa.DateTime(),
                existing_nullable=True,
                nullable=False,
            )

    _replace_warehouse_name_constraint(tenant_scoped=True)


def downgrade() -> None:
    duplicate_name = op.get_bind().scalar(
        sa.text(
            "SELECT name FROM warehouses GROUP BY name HAVING COUNT(*) > 1 "
            "LIMIT 1"
        )
    )
    if duplicate_name is not None:
        raise RuntimeError(
            "Cannot downgrade while warehouse names are repeated across organizations"
        )

    _replace_warehouse_name_constraint(tenant_scoped=False)
    for table in reversed(TIMESTAMP_TABLES):
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "updated_at",
                existing_type=sa.DateTime(),
                existing_nullable=False,
                nullable=True,
            )
            batch.alter_column(
                "created_at",
                existing_type=sa.DateTime(),
                existing_nullable=False,
                nullable=True,
            )
