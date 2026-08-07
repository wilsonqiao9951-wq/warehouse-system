"""add verified tenant domains and email identities

Revision ID: 20260806_0034
Revises: 20260806_0033
"""

from alembic import op
import sqlalchemy as sa


revision = "20260806_0034"
down_revision = "20260806_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization_domains",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(length=253), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("verification_token", sa.String(length=128), nullable=False),
        sa.Column("verification_name", sa.String(length=300), nullable=False),
        sa.Column("verification_value", sa.String(length=255), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("verification_error", sa.String(length=500), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("email_from_name", sa.String(length=160), nullable=True),
        sa.Column("email_from_local_part", sa.String(length=64), nullable=True),
        sa.Column(
            "email_identity_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'verified')",
            name="ck_organization_domain_status",
        ),
        sa.CheckConstraint(
            "version >= 0",
            name="ck_organization_domain_version_non_negative",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("domain", name="uq_organization_domain_name"),
        sa.UniqueConstraint(
            "organization_id",
            name="uq_organization_domain_org",
        ),
    )
    for column in ("id", "organization_id", "domain"):
        op.create_index(
            op.f(f"ix_organization_domains_{column}"),
            "organization_domains",
            [column],
        )


def downgrade() -> None:
    connection = op.get_bind()
    domain_count = connection.scalar(
        sa.text("SELECT COUNT(*) FROM organization_domains")
    )
    if domain_count:
        raise RuntimeError(
            "Cannot downgrade while verified-domain configuration exists"
        )
    for column in ("domain", "organization_id", "id"):
        op.drop_index(
            op.f(f"ix_organization_domains_{column}"),
            table_name="organization_domains",
        )
    op.drop_table("organization_domains")
