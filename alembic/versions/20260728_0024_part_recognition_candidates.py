"""add controlled part recognition candidates

Revision ID: 20260728_0024
Revises: 20260712_0023
"""
from alembic import op
import sqlalchemy as sa


revision = "20260728_0024"
down_revision = "20260712_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "part_recognition_observations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("work_order_id", sa.Integer(), nullable=True),
        sa.Column("machine_model", sa.String(length=255), nullable=True),
        sa.Column("label_text", sa.Text(), nullable=True),
        sa.Column("image_url", sa.String(length=500), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_part_recognition_observations_id",
        "part_recognition_observations",
        ["id"],
    )
    op.create_index(
        "ix_part_recognition_observations_machine_model",
        "part_recognition_observations",
        ["machine_model"],
    )
    op.create_index(
        "ix_part_recognition_observations_organization_id",
        "part_recognition_observations",
        ["organization_id"],
    )
    op.create_index(
        "ix_part_recognition_observations_work_order_id",
        "part_recognition_observations",
        ["work_order_id"],
    )

    op.create_table(
        "part_recognition_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("observation_id", sa.Integer(), nullable=False),
        sa.Column("part_id", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("employee_confirmed_by", sa.Integer(), nullable=True),
        sa.Column("employee_confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("admin_confirmed_by", sa.Integer(), nullable=True),
        sa.Column("admin_confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("usage_verified_by", sa.Integer(), nullable=True),
        sa.Column("usage_verified_at", sa.DateTime(), nullable=True),
        sa.Column("trusted_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_by", sa.Integer(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_part_recognition_confidence",
        ),
        sa.CheckConstraint("rank > 0", name="ck_part_recognition_rank_positive"),
        sa.CheckConstraint(
            "status IN ('ai_candidate', 'employee_confirmed', 'admin_confirmed', "
            "'usage_verified', 'trusted', 'rejected')",
            name="ck_part_recognition_status",
        ),
        sa.ForeignKeyConstraint(["admin_confirmed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["employee_confirmed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["observation_id"], ["part_recognition_observations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["part_id"], ["parts.id"]),
        sa.ForeignKeyConstraint(["rejected_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["usage_verified_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "observation_id",
            "part_id",
            name="uq_part_recognition_observation_part",
        ),
    )
    op.create_index(
        "ix_part_recognition_candidates_id",
        "part_recognition_candidates",
        ["id"],
    )
    op.create_index(
        "ix_part_recognition_candidates_observation_id",
        "part_recognition_candidates",
        ["observation_id"],
    )
    op.create_index(
        "ix_part_recognition_candidates_organization_id",
        "part_recognition_candidates",
        ["organization_id"],
    )
    op.create_index(
        "ix_part_recognition_candidates_part_id",
        "part_recognition_candidates",
        ["part_id"],
    )
    op.create_index(
        "ix_part_recognition_candidates_status",
        "part_recognition_candidates",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_part_recognition_candidates_status",
        table_name="part_recognition_candidates",
    )
    op.drop_index(
        "ix_part_recognition_candidates_part_id",
        table_name="part_recognition_candidates",
    )
    op.drop_index(
        "ix_part_recognition_candidates_organization_id",
        table_name="part_recognition_candidates",
    )
    op.drop_index(
        "ix_part_recognition_candidates_observation_id",
        table_name="part_recognition_candidates",
    )
    op.drop_index(
        "ix_part_recognition_candidates_id",
        table_name="part_recognition_candidates",
    )
    op.drop_table("part_recognition_candidates")
    op.drop_index(
        "ix_part_recognition_observations_work_order_id",
        table_name="part_recognition_observations",
    )
    op.drop_index(
        "ix_part_recognition_observations_organization_id",
        table_name="part_recognition_observations",
    )
    op.drop_index(
        "ix_part_recognition_observations_machine_model",
        table_name="part_recognition_observations",
    )
    op.drop_index(
        "ix_part_recognition_observations_id",
        table_name="part_recognition_observations",
    )
    op.drop_table("part_recognition_observations")
