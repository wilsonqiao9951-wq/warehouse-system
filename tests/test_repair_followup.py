from app.models import Organization, Part, RepairCaseReport
from test_repair_guidance_evidence import order, guidance


def submit(client,wid,closure=None,key=None):
    body={'symptom_codes':['low_flow'],'steps':['Measured flow after repair'], 'outcome':'resolved','result_notes':'Observed result'}
    if closure is not None:body['repair_followup']=closure
    return client.post(f'/api/muse/work-orders/{wid}/reports',json=body,headers={'Idempotency-Key':key} if key else {})


def approve(client,rid):
    r=client.post(f'/api/muse/reports/{rid}/review',json={'decision':'approved'});r.raise_for_status();return r.json()


def test_reviewed_recurrence_replaces_success_without_erasing_history(client):
    current,prior=order(client,'CURRENT'),order(client,'PRIOR')
    first=submit(client,prior).json()['report_id'];approve(client,first)
    closure={'previous_report_id':first,'recurrence':'recurred','observation_days':7}
    follow=submit(client,prior,closure).json()['report_id']
    assert guidance(client,current)['cases'][0]['case_id']==first
    assert not approve(client,follow)['guidance_eligible']
    result=guidance(client,current)
    assert result['reviewed_resolved_case_count']==0 and not result['part_candidates']
    assert result['non_resolved_cases'][0]['case_id']==follow
    assert any(n['code']=='reviewed_recurrence_present' for n in result['evidence_notices'])
    source=client.get(f'/api/muse/reports/{follow}').json()
    assert source['repair_followup']['previous_report_id']==first
    assert not source['guidance_eligible']
    assert client.get(f'/api/muse/reports/{first}').json()['outcome']=='resolved'
    approve_response=client.post(f'/api/muse/reports/{follow}/review',json={'decision':'rejected'})
    assert approve_response.status_code==200
    assert guidance(client,current)['cases'][0]['case_id']==first


def test_actual_parts_are_separate_from_mentions_and_do_not_certify_fit(client):
    current,prior=order(client,'CURRENT'),order(client,'PRIOR')
    with client.app.state.testing_session_local() as db:
        p=Part(organization_id=1,part_number='ACTUAL',name='Actual part');db.add(p);db.commit();pid=p.id
    rid=submit(client,prior,{'recurrence':'not_observed','observation_days':14,'actual_parts':[{'part_id':pid,'quantity':2}],'actual_parts_complete':True}).json()['report_id']
    approve(client,rid)
    result=guidance(client,current);part=result['part_candidates'][0]
    assert part['part_id']==pid and part['actual_use_evidence'][0]['quantity']==2
    assert part['actual_use_evidence'][0]['case_id']==rid
    assert not part['compatibility_confirmed'] and part['recommended_quantity'] is None
    source=client.get(f'/api/muse/reports/{rid}').json()
    assert source['part_ids']==[] and source['repair_followup']['actual_parts_complete']
    assert source['actual_use_source']=='technician_reported_actual_use'


def test_followup_validation_and_tenant_boundaries(client):
    wid,other=order(client,'ONE'),order(client,'OTHER')
    rid=submit(client,other).json()['report_id']
    assert submit(client,wid,{'previous_report_id':rid}).status_code==404
    assert submit(client,wid,{'recurrence':'not_observed'}).status_code==422
    assert submit(client,wid,{'actual_parts':[{'part_id':1,'quantity':0}]}).status_code==422
    assert submit(client,wid,{'actual_parts':[{'part_id':1,'quantity':1},{'part_id':1,'quantity':2}]}).status_code==422
    with client.app.state.testing_session_local() as db:
        db.add(Organization(id=2,name='Other',slug='other'));db.flush()
        p=Part(organization_id=2,part_number='FOREIGN',name='Foreign');db.add(p);db.commit();pid=p.id
    assert submit(client,wid,{'actual_parts':[{'part_id':pid,'quantity':1}]}).status_code==404
    rid=submit(client,wid).json()['report_id']
    response=client.post(f'/api/muse/work-orders/{wid}/reports',json={'symptom_codes':['leak'],'steps':['check'],'outcome':'resolved','result_notes':'result','repair_followup':{'previous_report_id':rid}})
    assert response.status_code==422


def test_followup_idempotency_and_changed_observation_conflict(client):
    wid=order(client,'ONE');key='repair-followup-test-key'
    body={'recurrence':'not_observed','observation_days':5}
    first=submit(client,wid,body,key);first.raise_for_status()
    assert submit(client,wid,body,key).json()['report_id']==first.json()['report_id']
    assert submit(client,wid,dict(body,observation_days=6),key).status_code==409
    with client.app.state.testing_session_local() as db:
        assert db.query(RepairCaseReport).count()==1
