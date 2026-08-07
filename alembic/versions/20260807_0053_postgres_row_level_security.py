"""add PostgreSQL tenant row-level security policies

Revision ID: 20260807_0053
Revises: 20260807_0052
Create Date: 2026-08-07
"""

from alembic import op


revision = "20260807_0053"
down_revision = "20260807_0052"
branch_labels = None
depends_on = None


TENANT_TABLES = (
    "audit_logs",
    "auth_security_events",
    "billing_lifecycle_events",
    "completion_policies",
    "customers",
    "enterprise_agent_runs",
    "equipment",
    "external_integrations",
    "external_sync_logs",
    "external_work_order_links",
    "import_batches",
    "inventory_count_lines",
    "inventory_count_sessions",
    "inventory_notifications",
    "inventory_regions",
    "inventory_transactions",
    "job_status",
    "machine_knowledge_entries",
    "machine_knowledge_profiles",
    "organization_billing_accounts",
    "organization_data_exports",
    "organization_data_restores",
    "organization_domains",
    "organization_usage_periods",
    "part_machine_associations",
    "part_recognition_analyses",
    "part_recognition_candidates",
    "part_recognition_observations",
    "parts",
    "password_reset_tokens",
    "qc_pictures",
    "replenishment_requests",
    "return_equipments",
    "storage_locations",
    "stripe_billing_operations",
    "stripe_webhook_receipts",
    "subscription_notices",
    "user_devices",
    "user_invitations",
    "user_permission_grants",
    "users",
    "vehicle_return_requests",
    "warehouses",
    "work_order_form_actions",
    "work_order_form_conflicts",
    "work_order_form_fields",
    "work_order_form_templates",
    "work_order_part_memory",
    "work_order_parts",
    "work_order_voice_notes",
    "work_orders",
)

POLICY_NAME = "openpartsflow_tenant_isolation"
POLICY_EXPRESSION = """
(
  current_setting('openpartsflow.platform_access', true) = 'on'
  OR organization_id = NULLIF(
    current_setting('openpartsflow.organization_id', true), ''
  )::integer
)
""".strip()


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{POLICY_NAME}" ON "{table}" '
            f"USING ({POLICY_EXPRESSION}) WITH CHECK ({POLICY_EXPRESSION})"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in reversed(TENANT_TABLES):
        op.execute(f'DROP POLICY IF EXISTS "{POLICY_NAME}" ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
