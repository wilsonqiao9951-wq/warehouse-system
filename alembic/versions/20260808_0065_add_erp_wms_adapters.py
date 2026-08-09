"""add governed ERP and WMS adapter connection evidence

Revision ID: 20260808_0065
Revises: 20260808_0064
Create Date: 2026-08-08
"""

import sqlalchemy as sa
from alembic import op


revision = "20260808_0065"
down_revision = "20260808_0064"
branch_labels = None
depends_on = None

CONFIG_TABLE = "integration_adapter_configurations"
TEST_TABLE = "integration_connection_tests"
POLICY_NAME = "openpartsflow_tenant_isolation"
POLICY_EXPRESSION = """
(
  current_setting('openpartsflow.platform_access', true) = 'on'
  OR organization_id = NULLIF(
    current_setting('openpartsflow.organization_id', true), ''
  )::integer
)
""".strip()


def _enable_rls(table_name: str) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(sa.text(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text(
            f"CREATE POLICY {POLICY_NAME} ON {table_name} "
            f"USING {POLICY_EXPRESSION} WITH CHECK {POLICY_EXPRESSION}"
        )
    )


def upgrade() -> None:
    op.create_table(
        CONFIG_TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column(
            "integration_id",
            sa.Integer(),
            sa.ForeignKey("external_integrations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("protocol", sa.String(length=30), nullable=False),
        sa.Column("base_url", sa.String(length=1000), nullable=False),
        sa.Column("health_path", sa.String(length=500), nullable=False, server_default="/"),
        sa.Column("auth_type", sa.String(length=30), nullable=False, server_default="none"),
        sa.Column("auth_username", sa.String(length=255), nullable=True),
        sa.Column("api_key_header", sa.String(length=80), nullable=True),
        sa.Column("credential_ciphertext", sa.Text(), nullable=True),
        sa.Column("credential_updated_at", sa.DateTime(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "integration_id", name="uq_integration_adapter_configuration_integration"
        ),
        sa.CheckConstraint(
            "protocol IN ('rest_json', 'odata_v4')",
            name="ck_integration_adapter_configuration_protocol",
        ),
        sa.CheckConstraint(
            "auth_type IN ('none', 'bearer', 'basic', 'api_key_header')",
            name="ck_integration_adapter_configuration_auth_type",
        ),
        sa.CheckConstraint(
            "(auth_type = 'none' AND auth_username IS NULL AND api_key_header IS NULL "
            "AND credential_ciphertext IS NULL) OR "
            "(auth_type = 'bearer' AND auth_username IS NULL AND api_key_header IS NULL) OR "
            "(auth_type = 'basic' AND auth_username IS NOT NULL AND api_key_header IS NULL) OR "
            "(auth_type = 'api_key_header' AND auth_username IS NULL AND api_key_header IS NOT NULL)",
            name="ck_integration_adapter_configuration_auth_metadata",
        ),
        sa.CheckConstraint(
            "timeout_seconds >= 1 AND timeout_seconds <= 30",
            name="ck_integration_adapter_configuration_timeout",
        ),
        sa.CheckConstraint(
            "version >= 0",
            name="ck_integration_adapter_configuration_version_non_negative",
        ),
    )
    for column in ("id", "organization_id", "integration_id"):
        op.create_index(f"ix_{CONFIG_TABLE}_{column}", CONFIG_TABLE, [column])
    _enable_rls(CONFIG_TABLE)

    op.create_table(
        TEST_TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column(
            "integration_id",
            sa.Integer(),
            sa.ForeignKey("external_integrations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "configuration_id",
            sa.Integer(),
            sa.ForeignKey(f"{CONFIG_TABLE}.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("configuration_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("response_status_code", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("protocol_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("protocol_signal", sa.String(length=40), nullable=False),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("evidence_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("tested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("tested_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('success', 'failed')",
            name="ck_integration_connection_test_status",
        ),
        sa.CheckConstraint(
            "configuration_version >= 0",
            name="ck_integration_connection_test_version_non_negative",
        ),
        sa.CheckConstraint(
            "latency_ms >= 0",
            name="ck_integration_connection_test_latency_non_negative",
        ),
        sa.CheckConstraint(
            "response_status_code IS NULL OR "
            "(response_status_code >= 100 AND response_status_code <= 599)",
            name="ck_integration_connection_test_http_status",
        ),
        sa.CheckConstraint(
            "length(evidence_fingerprint) = 64",
            name="ck_integration_connection_test_fingerprint",
        ),
        sa.CheckConstraint(
            "(status = 'success' AND protocol_confirmed = true AND error_code IS NULL) OR "
            "(status = 'failed' AND error_code IS NOT NULL)",
            name="ck_integration_connection_test_result",
        ),
    )
    for column in ("id", "organization_id", "integration_id", "configuration_id", "status"):
        op.create_index(f"ix_{TEST_TABLE}_{column}", TEST_TABLE, [column])
    op.create_index(
        "ix_integration_connection_test_org_integration_time",
        TEST_TABLE,
        ["organization_id", "integration_id", "tested_at"],
    )
    _enable_rls(TEST_TABLE)


def downgrade() -> None:
    for table_name in (TEST_TABLE, CONFIG_TABLE):
        if op.get_bind().dialect.name == "postgresql":
            op.execute(sa.text(f"DROP POLICY IF EXISTS {POLICY_NAME} ON {table_name}"))
    op.drop_index("ix_integration_connection_test_org_integration_time", table_name=TEST_TABLE)
    for column in ("status", "configuration_id", "integration_id", "organization_id", "id"):
        op.drop_index(f"ix_{TEST_TABLE}_{column}", table_name=TEST_TABLE)
    op.drop_table(TEST_TABLE)
    for column in ("integration_id", "organization_id", "id"):
        op.drop_index(f"ix_{CONFIG_TABLE}_{column}", table_name=CONFIG_TABLE)
    op.drop_table(CONFIG_TABLE)
