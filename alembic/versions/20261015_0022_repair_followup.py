"""Preserve recurrence observations and reported actual repair parts."""
from alembic import op
import sqlalchemy as sa

revision = '20261015_0022'
down_revision = '20261015_0021'
branch_labels = None
depends_on = None


def upgrade():
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('repair_case_reports')}
    if 'repair_followup' not in columns:
        op.add_column('repair_case_reports', sa.Column('repair_followup', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('repair_case_reports') as batch:
        batch.drop_column('repair_followup')
