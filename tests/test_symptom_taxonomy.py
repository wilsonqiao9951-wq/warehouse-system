from app.models import Organization, RepairCaseReport, WorkOrder
from app.services import symptoms


def job(client, ticket, description='', model='9100 Self-Serve'):
    r=client.post('/api/work-orders',json={'ticket_number':ticket,'machine_type':model,'problem_description':description})
    r.raise_for_status()
    return r.json()['id']


def feedback(client,wid,**extra):
    return client.post(f'/api/muse/work-orders/{wid}/reports',json={
        'steps':['Recorded checks'],'outcome':'resolved','result_notes':'Recorded results',**extra})


def approve(client,rid):
    r=client.post(f'/api/muse/reports/{rid}/review',json={'decision':'approved'});r.raise_for_status();return r.json()


def test_codes_aliases_and_ambiguous_text_are_not_diagnoses():
    r=symptoms.resolve(['LOW_FLOW','low-flow','出液量小'],text='流量小；漏水')
    assert r['canonical_codes']==['leak','low_flow'] and not r['needs_confirmation']
    assert r['raw_codes']==['LOW_FLOW','low-flow','出液量小'] and r['taxonomy_version']=='1.0'
    r=symptoms.resolve(text='没有漏水，只是怀疑流量小')
    assert not r['canonical_codes'] and r['needs_confirmation']
    assert 'leak' in r['suggested_codes'] and 'low_flow' in r['suggested_codes']
    assert symptoms.resolve(['UNLISTED'])['unknown_codes']==['UNLISTED']
    assert len({i['code'] for i in symptoms.taxonomy()['items']})==13


def test_feedback_preserves_raw_input_and_text_only_reports(client):
    wid=job(client,'TEXT')
    r=feedback(client,wid,symptom_text='出液量小；漏水');r.raise_for_status()
    result=r.json();rid=result['report_id']
    assert result['symptom_resolution']['canonical_codes']==['leak','low_flow']
    assert approve(client,rid)['guidance_eligible']
    source=client.get(f'/api/muse/reports/{rid}').json()
    assert source['symptom_resolution']['raw_text']=='出液量小；漏水'
    with client.app.state.testing_session_local() as db:
        report=db.get(RepairCaseReport,rid)
        assert report.symptom_codes==['leak','low_flow']
        assert report.symptom_context['source']=='technician_report'
        assert report.symptom_context['taxonomy_version']=='1.0'
    unknown=feedback(client,wid,symptom_codes=['CUSTOM_123'],symptom_text='需要进一步排查').json()
    assert unknown['symptom_resolution']['unknown_codes']==['CUSTOM_123']
    assert not approve(client,unknown['report_id'])['guidance_eligible']
    assert feedback(client,wid,symptom_codes=[],symptom_text='  ').status_code==422


def test_work_order_symptoms_and_alias_queries_retrieve_same_model_cases(client):
    current=job(client,'CURRENT','出液量小')
    prior=job(client,'PRIOR')
    other=job(client,'OTHER',model='9000 Self-Serve')
    rid=feedback(client,prior,symptom_codes=['weak flow']).json()['report_id'];approve(client,rid)
    approve(client,feedback(client,other,symptom_codes=['LOW_FLOW']).json()['report_id'])
    resolved=client.get(f'/api/muse/work-orders/{current}/symptoms').json()
    assert resolved['canonical_codes']==['low_flow']
    assert resolved['source']=='work_order_problem_description'
    queries=[{}, {'symptom_code':'LOW_FLOW'}, {'symptom_text':'出水量小'}, {'symptom_codes':['weak flow']}]
    for query in queries:
        r=client.post('/api/muse/query',json={'resource':'repair_guidance','work_order_id':current,**query})
        r.raise_for_status();data=r.json()
        assert data['reviewed_guidance']['reviewed_resolved_case_count']==1
        assert data['reviewed_guidance']['cases'][0]['case_id']==rid
        assert data['symptom_resolution']['canonical_codes']==['low_flow']
    r=client.post('/api/muse/query',json={'resource':'symptoms','work_order_id':current}).json()
    assert r['raw_text']=='出液量小'
    r=client.get(f'/api/muse/work-orders/{current}/guidance',params={'symptom_text':'没有漏水，只是怀疑流量小'}).json()
    assert not r['reviewed_guidance']['cases'] and not r['reviewed_guidance']['part_candidates']
    assert r['symptom_resolution']['needs_confirmation']


