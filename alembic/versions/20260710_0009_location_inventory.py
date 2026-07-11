"""track inventory by storage location"""
from alembic import op
import sqlalchemy as sa

revision = "20260710_0009"
down_revision = "20260710_0008"
branch_labels = None
depends_on = None

def upgrade() -> None:
    with op.batch_alter_table("inventory_transactions") as batch:
        batch.add_column(sa.Column("from_location_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("to_location_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_inventory_transactions_from_location", "storage_locations", ["from_location_id"], ["id"])
        batch.create_foreign_key("fk_inventory_transactions_to_location", "storage_locations", ["to_location_id"], ["id"])

def downgrade() -> None:
    with op.batch_alter_table("inventory_transactions") as batch:
        batch.drop_constraint("fk_inventory_transactions_to_location", type_="foreignkey")
        batch.drop_constraint("fk_inventory_transactions_from_location", type_="foreignkey")
        batch.drop_column("to_location_id")
        batch.drop_column("from_location_id")
