import hashlib,hmac,json,time
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from app.core.database import get_db
from app.core.config import settings
from app.core.security import create_access_token
from app.integrations.whatsapp import create_app
from app.models import Organization,User,UserRole,WorkOrder,RepairCaseReport,AuditLog,Part

SECRET='simulation-only-secret-'+('x'*40)
PHONE='15550000001';OTHER='15550000002'
REPORT={'symptom_codes':['low_flow'],'steps':['Synthetic measured flow check'],'outcome':'resolved','result_notes':'Synthetic flow restored'}

@pytest.fixture
def setup(client,tmp_path):
    settings.rbac_enforce=True;settings.legacy_header_auth=False
    factory=client.app.state.testing_session_local
    with factory() as db:
        db.add(Organization(id=2,name='Other',slug='other-wa'));db.flush()
        users=[User(organization_id=o,name=n,email=n+'@example.invalid',role=r,is_active=True) for o,n,r in [(1,'admin',UserRole.ADMIN),(1,'tech',UserRole.ENGINEER),(1,'teammate',UserRole.ENGINEER),(2,'foreign',UserRole.ENGINEER)]]
        db.add_all(users);db.flush()
        jobs=[WorkOrder(organization_id=o,ticket_number='WA-'+str(o),machine_type='9100 Self-Serve',problem_description='出液量小') for o in [1,2]];db.add_all(jobs)
        part=Part(organization_id=2,part_number='FOREIGN',name='foreign');db.add(part);db.commit()
        ids=[u.id for u in users];wids=[w.id for w in jobs];pid=part.id
    app=create_app(enabled=True,signing_secret=SECRET,state_path=tmp_path/'channel.sqlite3')
    app.dependency_overrides[get_db]=client.app.dependency_overrides[get_db]
    admin={'Authorization':'Bearer '+create_access_token(ids[0],1)[0]}
    with TestClient(app) as api:
        yield api,admin,ids,wids,pid,factory,tmp_path/'channel.sqlite3'

