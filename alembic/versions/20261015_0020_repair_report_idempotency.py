"""Make repair report retries idempotent within an organization."""
from alembic import op
import sqlalchemy as sa

revision = '20261015_0020'
down_revision = '20261015_0019'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {c['name'] for c in inspector.get_columns('repair_case_reports')}
    constraints = {c['name'] for c in inspector.get_unique_constraints('repair_case_reports')}
    with op.batch_alter_table('repair_case_reports') as batch:
        if 'idempotency_key' not in columns:
            batch.add_column(sa.Column('idempotency_key', sa.String(128), nullable=True))
        if 'request_fingerprint' not in columns:
            batch.add_column(sa.Column('request_fingerprint', sa.String(64), nullable=True))
        if 'uq_repair_report_org_idempotency' not in constraints:
            batch.create_unique_constraint('uq_repair_report_org_idempotency', ['organization_id', 'idempotency_key'])


def downgrade():
    with op.batch_alter_table('repair_case_reports') as batch:
        batch.drop_constraint('uq_repair_report_org_idempotency', type_='unique')
        batch.drop_column('request_fingerprint')
        batch.drop_column('idempotency_key')
