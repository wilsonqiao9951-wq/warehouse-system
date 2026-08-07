"""add enterprise data residency controls

Revision ID: 20260807_0055
Revises: 20260807_0054
Create Date: 2026-08-07
"""

from alembic import op
import sqlalchemy as sa


revision = "20260807_0055"
down_revision = "20260807_0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("organizations") as batch:
        batch.add_column(
            sa.Column("data_residency_region", sa.String(length=64), nullable=True)
        )
        batch.add_column(
            sa.Column("data_residency_enforced_at", sa.DateTime(), nullable=True)
        )
        batch.create_check_constraint(
            "ck_organizations_data_residency_evidence",
            "(data_residency_region IS NULL AND data_residency_enforced_at IS NULL) "
            "OR (data_residency_region IS NOT NULL AND data_residency_enforced_at IS NOT NULL)",
        )
        batch.create_check_constraint(
            "ck_organizations_data_residency_plan",
            "data_residency_region IS NULL OR plan_code = 'enterprise'",
        )
        batch.create_index(
            "ix_organizations_data_residency_region",
            ["data_residency_region"],
            unique=False,
        )


def downgrade() -> None:
    configured_organization = op.get_bind().scalar(
        sa.text(
            "SELECT id FROM organizations "
            "WHERE data_residency_region IS NOT NULL LIMIT 1"
        )
    )
    if configured_organization is not None:
        raise RuntimeError(
            "Cannot downgrade while organization data residency evidence exists"
        )

    with op.batch_alter_table("organizations") as batch:
        batch.drop_index("ix_organizations_data_residency_region")
        batch.drop_constraint(
            "ck_organizations_data_residency_plan",
            type_="check",
        )
        batch.drop_constraint(
            "ck_organizations_data_residency_evidence",
            type_="check",
        )
        batch.drop_column("data_residency_enforced_at")
        batch.drop_column("data_residency_region")
