from datetime import datetime,timedelta,timezone
from app.models import Organization,RepairCaseReport,WorkOrder
from test_repair_followup import submit,approve
from test_repair_guidance_evidence import order,guidance


def schedule(client,rid,days=-1):
    return client.put(f'/api/muse/reports/{rid}/followup-schedule',json={'due_at':(datetime.now(timezone.utc)+timedelta(days=days)).isoformat(),'reason':'Follow up repair'})


def listing(client,status='all'):
    r=client.get('/api/muse/followups',params={'scope':'all','status':status});r.raise_for_status();return r.json()


def test_due_pending_rejected_and_reviewed_completion(client):
    wid=order(client,'SOURCE');current=order(client,'CURRENT')
    rid=submit(client,wid).json()['report_id']
    assert schedule(client,rid).status_code==409
    approve(client,rid);schedule(client,rid).raise_for_status()
    item=listing(client)['items'][0]
    assert item['status']=='due' and item['reminder_required'] and item['previous_report_id']==rid
    follow=submit(client,wid,{'previous_report_id':rid,'recurrence':'recurred','observation_days':7}).json()['report_id']
    assert listing(client)['items'][0]['status']=='awaiting_review'
    assert guidance(client,current)['reviewed_resolved_case_count']==1
    client.post(f'/api/muse/reports/{follow}/review',json={'decision':'rejected'}).raise_for_status()
    assert listing(client)['items'][0]['status']=='due'
    approve(client,follow)
    item=listing(client)['items'][0]
    assert item['status']=='completed' and item['followup_report_id']==follow and not item['reminder_required']
    assert not listing(client,'open')['items']
    assert guidance(client,current)['reviewed_resolved_case_count']==0


def test_schedule_validation_cancel_and_gateway(client):
    wid=order(client,'SOURCE');rid=submit(client,wid).json()['report_id'];approve(client,rid)
    assert client.put(f'/api/muse/reports/{rid}/followup-schedule',json={'due_at':'2026-11-01T12:00:00','reason':'check'}).status_code==422
    schedule(client,rid,3).raise_for_status()
    r=client.post('/api/muse/query',json={'resource':'followups','scope':'all','followup_status':'upcoming'});r.raise_for_status()
    assert r.json()['items'][0]['status']=='upcoming' and not r.json()['items'][0]['reminder_required']
    assert client.get('/api/muse/followups?limit=101').status_code==422
    assert client.get('/api/muse/followups?skip=-1').status_code==422
    assert client.put(f'/api/muse/reports/{rid}/followup-schedule',json={'due_at':None,'reason':'Cancelled after reassessment'}).json()['cancelled']
    assert listing(client)['total']==0


def test_foreign_reports_and_schedules_are_hidden(client):
    wid=order(client,'SOURCE');rid=submit(client,wid).json()['report_id'];approve(client,rid);schedule(client,rid)
    with client.app.state.testing_session_local() as db:
        db.add(Organization(id=2,name='Other',slug='other'));db.flush()
        job=WorkOrder(organization_id=2,ticket_number='FOREIGN',machine_type='9100 Self-Serve');db.add(job);db.flush()
        report=RepairCaseReport(organization_id=2,work_order_id=job.id,machine_model='9100 Self-Serve',symptom_codes=['low_flow'],steps=['check'],outcome='resolved',part_ids=[],result_notes='result',review_status='approved',followup_due_at=datetime.now(timezone.utc).replace(tzinfo=None))
        db.add(report);db.commit();foreign=report.id
    assert [i['report_id'] for i in listing(client)['items']]==[rid]
    assert schedule(client,foreign).status_code==404
    assert client.get('/api/muse/followups').json()['total']==0
