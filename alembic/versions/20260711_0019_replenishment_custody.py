"""add auditable replenishment custody and inventory movements

Revision ID: 20260711_0019
Revises: 20260711_0018
"""
from alembic import op
import sqlalchemy as sa


revision = "20260711_0019"
down_revision = "20260711_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # warehouse_type existed as a runtime compatibility column before it was
    # formally required by the custody workflow. Make Alembic head complete on
    # both fresh and previously started databases.
    warehouse_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("warehouses")}
    if "warehouse_type" not in warehouse_columns:
        with op.batch_alter_table("warehouses") as batch:
            batch.add_column(
                sa.Column("warehouse_type", sa.String(length=20), nullable=False, server_default="main")
            )
    else:
        op.execute("UPDATE warehouses SET warehouse_type = 'main' WHERE warehouse_type IS NULL")
        with op.batch_alter_table("warehouses") as batch:
            batch.alter_column(
                "warehouse_type",
                existing_type=sa.String(length=20),
                nullable=False,
                server_default="main",
            )
    op.execute(
        "UPDATE warehouses SET warehouse_type = 'van' "
        "WHERE assigned_user_id IN ("
        "SELECT id FROM users WHERE lower(CAST(role AS VARCHAR)) = 'engineer'"
        ")"
    )

    with op.batch_alter_table("inventory_transactions") as batch:
        batch.add_column(sa.Column("replenishment_request_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("movement_stage", sa.String(length=20), nullable=True))
        batch.create_foreign_key(
            "fk_inventory_transactions_replenishment_request_id",
            "replenishment_requests",
            ["replenishment_request_id"],
            ["id"],
        )
        batch.create_index("ix_inventory_transactions_replenishment_request_id", ["replenishment_request_id"])
        batch.create_unique_constraint(
            "uq_inventory_replenishment_stage",
            ["replenishment_request_id", "movement_stage"],
        )
        batch.create_check_constraint(
            "ck_inventory_replenishment_stage",
            "movement_stage IS NULL OR movement_stage IN ('ship', 'receive')",
        )
        batch.create_check_constraint(
            "ck_inventory_replenishment_link",
            "(replenishment_request_id IS NULL AND movement_stage IS NULL) OR "
            "(replenishment_request_id IS NOT NULL AND movement_stage IS NOT NULL)",
        )

    with op.batch_alter_table("replenishment_requests") as batch:
        batch.add_column(sa.Column("notification_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("client_request_id", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("request_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("target_user_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(
            sa.Column("requires_reconciliation", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("picking_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("picking_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("shipped_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("shipped_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("received_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("received_device_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("received_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("completed_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("completed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("cancelled_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("cancelled_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("cancellation_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("shipment_transaction_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("receipt_transaction_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_replenishment_notification_id", "inventory_notifications", ["notification_id"], ["id"])
        batch.create_foreign_key("fk_replenishment_target_user_id", "users", ["target_user_id"], ["id"])
        batch.create_foreign_key("fk_replenishment_picking_by", "users", ["picking_by"], ["id"])
        batch.create_foreign_key("fk_replenishment_shipped_by", "users", ["shipped_by"], ["id"])
        batch.create_foreign_key("fk_replenishment_received_by", "users", ["received_by"], ["id"])
        batch.create_foreign_key("fk_replenishment_received_device_id", "user_devices", ["received_device_id"], ["id"])
        batch.create_foreign_key("fk_replenishment_completed_by", "users", ["completed_by"], ["id"])
        batch.create_foreign_key("fk_replenishment_cancelled_by", "users", ["cancelled_by"], ["id"])
        batch.create_index("ix_replenishment_requests_target_user_id", ["target_user_id"])
        batch.create_index("ix_replenishment_org_status", ["organization_id", "status"])
        batch.create_index("ix_replenishment_org_target_status", ["organization_id", "target_user_id", "status"])
        batch.create_unique_constraint("uq_replenishment_notification_id", ["notification_id"])
        batch.create_unique_constraint(
            "uq_replenishment_org_client_request",
            ["organization_id", "client_request_id"],
        )
        batch.create_unique_constraint("uq_replenishment_shipment_transaction_id", ["shipment_transaction_id"])
        batch.create_unique_constraint("uq_replenishment_receipt_transaction_id", ["receipt_transaction_id"])
        batch.create_check_constraint("ck_replenishment_quantity_positive", "quantity > 0")
        batch.create_check_constraint("ck_replenishment_version_non_negative", "version >= 0")
        batch.create_check_constraint(
            "ck_replenishment_status",
            "status IN ('requested', 'picking', 'shipped', 'received', 'completed', 'cancelled')",
        )

    # Legacy intermediate statuses were labels only and had no trustworthy
    # inventory movements. Re-open them instead of fabricating custody history.
    op.execute(
        "UPDATE replenishment_requests SET requires_reconciliation = TRUE "
        "WHERE status IN ('picking', 'shipped', 'received', 'completed')"
    )
    op.execute(
        "UPDATE replenishment_requests SET status = 'requested', version = 0 "
        "WHERE status IN ('picking', 'shipped', 'received')"
    )
    # Existing open requests resolve their current destination owner only after
    # an administrator explicitly reconciles the legacy record and picking begins.


def downgrade() -> None:
    linked_movements = op.get_bind().execute(
        sa.text(
            "SELECT COUNT(*) FROM inventory_transactions "
            "WHERE replenishment_request_id IS NOT NULL"
        )
    ).scalar_one()
    if linked_movements:
        raise RuntimeError(
            "Cannot downgrade replenishment custody while linked inventory movements exist; "
            "export and reconcile custody history first"
        )

    with op.batch_alter_table("replenishment_requests") as batch:
        batch.drop_constraint("ck_replenishment_status", type_="check")
        batch.drop_constraint("ck_replenishment_version_non_negative", type_="check")
        batch.drop_constraint("ck_replenishment_quantity_positive", type_="check")
        batch.drop_constraint("uq_replenishment_receipt_transaction_id", type_="unique")
        batch.drop_constraint("uq_replenishment_shipment_transaction_id", type_="unique")
        batch.drop_constraint("uq_replenishment_org_client_request", type_="unique")
        batch.drop_constraint("uq_replenishment_notification_id", type_="unique")
        batch.drop_index("ix_replenishment_org_target_status")
        batch.drop_index("ix_replenishment_org_status")
        batch.drop_index("ix_replenishment_requests_target_user_id")
        batch.drop_constraint("fk_replenishment_cancelled_by", type_="foreignkey")
        batch.drop_constraint("fk_replenishment_completed_by", type_="foreignkey")
        batch.drop_constraint("fk_replenishment_received_device_id", type_="foreignkey")
        batch.drop_constraint("fk_replenishment_received_by", type_="foreignkey")
        batch.drop_constraint("fk_replenishment_shipped_by", type_="foreignkey")
        batch.drop_constraint("fk_replenishment_picking_by", type_="foreignkey")
        batch.drop_constraint("fk_replenishment_target_user_id", type_="foreignkey")
        batch.drop_constraint("fk_replenishment_notification_id", type_="foreignkey")
        batch.drop_column("receipt_transaction_id")
        batch.drop_column("shipment_transaction_id")
        batch.drop_column("cancellation_reason")
        batch.drop_column("cancelled_at")
        batch.drop_column("cancelled_by")
        batch.drop_column("completed_at")
        batch.drop_column("completed_by")
        batch.drop_column("received_at")
        batch.drop_column("received_device_id")
        batch.drop_column("received_by")
        batch.drop_column("shipped_at")
        batch.drop_column("shipped_by")
        batch.drop_column("picking_at")
        batch.drop_column("picking_by")
        batch.drop_column("version")
        batch.drop_column("requires_reconciliation")
        batch.drop_column("target_user_id")
        batch.drop_column("request_reason")
        batch.drop_column("client_request_id")
        batch.drop_column("notification_id")

    with op.batch_alter_table("inventory_transactions") as batch:
        batch.drop_constraint("ck_inventory_replenishment_link", type_="check")
        batch.drop_constraint("ck_inventory_replenishment_stage", type_="check")
        batch.drop_constraint("uq_inventory_replenishment_stage", type_="unique")
        batch.drop_index("ix_inventory_transactions_replenishment_request_id")
        batch.drop_constraint("fk_inventory_transactions_replenishment_request_id", type_="foreignkey")
        batch.drop_column("movement_stage")
        batch.drop_column("replenishment_request_id")
