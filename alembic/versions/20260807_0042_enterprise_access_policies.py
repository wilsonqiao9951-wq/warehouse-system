"""add enterprise user permission grants

Revision ID: 20260807_0042
Revises: 20260807_0041
Create Date: 2026-08-07
"""

import sqlalchemy as sa
from alembic import op


revision = "20260807_0042"
down_revision = "20260807_0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_permission_grants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("permission_code", sa.String(length=80), nullable=False),
        sa.Column("effect", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("granted_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "effect IN ('allow', 'deny')",
            name="ck_user_permission_grants_effect",
        ),
        sa.ForeignKeyConstraint(["granted_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            "permission_code",
            name="uq_user_permission_grants_org_user_code",
        ),
    )
    op.create_index(
        "ix_user_permission_grants_organization_id",
        "user_permission_grants",
        ["organization_id"],
    )
    op.create_index(
        "ix_user_permission_grants_user_id",
        "user_permission_grants",
        ["user_id"],
    )
    op.create_index(
        "ix_user_permission_grants_org_user",
        "user_permission_grants",
        ["organization_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_permission_grants_org_user",
        table_name="user_permission_grants",
    )
    op.drop_index(
        "ix_user_permission_grants_user_id",
        table_name="user_permission_grants",
    )
    op.drop_index(
        "ix_user_permission_grants_organization_id",
        table_name="user_permission_grants",
    )
    op.drop_table("user_permission_grants")
