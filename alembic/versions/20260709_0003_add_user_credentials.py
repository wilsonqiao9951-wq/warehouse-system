"""add user credentials

Revision ID: 20260709_0003
Revises: 20260709_0002
Create Date: 2026-07-09 23:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260709_0003"
down_revision: Union[str, None] = "20260709_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    with op.batch_alter_table("users") as batch_op:
        if "password_hash" not in columns:
            batch_op.add_column(sa.Column("password_hash", sa.String(length=255), nullable=True))
        if "is_active" not in columns:
            batch_op.add_column(sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    with op.batch_alter_table("users") as batch_op:
        if "is_active" in columns:
            batch_op.drop_column("is_active")
        if "password_hash" in columns:
            batch_op.drop_column("password_hash")
