"""add governed integration parity contracts

Revision ID: 20260808_0064
Revises: 20260808_0063
Create Date: 2026-08-08
"""

import sqlalchemy as sa
from alembic import op


revision = "20260808_0064"
down_revision = "20260808_0063"
branch_labels = None
depends_on = None

TABLE_NAME = "integration_parity_contracts"
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
        sa.Column(
            "integration_id",
            sa.Integer(),
            sa.ForeignKey("external_integrations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_revision", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("required_capabilities_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("covered_capabilities_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("tables_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("automations_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("gaps_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("readiness_status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("readiness_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("validated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "integration_id",
            name="uq_integration_parity_contract_integration",
        ),
        sa.CheckConstraint(
            "readiness_status IN ('draft', 'ready', 'blocked')",
            name="ck_integration_parity_contract_readiness",
        ),
        sa.CheckConstraint(
            "readiness_score >= 0 AND readiness_score <= 100",
            name="ck_integration_parity_contract_score",
        ),
        sa.CheckConstraint(
            "length(source_fingerprint) = 64",
            name="ck_integration_parity_contract_fingerprint",
        ),
        sa.CheckConstraint(
            "version >= 0",
            name="ck_integration_parity_contract_version_non_negative",
        ),
    )
    op.create_index(f"ix_{TABLE_NAME}_id", TABLE_NAME, ["id"])
    op.create_index(f"ix_{TABLE_NAME}_organization_id", TABLE_NAME, ["organization_id"])
    op.create_index(f"ix_{TABLE_NAME}_integration_id", TABLE_NAME, ["integration_id"])
    op.create_index(f"ix_{TABLE_NAME}_readiness_status", TABLE_NAME, ["readiness_status"])
    op.create_index(
        "ix_integration_parity_contract_org_readiness",
        TABLE_NAME,
        ["organization_id", "readiness_status", "updated_at"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text(f"ALTER TABLE {TABLE_NAME} ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {TABLE_NAME} FORCE ROW LEVEL SECURITY"))
        op.execute(
            sa.text(
                f"CREATE POLICY {POLICY_NAME} ON {TABLE_NAME} "
                f"USING {POLICY_EXPRESSION} WITH CHECK {POLICY_EXPRESSION}"
            )
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text(f"DROP POLICY IF EXISTS {POLICY_NAME} ON {TABLE_NAME}"))
    op.drop_index("ix_integration_parity_contract_org_readiness", table_name=TABLE_NAME)
    op.drop_index(f"ix_{TABLE_NAME}_readiness_status", table_name=TABLE_NAME)
    op.drop_index(f"ix_{TABLE_NAME}_integration_id", table_name=TABLE_NAME)
    op.drop_index(f"ix_{TABLE_NAME}_organization_id", table_name=TABLE_NAME)
    op.drop_index(f"ix_{TABLE_NAME}_id", table_name=TABLE_NAME)
    op.drop_table(TABLE_NAME)
