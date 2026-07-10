"""add platform administrator flag

Revision ID: 20260710_0004
Revises: 20260709_0003
Create Date: 2026-07-10 00:05:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260710_0004"
down_revision: Union[str, None] = "20260709_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "is_platform_admin" not in columns:
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(
                sa.Column("is_platform_admin", sa.Boolean(), nullable=False, server_default=sa.false())
            )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "is_platform_admin" in columns:
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_column("is_platform_admin")
