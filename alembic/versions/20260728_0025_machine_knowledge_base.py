"""add governed machine knowledge base

Revision ID: 20260728_0025
Revises: 20260728_0024
"""
from alembic import op
import sqlalchemy as sa


revision = "20260728_0025"
down_revision = "20260728_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "machine_knowledge_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("manufacturer", sa.String(length=160), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("model_key", sa.String(length=255), nullable=False),
        sa.Column("equipment_type", sa.String(length=160), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "version >= 0",
            name="ck_machine_knowledge_profile_version_non_negative",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "model_key",
            name="uq_machine_knowledge_org_model",
        ),
    )
    op.create_index(
        "ix_machine_knowledge_profiles_id",
        "machine_knowledge_profiles",
        ["id"],
    )
    op.create_index(
        "ix_machine_knowledge_profiles_model",
        "machine_knowledge_profiles",
        ["model"],
    )
    op.create_index(
        "ix_machine_knowledge_profiles_organization_id",
        "machine_knowledge_profiles",
        ["organization_id"],
    )

    op.create_table(
        "machine_knowledge_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("entry_type", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("fault_code", sa.String(length=120), nullable=True),
        sa.Column("related_part_id", sa.Integer(), nullable=True),
        sa.Column("source_work_order_id", sa.Integer(), nullable=True),
        sa.Column("media_url", sa.String(length=1000), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("published_by", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("archived_by", sa.Integer(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "entry_type IN ('fault', 'repair_step', 'tool', 'caution', "
            "'common_error', 'photo', 'video', 'note')",
            name="ck_machine_knowledge_entry_type",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_machine_knowledge_entry_status",
        ),
        sa.CheckConstraint(
            "sort_order >= 0",
            name="ck_machine_knowledge_entry_sort_non_negative",
        ),
        sa.CheckConstraint(
            "version >= 0",
            name="ck_machine_knowledge_entry_version_non_negative",
        ),
        sa.ForeignKeyConstraint(["archived_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["machine_knowledge_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["published_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["related_part_id"], ["parts.id"]),
        sa.ForeignKeyConstraint(["source_work_order_id"], ["work_orders.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_machine_knowledge_entries_entry_type",
        "machine_knowledge_entries",
        ["entry_type"],
    )
    op.create_index(
        "ix_machine_knowledge_entries_fault_code",
        "machine_knowledge_entries",
        ["fault_code"],
    )
    op.create_index(
        "ix_machine_knowledge_entries_id",
        "machine_knowledge_entries",
        ["id"],
    )
    op.create_index(
        "ix_machine_knowledge_entries_organization_id",
        "machine_knowledge_entries",
        ["organization_id"],
    )
    op.create_index(
        "ix_machine_knowledge_entries_profile_id",
        "machine_knowledge_entries",
        ["profile_id"],
    )
    op.create_index(
        "ix_machine_knowledge_entries_related_part_id",
        "machine_knowledge_entries",
        ["related_part_id"],
    )
    op.create_index(
        "ix_machine_knowledge_entries_source_work_order_id",
        "machine_knowledge_entries",
        ["source_work_order_id"],
    )
    op.create_index(
        "ix_machine_knowledge_entries_status",
        "machine_knowledge_entries",
        ["status"],
    )
    op.create_index(
        "ix_machine_knowledge_entry_profile_status",
        "machine_knowledge_entries",
        ["profile_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_machine_knowledge_entry_profile_status",
        table_name="machine_knowledge_entries",
    )
    op.drop_index(
        "ix_machine_knowledge_entries_status",
        table_name="machine_knowledge_entries",
    )
    op.drop_index(
        "ix_machine_knowledge_entries_source_work_order_id",
        table_name="machine_knowledge_entries",
    )
    op.drop_index(
        "ix_machine_knowledge_entries_related_part_id",
        table_name="machine_knowledge_entries",
    )
    op.drop_index(
        "ix_machine_knowledge_entries_profile_id",
        table_name="machine_knowledge_entries",
    )
    op.drop_index(
        "ix_machine_knowledge_entries_organization_id",
        table_name="machine_knowledge_entries",
    )
    op.drop_index(
        "ix_machine_knowledge_entries_id",
        table_name="machine_knowledge_entries",
    )
    op.drop_index(
        "ix_machine_knowledge_entries_fault_code",
        table_name="machine_knowledge_entries",
    )
    op.drop_index(
        "ix_machine_knowledge_entries_entry_type",
        table_name="machine_knowledge_entries",
    )
    op.drop_table("machine_knowledge_entries")
    op.drop_index(
        "ix_machine_knowledge_profiles_organization_id",
        table_name="machine_knowledge_profiles",
    )
    op.drop_index(
        "ix_machine_knowledge_profiles_model",
        table_name="machine_knowledge_profiles",
    )
    op.drop_index(
        "ix_machine_knowledge_profiles_id",
        table_name="machine_knowledge_profiles",
    )
    op.drop_table("machine_knowledge_profiles")