def test_legacy_report_aliases_are_read_without_rewriting_and_unknowns_do_not_match(client):
    current=job(client,'CURRENT','流量小')
    prior=job(client,'LEGACY')
    with client.app.state.testing_session_local() as db:
        report=RepairCaseReport(organization_id=1,work_order_id=prior,machine_model='9100 Self-Serve',
            symptom_codes=['LOW-FLOW'],steps=['Legacy reported check'],outcome='resolved',part_ids=[],
            result_notes='Legacy result',review_status='approved')
        db.add(report);db.commit();rid=report.id
    data=client.get(f'/api/muse/work-orders/{current}/guidance').json()['reviewed_guidance']
    assert data['cases'][0]['case_id']==rid
    assert data['cases'][0]['symptom_resolution']['source']=='legacy_report_code_lookup'
    with client.app.state.testing_session_local() as db:
        report=db.get(RepairCaseReport,rid);assert report.symptom_codes==['LOW-FLOW'] and report.symptom_context is None
    data=client.get(f'/api/muse/work-orders/{current}/guidance',params={'symptom_code':'UNKNOWN'}).json()
    assert not data['reviewed_guidance']['cases'] and data['symptom_resolution']['unknown_codes']==['UNKNOWN']


def test_symptom_resolution_scope_auth_and_limits(client):
    from app.core.config import settings
    wid=job(client,'OWN','流量小')
    with client.app.state.testing_session_local() as db:
        db.add(Organization(id=2,name='Other',slug='other-symptoms'));db.flush()
        foreign=WorkOrder(organization_id=2,ticket_number='FOREIGN',machine_type='9100 Self-Serve',problem_description='Private foreign symptom')
        db.add(foreign);db.commit();fid=foreign.id
    assert client.get('/api/muse/symptoms').status_code==200
    assert client.get(f'/api/muse/work-orders/{fid}/symptoms').status_code==404
    assert client.post('/api/muse/symptoms/resolve',json={'work_order_id':fid}).status_code==404
    assert client.post('/api/muse/query',json={'resource':'symptoms','work_order_id':fid}).status_code==404
    assert client.post('/api/muse/symptoms/resolve',json={'symptom_text':'x'*5001}).status_code==422
    assert client.post('/api/muse/query',json={'resource':'symptoms','symptom_codes':['x'*81]}).status_code==422
    settings.rbac_enforce=True
    assert client.post('/api/muse/symptoms/resolve',json={'work_order_id':wid}).status_code==401
    assert client.get(f'/api/muse/work-orders/{wid}/symptoms').status_code==401


def test_alias_retry_is_idempotent_and_changed_free_text_conflicts(client):
    wid=job(client,'RETRY')
    payload={'symptom_codes':['LOW_FLOW'],'steps':['Check'],'outcome':'resolved','result_notes':'Measured'}
    headers={'Idempotency-Key':'symptom-test-1234567890'}
    first=client.post(f'/api/muse/work-orders/{wid}/reports',json=payload,headers=headers).json()
    retry=client.post(f'/api/muse/work-orders/{wid}/reports',json={**payload,'symptom_codes':['流量小']},headers=headers)
    assert retry.status_code==200 and retry.json()['report_id']==first['report_id'] and retry.json()['replayed']
    conflict=client.post(f'/api/muse/work-orders/{wid}/reports',json={**payload,'symptom_text':'new observation'},headers=headers)
    assert conflict.status_code==409
