"""add durable monthly commercial usage metering

Revision ID: 20260806_0033
Revises: 20260730_0032
"""

from alembic import op
import sqlalchemy as sa


revision = "20260806_0033"
down_revision = "20260730_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization_usage_periods",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("ai_requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("api_requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_ai_used_at", sa.DateTime(), nullable=True),
        sa.Column("last_api_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "ai_requests >= 0 AND api_requests >= 0",
            name="ck_organization_usage_counts_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "period_start",
            name="uq_organization_usage_period",
        ),
    )
    op.create_index(
        op.f("ix_organization_usage_periods_id"),
        "organization_usage_periods",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_organization_usage_periods_organization_id"),
        "organization_usage_periods",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_organization_usage_period_start",
        "organization_usage_periods",
        ["organization_id", "period_start"],
        unique=False,
    )


def downgrade() -> None:
    connection = op.get_bind()
    recorded_usage = connection.scalar(
        sa.text("SELECT COUNT(*) FROM organization_usage_periods")
    )
    if recorded_usage:
        raise RuntimeError(
            "Cannot downgrade while commercial AI/API usage records exist"
        )
    op.drop_index(
        "ix_organization_usage_period_start",
        table_name="organization_usage_periods",
    )
    op.drop_index(
        op.f("ix_organization_usage_periods_organization_id"),
        table_name="organization_usage_periods",
    )
    op.drop_index(
        op.f("ix_organization_usage_periods_id"),
        table_name="organization_usage_periods",
    )
    op.drop_table("organization_usage_periods")