def send(api,action,args=None,phone=PHONE,eid=None,text='',secret=SECRET,stamp=None,**overrides):
    body={'provider_id':'simulation','recipient_id':'simulation-line','sender_id':phone,'event_id':eid or uuid4().hex,'chat_type':'individual','action':action,'arguments':args or {},'user_text':text};body.update(overrides)
    raw=json.dumps(body,separators=(',',':')).encode();stamp=str(stamp or int(time.time()))
    sig='sha256='+hmac.new(secret.encode(),stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
    return api.post('/api/channels/whatsapp/events',content=raw,headers={'Content-Type':'application/json','X-Channel-Timestamp':stamp,'X-Channel-Signature':sig})

def bind(s,phone=PHONE,uid=None):
    api,admin,ids,*_=s
    r=api.post('/api/channels/whatsapp/bindings',json={'user_id':uid or ids[1],'sender_id':phone},headers=admin);assert r.status_code==200,r.text
    code=r.json()['binding_code'];r=send(api,'bind',{'binding_code':code},phone=phone);assert r.status_code==200,r.text
    return code

def claim(s):
    wid=s[3][0];r=send(s[0],'claim',{'work_order_id':wid},text=f'领取工单 {wid}');assert r.status_code==200,r.text
    return r.json()['data']['claim_version']

def draft(s,payload=None):
    version=claim(s)
    r=send(s[0],'report_draft',{'work_order_id':s[3][0],'claim_version':version,'report':payload or REPORT});assert r.status_code==200,r.text
    return r.json()['data']

def test_disabled_and_signature_boundary(setup):
    api=setup[0]
    with TestClient(create_app()) as disabled:assert disabled.post('/api/channels/whatsapp/events',json={}).status_code==503
    assert send(api,'query',{'query':{'resource':'identity'}},secret='wrong').status_code==401
    assert send(api,'query',{},stamp=int(time.time())-600).status_code==401
    assert send(api,'query',{},chat_type='group').status_code==422
    assert send(api,'query',{},provider_id='forged').status_code==403
    assert send(api,'query',{},recipient_id='other-line').status_code==403
    assert send(api,'query',{'query':{'resource':'identity'}}).status_code==403

def test_binding_is_admin_scoped_and_sender_proven(setup):
    api,admin,ids,_,_,factory,_=setup
    assert api.post('/api/channels/whatsapp/bindings',json={'user_id':ids[3],'sender_id':PHONE},headers=admin).status_code==404
    tech={'Authorization':'Bearer '+create_access_token(ids[1],1)[0]}
    assert api.post('/api/channels/whatsapp/bindings',json={'user_id':ids[1],'sender_id':PHONE},headers=tech).status_code==403
    invite=api.post('/api/channels/whatsapp/bindings',json={'user_id':ids[1],'sender_id':PHONE},headers=admin).json()
    assert send(api,'bind',{'binding_code':invite['binding_code']},phone=OTHER).status_code==403
    assert send(api,'bind',{'binding_code':'incorrect'}).status_code==403
    eid=uuid4().hex
    first=send(api,'bind',{'binding_code':invite['binding_code']},eid=eid);assert first.status_code==200
    assert send(api,'bind',{'binding_code':invite['binding_code']},eid=eid).json()['replayed']
    assert send(api,'bind',{'binding_code':invite['binding_code']}).status_code==403
    identity=send(api,'query',{'query':{'resource':'identity'}}).json()
    assert identity['data']['user_id']==ids[1] and identity['data']['organization_id']==1
    assert identity['reply_to']['recipient_id']==PHONE and identity['delivery_status']=='not_sent'

def test_queries_claims_and_feedback_are_tenant_scoped(setup):
    bind(setup);api=setup[0];foreign=setup[3][1]
    rows=send(api,'query',{'query':{'resource':'work_orders','scope':'all'}}).json()['data'];assert {r['id'] for r in rows}=={setup[3][0]}
    assert send(api,'query',{'query':{'resource':'identity','organization_id':2}}).status_code==422
    assert send(api,'query',{'query':{'resource':'repair_guidance','work_order_id':foreign}}).status_code==404
    assert send(api,'claim',{'work_order_id':foreign},text=f'领取工单 {foreign}').status_code==404
    assert send(api,'claim',{'work_order_id':setup[3][0]}).status_code==422
    d=draft(setup,{**REPORT,'part_ids':[setup[4]]})
    r=send(api,'report_confirm',{'draft_id':d['draft_id']},text=d['confirmation_text']);assert r.status_code==404
    with setup[5]() as db:assert db.scalar(select(func.count()).select_from(RepairCaseReport))==0

def test_confirmation_retry_and_distinct_event_ids_single_report(setup):
    bind(setup);d=draft(setup);api=setup[0]
    with setup[5]() as db:assert db.scalar(select(func.count()).select_from(RepairCaseReport))==0
    assert send(api,'report_confirm',{'draft_id':d['draft_id']},text='确认').status_code==422
    eid=uuid4().hex;args={'draft_id':d['draft_id']}
    first=send(api,'report_confirm',args,eid=eid,text=d['confirmation_text']);assert first.status_code==200,first.text
    a=first.json()['data'];assert a['review_status']=='pending' and a['guidance_eligible'] is False
    for eventid in [eid,uuid4().hex]:
        r=send(api,'report_confirm',args,eid=eventid,text=d['confirmation_text']);assert r.status_code==200 and r.json()['data']['report_id']==a['report_id'] and r.json()['data']['replayed']
    assert send(api,'query',{'query':{'resource':'identity'}},eid=eid).status_code==409
    with setup[5]() as db:
        assert db.scalar(select(func.count()).select_from(RepairCaseReport))==1
        assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action=='submit_repair_case'))==1
    guidance=send(api,'query',{'query':{'resource':'repair_guidance','work_order_id':setup[3][0],'symptom_code':'low_flow'}}).json()['data']['reviewed_guidance'];assert guidance['reviewed_resolved_case_count']==0

def test_revocation_inactivity_claim_version_and_draft_owner(setup):
    bind(setup);d=draft(setup);api=setup[0]
    bind(setup,OTHER,setup[2][2])
    assert send(api,'report_confirm',{'draft_id':d['draft_id']},phone=OTHER,text=d['confirmation_text']).status_code==404
    with setup[5]() as db:
        order=db.get(WorkOrder,setup[3][0]);order.claim_version+=1;db.commit()
    assert send(api,'report_confirm',{'draft_id':d['draft_id']},text=d['confirmation_text']).status_code==409
    assert api.delete('/api/channels/whatsapp/bindings/'+PHONE,headers=setup[1]).status_code==200
    assert send(api,'query',{'query':{'resource':'identity'}}).status_code==403
    with setup[5]() as db:
        user=db.get(User,setup[2][2]);user.is_active=False;db.commit()
    assert send(api,'query',{'query':{'resource':'identity'}},phone=OTHER).status_code==403

