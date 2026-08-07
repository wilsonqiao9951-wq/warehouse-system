"""add enterprise agent run evidence

Revision ID: 20260807_0045
Revises: 20260807_0044
Create Date: 2026-08-07
"""

import sqlalchemy as sa
from alembic import op


revision = "20260807_0045"
down_revision = "20260807_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enterprise_agent_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("intent", sa.String(length=40), nullable=False),
        sa.Column("question_sha256", sa.String(length=64), nullable=False),
        sa.Column("question_length", sa.Integer(), nullable=False),
        sa.Column("filters_json", sa.Text(), nullable=False),
        sa.Column("tools_json", sa.Text(), nullable=False),
        sa.Column("finding_count", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "intent IN ('daily_brief', 'backlog_risk', 'service_quality', "
            "'inventory_risk', 'integration_health')",
            name="ck_enterprise_agent_runs_intent",
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'failed')",
            name="ck_enterprise_agent_runs_status",
        ),
        sa.CheckConstraint(
            "question_length >= 0 AND finding_count >= 0 AND duration_ms >= 0",
            name="ck_enterprise_agent_runs_counts_non_negative",
        ),
        sa.CheckConstraint(
            "length(question_sha256) = 64",
            name="ck_enterprise_agent_runs_question_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_enterprise_agent_runs_id",
        "enterprise_agent_runs",
        ["id"],
    )
    op.create_index(
        "ix_enterprise_agent_runs_organization_id",
        "enterprise_agent_runs",
        ["organization_id"],
    )
    op.create_index(
        "ix_enterprise_agent_runs_user_id",
        "enterprise_agent_runs",
        ["user_id"],
    )
    op.create_index(
        "ix_enterprise_agent_runs_intent",
        "enterprise_agent_runs",
        ["intent"],
    )
    op.create_index(
        "ix_enterprise_agent_runs_org_created",
        "enterprise_agent_runs",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "ix_enterprise_agent_runs_org_user_created",
        "enterprise_agent_runs",
        ["organization_id", "user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_enterprise_agent_runs_org_user_created",
        table_name="enterprise_agent_runs",
    )
    op.drop_index(
        "ix_enterprise_agent_runs_org_created",
        table_name="enterprise_agent_runs",
    )
    op.drop_index(
        "ix_enterprise_agent_runs_intent",
        table_name="enterprise_agent_runs",
    )
    op.drop_index(
        "ix_enterprise_agent_runs_user_id",
        table_name="enterprise_agent_runs",
    )
    op.drop_index(
        "ix_enterprise_agent_runs_organization_id",
        table_name="enterprise_agent_runs",
    )
    op.drop_index("ix_enterprise_agent_runs_id", table_name="enterprise_agent_runs")
    op.drop_table("enterprise_agent_runs")
