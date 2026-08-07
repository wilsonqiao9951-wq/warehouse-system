"""add completed work order profit snapshots

Revision ID: 20260807_0061
Revises: 20260807_0060
Create Date: 2026-08-07
"""

import sqlalchemy as sa
from alembic import op


revision = "20260807_0061"
down_revision = "20260807_0060"
branch_labels = None
depends_on = None

TABLE_NAME = "work_order_profit_snapshots"
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
        TABLE_NAME,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("work_order_id", sa.Integer(), sa.ForeignKey("work_orders.id"), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=False),
        sa.Column("ticket_number", sa.String(length=120), nullable=False),
        sa.Column("engineer_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("engineer_name", sa.String(length=120), nullable=False),
        sa.Column("region_id", sa.Integer(), sa.ForeignKey("inventory_regions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("region_code", sa.String(length=50), nullable=True),
        sa.Column("region_name", sa.String(length=120), nullable=True),
        sa.Column("attribution_warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("attribution_method", sa.String(length=40), nullable=False),
        sa.Column("machine_type", sa.String(length=255), nullable=False),
        sa.Column("revenue", sa.Float(), nullable=False),
        sa.Column("labor_cost", sa.Float(), nullable=False),
        sa.Column("parts_cost", sa.Float(), nullable=False),
        sa.Column("profit", sa.Float(), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "work_order_id", name="uq_profit_snapshot_org_work_order"),
        sa.CheckConstraint(
            "attribution_method IN ('parts_usage_region', 'engineer_vehicle_region', 'default_region', 'unattributed')",
            name="ck_profit_snapshot_attribution_method",
        ),
        sa.CheckConstraint("length(source_fingerprint) = 64", name="ck_profit_snapshot_source_fingerprint"),
    )
    op.create_index("ix_work_order_profit_snapshots_id", TABLE_NAME, ["id"])
    op.create_index("ix_work_order_profit_snapshots_organization_id", TABLE_NAME, ["organization_id"])
    op.create_index("ix_work_order_profit_snapshots_work_order_id", TABLE_NAME, ["work_order_id"])
    op.create_index("ix_profit_snapshot_org_date", TABLE_NAME, ["organization_id", "snapshot_date"])
    op.create_index("ix_profit_snapshot_org_engineer_date", TABLE_NAME, ["organization_id", "engineer_id", "snapshot_date"])
    op.create_index("ix_profit_snapshot_org_region_date", TABLE_NAME, ["organization_id", "region_id", "snapshot_date"])
    op.create_index("ix_profit_snapshot_org_machine_date", TABLE_NAME, ["organization_id", "machine_type", "snapshot_date"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f'ALTER TABLE "{TABLE_NAME}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{TABLE_NAME}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{POLICY_NAME}" ON "{TABLE_NAME}" '
            f"USING ({POLICY_EXPRESSION}) WITH CHECK ({POLICY_EXPRESSION})"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f'DROP POLICY IF EXISTS "{POLICY_NAME}" ON "{TABLE_NAME}"')
        op.execute(f'ALTER TABLE "{TABLE_NAME}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{TABLE_NAME}" DISABLE ROW LEVEL SECURITY')
    op.drop_table(TABLE_NAME)
