"""add durable operations health history

Revision ID: 20260807_0057
Revises: 20260807_0056
Create Date: 2026-08-07
"""

from alembic import op
import sqlalchemy as sa


revision = "20260807_0057"
down_revision = "20260807_0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operations_health_samples",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instance_key", sa.String(length=64), nullable=False),
        sa.Column("sampled_at", sa.DateTime(), nullable=False),
        sa.Column("process_started_at", sa.DateTime(), nullable=False),
        sa.Column("uptime_seconds", sa.Integer(), nullable=False),
        sa.Column("schema_revision", sa.String(length=64), nullable=False),
        sa.Column("schema_ready", sa.Boolean(), nullable=False),
        sa.Column("worker_health", sa.String(length=16), nullable=False),
        sa.Column("request_window_seconds", sa.Integer(), nullable=False),
        sa.Column("request_total", sa.Integer(), nullable=False),
        sa.Column("server_errors", sa.Integer(), nullable=False),
        sa.Column("average_duration_ms", sa.Float(), nullable=False),
        sa.Column("p95_duration_ms", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "length(instance_key) = 64",
            name="ck_operations_health_instance_hash",
        ),
        sa.CheckConstraint(
            "uptime_seconds >= 0 AND request_window_seconds >= 1 "
            "AND request_total >= 0 AND server_errors >= 0 "
            "AND server_errors <= request_total "
            "AND average_duration_ms >= 0 AND p95_duration_ms >= 0",
            name="ck_operations_health_metrics_non_negative",
        ),
        sa.CheckConstraint(
            "worker_health IN ('ok', 'degraded')",
            name="ck_operations_health_worker_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "instance_key",
            "sampled_at",
            name="uq_operations_health_instance_sample",
        ),
    )
    op.create_index(
        "ix_operations_health_sampled_at",
        "operations_health_samples",
        ["sampled_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_operations_health_sampled_at",
        table_name="operations_health_samples",
    )
    op.drop_table("operations_health_samples")
