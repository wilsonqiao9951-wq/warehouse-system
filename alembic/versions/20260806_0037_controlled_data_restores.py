"""add controlled organization data restores

Revision ID: 20260806_0037
Revises: 20260806_0036
Create Date: 2026-08-06
"""

from alembic import op
import sqlalchemy as sa


revision = "20260806_0037"
down_revision = "20260806_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization_data_restores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("requested_by", sa.Integer(), nullable=True),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("rejected_by", sa.Integer(), nullable=True),
        sa.Column("applied_by", sa.Integer(), nullable=True),
        sa.Column("rolled_back_by", sa.Integer(), nullable=True),
        sa.Column("matched_export_id", sa.Integer(), nullable=True),
        sa.Column("format_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("archive_sha256", sa.String(length=64), nullable=False),
        sa.Column("archive_size_bytes", sa.Integer(), nullable=False),
        sa.Column("plan_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_schema_revision", sa.String(length=64), nullable=True),
        sa.Column("source_exported_at", sa.DateTime(), nullable=True),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("update_count", sa.Integer(), nullable=False),
        sa.Column("unchanged_count", sa.Integer(), nullable=False),
        sa.Column("conflict_count", sa.Integer(), nullable=False),
        sa.Column("protected_count", sa.Integer(), nullable=False),
        sa.Column("table_summary_json", sa.Text(), nullable=False),
        sa.Column("validation_messages_json", sa.Text(), nullable=False),
        sa.Column("approval_note", sa.String(length=1000), nullable=True),
        sa.Column("rollback_payload_json", sa.Text(), nullable=True),
        sa.Column("rollback_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "rollback_size_bytes", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "format_version = 'opf-portable-v1'",
            name="ck_organization_data_restore_format",
        ),
        sa.CheckConstraint(
            "status IN ('validated', 'approved', 'rejected', 'applied', 'rolled_back')",
            name="ck_organization_data_restore_status",
        ),
        sa.CheckConstraint(
            "archive_size_bytes >= 0 AND record_count >= 0 AND file_count >= 0 "
            "AND update_count >= 0 AND unchanged_count >= 0 "
            "AND conflict_count >= 0 AND protected_count >= 0 "
            "AND rollback_size_bytes >= 0 AND version >= 0",
            name="ck_organization_data_restore_counts_non_negative",
        ),
        sa.CheckConstraint(
            "length(archive_sha256) = 64 AND length(plan_sha256) = 64 "
            "AND (rollback_sha256 IS NULL OR length(rollback_sha256) = 64)",
            name="ck_organization_data_restore_hashes",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["rejected_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["applied_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["rolled_back_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["matched_export_id"], ["organization_data_exports.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("id", "organization_id", "requested_by"):
        op.create_index(
            op.f(f"ix_organization_data_restores_{column}"),
            "organization_data_restores",
            [column],
        )
    op.create_index(
        "ix_organization_data_restore_org_created",
        "organization_data_restores",
        ["organization_id", "created_at"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    restore_count = connection.scalar(
        sa.text("SELECT COUNT(*) FROM organization_data_restores")
    )
    if restore_count:
        raise RuntimeError(
            "Cannot downgrade while controlled data restore evidence exists"
        )

    op.drop_index(
        "ix_organization_data_restore_org_created",
        table_name="organization_data_restores",
    )
    for column in ("requested_by", "organization_id", "id"):
        op.drop_index(
            op.f(f"ix_organization_data_restores_{column}"),
            table_name="organization_data_restores",
        )
    op.drop_table("organization_data_restores")
