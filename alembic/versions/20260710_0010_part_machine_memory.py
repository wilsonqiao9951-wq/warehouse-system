"""remember employee-confirmed parts by machine model

Revision ID: 20260710_0010
Revises: 20260710_0009
"""
from alembic import op
import sqlalchemy as sa

revision = "20260710_0010"
down_revision = "20260710_0009"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "part_machine_associations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("machine_model", sa.String(length=255), nullable=False),
        sa.Column("part_id", sa.Integer(), sa.ForeignKey("parts.id"), nullable=False),
        sa.Column("photo_url", sa.String(length=500), nullable=True),
        sa.Column("recognition_source", sa.String(length=40), nullable=False, server_default="employee_photo"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("confirmed_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_confirmed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "machine_model", "part_id", name="uq_part_machine_part"),
    )
    op.create_index("ix_part_machine_associations_id", "part_machine_associations", ["id"])
    op.create_index("ix_part_machine_associations_organization_id", "part_machine_associations", ["organization_id"])
    op.create_index("ix_part_machine_associations_machine_model", "part_machine_associations", ["machine_model"])
    op.create_index("ix_part_machine_associations_part_id", "part_machine_associations", ["part_id"])

def downgrade() -> None:
    op.drop_table("part_machine_associations")
