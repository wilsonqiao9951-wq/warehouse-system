"""add governed disaster-recovery evidence retention

Revision ID: 20260807_0052
Revises: 20260807_0051
Create Date: 2026-08-07
"""

from alembic import op
import sqlalchemy as sa


revision = "20260807_0052"
down_revision = "20260807_0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("organizations") as batch:
        batch.add_column(
            sa.Column(
                "data_export_evidence_retention_days",
                sa.Integer(),
                nullable=False,
                server_default="365",
            )
        )
        batch.add_column(
            sa.Column(
                "data_restore_rehearsal_retention_days",
                sa.Integer(),
                nullable=False,
                server_default="90",
            )
        )
        batch.add_column(
            sa.Column(
                "data_restore_rollback_retention_days",
                sa.Integer(),
                nullable=False,
                server_default="30",
            )
        )
        batch.create_check_constraint(
            "ck_organizations_data_retention_days",
            "data_export_evidence_retention_days BETWEEN 30 AND 3650 "
            "AND data_restore_rehearsal_retention_days BETWEEN 7 AND 3650 "
            "AND data_restore_rollback_retention_days BETWEEN 7 AND 3650",
        )

    with op.batch_alter_table("organization_data_restores") as batch:
        batch.add_column(sa.Column("rollback_expires_at", sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column("rollback_evidence_purged_at", sa.DateTime(), nullable=True)
        )
        batch.add_column(
            sa.Column("rollback_evidence_purged_by", sa.Integer(), nullable=True)
        )
        batch.create_foreign_key(
            "fk_org_data_restore_purge_actor",
            "users",
            ["rollback_evidence_purged_by"],
            ["id"],
        )
        batch.create_index(
            "ix_org_data_restore_retention",
            ["organization_id", "status", "rollback_expires_at", "updated_at"],
            unique=False,
        )


def downgrade() -> None:
    connection = op.get_bind()
    custom_policy = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM organizations WHERE "
            "data_export_evidence_retention_days <> 365 OR "
            "data_restore_rehearsal_retention_days <> 90 OR "
            "data_restore_rollback_retention_days <> 30"
        )
    )
    retention_evidence = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM organization_data_restores WHERE "
            "rollback_expires_at IS NOT NULL OR "
            "rollback_evidence_purged_at IS NOT NULL OR "
            "rollback_evidence_purged_by IS NOT NULL"
        )
    )
    if custom_policy or retention_evidence:
        raise RuntimeError(
            "Cannot downgrade while data-retention policy or cleanup evidence exists"
        )

    with op.batch_alter_table("organization_data_restores") as batch:
        batch.drop_index("ix_org_data_restore_retention")
        batch.drop_constraint("fk_org_data_restore_purge_actor", type_="foreignkey")
        batch.drop_column("rollback_evidence_purged_by")
        batch.drop_column("rollback_evidence_purged_at")
        batch.drop_column("rollback_expires_at")

    with op.batch_alter_table("organizations") as batch:
        batch.drop_constraint("ck_organizations_data_retention_days", type_="check")
        batch.drop_column("data_restore_rollback_retention_days")
        batch.drop_column("data_restore_rehearsal_retention_days")
        batch.drop_column("data_export_evidence_retention_days")
