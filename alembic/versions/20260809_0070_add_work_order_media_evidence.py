"""add work order media evidence

Revision ID: 20260809_0070
Revises: 20260809_0069
Create Date: 2026-08-09
"""

import sqlalchemy as sa
from alembic import op


revision = "20260809_0070"
down_revision = "20260809_0069"
branch_labels = None
depends_on = None

TABLES = ("work_order_media",)
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
    op.create_table(
        "work_order_media",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column(
            "work_order_id",
            sa.Integer(),
            sa.ForeignKey("work_orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=24), nullable=False),
        sa.Column("caption", sa.String(length=500), nullable=True),
        sa.Column("media_type", sa.String(length=12), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("media_storage_key", sa.String(length=500), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("client_request_id", sa.String(length=100), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_device_id",
            sa.Integer(),
            sa.ForeignKey("user_devices.id"),
            nullable=True,
        ),
        sa.Column("claim_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "category IN ('arrival', 'before', 'during', 'after', 'damage', "
            "'serial_label', 'other')",
            name="ck_work_order_media_category",
        ),
        sa.CheckConstraint(
            "media_type IN ('photo', 'video')",
            name="ck_work_order_media_type",
        ),
        sa.CheckConstraint(
            "size_bytes > 0",
            name="ck_work_order_media_size_positive",
        ),
        sa.CheckConstraint(
            "length(file_sha256) = 64 AND length(request_fingerprint) = 64",
            name="ck_work_order_media_fingerprints",
        ),
        sa.CheckConstraint(
            "claim_version >= 0",
            name="ck_work_order_media_claim_version",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "client_request_id",
            name="uq_work_order_media_org_request",
        ),
    )
    for column in (
        "id",
        "organization_id",
        "work_order_id",
        "category",
        "media_type",
        "created_by",
    ):
        op.create_index(
            f"ix_work_order_media_{column}",
            "work_order_media",
            [column],
        )
    op.create_index(
        "ix_work_order_media_org_work_order_time",
        "work_order_media",
        ["organization_id", "work_order_id", "created_at"],
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("ALTER TABLE work_order_media ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text("ALTER TABLE work_order_media FORCE ROW LEVEL SECURITY"))
        op.execute(
            sa.text(
                f"CREATE POLICY {POLICY_NAME} ON work_order_media "
                f"USING {POLICY_EXPRESSION} WITH CHECK {POLICY_EXPRESSION}"
            )
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text(f"DROP POLICY IF EXISTS {POLICY_NAME} ON work_order_media"))
    op.drop_table("work_order_media")
