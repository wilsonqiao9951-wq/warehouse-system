"""add audit log query indexes

Revision ID: 20260807_0041
Revises: 20260807_0040
Create Date: 2026-08-07
"""

from alembic import op


revision = "20260807_0041"
down_revision = "20260807_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_audit_logs_org_timestamp",
        "audit_logs",
        ["organization_id", "timestamp"],
    )
    op.create_index(
        "ix_audit_logs_org_action_timestamp",
        "audit_logs",
        ["organization_id", "action", "timestamp"],
    )
    op.create_index(
        "ix_audit_logs_org_entity",
        "audit_logs",
        ["organization_id", "entity_type", "entity_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_org_entity", table_name="audit_logs")
    op.drop_index("ix_audit_logs_org_action_timestamp", table_name="audit_logs")
    op.drop_index("ix_audit_logs_org_timestamp", table_name="audit_logs")
