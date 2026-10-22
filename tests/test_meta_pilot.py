import json
import hashlib
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient
from app.core.database import get_db
from app.core.security import create_access_token
from app.models import UserRole
from app.integrations.whatsapp import create_app
from app.integrations.meta_whatsapp import Bridge
from scripts.meta_worker import SyntheticSender
from scripts import meta_preflight
from test_whatsapp_adapter import setup,send,SECRET,PHONE
from test_meta_production import production


@pytest.fixture
def pilot(setup,tmp_path):
    app=create_app(enabled=True,signing_secret=SECRET,state_path=tmp_path/'pilot.db',pilot_required=True)
    app.dependency_overrides[get_db]=setup[0].app.dependency_overrides[get_db]
    with TestClient(app) as api:yield api,setup,tmp_path/'pilot.db'


def grant(p):
    return p[0].put('/api/channels/whatsapp/pilots',headers=p[1][1],json={'user_id':p[1][2][1],'sender_id':PHONE,'reason':'Synthetic pilot approval'})


def invite(p):
    return p[0].post('/api/channels/whatsapp/bindings',headers=p[1][1],json={'user_id':p[1][2][1],'sender_id':PHONE})


def revoke(p):
    return p[0].delete('/api/channels/whatsapp/pilots/'+PHONE,headers=p[1][1],params={'reason':'Synthetic pilot withdrawal'})


def test_pilot_required_for_invite_redeem_and_cached_event(pilot):
    api,s,path=pilot
    assert invite(pilot).status_code==403
    assert grant(pilot).status_code==200
    code=invite(pilot).json()['binding_code']
    with sqlite3.connect(path) as db:db.execute('UPDATE pilot_members SET expires=0')
    assert send(api,'bind',{'binding_code':code}).status_code==403
    assert grant(pilot).status_code==200
    assert send(api,'bind',{'binding_code':code}).status_code==403
    code=invite(pilot).json()['binding_code']
    assert send(api,'bind',{'binding_code':code},eid='pilot-bind-fixed').status_code==200
    assert revoke(pilot).status_code==200
    assert send(api,'bind',{'binding_code':code},eid='pilot-bind-fixed').status_code==403
    assert send(api,'query',{'query':{'resource':'identity'}}).status_code==403
    assert grant(pilot).status_code==200
    assert send(api,'query',{'query':{'resource':'identity'}}).status_code==403


def test_pilot_admin_and_tenant_boundaries(pilot):
    api,s,path=pilot
    tech={'Authorization':'Bearer '+create_access_token(s[2][1],1)[0]}
    data={'user_id':s[2][1],'sender_id':PHONE,'reason':'Synthetic approval reason'}
    assert api.put('/api/channels/whatsapp/pilots',headers=tech,json=data).status_code==403
    assert api.put('/api/channels/whatsapp/pilots',headers=s[1],json={**data,'user_id':s[2][3]}).status_code==404
    assert api.put('/api/channels/whatsapp/pilots',headers=s[1],json={**data,'organization_id':2}).status_code==422
    assert grant(pilot).status_code==200
    with s[5]() as db:
        from app.models import User
        db.get(User,s[2][3]).role=UserRole.ADMIN;db.commit()
    foreign={'Authorization':'Bearer '+create_access_token(s[2][3],2)[0]}
    assert api.delete('/api/channels/whatsapp/pilots/'+PHONE,headers=foreign,params={'reason':'Cross organization deletion'}).status_code==404
    assert api.put('/api/channels/whatsapp/pilots',headers=s[1],json={**data,'user_id':s[2][2]}).status_code==409
    assert revoke(pilot).status_code==200
    with sqlite3.connect(path) as db:assert db.execute('SELECT COUNT(*) FROM pilot_audit').fetchone()[0]==2


