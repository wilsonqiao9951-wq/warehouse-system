"""add tenant branding, subscription state, and commercial limits

Revision ID: 20260730_0032
Revises: 20260729_0031
"""

from alembic import op
import sqlalchemy as sa


revision = "20260730_0032"
down_revision = "20260729_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("organizations") as batch_op:
        batch_op.add_column(
            sa.Column("brand_logo_url", sa.String(length=1000), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "brand_primary_color",
                sa.String(length=7),
                nullable=False,
                server_default="#155eef",
            )
        )
        batch_op.add_column(
            sa.Column(
                "brand_login_headline",
                sa.String(length=200),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "plan_code",
                sa.String(length=32),
                nullable=False,
                server_default="professional",
            )
        )
        batch_op.add_column(
            sa.Column(
                "subscription_status",
                sa.String(length=24),
                nullable=False,
                server_default="active",
            )
        )
        batch_op.add_column(
            sa.Column("trial_ends_at", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "max_users",
                sa.Integer(),
                nullable=True,
                server_default="50",
            )
        )
        batch_op.add_column(
            sa.Column(
                "max_warehouses",
                sa.Integer(),
                nullable=True,
                server_default="10",
            )
        )
        batch_op.add_column(
            sa.Column(
                "max_vehicle_warehouses",
                sa.Integer(),
                nullable=True,
                server_default="50",
            )
        )
        batch_op.add_column(
            sa.Column(
                "ai_monthly_limit",
                sa.Integer(),
                nullable=True,
                server_default="2000",
            )
        )
        batch_op.add_column(
            sa.Column(
                "api_monthly_limit",
                sa.Integer(),
                nullable=True,
                server_default="10000",
            )
        )
        batch_op.add_column(
            sa.Column(
                "settings_version",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.create_check_constraint(
            "ck_organizations_plan_code",
            "plan_code IN ('starter', 'professional', 'enterprise')",
        )
        batch_op.create_check_constraint(
            "ck_organizations_subscription_status",
            "subscription_status IN "
            "('trialing', 'active', 'past_due', 'suspended', 'cancelled')",
        )
        batch_op.create_check_constraint(
            "ck_organizations_settings_version_non_negative",
            "settings_version >= 0",
        )
        batch_op.create_check_constraint(
            "ck_organizations_limits_positive",
            "(max_users IS NULL OR max_users > 0) "
            "AND (max_warehouses IS NULL OR max_warehouses > 0) "
            "AND (max_vehicle_warehouses IS NULL OR max_vehicle_warehouses > 0) "
            "AND (ai_monthly_limit IS NULL OR ai_monthly_limit >= 0) "
            "AND (api_monthly_limit IS NULL OR api_monthly_limit >= 0)",
        )


def downgrade() -> None:
    connection = op.get_bind()
    customized = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM organizations WHERE "
            "brand_logo_url IS NOT NULL "
            "OR brand_primary_color <> '#155eef' "
            "OR brand_login_headline IS NOT NULL "
            "OR plan_code <> 'professional' "
            "OR subscription_status <> 'active' "
            "OR trial_ends_at IS NOT NULL "
            "OR max_users IS NULL OR max_users <> 50 "
            "OR max_warehouses IS NULL OR max_warehouses <> 10 "
            "OR max_vehicle_warehouses IS NULL OR max_vehicle_warehouses <> 50 "
            "OR ai_monthly_limit IS NULL OR ai_monthly_limit <> 2000 "
            "OR api_monthly_limit IS NULL OR api_monthly_limit <> 10000 "
            "OR settings_version <> 0"
        )
    )
    if customized:
        raise RuntimeError(
            "Cannot downgrade while commercial organization settings exist"
        )
    with op.batch_alter_table("organizations") as batch_op:
        batch_op.drop_constraint(
            "ck_organizations_limits_positive",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_organizations_settings_version_non_negative",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_organizations_subscription_status",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_organizations_plan_code",
            type_="check",
        )
        for column_name in (
            "settings_version",
            "api_monthly_limit",
            "ai_monthly_limit",
            "max_vehicle_warehouses",
            "max_warehouses",
            "max_users",
            "trial_ends_at",
            "subscription_status",
            "plan_code",
            "brand_login_headline",
            "brand_primary_color",
            "brand_logo_url",
        ):
            batch_op.drop_column(column_name)
