"""add outbound webhook delivery runtime

Revision ID: 20260729_0028
Revises: 20260728_0027
"""
from alembic import op
import sqlalchemy as sa


revision = "20260729_0028"
down_revision = "20260728_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("external_integrations") as batch_op:
        batch_op.add_column(
            sa.Column("webhook_url", sa.String(length=1000), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "subscribed_events_json",
                sa.Text(),
                nullable=False,
                server_default="[]",
            )
        )

    with op.batch_alter_table("external_sync_logs") as batch_op:
        batch_op.drop_constraint(
            "ck_external_sync_attempt_positive",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_external_sync_status",
            type_="check",
        )
        batch_op.add_column(sa.Column("payload_json", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("response_status_code", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("next_retry_at", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("last_attempt_at", sa.DateTime(), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_external_sync_attempt_non_negative",
            "attempt_count >= 0",
        )
        batch_op.create_check_constraint(
            "ck_external_sync_status",
            "status IN ('pending', 'processing', 'processed', 'failed')",
        )

    op.create_index(
        "ix_external_sync_due_delivery",
        "external_sync_logs",
        ["direction", "status", "next_retry_at"],
    )


def downgrade() -> None:
    op.execute(
        "UPDATE external_sync_logs "
        "SET status = 'failed', attempt_count = 1 "
        "WHERE status = 'pending' OR attempt_count < 1"
    )
    op.drop_index(
        "ix_external_sync_due_delivery",
        table_name="external_sync_logs",
    )
    with op.batch_alter_table("external_sync_logs") as batch_op:
        batch_op.drop_constraint(
            "ck_external_sync_attempt_non_negative",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_external_sync_status",
            type_="check",
        )
        batch_op.drop_column("last_attempt_at")
        batch_op.drop_column("next_retry_at")
        batch_op.drop_column("response_status_code")
        batch_op.drop_column("payload_json")
        batch_op.create_check_constraint(
            "ck_external_sync_attempt_positive",
            "attempt_count > 0",
        )
        batch_op.create_check_constraint(
            "ck_external_sync_status",
            "status IN ('processing', 'processed', 'failed')",
        )

    with op.batch_alter_table("external_integrations") as batch_op:
        batch_op.drop_column("subscribed_events_json")
        batch_op.drop_column("webhook_url")
