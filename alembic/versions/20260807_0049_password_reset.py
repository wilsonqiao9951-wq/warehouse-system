"""add single-use password reset delivery evidence

Revision ID: 20260807_0049
Revises: 20260807_0048
Create Date: 2026-08-07
"""

from alembic import op
import sqlalchemy as sa


revision = "20260807_0049"
down_revision = "20260807_0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("auth_security_events") as batch:
        batch.drop_constraint("ck_auth_security_events_type", type_="check")
        batch.drop_constraint("ck_auth_security_events_outcome", type_="check")
        batch.create_check_constraint(
            "ck_auth_security_events_type",
            "event_type IN ('login', 'session_revocation', 'password_reset')",
        )
        batch.create_check_constraint(
            "ck_auth_security_events_outcome",
            "outcome IN ('success', 'invalid_credentials', 'rate_limited', "
            "'subscription_denied', 'device_rejected', 'sessions_revoked', "
            "'reset_requested', 'reset_request_ignored', 'reset_delivered', "
            "'reset_delivery_failed', 'reset_completed', 'reset_rejected')",
        )

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("principal_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("delivery_status", sa.String(length=20), nullable=False),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(), nullable=True),
        sa.Column("delivery_attempted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "delivery_status IN ('manual', 'pending', 'sent', 'failed')",
            name="ck_password_reset_tokens_delivery_status",
        ),
        sa.CheckConstraint(
            "length(token_hash) = 64 AND length(principal_fingerprint) = 64 "
            "AND length(source_fingerprint) = 64",
            name="ck_password_reset_tokens_hashes",
        ),
        sa.CheckConstraint(
            "used_at IS NULL OR invalidated_at IS NULL",
            name="ck_password_reset_tokens_terminal_state",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    for column in ("id", "organization_id", "user_id"):
        op.create_index(
            op.f(f"ix_password_reset_tokens_{column}"),
            "password_reset_tokens",
            [column],
        )
    op.create_index(
        "ix_password_reset_tokens_org_created",
        "password_reset_tokens",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "ix_password_reset_tokens_user_active",
        "password_reset_tokens",
        ["user_id", "expires_at"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    reset_rows = connection.scalar(sa.text("SELECT COUNT(*) FROM password_reset_tokens"))
    reset_events = connection.scalar(
        sa.text("SELECT COUNT(*) FROM auth_security_events WHERE event_type = 'password_reset'")
    )
    if reset_rows or reset_events:
        raise RuntimeError(
            "Cannot downgrade while password reset or delivery evidence exists"
        )

    op.drop_index(
        "ix_password_reset_tokens_user_active",
        table_name="password_reset_tokens",
    )
    op.drop_index(
        "ix_password_reset_tokens_org_created",
        table_name="password_reset_tokens",
    )
    for column in ("user_id", "organization_id", "id"):
        op.drop_index(
            op.f(f"ix_password_reset_tokens_{column}"),
            table_name="password_reset_tokens",
        )
    op.drop_table("password_reset_tokens")

    with op.batch_alter_table("auth_security_events") as batch:
        batch.drop_constraint("ck_auth_security_events_outcome", type_="check")
        batch.drop_constraint("ck_auth_security_events_type", type_="check")
        batch.create_check_constraint(
            "ck_auth_security_events_type",
            "event_type IN ('login', 'session_revocation')",
        )
        batch.create_check_constraint(
            "ck_auth_security_events_outcome",
            "outcome IN ('success', 'invalid_credentials', 'rate_limited', "
            "'subscription_denied', 'device_rejected', 'sessions_revoked')",
        )
