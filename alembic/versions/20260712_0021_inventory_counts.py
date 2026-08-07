"""add auditable inventory counts

Revision ID: 20260712_0021
Revises: 20260712_0020
"""
from alembic import op
import sqlalchemy as sa


revision = "20260712_0021"
down_revision = "20260712_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_count_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("client_request_id", sa.String(length=100), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("storage_locations.id"), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("organization_id", "client_request_id", name="uq_inventory_count_org_client_request"),
        sa.CheckConstraint("version >= 0", name="ck_inventory_count_version_non_negative"),
        sa.CheckConstraint("status IN ('draft', 'submitted', 'approved', 'cancelled')", name="ck_inventory_count_status"),
    )
    op.create_index("ix_inventory_count_sessions_id", "inventory_count_sessions", ["id"])
    op.create_index("ix_inventory_count_sessions_organization_id", "inventory_count_sessions", ["organization_id"])
    op.create_index("ix_inventory_count_sessions_warehouse_id", "inventory_count_sessions", ["warehouse_id"])
    op.create_index("ix_inventory_count_sessions_location_id", "inventory_count_sessions", ["location_id"])
    op.create_index("ix_inventory_count_org_status", "inventory_count_sessions", ["organization_id", "status"])

    op.create_table(
        "inventory_count_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("inventory_count_sessions.id"), nullable=False),
        sa.Column("part_id", sa.Integer(), sa.ForeignKey("parts.id"), nullable=False),
        sa.Column("counted_quantity", sa.Integer(), nullable=False),
        sa.Column("submitted_book_quantity", sa.Integer(), nullable=True),
        sa.Column("approved_book_quantity", sa.Integer(), nullable=True),
        sa.Column("variance_quantity", sa.Integer(), nullable=True),
        sa.Column("counted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("counted_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("adjustment_transaction_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("session_id", "part_id", name="uq_inventory_count_session_part"),
        sa.UniqueConstraint("adjustment_transaction_id", name="uq_inventory_count_adjustment_transaction"),
        sa.CheckConstraint("counted_quantity >= 0", name="ck_inventory_count_line_quantity_non_negative"),
    )
    op.create_index("ix_inventory_count_lines_id", "inventory_count_lines", ["id"])
    op.create_index("ix_inventory_count_lines_organization_id", "inventory_count_lines", ["organization_id"])
    op.create_index("ix_inventory_count_lines_session_id", "inventory_count_lines", ["session_id"])
    op.create_index("ix_inventory_count_lines_part_id", "inventory_count_lines", ["part_id"])

    with op.batch_alter_table("inventory_transactions") as batch:
        batch.add_column(sa.Column("inventory_count_line_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_inventory_transactions_inventory_count_line_id", "inventory_count_lines",
            ["inventory_count_line_id"], ["id"],
        )
        batch.create_index("ix_inventory_transactions_inventory_count_line_id", ["inventory_count_line_id"], unique=True)


def downgrade() -> None:
    linked = op.get_bind().execute(sa.text(
        "SELECT COUNT(*) FROM inventory_transactions WHERE inventory_count_line_id IS NOT NULL"
    )).scalar_one()
    if linked:
        raise RuntimeError("Cannot downgrade inventory counts while approved adjustment movements exist")
    with op.batch_alter_table("inventory_transactions") as batch:
        batch.drop_index("ix_inventory_transactions_inventory_count_line_id")
        batch.drop_constraint("fk_inventory_transactions_inventory_count_line_id", type_="foreignkey")
        batch.drop_column("inventory_count_line_id")
    op.drop_index("ix_inventory_count_lines_part_id", table_name="inventory_count_lines")
    op.drop_index("ix_inventory_count_lines_session_id", table_name="inventory_count_lines")
    op.drop_index("ix_inventory_count_lines_organization_id", table_name="inventory_count_lines")
    op.drop_index("ix_inventory_count_lines_id", table_name="inventory_count_lines")
    op.drop_table("inventory_count_lines")
    op.drop_index("ix_inventory_count_org_status", table_name="inventory_count_sessions")
    op.drop_index("ix_inventory_count_sessions_location_id", table_name="inventory_count_sessions")
    op.drop_index("ix_inventory_count_sessions_warehouse_id", table_name="inventory_count_sessions")
    op.drop_index("ix_inventory_count_sessions_organization_id", table_name="inventory_count_sessions")
    op.drop_index("ix_inventory_count_sessions_id", table_name="inventory_count_sessions")
    op.drop_table("inventory_count_sessions")
