"""add auditable AI visual recognition attempts

Revision ID: 20260807_0047
Revises: 20260807_0046
Create Date: 2026-08-07
"""

from alembic import op
import sqlalchemy as sa


revision = "20260807_0047"
down_revision = "20260807_0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("part_recognition_observations") as batch:
        batch.add_column(
            sa.Column(
                "analysis_status",
                sa.String(length=20),
                server_default="not_requested",
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column(
                "analysis_version",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )
        batch.create_check_constraint(
            "ck_part_recognition_observation_analysis_status",
            "analysis_status IN ('not_requested', 'pending', 'succeeded', 'failed')",
        )
        batch.create_check_constraint(
            "ck_part_recognition_observation_analysis_version_non_negative",
            "analysis_version >= 0",
        )
        batch.create_index(
            "ix_part_recognition_observations_analysis_status",
            ["analysis_status"],
        )

    op.create_table(
        "part_recognition_analyses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("observation_id", sa.Integer(), nullable=False),
        sa.Column("requested_by", sa.Integer(), nullable=True),
        sa.Column("client_request_id", sa.String(length=100), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("image_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("output_sha256", sa.String(length=64), nullable=True),
        sa.Column("external_request_id", sa.String(length=200), nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("candidate_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "provider = 'openai'",
            name="ck_part_recognition_analysis_provider",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
            name="ck_part_recognition_analysis_status",
        ),
        sa.CheckConstraint(
            "attempt_number > 0",
            name="ck_part_recognition_analysis_attempt_positive",
        ),
        sa.CheckConstraint(
            "candidate_count >= 0",
            name="ck_part_recognition_analysis_candidate_count_non_negative",
        ),
        sa.CheckConstraint(
            "length(image_sha256) = 64 AND length(request_sha256) = 64",
            name="ck_part_recognition_analysis_input_hashes",
        ),
        sa.CheckConstraint(
            "output_sha256 IS NULL OR length(output_sha256) = 64",
            name="ck_part_recognition_analysis_output_hash",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND completed_at IS NULL AND failure_code IS NULL) OR "
            "(status = 'succeeded' AND completed_at IS NOT NULL "
            "AND failure_code IS NULL AND output_sha256 IS NOT NULL "
            "AND result_json IS NOT NULL) OR "
            "(status = 'failed' AND completed_at IS NOT NULL "
            "AND failure_code IS NOT NULL)",
            name="ck_part_recognition_analysis_completion",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["part_recognition_observations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "client_request_id",
            name="uq_part_recognition_analysis_org_request",
        ),
        sa.UniqueConstraint(
            "observation_id",
            "attempt_number",
            name="uq_part_recognition_analysis_attempt",
        ),
    )
    for column in ("id", "organization_id", "observation_id", "requested_by"):
        op.create_index(
            op.f(f"ix_part_recognition_analyses_{column}"),
            "part_recognition_analyses",
            [column],
        )
    op.create_index(
        "ix_part_recognition_analysis_org_created",
        "part_recognition_analyses",
        ["organization_id", "created_at"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    evidence = connection.scalar(
        sa.text("SELECT COUNT(*) FROM part_recognition_analyses")
    )
    if evidence:
        raise RuntimeError(
            "Cannot downgrade while AI visual recognition evidence exists"
        )

    op.drop_index(
        "ix_part_recognition_analysis_org_created",
        table_name="part_recognition_analyses",
    )
    for column in ("requested_by", "observation_id", "organization_id", "id"):
        op.drop_index(
            op.f(f"ix_part_recognition_analyses_{column}"),
            table_name="part_recognition_analyses",
        )
    op.drop_table("part_recognition_analyses")

    with op.batch_alter_table("part_recognition_observations") as batch:
        batch.drop_index("ix_part_recognition_observations_analysis_status")
        batch.drop_constraint(
            "ck_part_recognition_observation_analysis_version_non_negative",
            type_="check",
        )
        batch.drop_constraint(
            "ck_part_recognition_observation_analysis_status",
            type_="check",
        )
        batch.drop_column("analysis_version")
        batch.drop_column("analysis_status")
