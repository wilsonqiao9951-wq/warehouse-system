"""add durable operations alerts and outbound delivery evidence

Revision ID: 20260808_0066
Revises: 20260808_0065
Create Date: 2026-08-08
"""

import sqlalchemy as sa
from alembic import op


revision = "20260808_0066"
down_revision = "20260808_0065"
branch_labels = None
depends_on = None

INCIDENT_TABLE = "operations_alert_incidents"
DELIVERY_TABLE = "operations_alert_deliveries"


def upgrade() -> None:
    op.create_table(
        INCIDENT_TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("alert_code", sa.String(length=160), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("current_count", sa.Integer(), nullable=False),
        sa.Column("peak_count", sa.Integer(), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "severity IN ('warning', 'critical')",
            name="ck_operations_alert_incident_severity",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'resolved')",
            name="ck_operations_alert_incident_status",
        ),
        sa.CheckConstraint(
            "current_count >= 0 AND peak_count >= current_count AND observation_count >= 1",
            name="ck_operations_alert_incident_counts",
        ),
        sa.CheckConstraint(
            "version >= 0",
            name="ck_operations_alert_incident_version_non_negative",
        ),
        sa.CheckConstraint(
            "(status = 'open' AND resolved_at IS NULL) OR "
            "(status = 'resolved' AND resolved_at IS NOT NULL)",
            name="ck_operations_alert_incident_resolution",
        ),
    )
    op.create_index("ix_operations_alert_incident_status", INCIDENT_TABLE, ["status"])
    op.create_index("ix_operations_alert_incident_code", INCIDENT_TABLE, ["alert_code"])
    op.create_index(
        "ix_operations_alert_incident_observed", INCIDENT_TABLE, ["last_observed_at"]
    )
    op.create_index(
        "uq_operations_alert_incident_active_code",
        INCIDENT_TABLE,
        ["alert_code"],
        unique=True,
        sqlite_where=sa.text("status = 'open'"),
        postgresql_where=sa.text("status = 'open'"),
    )

    op.create_table(
        DELIVERY_TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "incident_id",
            sa.Integer(),
            sa.ForeignKey(f"{INCIDENT_TABLE}.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("response_status_code", sa.Integer(), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_operations_alert_delivery_idempotency"
        ),
        sa.CheckConstraint(
            "event_type IN ('triggered', 'escalated', 'reminder', 'resolved', 'test')",
            name="ck_operations_alert_delivery_event_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'sent', 'failed')",
            name="ck_operations_alert_delivery_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 5",
            name="ck_operations_alert_delivery_attempt_count",
        ),
        sa.CheckConstraint(
            "response_status_code IS NULL OR "
            "(response_status_code >= 100 AND response_status_code <= 599)",
            name="ck_operations_alert_delivery_http_status",
        ),
        sa.CheckConstraint(
            "length(request_hash) = 64 AND length(idempotency_key) = 64",
            name="ck_operations_alert_delivery_hashes",
        ),
        sa.CheckConstraint(
            "version >= 0",
            name="ck_operations_alert_delivery_version_non_negative",
        ),
    )
    op.create_index(
        "ix_operations_alert_delivery_status_due",
        DELIVERY_TABLE,
        ["status", "next_attempt_at"],
    )
    op.create_index(
        "ix_operations_alert_delivery_incident", DELIVERY_TABLE, ["incident_id"]
    )
    op.create_index(
        "ix_operations_alert_delivery_created", DELIVERY_TABLE, ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_operations_alert_delivery_created", table_name=DELIVERY_TABLE)
    op.drop_index("ix_operations_alert_delivery_incident", table_name=DELIVERY_TABLE)
    op.drop_index("ix_operations_alert_delivery_status_due", table_name=DELIVERY_TABLE)
    op.drop_table(DELIVERY_TABLE)
    op.drop_index("uq_operations_alert_incident_active_code", table_name=INCIDENT_TABLE)
    op.drop_index("ix_operations_alert_incident_observed", table_name=INCIDENT_TABLE)
    op.drop_index("ix_operations_alert_incident_code", table_name=INCIDENT_TABLE)
    op.drop_index("ix_operations_alert_incident_status", table_name=INCIDENT_TABLE)
    op.drop_table(INCIDENT_TABLE)