@pytest.mark.parametrize("rebind",[False,True])
def test_revoked_pilot_cancels_queued_reply_and_rebind_does_not_resurrect(pilot,tmp_path,rebind):
    api,s,path=pilot;assert grant(pilot).status_code==200
    code=invite(pilot).json()['binding_code'];assert send(api,'bind',{'binding_code':code}).status_code==200
    class Sender(SyntheticSender):
        calls=0
        def send(self,*args,**kwargs):self.calls+=1;return super().send(*args,**kwargs)
    sender=Sender();b=Bridge(state_path=tmp_path/'bridge.db',adapter=api,sender=sender,channel_secret=SECRET)
    b.accept([{'id':'pilot-queued-reply','sender':PHONE,'text':'我的身份','timestamp':int(time.time())}]);assert b.process_one()
    assert revoke(pilot).status_code==200
    if rebind:
        assert grant(pilot).status_code==200
        code=invite(pilot).json()['binding_code'];assert send(api,'bind',{'binding_code':code}).status_code==200
    assert b.send_one() and sender.calls==0
    with b.transaction() as db:assert db.execute('SELECT state FROM outbox').fetchone()[0]=='cancelled'


def test_preflight_is_read_only_redacted_and_not_activation(production,tmp_path,monkeypatch):
    monkeypatch.setenv('META_CHANNEL_ENABLED','false')
    monkeypatch.setenv('META_IMAGE_REF','registry.invalid/backend@sha256:'+'a'*64)
    config=__import__('app.integrations.meta_production',fromlist=['configuration']).configuration('check')
    from app.integrations.whatsapp import Store
    with Store(config['adapter_state']).transaction() as db:
        db.execute('INSERT INTO pilot_members VALUES(?,?,?,?,1)',(PHONE,2,1,time.time()+600))
    entries=[]
    for kind in ('business','adapter','bridge','uploads'):
        p=tmp_path/(kind+'.backup');p.write_bytes(b'synthetic-backup');p.chmod(0o600)
        entries.append({'kind':kind,'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps({'created_at':time.time(),'files':entries}))
    monkeypatch.setenv('META_BACKUP_MANIFEST',str(manifest))
    before=config['adapter_state'].read_bytes()
    r=meta_preflight.report();assert r['offline_checks_passed'] and not r['production_activation_authorized']
    assert not config['bridge_state'].exists() and config['adapter_state'].read_bytes()==before
    assert PHONE not in json.dumps(r) and all(p.read_text() not in json.dumps(r) for p in production.values())
    from pathlib import Path
    saved=Path(entries[0]['path']);saved.write_bytes(b'changed-backup')
    assert not meta_preflight.report()['checks']['backup_files_verified']
    saved.write_bytes(b'synthetic-backup')
    manifest.write_text(json.dumps({'created_at':time.time()-90000,'files':entries}))
    assert not meta_preflight.report()['checks']['backup_files_verified']
    manifest.write_text('{}');assert not meta_preflight.report()['checks']['backup_files_verified']
    monkeypatch.setenv('META_IMAGE_REF','registry.invalid/backend:latest');assert not meta_preflight.report()['checks']['image_pinned']
    monkeypatch.setenv('META_LIVE_SEND_ENABLED','true');assert not meta_preflight.report()['offline_checks_passed']


def test_revoked_pilot_cannot_confirm_feedback(pilot):
    from test_whatsapp_adapter import draft
    from sqlalchemy import select,func
    from app.models import RepairCaseReport
    api,s,path=pilot;assert grant(pilot).status_code==200
    code=invite(pilot).json()['binding_code'];assert send(api,'bind',{'binding_code':code}).status_code==200
    draft_data=draft((api,*s[1:]))
    assert revoke(pilot).status_code==200
    response=send(api,'report_confirm',{'draft_id':draft_data['draft_id']},text=draft_data['confirmation_text'])
    assert response.status_code==403
    with s[5]() as db:assert db.scalar(select(func.count()).select_from(RepairCaseReport))==0
