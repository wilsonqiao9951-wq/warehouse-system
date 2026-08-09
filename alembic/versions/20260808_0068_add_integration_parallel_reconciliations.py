"""add integration parallel reconciliation evidence

Revision ID: 20260808_0068
Revises: 20260808_0067
Create Date: 2026-08-08
"""

import sqlalchemy as sa
from alembic import op


revision = "20260808_0068"
down_revision = "20260808_0067"
branch_labels = None
depends_on = None

TABLE_NAME = "integration_parallel_reconciliations"
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
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column(
            "integration_id",
            sa.Integer(),
            sa.ForeignKey("external_integrations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "contract_id",
            sa.Integer(),
            sa.ForeignKey("integration_parity_contracts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_revision", sa.String(length=160), nullable=False),
        sa.Column("contract_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("snapshot_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("evidence_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("observed_from", sa.DateTime(), nullable=False),
        sa.Column("observed_to", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("input_record_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matched_record_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discrepancy_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("object_counts_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("discrepancies_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "integration_id",
            "evidence_fingerprint",
            name="uq_integration_parallel_reconciliation_evidence",
        ),
        sa.CheckConstraint(
            "status IN ('matched', 'differences')",
            name="ck_integration_parallel_reconciliation_status",
        ),
        sa.CheckConstraint(
            "input_record_count >= 0 AND matched_record_count >= 0 "
            "AND discrepancy_count >= 0",
            name="ck_integration_parallel_reconciliation_counts",
        ),
        sa.CheckConstraint(
            "observed_from <= observed_to",
            name="ck_integration_parallel_reconciliation_window",
        ),
        sa.CheckConstraint(
            "length(contract_fingerprint) = 64 "
            "AND length(snapshot_fingerprint) = 64 "
            "AND length(evidence_fingerprint) = 64",
            name="ck_integration_parallel_reconciliation_fingerprints",
        ),
    )
    op.create_index(f"ix_{TABLE_NAME}_id", TABLE_NAME, ["id"])
    op.create_index(f"ix_{TABLE_NAME}_organization_id", TABLE_NAME, ["organization_id"])
    op.create_index(f"ix_{TABLE_NAME}_integration_id", TABLE_NAME, ["integration_id"])
    op.create_index(f"ix_{TABLE_NAME}_contract_id", TABLE_NAME, ["contract_id"])
    op.create_index(f"ix_{TABLE_NAME}_status", TABLE_NAME, ["status"])
    op.create_index(
        "ix_integration_parallel_reconciliation_org_integration_time",
        TABLE_NAME,
        ["organization_id", "integration_id", "created_at"],
    )
    op.create_index(
        "ix_integration_parallel_reconciliation_org_status_time",
        TABLE_NAME,
        ["organization_id", "status", "created_at"],
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
    op.drop_index(
        "ix_integration_parallel_reconciliation_org_status_time",
        table_name=TABLE_NAME,
    )
    op.drop_index(
        "ix_integration_parallel_reconciliation_org_integration_time",
        table_name=TABLE_NAME,
    )
    op.drop_index(f"ix_{TABLE_NAME}_status", table_name=TABLE_NAME)
    op.drop_index(f"ix_{TABLE_NAME}_contract_id", table_name=TABLE_NAME)
    op.drop_index(f"ix_{TABLE_NAME}_integration_id", table_name=TABLE_NAME)
    op.drop_index(f"ix_{TABLE_NAME}_organization_id", table_name=TABLE_NAME)
    op.drop_index(f"ix_{TABLE_NAME}_id", table_name=TABLE_NAME)
    op.drop_table(TABLE_NAME)
