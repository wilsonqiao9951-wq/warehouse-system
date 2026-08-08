"""add governed low stock rules and alert evidence

Revision ID: 20260807_0062
Revises: 20260807_0061
Create Date: 2026-08-07
"""

import sqlalchemy as sa
from alembic import op


revision = "20260807_0062"
down_revision = "20260807_0061"
branch_labels = None
depends_on = None

RULE_TABLE = "stock_threshold_rules"
POLICY_NAME = "openpartsflow_tenant_isolation"
POLICY_EXPRESSION = """
(
  current_setting('openpartsflow.platform_access', true) = 'on'
  OR organization_id = NULLIF(
    current_setting('openpartsflow.organization_id', true), ''
  )::integer
)
""".strip()


def upgrade() -> None:
    op.create_table(
        RULE_TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("part_id", sa.Integer(), sa.ForeignKey("parts.id"), nullable=False),
        sa.Column("threshold_quantity", sa.Integer(), nullable=False),
        sa.Column("reorder_quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "organization_id",
            "warehouse_id",
            "part_id",
            name="uq_stock_threshold_rule_org_warehouse_part",
        ),
        sa.CheckConstraint(
            "threshold_quantity >= 0",
            name="ck_stock_threshold_rule_threshold_non_negative",
        ),
        sa.CheckConstraint(
            "reorder_quantity >= 1",
            name="ck_stock_threshold_rule_reorder_positive",
        ),
        sa.CheckConstraint("version >= 0", name="ck_stock_threshold_rule_version_non_negative"),
    )
    op.create_index("ix_stock_threshold_rules_id", RULE_TABLE, ["id"])
    op.create_index("ix_stock_threshold_rules_organization_id", RULE_TABLE, ["organization_id"])
    op.create_index(
        "ix_stock_threshold_rule_org_active",
        RULE_TABLE,
        ["organization_id", "is_active", "warehouse_id"],
    )

    with op.batch_alter_table("inventory_notifications") as batch:
        batch.add_column(sa.Column("threshold_rule_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("threshold_quantity", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("observed_quantity", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("acknowledged_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("acknowledged_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("acknowledgement_note", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("resolved_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("resolved_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("resolution_reason", sa.String(length=500), nullable=True))
        batch.create_foreign_key(
            "fk_inventory_notification_threshold_rule",
            RULE_TABLE,
            ["threshold_rule_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_inventory_notification_acknowledged_by",
            "users",
            ["acknowledged_by"],
            ["id"],
        )
        batch.create_foreign_key(
            "fk_inventory_notification_resolved_by",
            "users",
            ["resolved_by"],
            ["id"],
        )

    op.execute(
        "UPDATE inventory_notifications SET threshold_quantity = COALESCE(("
        "SELECT CASE WHEN parts.safety_stock > parts.min_stock "
        "THEN parts.safety_stock ELSE parts.min_stock END "
        "FROM parts WHERE parts.id = inventory_notifications.part_id"
        "), 0)"
    )
    op.execute(
        "UPDATE inventory_notifications SET status = 'resolved', "
        "resolved_at = updated_at, "
        "resolution_reason = 'Superseded duplicate active alert during low-stock governance migration', "
        "version = version + 1 "
        "WHERE status IN ('open', 'acknowledged') AND id NOT IN ("
        "SELECT MAX(id) FROM inventory_notifications "
        "WHERE status IN ('open', 'acknowledged') "
        "GROUP BY organization_id, warehouse_id, part_id)"
    )
    with op.batch_alter_table("inventory_notifications") as batch:
        batch.create_check_constraint(
            "ck_inventory_notification_status",
            "status IN ('open', 'acknowledged', 'resolved')",
        )
        batch.create_check_constraint(
            "ck_inventory_notification_version_non_negative",
            "version >= 0",
        )
    op.create_index(
        "uq_inventory_notification_active_stock",
        "inventory_notifications",
        ["organization_id", "warehouse_id", "part_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('open', 'acknowledged')"),
        postgresql_where=sa.text("status IN ('open', 'acknowledged')"),
    )
    op.create_index(
        "ix_inventory_notification_org_status_updated",
        "inventory_notifications",
        ["organization_id", "status", "updated_at"],
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(f'ALTER TABLE "{RULE_TABLE}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{RULE_TABLE}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{POLICY_NAME}" ON "{RULE_TABLE}" '
            f"USING ({POLICY_EXPRESSION}) WITH CHECK ({POLICY_EXPRESSION})"
        )


def downgrade() -> None:
    op.drop_index(
        "ix_inventory_notification_org_status_updated",
        table_name="inventory_notifications",
    )
    op.drop_index(
        "uq_inventory_notification_active_stock",
        table_name="inventory_notifications",
    )
    with op.batch_alter_table("inventory_notifications") as batch:
        batch.drop_constraint("ck_inventory_notification_version_non_negative", type_="check")
        batch.drop_constraint("ck_inventory_notification_status", type_="check")
        batch.drop_constraint("fk_inventory_notification_resolved_by", type_="foreignkey")
        batch.drop_constraint("fk_inventory_notification_acknowledged_by", type_="foreignkey")
        batch.drop_constraint("fk_inventory_notification_threshold_rule", type_="foreignkey")
        batch.drop_column("resolution_reason")
        batch.drop_column("resolved_at")
        batch.drop_column("resolved_by")
        batch.drop_column("acknowledgement_note")
        batch.drop_column("acknowledged_at")
        batch.drop_column("acknowledged_by")
        batch.drop_column("version")
        batch.drop_column("observed_quantity")
        batch.drop_column("threshold_quantity")
        batch.drop_column("threshold_rule_id")
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f'DROP POLICY IF EXISTS "{POLICY_NAME}" ON "{RULE_TABLE}"')
        op.execute(f'ALTER TABLE "{RULE_TABLE}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{RULE_TABLE}" DISABLE ROW LEVEL SECURITY')
    op.drop_table(RULE_TABLE)
