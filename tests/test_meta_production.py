import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from app.integrations import meta_production as prod
from app.integrations.meta_runtime import Worker
from app.core.database import get_db
from scripts import meta_deployment as deploy
from test_whatsapp_adapter import setup


@pytest.fixture
def production(tmp_path, monkeypatch):
    state=tmp_path/'state';state.mkdir(mode=0o700)
    adapter=tmp_path/'adapter';adapter.mkdir(mode=0o700)
    values={'META_DEPLOYMENT_MODE':'production','APP_ENV':'production','APP_DEBUG':'false',
            'META_CHANNEL_ENABLED':'true','META_LIVE_SEND_ENABLED':'false','WHATSAPP_ADAPTER_ENABLED':'false',
            'META_WABA_ID':'123456','META_PHONE_NUMBER_ID':'654321','META_GRAPH_VERSION':'v99.0',
            'META_ADAPTER_URL':'http://adapter:8011','DATABASE_URL':'postgresql+psycopg://test:test@db/test',
            'META_BRIDGE_STATE':str(state/'bridge.sqlite3'), 'WHATSAPP_ADAPTER_STATE':str(adapter/'channel.sqlite3')}
    paths={}
    for key in ('META_APP_SECRET','META_VERIFY_TOKEN','META_ACCESS_TOKEN','WHATSAPP_SIGNING_SECRET'):
        path=tmp_path/key;path.write_text(secrets.token_hex(32));path.chmod(0o600)
        paths[key]=path;values[key+'_FILE']=str(path);monkeypatch.delenv(key,raising=False)
    for k,v in values.items():monkeypatch.setenv(k,v)
    return paths


def test_production_disabled_does_not_read_secrets_or_open_state(production,monkeypatch):
    monkeypatch.setenv('META_CHANNEL_ENABLED','false')
    for p in production.values():p.unlink()
    with TestClient(deploy.webhook_app()) as client:
        assert client.post('/webhooks/meta/whatsapp',json={}).status_code==503
        assert client.get('/health').json()['enabled'] is False
    with TestClient(deploy.adapter_app()) as client:
        assert client.post('/api/channels/whatsapp/events',json={}).status_code==503
    deploy.main(['worker'])
    assert not os.path.exists(os.environ['META_BRIDGE_STATE'])
    assert not os.path.exists(os.environ['WHATSAPP_ADAPTER_STATE'])


@pytest.mark.parametrize('bad',['mode','symlink','hardlink','placeholder','short','oversize','directory','plaintext'])
def test_secret_rejections_are_sanitized(production,monkeypatch,bad):
    path=production['META_ACCESS_TOKEN'];secret=path.read_text()
    if bad=='mode':path.chmod(0o644)
    elif bad=='symlink':
        target=path.with_suffix('.target');path.rename(target);path.symlink_to(target)
    elif bad=='hardlink':os.link(path,path.with_suffix('.link'))
    elif bad=='placeholder':path.write_text('REPLACE_BEFORE_FUTURE_ACTIVATION_'+'x'*40)
    elif bad=='short':path.write_text('tiny')
    elif bad=='oversize':path.write_text('x'*9000)
    elif bad=='directory':path.unlink();path.mkdir()
    else:monkeypatch.setenv('META_ACCESS_TOKEN',secret)
    with pytest.raises(ValueError) as exc:prod.configuration('check')
    assert secret not in str(exc.value) and str(path) not in str(exc.value)


@pytest.mark.parametrize('key,value',[
    ('META_WABA_ID','REPLACE'),('META_PHONE_NUMBER_ID','bad/id'),('META_GRAPH_VERSION','latest'),
    ('META_ADAPTER_URL','http://example.com'),('META_CHANNEL_ENABLED','yes'),
    ('WHATSAPP_ADAPTER_ENABLED','true'),('DATABASE_URL','sqlite:///business.db'),
    ('META_BRIDGE_STATE','relative.db'),('APP_DEBUG','true')])
def test_production_invalid_configuration(production,monkeypatch,key,value):
    monkeypatch.setenv(key,value)
    with pytest.raises(ValueError):prod.configuration('check')


