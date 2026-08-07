"""add restore record rehydration evidence

Revision ID: 20260807_0038
Revises: 20260806_0037
Create Date: 2026-08-07
"""

from alembic import op
import sqlalchemy as sa


revision = "20260807_0038"
down_revision = "20260806_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("organization_data_restores") as batch_op:
        batch_op.add_column(
            sa.Column(
                "create_count",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_organization_data_restore_create_count_non_negative",
            "create_count >= 0",
        )


def downgrade() -> None:
    connection = op.get_bind()
    rehydrated_count = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM organization_data_restores "
            "WHERE create_count > 0"
        )
    )
    if rehydrated_count:
        raise RuntimeError(
            "Cannot downgrade while restore record rehydration evidence exists"
        )

    with op.batch_alter_table("organization_data_restores") as batch_op:
        batch_op.drop_constraint(
            "ck_organization_data_restore_create_count_non_negative",
            type_="check",
        )
        batch_op.drop_column("create_count")
