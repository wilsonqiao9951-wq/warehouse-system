"""add user invitations

Revision ID: 20260710_0006
Revises: 20260710_0005
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20260710_0006"
down_revision: Union[str, None] = "20260710_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_invitations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("role", sa.Enum("ADMIN", "MANAGER", "WAREHOUSE", "ENGINEER", "ASSISTANT", name="userrole"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("invited_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_user_invitations_id", "user_invitations", ["id"])
    op.create_index("ix_user_invitations_organization_id", "user_invitations", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_user_invitations_organization_id", table_name="user_invitations")
    op.drop_index("ix_user_invitations_id", table_name="user_invitations")
    op.drop_table("user_invitations")
