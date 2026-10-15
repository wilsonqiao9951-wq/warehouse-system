"""Preserve original symptom inputs and vocabulary version for repair feedback."""
from alembic import op
import sqlalchemy as sa

revision = '20261015_0021'
down_revision = '20261015_0020'
branch_labels = None
depends_on = None


def upgrade():
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('repair_case_reports')}
    if 'symptom_context' not in columns:
        op.add_column('repair_case_reports', sa.Column('symptom_context', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('repair_case_reports') as batch:
        batch.drop_column('symptom_context')
