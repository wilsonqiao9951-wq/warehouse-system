"""add customer data export integrity evidence

Revision ID: 20260806_0036
Revises: 20260806_0035
"""

from alembic import op
import sqlalchemy as sa


revision = "20260806_0036"
down_revision = "20260806_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization_data_exports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("requested_by", sa.Integer(), nullable=True),
        sa.Column(
            "format_version",
            sa.String(length=32),
            nullable=False,
            server_default="opf-portable-v1",
        ),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("missing_file_count", sa.Integer(), nullable=False),
        sa.Column(
            "include_files",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("table_counts_json", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "format_version = 'opf-portable-v1'",
            name="ck_organization_data_export_format",
        ),
        sa.CheckConstraint(
            "size_bytes >= 0 AND record_count >= 0 AND file_count >= 0 "
            "AND missing_file_count >= 0",
            name="ck_organization_data_export_counts_non_negative",
        ),
        sa.CheckConstraint(
            "length(sha256) = 64",
            name="ck_organization_data_export_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("id", "organization_id", "requested_by"):
        op.create_index(
            op.f(f"ix_organization_data_exports_{column}"),
            "organization_data_exports",
            [column],
        )
    op.create_index(
        "ix_organization_data_export_org_generated",
        "organization_data_exports",
        ["organization_id", "generated_at"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    evidence_count = connection.scalar(
        sa.text("SELECT COUNT(*) FROM organization_data_exports")
    )
    if evidence_count:
        raise RuntimeError(
            "Cannot downgrade while customer data export evidence exists"
        )

    op.drop_index(
        "ix_organization_data_export_org_generated",
        table_name="organization_data_exports",
    )
    for column in ("requested_by", "organization_id", "id"):
        op.drop_index(
            op.f(f"ix_organization_data_exports_{column}"),
            table_name="organization_data_exports",
        )
    op.drop_table("organization_data_exports")
