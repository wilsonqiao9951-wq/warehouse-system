"""add provider-neutral billing lifecycle evidence and notices

Revision ID: 20260806_0035
Revises: 20260806_0034
"""

from alembic import op
import sqlalchemy as sa


revision = "20260806_0035"
down_revision = "20260806_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization_billing_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("external_customer_id", sa.String(length=200), nullable=True),
        sa.Column("external_subscription_id", sa.String(length=200), nullable=True),
        sa.Column("current_period_start", sa.DateTime(), nullable=True),
        sa.Column("current_period_end", sa.DateTime(), nullable=True),
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("grace_ends_at", sa.DateTime(), nullable=True),
        sa.Column("last_event_at", sa.DateTime(), nullable=True),
        sa.Column("last_event_id", sa.String(length=200), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "provider IN ('manual', 'generic')",
            name="ck_billing_account_provider",
        ),
        sa.CheckConstraint(
            "(provider = 'manual' AND external_customer_id IS NULL "
            "AND external_subscription_id IS NULL) OR "
            "(provider = 'generic' AND external_customer_id IS NOT NULL "
            "AND external_subscription_id IS NOT NULL)",
            name="ck_billing_account_provider_refs",
        ),
        sa.CheckConstraint(
            "(current_period_start IS NULL AND current_period_end IS NULL) OR "
            "(current_period_start IS NOT NULL AND current_period_end IS NOT NULL "
            "AND current_period_end > current_period_start)",
            name="ck_billing_account_period",
        ),
        sa.CheckConstraint(
            "version >= 0",
            name="ck_billing_account_version_non_negative",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            name="uq_billing_account_org",
        ),
        sa.UniqueConstraint(
            "provider",
            "external_customer_id",
            name="uq_billing_account_provider_customer",
        ),
        sa.UniqueConstraint(
            "provider",
            "external_subscription_id",
            name="uq_billing_account_provider_subscription",
        ),
    )
    for column in ("id", "organization_id"):
        op.create_index(
            op.f(f"ix_organization_billing_accounts_{column}"),
            "organization_billing_accounts",
            [column],
        )

    op.create_table(
        "billing_lifecycle_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("billing_account_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("external_event_id", sa.String(length=200), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("processing_status", sa.String(length=30), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("before_subscription_status", sa.String(length=24), nullable=False),
        sa.Column("after_subscription_status", sa.String(length=24), nullable=False),
        sa.Column("before_plan_code", sa.String(length=32), nullable=False),
        sa.Column("after_plan_code", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "processing_status IN ('applied', 'ignored_stale')",
            name="ck_billing_event_processing_status",
        ),
        sa.CheckConstraint(
            "provider = 'generic'",
            name="ck_billing_event_provider",
        ),
        sa.CheckConstraint(
            "event_type IN ('trial.started', 'subscription.activated', "
            "'subscription.renewed', 'payment.failed', "
            "'subscription.cancellation_scheduled', "
            "'subscription.cancellation_reversed', "
            "'subscription.suspended', 'subscription.cancelled')",
            name="ck_billing_event_type",
        ),
        sa.CheckConstraint(
            "before_subscription_status IN ('trialing', 'active', 'past_due', "
            "'suspended', 'cancelled') AND "
            "after_subscription_status IN ('trialing', 'active', 'past_due', "
            "'suspended', 'cancelled')",
            name="ck_billing_event_subscription_statuses",
        ),
        sa.CheckConstraint(
            "before_plan_code IN ('starter', 'professional', 'enterprise') AND "
            "after_plan_code IN ('starter', 'professional', 'enterprise')",
            name="ck_billing_event_plan_codes",
        ),
        sa.CheckConstraint(
            "length(payload_sha256) = 64",
            name="ck_billing_event_payload_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["billing_account_id"],
            ["organization_billing_accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "external_event_id",
            name="uq_billing_event_provider_event",
        ),
    )
    for column in ("id", "organization_id", "billing_account_id"):
        op.create_index(
            op.f(f"ix_billing_lifecycle_events_{column}"),
            "billing_lifecycle_events",
            [column],
        )
    op.create_index(
        "ix_billing_event_org_occurred",
        "billing_lifecycle_events",
        ["organization_id", "occurred_at"],
    )

    op.create_table(
        "subscription_notices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("source_event_id", sa.Integer(), nullable=True),
        sa.Column("notice_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("effective_at", sa.DateTime(), nullable=False),
        sa.Column("acknowledged_by", sa.Integer(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "notice_type IN ('trial_ending', 'trial_expired', "
            "'renewal_upcoming', 'renewal_overdue', 'cancellation_scheduled', "
            "'payment_past_due', 'subscription_suspended', "
            "'subscription_cancelled')",
            name="ck_subscription_notice_type",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved')",
            name="ck_subscription_notice_status",
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'critical')",
            name="ck_subscription_notice_severity",
        ),
        sa.CheckConstraint(
            "version >= 0",
            name="ck_subscription_notice_version_non_negative",
        ),
        sa.ForeignKeyConstraint(["acknowledged_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_event_id"],
            ["billing_lifecycle_events.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "notice_type",
            "effective_at",
            name="uq_subscription_notice_milestone",
        ),
    )
    for column in ("id", "organization_id"):
        op.create_index(
            op.f(f"ix_subscription_notices_{column}"),
            "subscription_notices",
            [column],
        )
    op.create_index(
        "ix_subscription_notice_org_status_effective",
        "subscription_notices",
        ["organization_id", "status", "effective_at"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    evidence_count = connection.scalar(
        sa.text(
            "SELECT "
            "(SELECT COUNT(*) FROM organization_billing_accounts) + "
            "(SELECT COUNT(*) FROM billing_lifecycle_events) + "
            "(SELECT COUNT(*) FROM subscription_notices)"
        )
    )
    if evidence_count:
        raise RuntimeError(
            "Cannot downgrade while billing configuration or lifecycle evidence exists"
        )

    op.drop_index(
        "ix_subscription_notice_org_status_effective",
        table_name="subscription_notices",
    )
    for column in ("organization_id", "id"):
        op.drop_index(
            op.f(f"ix_subscription_notices_{column}"),
            table_name="subscription_notices",
        )
    op.drop_table("subscription_notices")

    op.drop_index(
        "ix_billing_event_org_occurred",
        table_name="billing_lifecycle_events",
    )
    for column in ("billing_account_id", "organization_id", "id"):
        op.drop_index(
            op.f(f"ix_billing_lifecycle_events_{column}"),
            table_name="billing_lifecycle_events",
        )
    op.drop_table("billing_lifecycle_events")

    for column in ("organization_id", "id"):
        op.drop_index(
            op.f(f"ix_organization_billing_accounts_{column}"),
            table_name="organization_billing_accounts",
        )
    op.drop_table("organization_billing_accounts")
