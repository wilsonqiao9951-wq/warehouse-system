"""add verified invitation email delivery evidence

Revision ID: 20260807_0051
Revises: 20260807_0050
Create Date: 2026-08-07
"""

from alembic import op
import sqlalchemy as sa


revision = "20260807_0051"
down_revision = "20260807_0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user_invitations") as batch:
        batch.add_column(
            sa.Column(
                "delivery_status",
                sa.String(length=20),
                nullable=False,
                server_default="manual",
            )
        )
        batch.add_column(
            sa.Column("delivery_failure_code", sa.String(length=64), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "delivery_attempt_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column("last_delivery_attempt_at", sa.DateTime(), nullable=True)
        )
        batch.add_column(sa.Column("delivered_at", sa.DateTime(), nullable=True))
        batch.create_check_constraint(
            "ck_user_invitations_delivery_status",
            "delivery_status IN ('manual', 'pending', 'sent', 'failed')",
        )
        batch.create_check_constraint(
            "ck_user_invitations_delivery_attempt_count_non_negative",
            "delivery_attempt_count >= 0",
        )
        batch.create_index(
            "ix_user_invitations_org_delivery_created",
            ["organization_id", "delivery_status", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    connection = op.get_bind()
    evidence = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM user_invitations "
            "WHERE delivery_status <> 'manual' "
            "OR delivery_attempt_count <> 0 "
            "OR delivery_failure_code IS NOT NULL "
            "OR last_delivery_attempt_at IS NOT NULL "
            "OR delivered_at IS NOT NULL"
        )
    )
    if evidence:
        raise RuntimeError(
            "Cannot downgrade while invitation delivery evidence exists"
        )

    with op.batch_alter_table("user_invitations") as batch:
        batch.drop_index("ix_user_invitations_org_delivery_created")
        batch.drop_constraint(
            "ck_user_invitations_delivery_attempt_count_non_negative",
            type_="check",
        )
        batch.drop_constraint(
            "ck_user_invitations_delivery_status",
            type_="check",
        )
        batch.drop_column("delivered_at")
        batch.drop_column("last_delivery_attempt_at")
        batch.drop_column("delivery_attempt_count")
        batch.drop_column("delivery_failure_code")
        batch.drop_column("delivery_status")
