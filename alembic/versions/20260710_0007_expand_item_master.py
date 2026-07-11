"""expand generic item master

Revision ID: 20260710_0007
Revises: 20260710_0006
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20260710_0007"
down_revision: Union[str, None] = "20260710_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("parts") as batch_op:
        batch_op.add_column(sa.Column("category", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("barcode", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("item_type", sa.String(length=50), nullable=False, server_default="stock"))
        batch_op.add_column(sa.Column("tracking_mode", sa.String(length=20), nullable=False, server_default="none"))
        batch_op.add_column(sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("custom_fields", sa.JSON(), nullable=False, server_default="{}"))
        batch_op.create_unique_constraint("uq_parts_org_barcode", ["organization_id", "barcode"])


def downgrade() -> None:
    with op.batch_alter_table("parts") as batch_op:
        batch_op.drop_constraint("uq_parts_org_barcode", type_="unique")
        batch_op.drop_column("custom_fields")
        batch_op.drop_column("is_active")
        batch_op.drop_column("tracking_mode")
        batch_op.drop_column("item_type")
        batch_op.drop_column("barcode")
        batch_op.drop_column("category")
