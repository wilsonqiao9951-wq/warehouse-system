"""add parts import batches and tenant part uniqueness

Revision ID: 20260710_0005
Revises: 20260710_0004
Create Date: 2026-07-10 08:15:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260710_0005"
down_revision: Union[str, None] = "20260710_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    unique_constraints = sa.inspect(bind).get_unique_constraints("parts")
    existing_part_unique = next(
        (constraint for constraint in unique_constraints if constraint.get("column_names") == ["part_number"]),
        None,
    )
    naming_convention = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
    with op.batch_alter_table("parts", naming_convention=naming_convention) as batch_op:
        if existing_part_unique:
            batch_op.drop_constraint(existing_part_unique.get("name") or "uq_parts_part_number", type_="unique")
        batch_op.create_unique_constraint("uq_parts_org_part_number", ["organization_id", "part_number"])

    op.create_table(
        "import_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("import_type", sa.String(length=50), nullable=False, server_default="parts"),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="previewed"),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("errors_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("committed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_import_batches_id", "import_batches", ["id"])
    op.create_index("ix_import_batches_organization_id", "import_batches", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_import_batches_organization_id", table_name="import_batches")
    op.drop_index("ix_import_batches_id", table_name="import_batches")
    op.drop_table("import_batches")
    with op.batch_alter_table("parts") as batch_op:
        batch_op.drop_constraint("uq_parts_org_part_number", type_="unique")
        batch_op.create_unique_constraint("uq_parts_part_number", ["part_number"])
