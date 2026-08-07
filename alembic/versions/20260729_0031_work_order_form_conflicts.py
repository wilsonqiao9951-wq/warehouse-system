"""add audited offline work-order form conflict resolution

Revision ID: 20260729_0031
Revises: 20260729_0030
"""
from alembic import op
import sqlalchemy as sa


revision = "20260729_0031"
down_revision = "20260729_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "work_order_form_conflicts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("work_order_id", sa.Integer(), nullable=False),
        sa.Column("client_queue_id", sa.String(length=80), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_device_id", sa.Integer(), nullable=False),
        sa.Column("claim_version", sa.Integer(), nullable=False),
        sa.Column("base_form_version", sa.Integer(), nullable=False),
        sa.Column("server_form_version", sa.Integer(), nullable=False),
        sa.Column("local_values_json", sa.Text(), nullable=False),
        sa.Column("server_values_json", sa.Text(), nullable=False),
        sa.Column("local_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("resolved_values_json", sa.Text(), nullable=True),
        sa.Column("resolved_server_form_version", sa.Integer(), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'kept_server', 'applied_local', 'merged')",
            name="ck_work_order_form_conflict_status",
        ),
        sa.CheckConstraint(
            "base_form_version >= 0 AND server_form_version >= 0",
            name="ck_work_order_form_conflict_form_versions_non_negative",
        ),
        sa.CheckConstraint(
            "claim_version >= 0 AND version >= 0",
            name="ck_work_order_form_conflict_versions_non_negative",
        ),
        sa.CheckConstraint(
            "resolved_server_form_version IS NULL OR resolved_server_form_version >= 0",
            name="ck_work_order_form_conflict_resolved_version_non_negative",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_device_id"], ["user_devices.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["work_order_id"],
            ["work_orders.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "client_queue_id",
            name="uq_work_order_form_conflict_org_queue",
        ),
    )
    for column in (
        "id",
        "organization_id",
        "work_order_id",
        "status",
    ):
        op.create_index(
            op.f(f"ix_work_order_form_conflicts_{column}"),
            "work_order_form_conflicts",
            [column],
        )
    op.create_index(
        "ix_work_order_form_conflicts_org_status",
        "work_order_form_conflicts",
        ["organization_id", "status"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    conflict_count = connection.scalar(
        sa.text("SELECT COUNT(*) FROM work_order_form_conflicts")
    )
    if conflict_count:
        raise RuntimeError(
            "Cannot downgrade while work-order form conflict evidence exists"
        )
    op.drop_index(
        "ix_work_order_form_conflicts_org_status",
        table_name="work_order_form_conflicts",
    )
    for column in (
        "status",
        "work_order_id",
        "organization_id",
        "id",
    ):
        op.drop_index(
            op.f(f"ix_work_order_form_conflicts_{column}"),
            table_name="work_order_form_conflicts",
        )
    op.drop_table("work_order_form_conflicts")
