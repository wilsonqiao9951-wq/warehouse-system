"""add configurable work order completion policies

Revision ID: 20260711_0017
Revises: 20260711_0016
"""
from alembic import op
import sqlalchemy as sa

revision = "20260711_0017"
down_revision = "20260711_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "completion_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("job_type_key", sa.String(length=120), nullable=False, server_default="*"),
        sa.Column("require_repair_result", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("require_customer_signature", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("require_completion_photo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("require_all_checklist_items", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("require_parts_usage", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("require_manager_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "job_type_key", name="uq_completion_policy_org_job_type"),
    )
    op.create_index("ix_completion_policies_organization_id", "completion_policies", ["organization_id"])
    with op.batch_alter_table("work_orders") as batch:
        batch.add_column(sa.Column("completion_requested_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("completion_requested_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("completion_approved_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("completion_approved_at", sa.DateTime(), nullable=True))
        batch.create_foreign_key("fk_work_orders_completion_requested_by", "users", ["completion_requested_by"], ["id"])
        batch.create_foreign_key("fk_work_orders_completion_approved_by", "users", ["completion_approved_by"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("work_orders") as batch:
        batch.drop_constraint("fk_work_orders_completion_approved_by", type_="foreignkey")
        batch.drop_constraint("fk_work_orders_completion_requested_by", type_="foreignkey")
        batch.drop_column("completion_approved_at")
        batch.drop_column("completion_approved_by")
        batch.drop_column("completion_requested_at")
        batch.drop_column("completion_requested_by")
    op.drop_table("completion_policies")