def test_concurrent_confirmation_and_persisted_deduplication(setup):
    bind(setup);d=draft(setup)
    def submit(_):return send(setup[0],'report_confirm',{'draft_id':d['draft_id']},text=d['confirmation_text'])
    with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(submit,range(2)))
    assert all(r.status_code==200 for r in responses),[r.text for r in responses]
    assert len({r.json()['data']['report_id'] for r in responses})==1
    # Simulate process restart with the same persistent adapter database.
    app=create_app(enabled=True,signing_secret=SECRET,state_path=setup[6]);app.dependency_overrides[get_db]=setup[0].app.dependency_overrides[get_db]
    with TestClient(app) as other:
        r=send(other,'report_confirm',{'draft_id':d['draft_id']},text=d['confirmation_text']);assert r.status_code==200 and r.json()['data']['replayed']

def test_expiry_tampering_and_rebinding_invalidates_old_events(setup):
    import sqlite3
    api=setup[0];code=bind(setup);eid=uuid4().hex
    assert send(api,'query',{'query':{'resource':'identity'}},eid=eid).status_code==200
    d=draft(setup)
    with sqlite3.connect(setup[6]) as c:c.execute('UPDATE drafts SET expires=0')
    assert send(api,'report_confirm',{'draft_id':d['draft_id']},text=d['confirmation_text']).status_code==410
    assert send(api,'report_confirm',{'draft_id':[]},text='confirm').status_code==422
    assert api.delete('/api/channels/whatsapp/bindings/'+PHONE,headers=setup[1]).status_code==200
    bind(setup)
    assert send(api,'query',{'query':{'resource':'identity'}},eid=eid).status_code==409
    assert send(api,'bind',{'binding_code':code}).status_code==403
    assert send(api,'report_confirm',{'draft_id':d['draft_id']},text=d['confirmation_text']).status_code==410
    # The new channel device cannot silently take over an old device's claimed work order.
    assert send(api,'claim',{'work_order_id':setup[3][0]},text=f'领取工单 {setup[3][0]}').status_code==409

def test_bound_phone_cannot_choose_another_organization(setup):
    api,admin,ids,wids,_,factory,state=setup
    with factory() as db:
        foreign_admin=User(organization_id=2,name='foreign-admin',email='foreign-admin@example.invalid',role=UserRole.ADMIN,is_active=True);db.add(foreign_admin);db.commit();uid=foreign_admin.id
    foreign_auth={'Authorization':'Bearer '+create_access_token(uid,2)[0]}
    bind(setup)
    r=api.post('/api/channels/whatsapp/bindings',json={'user_id':ids[3],'sender_id':OTHER},headers=foreign_auth);assert r.status_code==200
    assert send(api,'bind',{'binding_code':r.json()['binding_code']},phone=OTHER).status_code==200
    rows=send(api,'query',{'query':{'resource':'work_orders','scope':'all'}},phone=OTHER).json()['data'];assert {r['id'] for r in rows}=={wids[1]}
    assert api.delete('/api/channels/whatsapp/bindings/'+PHONE,headers=foreign_auth).status_code==404
    assert send(api,'query',{'query':{'resource':'repair_guidance','work_order_id':wids[0]}},phone=OTHER).status_code==404

def test_backend_commit_before_adapter_crash_is_safe_to_retry(setup,monkeypatch):
    from app.integrations import whatsapp
    bind(setup);d=draft(setup);original=whatsapp.submit_report
    def interrupted(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('Simulated adapter crash after backend commit')
    monkeypatch.setattr(whatsapp,'submit_report',interrupted)
    eid=uuid4().hex
    with pytest.raises(RuntimeError):send(setup[0],'report_confirm',{'draft_id':d['draft_id']},eid=eid,text=d['confirmation_text'])
    monkeypatch.setattr(whatsapp,'submit_report',original)
    r=send(setup[0],'report_confirm',{'draft_id':d['draft_id']},eid=eid,text=d['confirmation_text']);assert r.status_code==200 and r.json()['data']['replayed']
    with setup[5]() as db:assert db.scalar(select(func.count()).select_from(RepairCaseReport))==1
