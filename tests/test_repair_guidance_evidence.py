from app.models import (Equipment, InventoryTransaction, Organization, Part,
                        RepairCaseReport, TransactionType, Warehouse, WorkOrder)


def order(client, ticket, model='9100 Self-Serve'):
    r = client.post('/api/work-orders', json={'ticket_number': ticket, 'machine_type': model})
    r.raise_for_status()
    return r.json()['id']


def reviewed(client, wid, parts=(), outcome='resolved', code='LOW_FLOW'):
    r = client.post(f'/api/muse/work-orders/{wid}/reports', json={
        'symptom_codes': [code], 'steps': ['Measure flow', 'Inspect filter', 'Measure flow'],
        'outcome': outcome, 'result_notes': 'Recorded actual measurements', 'part_ids': list(parts)})
    r.raise_for_status()
    rid = r.json()['report_id']
    client.post(f'/api/muse/reports/{rid}/review', json={'decision': 'approved'}).raise_for_status()
    return rid


def guidance(client, wid, code='LOW_FLOW'):
    r = client.get(f'/api/muse/work-orders/{wid}/guidance', params={'symptom_code': code})
    r.raise_for_status()
    return r.json()['reviewed_guidance']


def test_recommendations_have_case_step_inventory_sources_and_no_side_effects(client):
    current = order(client, 'CURRENT')
    first, second = order(client, 'FIRST'), order(client, 'SECOND')
    with client.app.state.testing_session_local() as db:
        part = Part(organization_id=1, part_number='FILTER', name='Filter')
        warehouse = Warehouse(organization_id=1, code='MAIN', name='Main')
        db.add_all([part, warehouse]); db.flush()
        pid, whid = part.id, warehouse.id
        db.add(InventoryTransaction(organization_id=1, part_id=pid, transaction_type=TransactionType.INBOUND,
                                   quantity=4, to_warehouse_id=whid))
        db.commit()
    ids = {reviewed(client, first, [pid]), reviewed(client, second, [pid])}
    result = guidance(client, current)
    assert result['evidence_status'] == 'multiple_reviewed_cases' and not result['needs_more_evidence']
    candidate = result['part_candidates'][0]
    assert set(candidate['source_case_ids']) == ids and candidate['supporting_case_count'] == 2
    assert candidate['available_quantity'] == 4 and candidate['availability'] == 'in_stock'
    assert candidate['available_positions'][0]['warehouse_id'] == whid
    assert not candidate['compatibility_confirmed'] and not candidate['automatically_selected']
    assert not candidate['inventory_reserved'] and candidate['requires_technician_confirmation']
    assert len(result['suggested_checks']) == 2
    assert all(set(s['source_case_ids']) == ids and not s['execution_required'] for s in result['suggested_checks'])
    assert all(c['source_work_order_id'] in {first, second} and c['reviewed_at'] for c in result['cases'])
    source = client.get(result['cases'][0]['source_path'])
    assert source.status_code == 200 and source.json()['guidance_eligible']
    assert source.json()['part_ids'] == [pid]
    assert client.get(f'/api/work-orders/{current}/part-recommendations').json() == []
    legacy = client.get(f'/api/work-orders/{current}/part-recommendations', params={'symptom_code': 'LOW_FLOW'}).json()
    assert legacy[0]['source_case_ids'] == candidate['source_case_ids']
    assert legacy[0]['recommended_quantity'] is None and legacy[0]['quantity_confirmation_required']
    assert legacy[0]['available_quantity'] == 4 and not legacy[0]['compatibility_confirmed']
    assert client.post('/api/muse/query', json={'resource': 'repair_guidance', 'work_order_id': current,
                                              'symptom_code': 'LOW_FLOW'}).json()['reviewed_guidance'] == result
    with client.app.state.testing_session_local() as db:
        assert len(db.query(InventoryTransaction).all()) == 1
        assert db.get(WorkOrder, current).status != 'COMPLETED'


