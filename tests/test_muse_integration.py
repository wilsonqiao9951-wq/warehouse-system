from sqlalchemy import select
from app.core.config import settings
from app.models import Organization,Part,WorkOrder,User,UserRole,RepairCaseReport


def order(client,ticket,model='9100 Self-Serve'):
    return client.post('/api/work-orders',json={'ticket_number':ticket,'machine_type':model}).json()['id']


def report(client,wid,outcome='resolved'):
    return client.post(f'/api/muse/work-orders/{wid}/reports',json={'symptom_codes':['LOW_FLOW'],'steps':['Inspect documented filter condition'],'outcome':outcome,'result_notes':'Flow restored after documented repair','part_ids':[]})


def test_muse_discovery_query_and_auth(client):
    manifest=client.get('/api/muse').json();assert manifest['query_path']=='/api/muse/query'
    assert client.post('/api/muse/query',json={'resource':'freestyle_models'}).status_code==200
    assert client.post('/api/muse/query',json={'resource':'freestyle_parts'}).status_code==422
    assert client.post('/api/muse/query',json={'resource':'catalog','limit':101}).status_code==422
    settings.rbac_enforce=True
    assert client.post('/api/muse/query',json={'resource':'identity'}).status_code==401


def test_reviewed_outcome_learning_preserves_model_org_and_failure_evidence(client):
    current=order(client,'CURRENT');prior=order(client,'PRIOR');different=order(client,'OTHER','9000 Self-Serve')
    pending=report(client,prior);assert pending.status_code==200 and pending.json()['guidance_eligible'] is False
    def guidance():return client.get(f'/api/muse/work-orders/{current}/guidance',params={'symptom_code':'LOW_FLOW'}).json()['reviewed_guidance']
    assert guidance()['reviewed_resolved_case_count']==0
    assert client.post(f"/api/muse/reports/{pending.json()['report_id']}/review",json={'decision':'approved'}).status_code==200
    assert guidance()['reviewed_resolved_case_count']==1
    other=report(client,different).json();client.post(f"/api/muse/reports/{other['report_id']}/review",json={'decision':'approved'})
    assert guidance()['reviewed_resolved_case_count']==1
    repeated=report(client,prior,'unresolved').json();client.post(f"/api/muse/reports/{repeated['report_id']}/review",json={'decision':'approved'})
    result=guidance();assert result['reviewed_resolved_case_count']==0 and result['reviewed_non_resolved_case_count']==1
    assert result['model_training_performed'] is False and result['part_candidates']==[]
    assert client.post('/api/muse/query',json={'resource':'repair_guidance','work_order_id':current,'symptom_code':'LOW_FLOW'}).status_code==200
    with client.app.state.testing_session_local() as db:
        db.add(Organization(id=2,name='Other',slug='other'));db.flush();wo=WorkOrder(organization_id=2,ticket_number='FOREIGN',machine_type='9100 Self-Serve');db.add(wo);db.flush();foreign=wo.id;db.commit()
    assert report(client,foreign).status_code==404
    assert client.get(f'/api/muse/work-orders/{foreign}/guidance').status_code==404


def test_technician_cannot_review_or_submit_unclaimed_job(client):
    wid=order(client,'LOCKED')
    with client.app.state.testing_session_local() as db:
        tech=User(organization_id=1,name='Tech',email='tech@example.invalid',role=UserRole.ENGINEER,is_active=True);db.add(tech);db.commit();uid=tech.id
    rid=report(client,wid).json()['report_id']
    settings.rbac_enforce=True
    try:
        headers={'X-User-Id':str(uid)}
        assert client.post(f'/api/muse/reports/{rid}/review',json={'decision':'approved'},headers=headers).status_code==403
        r=client.post(f'/api/muse/work-orders/{wid}/reports',json={'symptom_codes':['X'],'steps':['Check'],'outcome':'resolved','result_notes':'done'},headers=headers)
        assert r.status_code in (401,403,409)
    finally:settings.rbac_enforce=False


def test_production_rejects_placeholder_secret_and_debug(monkeypatch):
    import pytest
    from app.core.config import validate_production_settings
    monkeypatch.setattr(settings,'app_env','production')
    monkeypatch.setattr(settings,'jwt_secret_key','development-only-change-me-32-bytes-minimum')
    with pytest.raises(RuntimeError):validate_production_settings()
    monkeypatch.setattr(settings,'jwt_secret_key','test-only-not-a-real-secret-'+('x'*32))
    monkeypatch.setattr(settings,'app_debug',True)
    with pytest.raises(RuntimeError):validate_production_settings()
    monkeypatch.setattr(settings,'app_debug',False)
    validate_production_settings()


def test_bootstrap_owner_is_one_time_and_hashes_password(client):
    import pytest
    from scripts.bootstrap_owner import create_owner
    from app.core.security import verify_password
    with client.app.state.testing_session_local() as db:
        uid=create_owner(db,'owner@example.invalid','temporary-test-password','Test team')
        user=db.get(User,uid)
        assert user.is_platform_admin and verify_password('temporary-test-password',user.password_hash)
        with pytest.raises(ValueError):create_owner(db,'second@example.invalid','temporary-test-password','Other')
