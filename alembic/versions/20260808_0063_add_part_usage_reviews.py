"""add governed part usage baselines and review evidence

Revision ID: 20260808_0063
Revises: 20260807_0062
Create Date: 2026-08-08
"""

import sqlalchemy as sa
from alembic import op


revision = "20260808_0063"
down_revision = "20260807_0062"
branch_labels = None
depends_on = None

BASELINE_TABLE = "part_usage_baselines"
REVIEW_TABLE = "part_usage_reviews"
TENANT_TABLES = (BASELINE_TABLE, REVIEW_TABLE)
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
        BASELINE_TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("part_id", sa.Integer(), sa.ForeignKey("parts.id"), nullable=False),
        sa.Column("scope", sa.String(length=30), nullable=False),
        sa.Column("job_type_key", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("machine_type_key", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("store_key", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("sample_work_orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sample_usage_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("segment_work_orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mean_quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("stddev_quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("p90_quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("spike_threshold", sa.Float(), nullable=False, server_default="0"),
        sa.Column("support_ratio", sa.Float(), nullable=False, server_default="0"),
        sa.Column("first_observed_at", sa.DateTime(), nullable=True),
        sa.Column("last_observed_at", sa.DateTime(), nullable=True),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "organization_id", "part_id", "scope", "job_type_key", "machine_type_key", "store_key",
            name="uq_part_usage_baseline_segment",
        ),
        sa.CheckConstraint(
            "scope IN ('job_machine_store', 'job_machine', 'machine', 'job', 'organization')",
            name="ck_part_usage_baseline_scope",
        ),
        sa.CheckConstraint(
            "sample_work_orders >= 0 AND sample_usage_rows >= 0 AND segment_work_orders >= 0 AND total_quantity >= 0",
            name="ck_part_usage_baseline_counts_non_negative",
        ),
        sa.CheckConstraint(
            "mean_quantity >= 0 AND stddev_quantity >= 0 AND p90_quantity >= 0 AND spike_threshold >= 0 "
            "AND support_ratio >= 0 AND support_ratio <= 1",
            name="ck_part_usage_baseline_metrics_valid",
        ),
        sa.CheckConstraint("length(source_fingerprint) = 64", name="ck_part_usage_baseline_fingerprint"),
        sa.CheckConstraint("version >= 0", name="ck_part_usage_baseline_version_non_negative"),
    )
    op.create_index("ix_part_usage_baselines_id", BASELINE_TABLE, ["id"])
    op.create_index("ix_part_usage_baselines_organization_id", BASELINE_TABLE, ["organization_id"])
    op.create_index("ix_part_usage_baselines_part_id", BASELINE_TABLE, ["part_id"])
    op.create_index(
        "ix_part_usage_baseline_org_scope",
        BASELINE_TABLE,
        ["organization_id", "scope", "computed_at"],
    )

    op.create_table(
        REVIEW_TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("work_order_id", sa.Integer(), sa.ForeignKey("work_orders.id"), nullable=False),
        sa.Column("work_order_part_id", sa.Integer(), sa.ForeignKey("work_order_parts.id"), nullable=False),
        sa.Column("part_id", sa.Integer(), sa.ForeignKey("parts.id"), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("engineer_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("baseline_id", sa.Integer(), sa.ForeignKey(f"{BASELINE_TABLE}.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("severity", sa.String(length=12), nullable=False),
        sa.Column("reason_codes_json", sa.Text(), nullable=False),
        sa.Column("explanation_json", sa.Text(), nullable=False),
        sa.Column("observed_quantity", sa.Integer(), nullable=False),
        sa.Column("observed_parts_cost", sa.Float(), nullable=False),
        sa.Column("baseline_scope", sa.String(length=30), nullable=True),
        sa.Column("baseline_sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("baseline_mean_quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("baseline_p90_quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("baseline_spike_threshold", sa.Float(), nullable=False, server_default="0"),
        sa.Column("segment_work_order_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("combination_support_ratio", sa.Float(), nullable=False, server_default="0"),
        sa.Column("usage_timezone", sa.String(length=64), nullable=False, server_default="UTC"),
        sa.Column("usage_local_hour", sa.Integer(), nullable=True),
        sa.Column("evaluation_version", sa.String(length=24), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("acknowledged_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("acknowledgement_note", sa.String(length=500), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("decision_reason", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "work_order_part_id", name="uq_part_usage_review_usage"),
        sa.CheckConstraint(
            "status IN ('pending', 'acknowledged', 'confirmed', 'dismissed')",
            name="ck_part_usage_review_status",
        ),
        sa.CheckConstraint("severity IN ('low', 'medium', 'high')", name="ck_part_usage_review_severity"),
        sa.CheckConstraint(
            "observed_quantity > 0 AND observed_parts_cost >= 0 AND baseline_sample_size >= 0 "
            "AND segment_work_order_count >= 0",
            name="ck_part_usage_review_counts_valid",
        ),
        sa.CheckConstraint(
            "baseline_mean_quantity >= 0 AND baseline_p90_quantity >= 0 AND baseline_spike_threshold >= 0 "
            "AND combination_support_ratio >= 0 AND combination_support_ratio <= 1",
            name="ck_part_usage_review_metrics_valid",
        ),
        sa.CheckConstraint(
            "usage_local_hour IS NULL OR (usage_local_hour >= 0 AND usage_local_hour <= 23)",
            name="ck_part_usage_review_local_hour",
        ),
        sa.CheckConstraint("length(source_fingerprint) = 64", name="ck_part_usage_review_fingerprint"),
        sa.CheckConstraint("version >= 0", name="ck_part_usage_review_version_non_negative"),
    )
    op.create_index("ix_part_usage_reviews_id", REVIEW_TABLE, ["id"])
    op.create_index("ix_part_usage_reviews_organization_id", REVIEW_TABLE, ["organization_id"])
    op.create_index("ix_part_usage_reviews_work_order_id", REVIEW_TABLE, ["work_order_id"])
    op.create_index("ix_part_usage_reviews_work_order_part_id", REVIEW_TABLE, ["work_order_part_id"])
    op.create_index("ix_part_usage_reviews_part_id", REVIEW_TABLE, ["part_id"])
    op.create_index("ix_part_usage_reviews_warehouse_id", REVIEW_TABLE, ["warehouse_id"])
    op.create_index("ix_part_usage_reviews_engineer_id", REVIEW_TABLE, ["engineer_id"])
    op.create_index("ix_part_usage_reviews_status", REVIEW_TABLE, ["status"])
    op.create_index("ix_part_usage_reviews_severity", REVIEW_TABLE, ["severity"])
    op.create_index(
        "ix_part_usage_review_org_status_severity",
        REVIEW_TABLE,
        ["organization_id", "status", "severity", "created_at"],
    )
    op.create_index(
        "ix_part_usage_review_org_engineer",
        REVIEW_TABLE,
        ["organization_id", "engineer_id", "created_at"],
    )

    if op.get_bind().dialect.name == "postgresql":
        for table_name in TENANT_TABLES:
            op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
            op.execute(
                f'CREATE POLICY "{POLICY_NAME}" ON "{table_name}" '
                f"USING ({POLICY_EXPRESSION}) WITH CHECK ({POLICY_EXPRESSION})"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table_name in reversed(TENANT_TABLES):
            op.execute(f'DROP POLICY IF EXISTS "{POLICY_NAME}" ON "{table_name}"')
            op.execute(f'ALTER TABLE "{table_name}" NO FORCE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY')
    op.drop_table(REVIEW_TABLE)
    op.drop_table(BASELINE_TABLE)