def test_no_evidence_and_single_case_are_explicit_and_repeats_do_not_inflate(client):
    current, prior = order(client, 'CURRENT'), order(client, 'PRIOR')
    result = guidance(client, current)
    assert result['needs_more_evidence'] and result['evidence_status'] == 'insufficient'
    assert result['part_candidates'] == [] and result['suggested_checks'] == []
    assert 'no_reviewed_matching_cases' in {n['code'] for n in result['evidence_notices']}
    assert 'symptom_code_required' in {n['code'] for n in guidance(client, current, '')['evidence_notices']}
    reviewed(client, prior)
    rid = reviewed(client, prior)
    result = guidance(client, current)
    assert result['reviewed_resolved_case_count'] == 1 and result['needs_more_evidence']
    assert result['cases'][0]['case_id'] == rid
    assert result['suggested_checks'][0]['supporting_case_count'] == 1


def test_failed_outcomes_and_inventory_issues_are_not_positive_fitment(client):
    current = order(client, 'CURRENT')
    with client.app.state.testing_session_local() as db:
        parts = [Part(organization_id=1, part_number=pn, name=pn, is_active=pn != 'INACTIVE')
                 for pn in ['AVAILABLE', 'NEGATIVE', 'INACTIVE', 'CLOSED']]
        main = Warehouse(organization_id=1, code='MAIN', name='Main')
        closed = Warehouse(organization_id=1, code='CLOSED', name='Closed', is_active=False)
        db.add_all([*parts, main, closed]); db.flush()
        pids = [p.id for p in parts]
        for part in parts:
            db.add(InventoryTransaction(organization_id=1, part_id=part.id, transaction_type=TransactionType.INBOUND,
                quantity=10, to_warehouse_id=closed.id if part.part_number == 'CLOSED' else main.id))
        db.add(InventoryTransaction(organization_id=1, part_id=pids[1], transaction_type=TransactionType.OUTBOUND,
            quantity=11, from_warehouse_id=main.id))
        db.commit()
    for ticket in ['A', 'B']:
        reviewed(client, order(client, ticket), pids)
    failure = reviewed(client, order(client, 'FAILURE'), [pids[0]], 'unresolved')
    result = guidance(client, current)
    by_number = {p['part_number']: p for p in result['part_candidates']}
    assert result['needs_more_evidence']
    assert by_number['AVAILABLE']['non_resolved_source_case_ids'] == [failure]
    assert by_number['AVAILABLE']['evidence_status'] == 'limited'
    assert by_number['AVAILABLE']['non_resolved_evidence'][0]['outcome'] == 'unresolved'
    for number, state in [('NEGATIVE', 'inventory_inconsistent'), ('INACTIVE', 'inactive_part'), ('CLOSED', 'out_of_stock')]:
        assert by_number[number]['availability'] == state
        assert by_number[number]['available_quantity'] == 0
    assert all(not p['compatibility_confirmed'] for p in by_number.values())


def test_source_model_changes_and_tenant_poisoning_fail_closed(client):
    current, prior = order(client, 'CURRENT'), order(client, 'PRIOR')
    rid = reviewed(client, prior)
    with client.app.state.testing_session_local() as db:
        db.get(WorkOrder, prior).machine_type = '9000 Self-Serve'
        db.add(Organization(id=2, name='Other', slug='other-evidence')); db.flush()
        foreign = WorkOrder(organization_id=2, ticket_number='FOREIGN', machine_type='9100 Self-Serve')
        part = Part(organization_id=2, part_number='FOREIGN', name='Other organization')
        db.add_all([foreign, part]); db.flush()
        db.add(RepairCaseReport(organization_id=1, work_order_id=foreign.id, machine_model='9100 Self-Serve',
            symptom_codes=['low_flow'], steps=['Foreign data'], outcome='resolved', part_ids=[part.id],
            result_notes='Invalid tenant link', review_status='approved'))
        db.commit()
    result = guidance(client, current)
    assert not result['cases'] and not result['part_candidates']
    assert rid not in [c['case_id'] for c in result['cases']]
    with client.app.state.testing_session_local() as db:
        conflict = Equipment(organization_id=1, model='Viper 4'); db.add(conflict); db.flush()
        db.get(WorkOrder, current).equipment_id = conflict.id; db.commit()
    result = guidance(client, current)
    assert result['machine_model'] is None and result['needs_more_evidence']
    assert 'machine_model_unconfirmed' in {n['code'] for n in result['evidence_notices']}


