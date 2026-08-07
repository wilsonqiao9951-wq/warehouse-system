"""add controlled restore media evidence

Revision ID: 20260807_0039
Revises: 20260807_0038
Create Date: 2026-08-07
"""

from alembic import op
import sqlalchemy as sa


revision = "20260807_0039"
down_revision = "20260807_0038"
branch_labels = None
depends_on = None


FILE_COUNT_COLUMNS = (
    "file_create_count",
    "file_overwrite_count",
    "file_unchanged_count",
    "file_conflict_count",
    "file_rollback_size_bytes",
)


def upgrade() -> None:
    with op.batch_alter_table("organization_data_restores") as batch_op:
        for column_name in FILE_COUNT_COLUMNS:
            batch_op.add_column(
                sa.Column(
                    column_name,
                    sa.Integer(),
                    server_default="0",
                    nullable=False,
                )
            )
        batch_op.add_column(
            sa.Column("file_rollback_sha256", sa.String(length=64), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_organization_data_restore_file_counts_non_negative",
            "file_create_count >= 0 AND file_overwrite_count >= 0 "
            "AND file_unchanged_count >= 0 AND file_conflict_count >= 0 "
            "AND file_rollback_size_bytes >= 0",
        )
        batch_op.create_check_constraint(
            "ck_organization_data_restore_file_rollback_hash",
            "file_rollback_sha256 IS NULL OR length(file_rollback_sha256) = 64",
        )


def downgrade() -> None:
    connection = op.get_bind()
    media_evidence_count = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM organization_data_restores "
            "WHERE file_create_count > 0 OR file_overwrite_count > 0 "
            "OR file_rollback_sha256 IS NOT NULL OR file_rollback_size_bytes > 0"
        )
    )
    if media_evidence_count:
        raise RuntimeError(
            "Cannot downgrade while restore media writeback evidence exists"
        )

    with op.batch_alter_table("organization_data_restores") as batch_op:
        batch_op.drop_constraint(
            "ck_organization_data_restore_file_rollback_hash",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_organization_data_restore_file_counts_non_negative",
            type_="check",
        )
        batch_op.drop_column("file_rollback_sha256")
        for column_name in reversed(FILE_COUNT_COLUMNS):
            batch_op.drop_column(column_name)
