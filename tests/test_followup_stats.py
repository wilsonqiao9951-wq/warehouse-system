from datetime import datetime,timedelta,timezone
from app.models import RepairCaseReport,Organization,WorkOrder
from test_repair_followup import submit,approve
from test_repair_guidance_evidence import order
from test_followup_schedule import schedule


def stats(client):
    r=client.get('/api/muse/followups/stats?scope=all');r.raise_for_status();return r.json()


def test_overdue_late_and_review_waiting_are_distinct(client):
    wid=order(client,'DELAY');rid=submit(client,wid).json()['report_id'];approve(client,rid);schedule(client,rid,-3)
    data=stats(client);assert data['overdue_work_order_count']==1 and data['submission_timing_counts']['overdue']==1
    item=client.get('/api/muse/followups?scope=all&status=overdue').json()['items'][0]
    assert item['overdue_days']==3 and item['followup_needed']
    fid=submit(client,wid,{'previous_report_id':rid,'recurrence':'recurred'}).json()['report_id']
    data=stats(client)
    assert data['overdue_work_order_count']==0 and data['status_counts']['awaiting_review']==1
    assert data['submission_timing_counts']['late']==1 and data['reviewed_recurrence_count']==0
    assert client.get('/api/muse/followups?scope=all&status=late').json()['total']==1
    approve(client,fid)
    data=stats(client);assert data['reviewed_recurrence_count']==1 and data['status_counts']['completed']==1
    assert data['submission_timing_counts']['late']==1
    assert client.get(data['sources']['recurrences']).json()['items'][0]['report_id']==fid
    client.post(f'/api/muse/reports/{fid}/review',json={'decision':'rejected'}).raise_for_status()
    assert stats(client)['submission_timing_counts']['overdue']==1 and stats(client)['reviewed_recurrence_count']==0


def test_on_time_submission_not_overdue_while_review_waits(client):
    wid=order(client,'TIMELY');rid=submit(client,wid).json()['report_id'];approve(client,rid);schedule(client,rid,-1)
    fid=submit(client,wid,{'previous_report_id':rid,'recurrence':'unknown'}).json()['report_id']
    with client.app.state.testing_session_local() as db:
        db.get(RepairCaseReport,fid).created_at=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(days=2);db.commit()
    data=stats(client)
    assert data['submission_timing_counts']['on_time']==1 and data['overdue_work_order_count']==0
    assert data['status_counts']['awaiting_review']==1
    assert client.get('/api/muse/followups?scope=all&status=overdue').json()['total']==0


def test_unscheduled_recurrences_latest_reviewed_and_tenant_scope(client):
    wid=order(client,'UNSCHEDULED');rid=submit(client,wid,{'recurrence':'recurred'}).json()['report_id'];approve(client,rid)
    assert stats(client)['scheduled_followup_count']==0 and stats(client)['reviewed_recurrence_count']==1
    next_id=submit(client,wid,{'previous_report_id':rid,'recurrence':'not_observed','observation_days':7}).json()['report_id']
    assert stats(client)['reviewed_recurrence_count']==1
    approve(client,next_id);assert stats(client)['reviewed_recurrence_count']==0
    with client.app.state.testing_session_local() as db:
        db.add(Organization(id=2,name='Other',slug='other'));db.flush()
        job=WorkOrder(organization_id=2,ticket_number='FOREIGN');db.add(job);db.flush()
        db.add(RepairCaseReport(organization_id=2,work_order_id=job.id,symptom_codes=['low_flow'],steps=['check'],outcome='unresolved',part_ids=[],result_notes='result',review_status='approved',repair_followup={'recurrence':'recurred'}));db.commit()
    assert stats(client)['reviewed_recurrence_count']==0
    result=client.post('/api/muse/query',json={'resource':'followup_stats','scope':'all'});result.raise_for_status()
    assert result.json()['reviewed_recurrence_count']==0
    assert client.post('/api/muse/query',json={'resource':'repair_recurrences','scope':'all'}).json()['total']==0
    assert client.get('/api/muse/followups/recurrences?limit=101').status_code==422
