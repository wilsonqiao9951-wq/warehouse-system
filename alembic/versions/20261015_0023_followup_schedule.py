"""Add explicitly scheduled repair follow-ups."""
from alembic import op
import sqlalchemy as sa
revision='20261015_0023'
down_revision='20261015_0022'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('repair_case_reports',sa.Column('followup_due_at',sa.DateTime(),nullable=True))
    op.create_index('ix_repair_case_reports_followup_due_at','repair_case_reports',['followup_due_at'])

def downgrade():
    op.drop_index('ix_repair_case_reports_followup_due_at',table_name='repair_case_reports')
    with op.batch_alter_table('repair_case_reports') as batch:batch.drop_column('followup_due_at')
