from sqlalchemy import func, select

from app.core.rbac import Actor, get_current_actor
from app.models import AuditLog, Organization, RepairCaseReport, User, UserRole, WorkOrder

PAYLOAD = {'symptom_codes': ['LOW_FLOW'], 'steps': ['Check flow'], 'outcome': 'resolved',
           'result_notes': 'Flow measured and restored', 'part_ids': []}
KEY = 'report-1234567890abcdef'


def job(client, ticket):
    response = client.post('/api/work-orders', json={'ticket_number': ticket, 'machine_type': '9100 Self-Serve'})
    assert response.status_code == 200
    return response.json()['id']


def submit(client, wid, payload=None, key=KEY):
    headers = {'Idempotency-Key': key} if key else {}
    return client.post(f'/api/muse/work-orders/{wid}/reports', json=payload or PAYLOAD, headers=headers)


def test_retry_returns_original_report_and_single_audit_even_after_review(client):
    wid = job(client, 'RETRY')
    first = submit(client, wid)
    assert first.status_code == 200 and first.json()['replayed'] is False
    rid = first.json()['report_id']
    repeated = submit(client, wid)
    assert repeated.json()['report_id'] == rid and repeated.json()['replayed'] is True
    client.post(f'/api/muse/reports/{rid}/review', json={'decision': 'approved'}).raise_for_status()
    repeated = submit(client, wid).json()
    assert repeated['review_status'] == 'approved' and repeated['guidance_eligible'] is True
    with client.app.state.testing_session_local() as db:
        assert db.scalar(select(func.count()).select_from(RepairCaseReport)) == 1
        assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == 'submit_repair_case')) == 1


def test_same_key_with_changed_result_or_different_order_conflicts(client):
    wid = job(client, 'FIRST')
    other = job(client, 'SECOND')
    submit(client, wid).raise_for_status()
    assert submit(client, wid, {**PAYLOAD, 'outcome': 'unresolved'}).status_code == 409
    assert submit(client, other).status_code == 409
    with client.app.state.testing_session_local() as db:
        assert db.scalar(select(func.count()).select_from(RepairCaseReport)) == 1


def test_normalized_retry_and_old_clients_without_key(client):
    wid = job(client, 'NORMALIZED')
    first = submit(client, wid).json()
    normalized = {**PAYLOAD, 'symptom_codes': [' low_flow ', 'LOW_FLOW'],
                  'steps': [' Check flow '], 'result_notes': ' Flow measured and restored '}
    assert submit(client, wid, normalized).json()['report_id'] == first['report_id']
    one = submit(client, wid, key=None).json()['report_id']
    two = submit(client, wid, key=None).json()['report_id']
    assert one != two  # Existing clients retain their original append behavior.
    assert submit(client, wid, key='too-short').status_code == 422
    assert submit(client, wid, key='invalid key with spaces').status_code == 422


def test_keys_are_tenant_scoped_and_cannot_replay_another_users_report(client):
    wid = job(client, 'LOCAL')
    with client.app.state.testing_session_local() as db:
        db.add(Organization(id=2, name='Other', slug='other-idempotency'))
        db.flush()
        users = [User(organization_id=org, name=f'User {i}', email=f'idem-{i}@example.invalid',
                      role=UserRole.ADMIN, is_active=True) for i, org in enumerate([1, 1, 2])]
        db.add_all(users)
        other = WorkOrder(organization_id=2, ticket_number='FOREIGN', machine_type='9100 Self-Serve')
        db.add(other)
        db.commit()
        identities = [(u.id, u.organization_id) for u in users]
        foreign_id = other.id

    def identity(index):
        uid, org = identities[index]
        client.app.dependency_overrides[get_current_actor] = lambda: Actor(uid, UserRole.ADMIN, org, auth_method='test')

    identity(0)
    first = submit(client, wid).json()
    identity(1)
    assert submit(client, wid).status_code == 409
    identity(2)
    assert submit(client, wid).status_code == 404
    foreign = submit(client, foreign_id)
    assert foreign.status_code == 200 and foreign.json()['report_id'] != first['report_id']
    identity(0)
    assert submit(client, wid).json()['report_id'] == first['report_id']
