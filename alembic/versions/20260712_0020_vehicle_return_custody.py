"""add authenticated vehicle return custody

Revision ID: 20260712_0020
Revises: 20260711_0019
"""
from alembic import op
import sqlalchemy as sa


revision = "20260712_0020"
down_revision = "20260711_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vehicle_return_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("client_request_id", sa.String(length=100), nullable=False),
        sa.Column("part_id", sa.Integer(), sa.ForeignKey("parts.id"), nullable=False),
        sa.Column("source_warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("destination_warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("engineer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="requested"),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("requested_device_id", sa.Integer(), sa.ForeignKey("user_devices.id"), nullable=False),
        sa.Column("requested_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("shipped_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("shipped_device_id", sa.Integer(), sa.ForeignKey("user_devices.id"), nullable=True),
        sa.Column("shipped_at", sa.DateTime(), nullable=True),
        sa.Column("received_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("shipment_transaction_id", sa.Integer(), nullable=True),
        sa.Column("receipt_transaction_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("organization_id", "client_request_id", name="uq_vehicle_return_org_client_request"),
        sa.UniqueConstraint("shipment_transaction_id", name="uq_vehicle_return_shipment_transaction_id"),
        sa.UniqueConstraint("receipt_transaction_id", name="uq_vehicle_return_receipt_transaction_id"),
        sa.CheckConstraint("quantity > 0", name="ck_vehicle_return_quantity_positive"),
        sa.CheckConstraint("version >= 0", name="ck_vehicle_return_version_non_negative"),
        sa.CheckConstraint(
            "status IN ('requested', 'approved', 'shipped', 'received', 'cancelled')",
            name="ck_vehicle_return_status",
        ),
    )
    op.create_index("ix_vehicle_return_requests_id", "vehicle_return_requests", ["id"])
    op.create_index("ix_vehicle_return_requests_organization_id", "vehicle_return_requests", ["organization_id"])
    op.create_index("ix_vehicle_return_requests_engineer_id", "vehicle_return_requests", ["engineer_id"])
    op.create_index("ix_vehicle_return_org_status", "vehicle_return_requests", ["organization_id", "status"])
    op.create_index(
        "ix_vehicle_return_org_engineer_status",
        "vehicle_return_requests",
        ["organization_id", "engineer_id", "status"],
    )

    with op.batch_alter_table("inventory_transactions") as batch:
        batch.drop_constraint("ck_inventory_replenishment_link", type_="check")
        batch.drop_constraint("ck_inventory_replenishment_stage", type_="check")
        batch.add_column(sa.Column("vehicle_return_request_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_inventory_transactions_vehicle_return_request_id",
            "vehicle_return_requests",
            ["vehicle_return_request_id"],
            ["id"],
        )
        batch.create_index("ix_inventory_transactions_vehicle_return_request_id", ["vehicle_return_request_id"])
        batch.create_unique_constraint(
            "uq_inventory_vehicle_return_stage",
            ["vehicle_return_request_id", "movement_stage"],
        )
        batch.create_check_constraint(
            "ck_inventory_replenishment_stage",
            "movement_stage IS NULL OR movement_stage IN "
            "('ship', 'receive', 'return_ship', 'return_receive')",
        )
        batch.create_check_constraint(
            "ck_inventory_replenishment_link",
            "(replenishment_request_id IS NULL AND vehicle_return_request_id IS NULL AND movement_stage IS NULL) OR "
            "(replenishment_request_id IS NOT NULL AND vehicle_return_request_id IS NULL "
            "AND movement_stage IN ('ship', 'receive')) OR "
            "(replenishment_request_id IS NULL AND vehicle_return_request_id IS NOT NULL "
            "AND movement_stage IN ('return_ship', 'return_receive'))",
        )


def downgrade() -> None:
    linked_movements = op.get_bind().execute(
        sa.text(
            "SELECT COUNT(*) FROM inventory_transactions "
            "WHERE vehicle_return_request_id IS NOT NULL"
        )
    ).scalar_one()
    if linked_movements:
        raise RuntimeError(
            "Cannot downgrade vehicle return custody while linked inventory movements exist; "
            "export and reconcile return history first"
        )

    with op.batch_alter_table("inventory_transactions") as batch:
        batch.drop_constraint("ck_inventory_replenishment_link", type_="check")
        batch.drop_constraint("ck_inventory_replenishment_stage", type_="check")
        batch.drop_constraint("uq_inventory_vehicle_return_stage", type_="unique")
        batch.drop_index("ix_inventory_transactions_vehicle_return_request_id")
        batch.drop_constraint("fk_inventory_transactions_vehicle_return_request_id", type_="foreignkey")
        batch.drop_column("vehicle_return_request_id")
        batch.create_check_constraint(
            "ck_inventory_replenishment_stage",
            "movement_stage IS NULL OR movement_stage IN ('ship', 'receive')",
        )
        batch.create_check_constraint(
            "ck_inventory_replenishment_link",
            "(replenishment_request_id IS NULL AND movement_stage IS NULL) OR "
            "(replenishment_request_id IS NOT NULL AND movement_stage IS NOT NULL)",
        )

    op.drop_index("ix_vehicle_return_org_engineer_status", table_name="vehicle_return_requests")
    op.drop_index("ix_vehicle_return_org_status", table_name="vehicle_return_requests")
    op.drop_index("ix_vehicle_return_requests_engineer_id", table_name="vehicle_return_requests")
    op.drop_index("ix_vehicle_return_requests_organization_id", table_name="vehicle_return_requests")
    op.drop_index("ix_vehicle_return_requests_id", table_name="vehicle_return_requests")
    op.drop_table("vehicle_return_requests")
