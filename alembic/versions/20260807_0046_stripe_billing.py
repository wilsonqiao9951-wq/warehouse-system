"""add Stripe billing operations and provider evidence

Revision ID: 20260807_0046
Revises: 20260807_0045
Create Date: 2026-08-07
"""

from alembic import op
import sqlalchemy as sa


revision = "20260807_0046"
down_revision = "20260807_0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("organization_billing_accounts") as batch:
        batch.drop_constraint("ck_billing_account_provider_refs", type_="check")
        batch.drop_constraint("ck_billing_account_provider", type_="check")
        batch.create_check_constraint(
            "ck_billing_account_provider",
            "provider IN ('manual', 'generic', 'stripe')",
        )
        batch.create_check_constraint(
            "ck_billing_account_provider_refs",
            "(provider = 'manual' AND external_customer_id IS NULL "
            "AND external_subscription_id IS NULL) OR "
            "(provider = 'generic' AND external_customer_id IS NOT NULL "
            "AND external_subscription_id IS NOT NULL) OR "
            "(provider = 'stripe' AND (external_subscription_id IS NULL "
            "OR external_customer_id IS NOT NULL))",
        )

    with op.batch_alter_table("billing_lifecycle_events") as batch:
        batch.drop_constraint("ck_billing_event_provider", type_="check")
        batch.create_check_constraint(
            "ck_billing_event_provider",
            "provider IN ('generic', 'stripe')",
        )

    op.create_table(
        "stripe_billing_operations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("billing_account_id", sa.Integer(), nullable=True),
        sa.Column("requested_by", sa.Integer(), nullable=True),
        sa.Column("client_request_id", sa.String(length=100), nullable=False),
        sa.Column("operation_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("target_plan_code", sa.String(length=32), nullable=True),
        sa.Column("amount_minor", sa.Integer(), nullable=True),
        sa.Column("external_object_id", sa.String(length=200), nullable=True),
        sa.Column("external_request_id", sa.String(length=200), nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "operation_type IN ('checkout', 'portal', 'refund')",
            name="ck_stripe_billing_operation_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
            name="ck_stripe_billing_operation_status",
        ),
        sa.CheckConstraint(
            "target_plan_code IS NULL OR target_plan_code IN "
            "('starter', 'professional', 'enterprise')",
            name="ck_stripe_billing_operation_plan",
        ),
        sa.CheckConstraint(
            "amount_minor IS NULL OR amount_minor > 0",
            name="ck_stripe_billing_operation_amount_positive",
        ),
        sa.CheckConstraint(
            "length(request_sha256) = 64",
            name="ck_stripe_billing_operation_request_hash",
        ),
        sa.ForeignKeyConstraint(
            ["billing_account_id"], ["organization_billing_accounts.id"]
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "client_request_id",
            name="uq_stripe_billing_operation_org_request",
        ),
    )
    for column in ("id", "organization_id", "billing_account_id", "requested_by"):
        op.create_index(
            op.f(f"ix_stripe_billing_operations_{column}"),
            "stripe_billing_operations",
            [column],
        )
    op.create_index(
        "ix_stripe_billing_operation_org_created",
        "stripe_billing_operations",
        ["organization_id", "created_at"],
    )
    op.create_table(
        "stripe_webhook_receipts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("external_event_id", sa.String(length=200), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("processing_status", sa.String(length=20), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "processing_status IN ('bound', 'ignored')",
            name="ck_stripe_webhook_receipt_status",
        ),
        sa.CheckConstraint(
            "length(payload_sha256) = 64",
            name="ck_stripe_webhook_receipt_payload_hash",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "external_event_id", name="uq_stripe_webhook_receipt_event"
        ),
    )
    op.create_index(
        op.f("ix_stripe_webhook_receipts_id"),
        "stripe_webhook_receipts",
        ["id"],
    )
    op.create_index(
        op.f("ix_stripe_webhook_receipts_organization_id"),
        "stripe_webhook_receipts",
        ["organization_id"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    stripe_evidence = connection.scalar(
        sa.text(
            "SELECT "
            "(SELECT COUNT(*) FROM stripe_billing_operations) + "
            "(SELECT COUNT(*) FROM stripe_webhook_receipts) + "
            "(SELECT COUNT(*) FROM organization_billing_accounts "
            "WHERE provider = 'stripe') + "
            "(SELECT COUNT(*) FROM billing_lifecycle_events "
            "WHERE provider = 'stripe')"
        )
    )
    if stripe_evidence:
        raise RuntimeError("Cannot downgrade while Stripe billing evidence exists")

    op.drop_index(
        op.f("ix_stripe_webhook_receipts_organization_id"),
        table_name="stripe_webhook_receipts",
    )
    op.drop_index(
        op.f("ix_stripe_webhook_receipts_id"),
        table_name="stripe_webhook_receipts",
    )
    op.drop_table("stripe_webhook_receipts")

    op.drop_index(
        "ix_stripe_billing_operation_org_created",
        table_name="stripe_billing_operations",
    )
    for column in ("requested_by", "billing_account_id", "organization_id", "id"):
        op.drop_index(
            op.f(f"ix_stripe_billing_operations_{column}"),
            table_name="stripe_billing_operations",
        )
    op.drop_table("stripe_billing_operations")

    with op.batch_alter_table("billing_lifecycle_events") as batch:
        batch.drop_constraint("ck_billing_event_provider", type_="check")
        batch.create_check_constraint(
            "ck_billing_event_provider", "provider = 'generic'"
        )
    with op.batch_alter_table("organization_billing_accounts") as batch:
        batch.drop_constraint("ck_billing_account_provider_refs", type_="check")
        batch.drop_constraint("ck_billing_account_provider", type_="check")
        batch.create_check_constraint(
            "ck_billing_account_provider",
            "provider IN ('manual', 'generic')",
        )
        batch.create_check_constraint(
            "ck_billing_account_provider_refs",
            "(provider = 'manual' AND external_customer_id IS NULL "
            "AND external_subscription_id IS NULL) OR "
            "(provider = 'generic' AND external_customer_id IS NOT NULL "
            "AND external_subscription_id IS NOT NULL)",
        )
