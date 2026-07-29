"""add governed work-order and media knowledge capture

Revision ID: 20260728_0026
Revises: 20260728_0025
"""
from alembic import op
import sqlalchemy as sa


revision = "20260728_0026"
down_revision = "20260728_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("machine_knowledge_entries") as batch_op:
        batch_op.add_column(
            sa.Column("related_part_role", sa.String(length=30), nullable=True)
        )
        batch_op.add_column(
            sa.Column("alternative_for_part_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("installation_location", sa.String(length=500), nullable=True)
        )
        batch_op.add_column(
            sa.Column("origin_key", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column("media_storage_key", sa.String(length=500), nullable=True)
        )
        batch_op.add_column(
            sa.Column("media_mime_type", sa.String(length=100), nullable=True)
        )
        batch_op.add_column(
            sa.Column("media_size_bytes", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_machine_knowledge_alternative_for_part",
            "parts",
            ["alternative_for_part_id"],
            ["id"],
        )
        batch_op.create_unique_constraint(
            "uq_machine_knowledge_entry_profile_origin",
            ["profile_id", "origin_key"],
        )
        batch_op.create_check_constraint(
            "ck_machine_knowledge_related_part_role",
            "related_part_role IS NULL OR related_part_role IN "
            "('recommended', 'alternative', 'consumable', 'reference')",
        )
        batch_op.create_check_constraint(
            "ck_machine_knowledge_part_role_requires_part",
            "related_part_role IS NULL OR related_part_id IS NOT NULL",
        )
        batch_op.create_check_constraint(
            "ck_machine_knowledge_alternative_requires_primary",
            "related_part_role != 'alternative' OR alternative_for_part_id IS NOT NULL",
        )
        batch_op.create_check_constraint(
            "ck_machine_knowledge_alternative_distinct",
            "alternative_for_part_id IS NULL OR alternative_for_part_id != related_part_id",
        )
        batch_op.create_check_constraint(
            "ck_machine_knowledge_primary_only_for_alternative",
            "alternative_for_part_id IS NULL OR related_part_role = 'alternative'",
        )
        batch_op.create_check_constraint(
            "ck_machine_knowledge_media_size_non_negative",
            "media_size_bytes IS NULL OR media_size_bytes >= 0",
        )
    op.create_index(
        "ix_machine_knowledge_entries_alternative_for_part_id",
        "machine_knowledge_entries",
        ["alternative_for_part_id"],
    )
    op.create_index(
        "ix_machine_knowledge_entries_origin_key",
        "machine_knowledge_entries",
        ["origin_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_machine_knowledge_entries_origin_key",
        table_name="machine_knowledge_entries",
    )
    op.drop_index(
        "ix_machine_knowledge_entries_alternative_for_part_id",
        table_name="machine_knowledge_entries",
    )
    with op.batch_alter_table("machine_knowledge_entries") as batch_op:
        batch_op.drop_constraint(
            "ck_machine_knowledge_media_size_non_negative",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_machine_knowledge_primary_only_for_alternative",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_machine_knowledge_alternative_distinct",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_machine_knowledge_alternative_requires_primary",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_machine_knowledge_part_role_requires_part",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_machine_knowledge_related_part_role",
            type_="check",
        )
        batch_op.drop_constraint(
            "uq_machine_knowledge_entry_profile_origin",
            type_="unique",
        )
        batch_op.drop_constraint(
            "fk_machine_knowledge_alternative_for_part",
            type_="foreignkey",
        )
        batch_op.drop_column("media_size_bytes")
        batch_op.drop_column("media_mime_type")
        batch_op.drop_column("media_storage_key")
        batch_op.drop_column("origin_key")
        batch_op.drop_column("installation_location")
        batch_op.drop_column("alternative_for_part_id")
        batch_op.drop_column("related_part_role")
