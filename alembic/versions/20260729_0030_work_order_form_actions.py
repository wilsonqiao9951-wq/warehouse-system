"""add durable work-order form notification and inventory-review actions

Revision ID: 20260729_0030
Revises: 20260729_0029
"""
from alembic import op
import sqlalchemy as sa


revision = "20260729_0030"
down_revision = "20260729_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "work_order_form_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("work_order_id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=True),
        sa.Column("field_key", sa.String(length=64), nullable=False),
        sa.Column("field_label", sa.String(length=160), nullable=False),
        sa.Column("action_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("triggered_form_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("acknowledged_by", sa.Integer(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "action_type IN ('notification', 'inventory_review')",
            name="ck_work_order_form_action_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'acknowledged', 'resolved')",
            name="ck_work_order_form_action_status",
        ),
        sa.CheckConstraint(
            "triggered_form_version >= 1",
            name="ck_work_order_form_action_trigger_version_positive",
        ),
        sa.CheckConstraint(
            "version >= 0",
            name="ck_work_order_form_action_version_non_negative",
        ),
        sa.ForeignKeyConstraint(["acknowledged_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["work_order_form_templates.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["work_order_id"],
            ["work_orders.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "work_order_id",
            "triggered_form_version",
            "field_key",
            "action_type",
            name="uq_work_order_form_action_trigger",
        ),
    )
    for column in (
        "id",
        "organization_id",
        "work_order_id",
        "template_id",
        "action_type",
        "status",
    ):
        op.create_index(
            op.f(f"ix_work_order_form_actions_{column}"),
            "work_order_form_actions",
            [column],
        )
    op.create_index(
        "ix_work_order_form_actions_org_status_type",
        "work_order_form_actions",
        ["organization_id", "status", "action_type"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    action_count = connection.scalar(
        sa.text("SELECT COUNT(*) FROM work_order_form_actions")
    )
    if action_count:
        raise RuntimeError(
            "Cannot downgrade while configured-form action evidence exists"
        )
    op.drop_index(
        "ix_work_order_form_actions_org_status_type",
        table_name="work_order_form_actions",
    )
    for column in (
        "status",
        "action_type",
        "template_id",
        "work_order_id",
        "organization_id",
        "id",
    ):
        op.drop_index(
            op.f(f"ix_work_order_form_actions_{column}"),
            table_name="work_order_form_actions",
        )
    op.drop_table("work_order_form_actions")
