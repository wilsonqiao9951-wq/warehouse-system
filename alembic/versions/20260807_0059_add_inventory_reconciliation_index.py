"""add inventory reconciliation queue index

Revision ID: 20260807_0059
Revises: 20260807_0058
Create Date: 2026-08-07
"""

from alembic import op


revision = "20260807_0059"
down_revision = "20260807_0058"
branch_labels = None
depends_on = None


INDEX_NAME = "ix_replenishment_org_reconcile_updated"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "replenishment_requests",
        ["organization_id", "requires_reconciliation", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="replenishment_requests")
