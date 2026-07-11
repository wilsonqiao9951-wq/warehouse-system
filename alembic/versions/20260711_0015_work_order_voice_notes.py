"""add work order voice notes

Revision ID: 20260711_0015
Revises: 20260711_0014
"""
from alembic import op
import sqlalchemy as sa

revision = "20260711_0015"
down_revision = "20260711_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "work_order_voice_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("work_order_id", sa.Integer(), sa.ForeignKey("work_orders.id"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("audio_url", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("transcription_status", sa.String(length=30), nullable=False, server_default="not_requested"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_work_order_voice_notes_organization_id", "work_order_voice_notes", ["organization_id"])
    op.create_index("ix_work_order_voice_notes_work_order_id", "work_order_voice_notes", ["work_order_id"])


def downgrade() -> None:
    op.drop_table("work_order_voice_notes")
