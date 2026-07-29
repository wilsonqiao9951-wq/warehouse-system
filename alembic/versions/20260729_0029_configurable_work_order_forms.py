"""add configurable work-order form templates and immutable job snapshots

Revision ID: 20260729_0029
Revises: 20260729_0028
"""
from alembic import op
import sqlalchemy as sa


revision = "20260729_0029"
down_revision = "20260729_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "work_order_form_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("industry", sa.String(length=80), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("applicable_machine_type", sa.String(length=255), nullable=True),
        sa.Column("applicable_job_type", sa.String(length=120), nullable=True),
        sa.Column(
            "default_work_order_status",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "default_work_order_status IN ('open', 'scheduled')",
            name="ck_work_order_form_template_default_status",
        ),
        sa.CheckConstraint(
            "version >= 0",
            name="ck_work_order_form_template_version_non_negative",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "name",
            name="uq_work_order_form_template_org_name",
        ),
    )
    for column in (
        "id",
        "organization_id",
        "industry",
        "applicable_machine_type",
        "applicable_job_type",
    ):
        op.create_index(
            op.f(f"ix_work_order_form_templates_{column}"),
            "work_order_form_templates",
            [column],
        )

    op.create_table(
        "work_order_form_fields",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("field_key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("field_type", sa.String(length=20), nullable=False),
        sa.Column("help_text", sa.String(length=1000), nullable=True),
        sa.Column("placeholder", sa.String(length=500), nullable=True),
        sa.Column("default_value_json", sa.Text(), nullable=True),
        sa.Column("options_json", sa.Text(), nullable=False),
        sa.Column("required_at_completion", sa.Boolean(), nullable=False),
        sa.Column("requires_photo", sa.Boolean(), nullable=False),
        sa.Column("requires_signature", sa.Boolean(), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("triggers_notification", sa.Boolean(), nullable=False),
        sa.Column("affects_inventory", sa.Boolean(), nullable=False),
        sa.Column("include_in_ai_learning", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "field_type IN ('text', 'textarea', 'number', 'boolean', 'date', "
            "'select', 'photo', 'signature')",
            name="ck_work_order_form_field_type",
        ),
        sa.CheckConstraint(
            "sort_order >= 0",
            name="ck_work_order_form_field_sort_non_negative",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["work_order_form_templates.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "template_id",
            "field_key",
            name="uq_work_order_form_field_template_key",
        ),
    )
    for column in ("id", "organization_id", "template_id"):
        op.create_index(
            op.f(f"ix_work_order_form_fields_{column}"),
            "work_order_form_fields",
            [column],
        )

    with op.batch_alter_table("work_orders") as batch_op:
        batch_op.add_column(
            sa.Column("form_template_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("form_template_version", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "form_version",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column("form_schema_json", sa.Text(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "form_data_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            )
        )
        batch_op.create_foreign_key(
            "fk_work_orders_form_template_id",
            "work_order_form_templates",
            ["form_template_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_check_constraint(
            "ck_work_order_form_version_non_negative",
            "form_version >= 0",
        )
        batch_op.create_check_constraint(
            "ck_work_order_form_template_version_non_negative",
            "form_template_version IS NULL OR form_template_version >= 0",
        )
        batch_op.create_index(
            op.f("ix_work_orders_form_template_id"),
            ["form_template_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("work_orders") as batch_op:
        batch_op.drop_index(op.f("ix_work_orders_form_template_id"))
        batch_op.drop_constraint(
            "ck_work_order_form_template_version_non_negative",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_work_order_form_version_non_negative",
            type_="check",
        )
        batch_op.drop_constraint(
            "fk_work_orders_form_template_id",
            type_="foreignkey",
        )
        batch_op.drop_column("form_data_json")
        batch_op.drop_column("form_schema_json")
        batch_op.drop_column("form_version")
        batch_op.drop_column("form_template_version")
        batch_op.drop_column("form_template_id")

    for column in ("template_id", "organization_id", "id"):
        op.drop_index(
            op.f(f"ix_work_order_form_fields_{column}"),
            table_name="work_order_form_fields",
        )
    op.drop_table("work_order_form_fields")
    for column in (
        "applicable_job_type",
        "applicable_machine_type",
        "industry",
        "organization_id",
        "id",
    ):
        op.drop_index(
            op.f(f"ix_work_order_form_templates_{column}"),
            table_name="work_order_form_templates",
        )
    op.drop_table("work_order_form_templates")
