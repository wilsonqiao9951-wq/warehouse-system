"""formalize legacy operational tables

Revision ID: 20260807_0040
Revises: 20260807_0039
Create Date: 2026-08-07
"""

from alembic import op
import sqlalchemy as sa


revision = "20260807_0040"
down_revision = "20260807_0039"
branch_labels = None
depends_on = None


TABLES = (
    "audit_logs",
    "job_status",
    "qc_pictures",
    "return_equipments",
)

WORK_ORDER_COMPATIBILITY_COLUMNS = (
    "wo_number",
    "schedule_date",
    "outlet_name",
    "job_type",
    "description",
    "city",
    "state",
    "zip",
    "contact_phone",
)


def upgrade() -> None:
    with op.batch_alter_table("parts") as batch_op:
        batch_op.add_column(
            sa.Column("min_stock", sa.Integer(), server_default="0", nullable=False)
        )
    op.execute(
        "UPDATE parts SET min_stock = COALESCE(safety_stock, 0)"
    )

    with op.batch_alter_table("work_order_parts") as batch_op:
        batch_op.add_column(
            sa.Column("total_cost", sa.Float(), server_default="0", nullable=False)
        )
    op.execute(
        "UPDATE work_order_parts SET total_cost = COALESCE(quantity * unit_cost, 0)"
    )

    with op.batch_alter_table("work_orders") as batch_op:
        batch_op.add_column(sa.Column("wo_number", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("schedule_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("outlet_name", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("job_type", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("description", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("city", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("state", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("zip", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("contact_phone", sa.String(length=50), nullable=True))
        batch_op.create_unique_constraint(
            "uq_work_orders_wo_number",
            ["wo_number"],
        )
    op.execute(
        "UPDATE work_orders SET "
        "wo_number = COALESCE(wo_number, ticket_number), "
        "outlet_name = COALESCE(outlet_name, store_name), "
        "description = COALESCE(description, problem_description)"
    )

    op.create_table(
        "qc_pictures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id"),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "work_order_id",
            sa.Integer(),
            sa.ForeignKey("work_orders.id"),
            nullable=False,
        ),
        sa.Column("image_url", sa.String(length=500), nullable=False),
        sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_qc_pictures_id", "qc_pictures", ["id"])
    op.create_index(
        "ix_qc_pictures_organization_id",
        "qc_pictures",
        ["organization_id"],
    )

    op.create_table(
        "job_status",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id"),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "work_order_id",
            sa.Integer(),
            sa.ForeignKey("work_orders.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_job_status_id", "job_status", ["id"])
    op.create_index(
        "ix_job_status_organization_id",
        "job_status",
        ["organization_id"],
    )

    op.create_table(
        "return_equipments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id"),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "work_order_id",
            sa.Integer(),
            sa.ForeignKey("work_orders.id"),
            nullable=False,
        ),
        sa.Column("equipment_type", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_return_equipments_id", "return_equipments", ["id"])
    op.create_index(
        "ix_return_equipments_organization_id",
        "return_equipments",
        ["organization_id"],
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id"),
            nullable=False,
            server_default="1",
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("entity_type", sa.String(length=120), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_audit_logs_id", "audit_logs", ["id"])
    op.create_index(
        "ix_audit_logs_organization_id",
        "audit_logs",
        ["organization_id"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    populated = {
        table_name: connection.scalar(
            sa.text(f'SELECT COUNT(*) FROM "{table_name}"')
        )
        for table_name in TABLES
    }
    if any(populated.values()):
        summary = ", ".join(
            f"{table_name}={count}"
            for table_name, count in populated.items()
            if count
        )
        raise RuntimeError(
            "Cannot downgrade while operational history exists: " + summary
        )

    compatibility_data_count = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM work_orders WHERE "
            "schedule_date IS NOT NULL OR job_type IS NOT NULL OR city IS NOT NULL "
            "OR state IS NOT NULL OR zip IS NOT NULL OR contact_phone IS NOT NULL "
            "OR (wo_number IS NOT NULL AND wo_number != ticket_number) "
            "OR (outlet_name IS NOT NULL AND outlet_name != COALESCE(store_name, '')) "
            "OR (description IS NOT NULL "
            "AND description != COALESCE(problem_description, ''))"
        )
    )
    custom_threshold_count = connection.scalar(
        sa.text(
            "SELECT (SELECT COUNT(*) FROM parts "
            "WHERE min_stock != COALESCE(safety_stock, 0)) + "
            "(SELECT COUNT(*) FROM work_order_parts "
            "WHERE total_cost != COALESCE(quantity * unit_cost, 0))"
        )
    )
    if compatibility_data_count or custom_threshold_count:
        raise RuntimeError(
            "Cannot downgrade while compatibility fields contain independent data"
        )

    op.drop_index("ix_audit_logs_organization_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_id", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index(
        "ix_return_equipments_organization_id",
        table_name="return_equipments",
    )
    op.drop_index("ix_return_equipments_id", table_name="return_equipments")
    op.drop_table("return_equipments")
    op.drop_index("ix_job_status_organization_id", table_name="job_status")
    op.drop_index("ix_job_status_id", table_name="job_status")
    op.drop_table("job_status")
    op.drop_index("ix_qc_pictures_organization_id", table_name="qc_pictures")
    op.drop_index("ix_qc_pictures_id", table_name="qc_pictures")
    op.drop_table("qc_pictures")

    with op.batch_alter_table("work_orders") as batch_op:
        batch_op.drop_constraint("uq_work_orders_wo_number", type_="unique")
        for column_name in reversed(WORK_ORDER_COMPATIBILITY_COLUMNS):
            batch_op.drop_column(column_name)
    with op.batch_alter_table("work_order_parts") as batch_op:
        batch_op.drop_column("total_cost")
    with op.batch_alter_table("parts") as batch_op:
        batch_op.drop_column("min_stock")
