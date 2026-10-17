from app.models import Part,WorkOrder,RepairCaseReport,Organization
from test_repair_followup import submit,approve
from test_repair_guidance_evidence import order


def stats(client,**params):
    r=client.get('/api/muse/repair-statistics',params=params);r.raise_for_status();return r.json()


def test_latest_reviewed_case_counts_actual_use_and_sources(client):
    wid=order(client,'ONE')
    with client.app.state.testing_session_local() as db:
        p=Part(organization_id=1,part_number='USED',name='Used part');db.add(p);db.commit();pid=p.id
    first=submit(client,wid,{'recurrence':'not_observed','observation_days':7,'actual_parts':[{'part_id':pid,'quantity':2}],'actual_parts_complete':True}).json()['report_id'];approve(client,first)
    second=submit(client,wid,{'previous_report_id':first,'recurrence':'recurred','observation_days':14,'actual_parts':[{'part_id':pid,'quantity':1}],'actual_parts_complete':True}).json()['report_id']
    assert stats(client)['items'][0]['recurrence_counts']['recurred']==0
    approve(client,second)
    group=stats(client)['items'][0]
    assert group['work_order_count']==1 and group['actual_parts'][0]['reported_quantity']==1
    assert group['recurrence_counts']['recurred']==1 and group['repeat_failure_signal']
    assert group['needs_more_evidence'] and not group['compatibility_confirmed']
    assert group['actual_parts'][0]['source_case_ids']==[second]
    cases=client.get(group['sources_path']).json()
    assert cases['items'][0]['case_id']==second and cases['total']==1
    assert client.get(cases['items'][0]['source_path']).status_code==200
    approve(client,submit(client,order(client,'TWO')).json()['report_id'])
    assert stats(client)['items'][0]['work_order_count']==2


def test_exact_models_unknown_filters_and_model_correction(client):
    for model in ['9100 Self-Serve','9000 Self-Serve','Viper 3']:
        approve(client,submit(client,order(client,model,model)).json()['report_id'])
    result=stats(client);assert result['total']==3
    assert stats(client,machine_model='9100 Self-Serve',symptom_code='LOW-FLOW')['total']==1
    assert stats(client,symptom_code='NOT_A_CODE')['total']==0
    assert stats(client,machine_model='Viper 2')['needs_more_evidence']
    with client.app.state.testing_session_local() as db:
        source=db.query(WorkOrder).filter_by(machine_type='9100 Self-Serve').one();source.machine_type='Viper 4';db.commit()
    assert stats(client)['excluded_report_counts']['unconfirmed_model_reports']==1
    assert stats(client)['total']==2


def test_multisymptom_and_foreign_records_do_not_inflate(client):
    wid=order(client,'MULTI')
    r=client.post(f'/api/muse/work-orders/{wid}/reports',json={'symptom_codes':['low_flow','leak'],'steps':['check'],'outcome':'partial','part_ids':[],'result_notes':'result'});r.raise_for_status();approve(client,r.json()['report_id'])
    assert stats(client)['total']==2
    assert all(i['work_order_count']==1 for i in stats(client)['items'])
    with client.app.state.testing_session_local() as db:
        db.add(Organization(id=2,name='Other',slug='other'));db.flush()
        job=WorkOrder(organization_id=2,ticket_number='FOREIGN',machine_type='9100 Self-Serve');db.add(job);db.flush()
        db.add(RepairCaseReport(organization_id=2,work_order_id=job.id,machine_model='9100 Self-Serve',symptom_codes=['low_flow'],steps=['check'],outcome='resolved',part_ids=[],result_notes='private',review_status='approved'));db.commit()
    result=client.post('/api/muse/query',json={'resource':'repair_statistics','machine_model':'9100 Self-Serve','symptom_code':'low_flow'});result.raise_for_status()
    assert result.json()['items'][0]['work_order_count']==1
    assert stats(client,limit=1)['total']==2 and len(stats(client,limit=1)['items'])==1
    assert client.get('/api/muse/repair-statistics/cases?machine_model=x&symptom_code=y&limit=101').status_code==422
