"""add authentication security evidence and revocable sessions

Revision ID: 20260807_0048
Revises: 20260807_0047
Create Date: 2026-08-07
"""

from alembic import op
import sqlalchemy as sa


revision = "20260807_0048"
down_revision = "20260807_0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "auth_version",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )
        batch.create_check_constraint(
            "ck_users_auth_version_non_negative",
            "auth_version >= 0",
        )

    op.create_table(
        "auth_security_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("principal_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('login', 'session_revocation')",
            name="ck_auth_security_events_type",
        ),
        sa.CheckConstraint(
            "outcome IN ('success', 'invalid_credentials', 'rate_limited', "
            "'subscription_denied', 'device_rejected', 'sessions_revoked')",
            name="ck_auth_security_events_outcome",
        ),
        sa.CheckConstraint(
            "length(principal_fingerprint) = 64 AND length(source_fingerprint) = 64",
            name="ck_auth_security_events_fingerprints",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("id", "organization_id", "user_id"):
        op.create_index(
            op.f(f"ix_auth_security_events_{column}"),
            "auth_security_events",
            [column],
        )
    op.create_index(
        "ix_auth_security_events_principal_occurred",
        "auth_security_events",
        ["principal_fingerprint", "occurred_at"],
    )
    op.create_index(
        "ix_auth_security_events_source_occurred",
        "auth_security_events",
        ["source_fingerprint", "occurred_at"],
    )
    op.create_index(
        "ix_auth_security_events_org_occurred",
        "auth_security_events",
        ["organization_id", "occurred_at"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    events = connection.scalar(sa.text("SELECT COUNT(*) FROM auth_security_events"))
    revised_users = connection.scalar(
        sa.text("SELECT COUNT(*) FROM users WHERE auth_version != 0")
    )
    if events or revised_users:
        raise RuntimeError(
            "Cannot downgrade while authentication security or session-revocation evidence exists"
        )

    for name in (
        "ix_auth_security_events_org_occurred",
        "ix_auth_security_events_source_occurred",
        "ix_auth_security_events_principal_occurred",
    ):
        op.drop_index(name, table_name="auth_security_events")
    for column in ("user_id", "organization_id", "id"):
        op.drop_index(
            op.f(f"ix_auth_security_events_{column}"),
            table_name="auth_security_events",
        )
    op.drop_table("auth_security_events")

    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_users_auth_version_non_negative", type_="check")
        batch.drop_column("auth_version")
