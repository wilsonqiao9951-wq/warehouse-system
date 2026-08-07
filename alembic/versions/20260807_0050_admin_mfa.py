"""add administrator multi-factor authentication

Revision ID: 20260807_0050
Revises: 20260807_0049
Create Date: 2026-08-07
"""

from alembic import op
import sqlalchemy as sa


revision = "20260807_0050"
down_revision = "20260807_0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("mfa_secret_encrypted", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("mfa_recovery_codes_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("mfa_enabled_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("mfa_enrollment_expires_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("mfa_last_used_step", sa.BigInteger(), nullable=True))
        batch.create_check_constraint(
            "ck_users_mfa_enabled_complete",
            "mfa_enabled_at IS NULL OR (mfa_secret_encrypted IS NOT NULL AND mfa_recovery_codes_json IS NOT NULL)",
        )
        batch.create_check_constraint(
            "ck_users_mfa_last_used_step_non_negative",
            "mfa_last_used_step IS NULL OR mfa_last_used_step >= 0",
        )

    with op.batch_alter_table("auth_security_events") as batch:
        batch.drop_constraint("ck_auth_security_events_type", type_="check")
        batch.drop_constraint("ck_auth_security_events_outcome", type_="check")
        batch.create_check_constraint(
            "ck_auth_security_events_type",
            "event_type IN ('login', 'session_revocation', 'password_reset', 'mfa')",
        )
        batch.create_check_constraint(
            "ck_auth_security_events_outcome",
            "outcome IN ('success', 'invalid_credentials', 'rate_limited', "
            "'subscription_denied', 'device_rejected', 'sessions_revoked', "
            "'reset_requested', 'reset_request_ignored', 'reset_delivered', "
            "'reset_delivery_failed', 'reset_completed', 'reset_rejected', "
            "'mfa_challenge_required', 'mfa_success', 'mfa_invalid', "
            "'mfa_recovery_used', 'mfa_enrolled', 'mfa_disabled', "
            "'mfa_recovery_regenerated')",
        )


def downgrade() -> None:
    connection = op.get_bind()
    enabled = connection.scalar(sa.text("SELECT COUNT(*) FROM users WHERE mfa_enabled_at IS NOT NULL"))
    events = connection.scalar(sa.text("SELECT COUNT(*) FROM auth_security_events WHERE event_type = 'mfa'"))
    if enabled or events:
        raise RuntimeError("Cannot downgrade while MFA credentials or security evidence exists")

    with op.batch_alter_table("auth_security_events") as batch:
        batch.drop_constraint("ck_auth_security_events_outcome", type_="check")
        batch.drop_constraint("ck_auth_security_events_type", type_="check")
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

    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_users_mfa_last_used_step_non_negative", type_="check")
        batch.drop_constraint("ck_users_mfa_enabled_complete", type_="check")
        batch.drop_column("mfa_last_used_step")
        batch.drop_column("mfa_enrollment_expires_at")
        batch.drop_column("mfa_enabled_at")
        batch.drop_column("mfa_recovery_codes_json")
        batch.drop_column("mfa_secret_encrypted")
