"""add external integration keys, work-order links, and sync logs

Revision ID: 20260728_0027
Revises: 20260728_0026
"""
from alembic import op
import sqlalchemy as sa


revision = "20260728_0027"
down_revision = "20260728_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_integrations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("key_prefix", sa.String(length=24), nullable=False),
        sa.Column("api_key_hash", sa.String(length=64), nullable=False),
        sa.Column("field_mapping_json", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "provider IN ('appsheet', 'generic', 'google_sheets', 'crm', 'erp', 'wms')",
            name="ck_external_integration_provider",
        ),
        sa.CheckConstraint(
            "version >= 0",
            name="ck_external_integration_version_non_negative",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "api_key_hash",
            name="uq_external_integration_api_key_hash",
        ),
        sa.UniqueConstraint(
            "key_prefix",
            name="uq_external_integration_key_prefix",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "name",
            name="uq_external_integration_org_name",
        ),
    )
    op.create_index(
        op.f("ix_external_integrations_id"),
        "external_integrations",
        ["id"],
    )
    op.create_index(
        op.f("ix_external_integrations_organization_id"),
        "external_integrations",
        ["organization_id"],
    )
    op.create_index(
        op.f("ix_external_integrations_provider"),
        "external_integrations",
        ["provider"],
    )

    op.create_table(
        "external_work_order_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("work_order_id", sa.Integer(), nullable=False),
        sa.Column("last_inbound_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["integration_id"],
            ["external_integrations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["work_order_id"],
            ["work_orders.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "integration_id",
            "external_id",
            name="uq_external_work_order_integration_external",
        ),
        sa.UniqueConstraint(
            "integration_id",
            "work_order_id",
            name="uq_external_work_order_integration_work_order",
        ),
    )
    op.create_index(
        op.f("ix_external_work_order_links_id"),
        "external_work_order_links",
        ["id"],
    )
    op.create_index(
        op.f("ix_external_work_order_links_integration_id"),
        "external_work_order_links",
        ["integration_id"],
    )
    op.create_index(
        op.f("ix_external_work_order_links_organization_id"),
        "external_work_order_links",
        ["organization_id"],
    )
    op.create_index(
        op.f("ix_external_work_order_links_work_order_id"),
        "external_work_order_links",
        ["work_order_id"],
    )

    op.create_table(
        "external_sync_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("work_order_id", sa.Integer(), nullable=True),
        sa.Column("changed_fields_json", sa.Text(), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "attempt_count > 0",
            name="ck_external_sync_attempt_positive",
        ),
        sa.CheckConstraint(
            "direction IN ('inbound', 'outbound')",
            name="ck_external_sync_direction",
        ),
        sa.CheckConstraint(
            "status IN ('processing', 'processed', 'failed')",
            name="ck_external_sync_status",
        ),
        sa.ForeignKeyConstraint(
            ["integration_id"],
            ["external_integrations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["work_order_id"],
            ["work_orders.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "integration_id",
            "idempotency_key",
            name="uq_external_sync_integration_idempotency",
        ),
    )
    op.create_index(
        op.f("ix_external_sync_logs_event_type"),
        "external_sync_logs",
        ["event_type"],
    )
    op.create_index(
        op.f("ix_external_sync_logs_external_id"),
        "external_sync_logs",
        ["external_id"],
    )
    op.create_index(
        op.f("ix_external_sync_logs_id"),
        "external_sync_logs",
        ["id"],
    )
    op.create_index(
        op.f("ix_external_sync_logs_integration_id"),
        "external_sync_logs",
        ["integration_id"],
    )
    op.create_index(
        op.f("ix_external_sync_logs_organization_id"),
        "external_sync_logs",
        ["organization_id"],
    )
    op.create_index(
        op.f("ix_external_sync_logs_status"),
        "external_sync_logs",
        ["status"],
    )
    op.create_index(
        op.f("ix_external_sync_logs_work_order_id"),
        "external_sync_logs",
        ["work_order_id"],
    )
    op.create_index(
        "ix_external_sync_org_integration_created",
        "external_sync_logs",
        ["organization_id", "integration_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_external_sync_org_integration_created",
        table_name="external_sync_logs",
    )
    op.drop_index(
        op.f("ix_external_sync_logs_work_order_id"),
        table_name="external_sync_logs",
    )
    op.drop_index(
        op.f("ix_external_sync_logs_status"),
        table_name="external_sync_logs",
    )
    op.drop_index(
        op.f("ix_external_sync_logs_organization_id"),
        table_name="external_sync_logs",
    )
    op.drop_index(
        op.f("ix_external_sync_logs_integration_id"),
        table_name="external_sync_logs",
    )
    op.drop_index(
        op.f("ix_external_sync_logs_id"),
        table_name="external_sync_logs",
    )
    op.drop_index(
        op.f("ix_external_sync_logs_external_id"),
        table_name="external_sync_logs",
    )
    op.drop_index(
        op.f("ix_external_sync_logs_event_type"),
        table_name="external_sync_logs",
    )
    op.drop_table("external_sync_logs")
    op.drop_index(
        op.f("ix_external_work_order_links_work_order_id"),
        table_name="external_work_order_links",
    )
    op.drop_index(
        op.f("ix_external_work_order_links_organization_id"),
        table_name="external_work_order_links",
    )
    op.drop_index(
        op.f("ix_external_work_order_links_integration_id"),
        table_name="external_work_order_links",
    )
    op.drop_index(
        op.f("ix_external_work_order_links_id"),
        table_name="external_work_order_links",
    )
    op.drop_table("external_work_order_links")
    op.drop_index(
        op.f("ix_external_integrations_provider"),
        table_name="external_integrations",
    )
    op.drop_index(
        op.f("ix_external_integrations_organization_id"),
        table_name="external_integrations",
    )
    op.drop_index(
        op.f("ix_external_integrations_id"),
        table_name="external_integrations",
    )
    op.drop_table("external_integrations")
