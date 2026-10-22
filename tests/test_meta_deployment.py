"""Isolated deployment contract and real loopback process lifecycle. No Meta network."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from scripts import meta_deployment as deploy
from app.integrations.meta_runtime import Operations


@pytest.fixture
def simulation(tmp_path, monkeypatch):
    (tmp_path / '.simulation-only').write_text('simulation-only-v1')
    for key, value in {'META_DEPLOYMENT_MODE':'simulation', 'META_LIVE_SEND_ENABLED':'false',
                       'WHATSAPP_ADAPTER_ENABLED':'false', 'META_SIMULATION_ROOT':str(tmp_path),
                       'APP_ENV':'test', 'DATABASE_URL':'sqlite:///'+str(tmp_path/'business.sqlite3')}.items():
        monkeypatch.setenv(key,value)
    return tmp_path


def test_disabled_factories_never_open_state_or_send(tmp_path, monkeypatch):
    monkeypatch.setenv('META_DEPLOYMENT_MODE','disabled')
    monkeypatch.setenv('META_LIVE_SEND_ENABLED','false')
    monkeypatch.setenv('WHATSAPP_ADAPTER_ENABLED','false')
    monkeypatch.chdir(tmp_path)
    for app, path in [(deploy.webhook_app(),'/webhooks/meta/whatsapp'),
                      (deploy.adapter_app(),'/api/channels/whatsapp/events')]:
        with TestClient(app) as client:
            assert client.post(path,json={}).status_code==503
            assert client.get('/health').json()['enabled'] is False
    deploy.main(['worker'])
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('key,value',[
    ('META_DEPLOYMENT_MODE','production'), ('META_LIVE_SEND_ENABLED','true'),
    ('WHATSAPP_ADAPTER_ENABLED','true'), ('DATABASE_URL','sqlite:///real.db'),
    ('APP_ENV','production'), ('META_ADAPTER_URL','https://example.com'),
    ('META_ADAPTER_URL','http://user:password@adapter:8011'),
    ('META_ADAPTER_URL','http://127.0.0.1:8011/redirect')])
def test_invalid_or_live_configuration_rejected(simulation,monkeypatch,key,value):
    monkeypatch.setenv(key,value)
    with pytest.raises(ValueError):deploy.configuration()


def test_missing_simulation_marker_rejected(simulation):
    (simulation/'.simulation-only').unlink()
    with pytest.raises((ValueError,FileNotFoundError)):deploy.configuration()


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


def wait_for(check, processes=()):
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        assert all(p.poll() is None for p in processes),'Service exited unexpectedly'
        try:
            if check():return
        except (httpx.HTTPError,sqlite3.Error,KeyError):pass
        time.sleep(.05)
    raise AssertionError('Service readiness deadline exceeded')


def test_process_wiring_stop_restart_and_state_preserving_rollback(simulation,monkeypatch):
    adapter_port,webhook_port=port(),port()
    monkeypatch.setenv('META_ADAPTER_URL',f'http://127.0.0.1:{adapter_port}')
    config=deploy.configuration();env=os.environ.copy();env['PYTHONUNBUFFERED']='1'
    root=Path(__file__).resolve().parents[1]
    # Seed only the fresh isolated business DB. No application .env is loaded for DB selection.
    seed='''
import json
from app.core.database import Base,engine,SessionLocal
from app.models import Organization,User,UserRole
from app.core.security import create_access_token
Base.metadata.create_all(engine)
with SessionLocal() as db:
 db.add(Organization(id=1,name='Simulation',slug='simulation'));db.flush()
 db.add_all([User(id=1,organization_id=1,name='admin',email='admin@example.invalid',role=UserRole.ADMIN,is_active=True),User(id=2,organization_id=1,name='tech',email='tech@example.invalid',role=UserRole.ENGINEER,is_active=True)]);db.commit()
print(json.dumps({'token':create_access_token(1,1)[0]}))
'''
    seeded=subprocess.run([sys.executable,'-c',seed],cwd=root,env=env,capture_output=True,text=True,check=True)
    token=json.loads(seeded.stdout.strip().splitlines()[-1])['token']
    processes=[]
    def start(args):
        p=subprocess.Popen([sys.executable,*args],cwd=root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        processes.append(p);return p
    def stop(p):
        p.send_signal(signal.SIGTERM);p.wait(timeout=15);assert p.returncode in ((0,-signal.SIGTERM) if 'uvicorn' in p.args else (0,))
        processes.remove(p)
    with httpx.Client(trust_env=False,timeout=2) as http:
        try:
            adapter=start(['-m','uvicorn','scripts.meta_deployment:adapter_app','--factory','--host','127.0.0.1','--port',str(adapter_port),'--no-access-log'])
            hook=start(['-m','uvicorn','scripts.meta_deployment:webhook_app','--factory','--host','127.0.0.1','--port',str(webhook_port),'--no-access-log'])
            abase=f'http://127.0.0.1:{adapter_port}';wbase=f'http://127.0.0.1:{webhook_port}'
            wait_for(lambda:http.get(abase+'/health').status_code==200 and http.get(wbase+'/health').status_code==200,processes)
            assert http.get(wbase+'/health').json()['live_transport_enabled'] is False
            assert http.get(wbase+'/webhooks/meta/whatsapp',params={'hub.mode':'subscribe','hub.verify_token':config['verify_token'],'hub.challenge':'probe'}).text=='probe'
            invitation=http.post(abase+'/api/channels/whatsapp/bindings',headers={'Authorization':'Bearer '+token},json={'user_id':2,'sender_id':'15550000001'})
            assert invitation.status_code==200
            def post(mid,text):
                payload={'object':'whatsapp_business_account','entry':[{'id':'simulation-waba','changes':[{'field':'messages','value':{'messaging_product':'whatsapp','metadata':{'phone_number_id':'simulation-line'},'messages':[{'from':'15550000001','id':mid,'timestamp':str(int(time.time())),'type':'text','text':{'body':text}}]}}]}]}
                raw=json.dumps(payload).encode()
                signature='sha256='+hmac.new(config['app_secret'].encode(),raw,hashlib.sha256).hexdigest()
                response=http.post(wbase+'/webhooks/meta/whatsapp',content=raw,headers={'X-Hub-Signature-256':signature})
                assert response.status_code==200,response.text
                return raw,signature
            raw,sig=post('simulation-binding-event','绑定 '+invitation.json()['binding_code'])
            worker=start(['-m','scripts.meta_deployment','worker'])
            ops=Operations(simulation/'bridge.sqlite3')
            wait_for(lambda:ops.monitor()['counts']['outbox'].get('accepted')==1,processes)
            duplicate=subprocess.run([sys.executable,'-m','scripts.meta_deployment','worker'],cwd=root,env=env,capture_output=True,timeout=10)
            assert duplicate.returncode!=0
            stop(worker)
            assert ops.monitor()['worker']['state']=='stopped'
            backup=ops.backup(simulation/'pre-release.sqlite3',operator='simulation-release')
            assert backup['integrity']=='ok'
            # Roll back to the disabled deployment without restoring stale DB snapshots.
            stop(hook);env['META_DEPLOYMENT_MODE']='disabled'
            hook=start(['-m','uvicorn','scripts.meta_deployment:webhook_app','--factory','--host','127.0.0.1','--port',str(webhook_port),'--no-access-log'])
            wait_for(lambda:http.get(wbase+'/health').status_code==200,processes)
            assert http.post(wbase+'/webhooks/meta/whatsapp',content=raw).status_code==503
            disabled=subprocess.run([sys.executable,'-m','scripts.meta_deployment','worker'],cwd=root,env=env,capture_output=True,timeout=10)
            assert disabled.returncode==0
            stop(hook);env['META_DEPLOYMENT_MODE']='simulation'
            hook=start(['-m','uvicorn','scripts.meta_deployment:webhook_app','--factory','--host','127.0.0.1','--port',str(webhook_port),'--no-access-log'])
            wait_for(lambda:http.get(wbase+'/health').status_code==200,processes)
            assert http.post(wbase+'/webhooks/meta/whatsapp',content=raw,headers={'X-Hub-Signature-256':sig}).status_code==200
            worker=start(['-m','scripts.meta_deployment','worker'])
            wait_for(lambda:ops.monitor()['lock_held'],processes)
            post('simulation-identity-event','我的身份')
            wait_for(lambda:ops.monitor()['counts']['outbox'].get('accepted')==2,processes)
            stop(worker)
            with sqlite3.connect(simulation/'bridge.sqlite3') as db:
                assert db.execute('SELECT COUNT(*) FROM delivery_attempts').fetchone()[0]==2
                assert db.execute("SELECT COUNT(*) FROM worker_audit WHERE event='stopped'").fetchone()[0]==2
        finally:
            for p in processes:
                if p.poll() is None:p.terminate()
            for p in processes:
                try:p.wait(timeout=15)
                except subprocess.TimeoutExpired:p.kill();p.wait()
