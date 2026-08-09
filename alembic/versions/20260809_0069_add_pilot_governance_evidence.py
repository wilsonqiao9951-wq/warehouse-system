"""add governed pilot evidence

Revision ID: 20260809_0069
Revises: 20260808_0068
Create Date: 2026-08-09
"""

import sqlalchemy as sa
from alembic import op


revision = "20260809_0069"
down_revision = "20260808_0068"
branch_labels = None
depends_on = None

TABLES = ("pilot_campaigns", "pilot_attestations", "pilot_issues")
POLICY_NAME = "openpartsflow_tenant_isolation"
POLICY_EXPRESSION = """
(
  current_setting('openpartsflow.platform_access', true) = 'on'
  OR organization_id = NULLIF(
    current_setting('openpartsflow.organization_id', true), ''
  )::integer
)
""".strip()


def _secure_table(table_name: str) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(sa.text(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text(
            f"CREATE POLICY {POLICY_NAME} ON {table_name} "
            f"USING {POLICY_EXPRESSION} WITH CHECK {POLICY_EXPRESSION}"
        )
    )


def upgrade() -> None:
    op.create_table(
        "pilot_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("planned_start", sa.Date(), nullable=False),
        sa.Column("planned_end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("decision_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decision_reason", sa.String(length=500), nullable=True),
        sa.Column("decision_snapshot_json", sa.Text(), nullable=True),
        sa.Column("decision_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'decision_pending', 'go', 'no_go')",
            name="ck_pilot_campaigns_status",
        ),
        sa.CheckConstraint("planned_start <= planned_end", name="ck_pilot_campaigns_planned_window"),
        sa.CheckConstraint("version >= 0", name="ck_pilot_campaigns_version"),
        sa.CheckConstraint(
            "decision_fingerprint IS NULL OR length(decision_fingerprint) = 64",
            name="ck_pilot_campaigns_decision_fingerprint",
        ),
    )
    for column in ("id", "organization_id", "status"):
        op.create_index(f"ix_pilot_campaigns_{column}", "pilot_campaigns", [column])
    op.create_index(
        "ix_pilot_campaigns_org_status_time",
        "pilot_campaigns",
        ["organization_id", "status", "created_at"],
    )
    op.create_index(
        "ix_pilot_campaigns_one_live_per_org",
        "pilot_campaigns",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('active', 'decision_pending')"),
        sqlite_where=sa.text("status IN ('active', 'decision_pending')"),
    )

    op.create_table(
        "pilot_attestations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("pilot_campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("attestation_type", sa.String(length=20), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("completed_items_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("evidence_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("attestation_type IN ('training', 'uat')", name="ck_pilot_attestations_type"),
        sa.CheckConstraint("result IN ('passed', 'failed')", name="ck_pilot_attestations_result"),
        sa.CheckConstraint("role IN ('admin', 'manager', 'warehouse', 'engineer')", name="ck_pilot_attestations_role"),
        sa.CheckConstraint("length(evidence_fingerprint) = 64", name="ck_pilot_attestations_fingerprint"),
        sa.UniqueConstraint(
            "campaign_id", "user_id", "attestation_type", "evidence_fingerprint",
            name="uq_pilot_attestations_exact_evidence",
        ),
    )
    for column in ("id", "organization_id", "campaign_id", "user_id", "role", "attestation_type", "result"):
        op.create_index(f"ix_pilot_attestations_{column}", "pilot_attestations", [column])
    op.create_index(
        "ix_pilot_attestations_org_campaign_time",
        "pilot_attestations",
        ["organization_id", "campaign_id", "created_at"],
    )

    op.create_table(
        "pilot_issues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("pilot_campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("detail", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reported_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("resolved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolution_reason", sa.String(length=500), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("severity IN ('sev1', 'sev2', 'sev3')", name="ck_pilot_issues_severity"),
        sa.CheckConstraint("status IN ('open', 'resolved')", name="ck_pilot_issues_status"),
        sa.CheckConstraint("version >= 0", name="ck_pilot_issues_version"),
    )
    for column in ("id", "organization_id", "campaign_id", "severity", "status"):
        op.create_index(f"ix_pilot_issues_{column}", "pilot_issues", [column])
    op.create_index(
        "ix_pilot_issues_org_campaign_status",
        "pilot_issues",
        ["organization_id", "campaign_id", "status"],
    )

    for table_name in TABLES:
        _secure_table(table_name)


def downgrade() -> None:
    for table_name in reversed(TABLES):
        if op.get_bind().dialect.name == "postgresql":
            op.execute(sa.text(f"DROP POLICY IF EXISTS {POLICY_NAME} ON {table_name}"))
        op.drop_table(table_name)