def test_inventory_alone_wrong_symptom_and_other_models_do_not_recommend(client):
    current = order(client, 'CURRENT', 'Viper 3')
    with client.app.state.testing_session_local() as db:
        part = Part(organization_id=1, part_number='UNPROVEN', name='Unproven part')
        db.add(part); db.commit(); pid = part.id
    reviewed(client, order(client, 'VIPER2', 'Viper 2'), [pid])
    reviewed(client, order(client, 'VIPER4', 'Viper 4'), [pid])
    reviewed(client, order(client, 'WRONG-SYMPTOM', 'Viper 3'), [pid], code='NO_POWER')
    result = guidance(client, current)
    assert result['part_candidates'] == [] and result['reviewed_resolved_case_count'] == 0
    assert result['needs_more_evidence']


def test_case_source_permissions_do_not_expose_other_pending_or_foreign_reports(client):
    from app.core.rbac import Actor, get_current_actor
    from app.models import User, UserRole
    wid = order(client, 'SOURCE')
    payload = {'symptom_codes': ['X'], 'steps': ['Check'], 'outcome': 'resolved',
               'result_notes': 'Measured', 'part_ids': []}
    pending = client.post(f'/api/muse/work-orders/{wid}/reports', json=payload).json()['report_id']
    approved = reviewed(client, wid)
    with client.app.state.testing_session_local() as db:
        user = User(organization_id=1, name='Reader', email='source-reader@example.invalid', role=UserRole.ENGINEER)
        db.add(user); db.commit(); uid = user.id
    client.app.dependency_overrides[get_current_actor] = lambda: Actor(uid, UserRole.ENGINEER, 1)
    assert client.get(f'/api/muse/reports/{pending}').status_code == 404
    assert client.get(f'/api/muse/reports/{approved}').status_code == 200
    with client.app.state.testing_session_local() as db:
        db.get(RepairCaseReport, pending).submitted_by = uid; db.commit()
    assert client.get(f'/api/muse/reports/{pending}').status_code == 200
    client.app.dependency_overrides[get_current_actor] = lambda: Actor(uid, UserRole.ADMIN, 2)
    assert client.get(f'/api/muse/reports/{approved}').status_code == 404


def test_stock_does_not_outrank_independent_reviewed_case_evidence(client):
    current = order(client, 'CURRENT')
    with client.app.state.testing_session_local() as db:
        strong = Part(organization_id=1, part_number='STRONG', name='Two cases, no stock')
        weak = Part(organization_id=1, part_number='WEAK', name='One case, ample stock')
        warehouse = Warehouse(organization_id=1, code='MAIN', name='Main')
        db.add_all([strong, weak, warehouse]); db.flush()
        strong_id, weak_id = strong.id, weak.id
        db.add(InventoryTransaction(organization_id=1, part_id=weak_id, transaction_type=TransactionType.INBOUND,
                                   quantity=100, to_warehouse_id=warehouse.id))
        db.commit()
    reviewed(client, order(client, 'A'), [strong_id, weak_id])
    reviewed(client, order(client, 'B'), [strong_id])
    result = guidance(client, current)['part_candidates']
    assert [p['part_id'] for p in result] == [strong_id, weak_id]
    assert result[0]['available_quantity'] == 0 and result[0]['availability'] == 'out_of_stock'
    assert result[1]['available_quantity'] == 100 and result[1]['needs_more_evidence']
