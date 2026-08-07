"""add multi-instance worker leases

Revision ID: 20260807_0056
Revises: 20260807_0055
Create Date: 2026-08-07
"""

from alembic import op
import sqlalchemy as sa


revision = "20260807_0056"
down_revision = "20260807_0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_leases",
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("owner_id", sa.String(length=200), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("acquired_at", sa.DateTime(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(), nullable=False),
        sa.Column("run_started_at", sa.DateTime(), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_type", sa.String(length=160), nullable=True),
        sa.Column("last_result_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "length(trim(name)) > 0 AND length(trim(owner_id)) > 0",
            name="ck_worker_leases_identity_nonblank",
        ),
        sa.CheckConstraint(
            "generation >= 1",
            name="ck_worker_leases_generation_positive",
        ),
        sa.CheckConstraint(
            "lease_expires_at >= heartbeat_at",
            name="ck_worker_leases_expiration_after_heartbeat",
        ),
        sa.CheckConstraint(
            "last_result_count IS NULL OR last_result_count >= 0",
            name="ck_worker_leases_result_non_negative",
        ),
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_index(
        "ix_worker_leases_expiration",
        "worker_leases",
        ["lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_worker_leases_next_run",
        "worker_leases",
        ["next_run_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_worker_leases_next_run", table_name="worker_leases")
    op.drop_index("ix_worker_leases_expiration", table_name="worker_leases")
    op.drop_table("worker_leases")
