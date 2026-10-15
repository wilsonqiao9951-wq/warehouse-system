"""add tenant-scoped reviewed repair reports
Revision ID: 20261015_0019
Revises: 20260711_0018
"""
from alembic import op
import sqlalchemy as sa
revision='20261015_0019'
down_revision='20260711_0018'
branch_labels=None
depends_on=None

def upgrade():
    if sa.inspect(op.get_bind()).has_table('repair_case_reports'):return
    op.create_table('repair_case_reports',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('organization_id',sa.Integer(),sa.ForeignKey('organizations.id'),nullable=False),sa.Column('work_order_id',sa.Integer(),sa.ForeignKey('work_orders.id'),nullable=False),sa.Column('submitted_by',sa.Integer(),sa.ForeignKey('users.id')),sa.Column('machine_model',sa.String(255)),sa.Column('symptom_codes',sa.JSON(),nullable=False),sa.Column('steps',sa.JSON(),nullable=False),sa.Column('outcome',sa.String(30),nullable=False),sa.Column('part_ids',sa.JSON(),nullable=False),sa.Column('result_notes',sa.Text(),nullable=False),sa.Column('review_status',sa.String(20),nullable=False,server_default='pending'),sa.Column('reviewed_by',sa.Integer(),sa.ForeignKey('users.id')),sa.Column('reviewed_at',sa.DateTime()),sa.Column('created_at',sa.DateTime(),nullable=False,server_default=sa.func.now()))
    for field in ('organization_id','work_order_id','machine_model'):op.create_index('ix_repair_case_reports_'+field,'repair_case_reports',[field])

def downgrade():
    op.drop_table('repair_case_reports')