def test_private_state_and_role_secret_scoping(production,monkeypatch):
    config=prod.configuration('check')
    assert config['bridge_state']!=config['adapter_state']
    assert not config['bridge_state'].exists()  # Validation does not initialize a queue.
    production['META_ACCESS_TOKEN'].unlink()
    assert 'token' not in prod.configuration('webhook')
    assert 'app_secret' not in prod.configuration('adapter')
    with pytest.raises(ValueError):prod.configuration('worker')
    config['bridge_state'].parent.chmod(0o755)
    with pytest.raises(ValueError):prod.configuration('webhook')


def test_check_output_and_held_worker_do_not_expose_or_process(production,capsys):
    deploy.main(['check']);deploy.main(['worker'])
    output=capsys.readouterr().out
    assert 'worker_started=false' in output and 'no queue opened' in output
    assert all(p.read_text() not in output for p in production.values())
    assert not os.path.exists(os.environ['META_BRIDGE_STATE'])


def test_production_factories_signed_binding_and_graph_mock(production,monkeypatch,setup):
    # Production factories, real tenant-aware adapter, synthetic credentials and no external requests.
    monkeypatch.setenv('META_LIVE_SEND_ENABLED','true')
    app=deploy.adapter_app()
    app.dependency_overrides[get_db]=setup[0].app.dependency_overrides[get_db]
    calls=[]
    def send(request):
        calls.append(request)
        assert request.headers['Authorization']=='Bearer '+production['META_ACCESS_TOKEN'].read_text()
        assert request.url.path=='/v99.0/654321/messages'
        return httpx.Response(200,json={'messages':[{'id':'fake-'+str(len(calls))}]})
    with TestClient(app) as adapter,TestClient(deploy.webhook_app()) as webhook:
        code=adapter.post('/api/channels/whatsapp/bindings',headers=setup[1],json={'user_id':setup[2][1],'sender_id':'15550000001'}).json()['binding_code']
        payload={'object':'whatsapp_business_account','entry':[{'id':'123456','changes':[{'field':'messages','value':{'messaging_product':'whatsapp','metadata':{'phone_number_id':'654321'},'messages':[{'id':'production-mock-binding','from':'15550000001','timestamp':str(int(time.time())),'type':'text','text':{'body':'绑定 '+code}}]}}]}]}
        raw=json.dumps(payload).encode();sig='sha256='+hmac.new(production['META_APP_SECRET'].read_bytes(),raw,hashlib.sha256).hexdigest()
        assert webhook.post('/webhooks/meta/whatsapp',content=raw,headers={'X-Hub-Signature-256':sig}).status_code==200
        bridge=deploy.bridge(prod.configuration('worker'),adapter,transport=httpx.MockTransport(send))
        Worker(bridge,poll_seconds=.01).run(max_cycles=1)
        assert len(calls)==1
        assert webhook.post('/webhooks/meta/whatsapp',content=raw,headers={'X-Hub-Signature-256':sig}).status_code==200
        Worker(bridge,poll_seconds=.01).run(max_cycles=1)
        assert len(calls)==1
        with sqlite3.connect(bridge.path) as db:
            assert db.execute('SELECT COUNT(*) FROM delivery_attempts').fetchone()[0]==1
        # Webhook never owns an enabled sender even when the worker's explicit send flag is true.
        assert webhook.get('/health').json()['live_transport_enabled'] is False


def test_state_alias_and_unsafe_existing_file_rejected(production,monkeypatch):
    path=prod.configuration('check')['bridge_state']
    path.write_text('');path.chmod(0o644)
    with pytest.raises(ValueError):prod.configuration('webhook')
    path.chmod(0o600)
    assert prod.configuration('webhook')['bridge_state']==path
    target=path.with_suffix('.target');path.rename(target);path.symlink_to(target)
    with pytest.raises(ValueError):prod.configuration('worker')
    monkeypatch.setenv('META_BRIDGE_STATE',os.environ['WHATSAPP_ADAPTER_STATE'])
    with pytest.raises(ValueError):prod.configuration('adapter')


def test_sending_cannot_enable_without_channel(production,monkeypatch):
    monkeypatch.setenv('META_CHANNEL_ENABLED','false')
    monkeypatch.setenv('META_LIVE_SEND_ENABLED','true')
    with pytest.raises(ValueError):prod.configuration('worker')
