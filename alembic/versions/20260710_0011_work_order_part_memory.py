"""learn parts used on similar work orders

Revision ID: 20260710_0011
Revises: 20260710_0010
"""
from alembic import op
import sqlalchemy as sa

revision = "20260710_0011"
down_revision = "20260710_0010"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "work_order_part_memory",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("machine_type", sa.String(length=255), nullable=True),
        sa.Column("job_type", sa.String(length=120), nullable=True),
        sa.Column("part_id", sa.Integer(), sa.ForeignKey("parts.id"), nullable=False),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("total_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "machine_type", "job_type", "part_id", name="uq_work_order_part_memory"),
    )
    for name, column in [("id", "id"), ("organization_id", "organization_id"), ("machine_type", "machine_type"), ("job_type", "job_type"), ("part_id", "part_id")]:
        op.create_index(f"ix_work_order_part_memory_{name}", "work_order_part_memory", [column])

def downgrade() -> None:
    op.drop_table("work_order_part_memory")
