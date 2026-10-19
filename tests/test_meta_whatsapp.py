"""No network or live credentials: Meta envelope -> real adapter -> synthetic sender."""
import copy
import hashlib
import hmac
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.integrations.meta_whatsapp import Bridge, create_app
from app.models import RepairCaseReport, AuditLog
from test_whatsapp_adapter import setup, SECRET, PHONE, OTHER, REPORT, bind

APP_SECRET = 'simulation-meta-app-secret-' + 'a' * 32
VERIFY_TOKEN = 'simulation-meta-verify-token-' + 'v' * 32


class FakeSender:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.crash = False

    def send(self, payload, *, key):
        self.calls.append((key, payload))
        if self.crash:
            raise KeyboardInterrupt('Process died after provider accepted')
        if self.fail:
            raise TimeoutError('Provider acceptance unknown')
        return 'wamid.synthetic.' + key


@pytest.fixture
def meta(setup, tmp_path):
    sender = FakeSender()
    bridge = Bridge(state_path=tmp_path/'meta.sqlite3', adapter=setup[0], sender=sender, channel_secret=SECRET)
    app = create_app(enabled=True, bridge=bridge, app_secret=APP_SECRET,
                     verify_token=VERIFY_TOKEN, waba_id='test-waba', phone_number_id='test-line')
    with TestClient(app) as api:
        yield api, bridge, sender


def envelope(text, *, phone=PHONE, mid=None, stamp=None):
    return {'object': 'whatsapp_business_account', 'entry': [{'id': 'test-waba', 'changes': [{
        'field': 'messages', 'value': {'messaging_product': 'whatsapp',
        'metadata': {'phone_number_id': 'test-line'},
        # Deliberately conflicting contact metadata must never override messages[].from.
        'contacts': [{'wa_id': OTHER, 'profile': {'name': 'Untrusted display name'}}],
        'messages': [{'from': phone, 'id': mid or 'wamid.' + uuid4().hex,
                      'timestamp': str(stamp if stamp is not None else int(time.time())),
                      'type': 'text', 'text': {'body': text}}]}}]}]}


def post(meta, payload, secret=APP_SECRET):
    raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
    sig = 'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return meta[0].post('/webhooks/meta/whatsapp', content=raw,
                        headers={'X-Hub-Signature-256': sig, 'Content-Type': 'application/json'})


def rows(meta, table):
    with meta[1].transaction() as db:
        return [dict(r) for r in db.execute('SELECT * FROM ' + table + ' ORDER BY rowid')]


def dispatch(meta, text, **kwargs):
    payload = envelope(text, **kwargs)
    assert post(meta, payload).status_code == 200
    assert meta[1].process_one()
    return rows(meta, 'inbox')[-1]


def test_disabled_and_verification_challenge(meta):
    with TestClient(create_app()) as disabled:
        assert disabled.post('/webhooks/meta/whatsapp', json={}).status_code == 503
        assert disabled.get('/health').json()['live_transport_implemented'] is False
    params = {'hub.mode': 'subscribe', 'hub.verify_token': VERIFY_TOKEN, 'hub.challenge': '123456'}
    response = meta[0].get('/webhooks/meta/whatsapp', params=params)
    assert response.status_code == 200 and response.text == '123456'
    params['hub.verify_token'] = 'wrong'
    assert meta[0].get('/webhooks/meta/whatsapp', params=params).status_code == 403
    with pytest.raises(ValueError):
        create_app(enabled=True)


def test_platform_signature_raw_body_and_account_scope(meta):
    p = envelope('我的身份')
    assert post(meta, p, secret='wrong').status_code == 401
    signed_raw = json.dumps(p).encode()
    signature = 'sha256=' + hmac.new(APP_SECRET.encode(), signed_raw, hashlib.sha256).hexdigest()
    assert meta[0].post('/webhooks/meta/whatsapp', content=signed_raw+b' ', headers={'X-Hub-Signature-256': signature}).status_code == 401
    p['entry'][0]['id'] = 'another-waba'
    assert post(meta, p).status_code == 403
    p['entry'][0]['id'] = 'test-waba'
    p['entry'][0]['changes'][0]['value']['metadata']['phone_number_id'] = 'another-line'
    assert post(meta, p).status_code == 403
    assert not rows(meta, 'inbox') and not meta[2].calls


def test_binding_organization_feedback_and_automatic_reply(meta, setup):
    assert dispatch(meta, '我的身份')['http_status'] == 403
    invite = setup[0].post('/api/channels/whatsapp/bindings', headers=setup[1],
                          json={'user_id': setup[2][1], 'sender_id': PHONE}).json()
    command = '绑定 ' + invite['binding_code']
    assert dispatch(meta, command, phone=OTHER)['http_status'] == 403
    assert dispatch(meta, command)['http_status'] == 200
    assert meta[1].send_one()
    assert meta[2].calls[-1][1]['to'] == PHONE
    assert json.loads(meta[2].calls[-1][1]['text']['body'])['bound'] is True
    assert dispatch(meta, '本组织工单')['http_status'] == 200
    meta[1].send_one()
    orders = json.loads(meta[2].calls[-1][1]['text']['body'])
    assert [w['id'] for w in orders] == [setup[3][0]]
    assert dispatch(meta, '查询 ' + json.dumps({'resource': 'repair_guidance', 'work_order_id': setup[3][1]}))['http_status'] == 404
    assert dispatch(meta, '查询 ' + json.dumps({'resource': 'identity', 'organization_id': 2}))['http_status'] == 422
    wid = setup[3][0]
    assert dispatch(meta, f'领取工单 {wid}')['http_status'] == 200
    meta[1].send_one()
    version = json.loads(meta[2].calls[-1][1]['text']['body'])['claim_version']
    args = {'work_order_id': wid, 'claim_version': version, 'report': REPORT}
    assert dispatch(meta, '反馈 '+json.dumps(args))['http_status'] == 200
    meta[1].send_one()
    draft = json.loads(meta[2].calls[-1][1]['text']['body'])
    assert draft['submitted'] is False
    assert dispatch(meta, draft['confirmation_text'], phone=OTHER)['http_status'] == 422
    assert dispatch(meta, '确认')['http_status'] == 422
    with setup[5]() as db:
        assert db.scalar(select(func.count()).select_from(RepairCaseReport)) == 0
    confirmed = envelope(draft['confirmation_text'])
    assert post(meta, confirmed).status_code == 200
    meta[1].process_one(); meta[1].send_one()
    result = json.loads(meta[2].calls[-1][1]['text']['body'])
    assert result['review_status'] == 'pending' and result['guidance_eligible'] is False
    count = len(meta[2].calls)
    assert post(meta, confirmed).status_code == 200
    assert not meta[1].process_one() and not meta[1].send_one()
    assert len(meta[2].calls) == count
    assert dispatch(meta, draft['confirmation_text'])['http_status'] == 200
    meta[1].send_one()
    assert json.loads(meta[2].calls[-1][1]['text']['body'])['report_id'] == result['report_id']
    with setup[5]() as db:
        assert db.scalar(select(func.count()).select_from(RepairCaseReport)) == 1
        assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == 'submit_repair_case')) == 1


def test_batch_atomicity_status_events_and_media(meta):
    status = envelope('unused')
    value = status['entry'][0]['changes'][0]['value']
    value.pop('messages')
    value['statuses'] = [{'id': 'wamid.status', 'status': 'delivered'}]
    assert post(meta, status).json()['text_messages'] == 0
    p = envelope('x')
    p['entry'][0]['changes'][0]['value']['messages'][0]['type'] = 'image'
    assert post(meta, p).json()['text_messages'] == 0
    p = envelope('我的身份')
    second = copy.deepcopy(p['entry'][0]); second['id'] = 'foreign-waba'
    p['entry'].append(second)
    assert post(meta, p).status_code == 403
    assert not rows(meta, 'inbox')
    assert post(meta, {'object': 'whatsapp_business_account', 'entry': [None]}).status_code == 422
    assert meta[0].post('/webhooks/meta/whatsapp', content=b'x'*262145).status_code == 413


def test_duplicate_conflict_restart_and_concurrent_send(meta, setup):
    bind(setup)
    payload = envelope('我的身份')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: post(meta, payload).status_code, range(2)))
    assert results == [200, 200] and len(rows(meta, 'inbox')) == 1
    meta[1].process_one()
    restarted = Bridge(state_path=meta[1].path, adapter=setup[0], sender=meta[2], channel_secret=SECRET)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda b: b.send_one(), [meta[1], restarted]))
    assert len(meta[2].calls) == 1 and rows(meta, 'outbox')[0]['state'] == 'accepted'
    assert not restarted.process_one() and not restarted.send_one()
    payload['entry'][0]['changes'][0]['value']['messages'][0]['text']['body'] = '本组织工单'
    assert post(meta, payload).status_code == 409


@pytest.mark.parametrize('crash', [False, True])
def test_ambiguous_send_is_not_automatically_retried(meta, setup, crash):
    bind(setup); dispatch(meta, '我的身份')
    meta[2].fail = not crash; meta[2].crash = crash
    if crash:
        with pytest.raises(KeyboardInterrupt):
            meta[1].send_one()
    else:
        meta[1].send_one()
    assert rows(meta, 'outbox')[0]['state'] == ('sending' if crash else 'uncertain')
    restarted = Bridge(state_path=meta[1].path, adapter=setup[0], sender=meta[2], channel_secret=SECRET)
    assert not restarted.send_one() and len(meta[2].calls) == 1


@pytest.mark.parametrize('rebind', [False, True])
def test_revoked_or_rebound_identity_cannot_receive_queued_reply(meta, setup, rebind):
    bind(setup); dispatch(meta, '本组织工单')
    setup[0].delete('/api/channels/whatsapp/bindings/'+PHONE, headers=setup[1])
    if rebind:
        bind(setup, uid=setup[2][2])
    meta[1].send_one()
    assert rows(meta, 'outbox')[0]['state'] == 'cancelled' and not meta[2].calls


def test_expired_inbound_and_outbound(meta, setup):
    bind(setup)
    row = dispatch(meta, '我的身份', stamp=int(time.time())-86401)
    assert row['state'] == 'expired' and not rows(meta, 'outbox')
    assert post(meta, envelope('我的身份', stamp=int(time.time())+600)).status_code == 422
    dispatch(meta, '我的身份')
    with meta[1].transaction() as db:
        db.execute('UPDATE outbox SET expires=0')
    meta[1].send_one()
    assert rows(meta, 'outbox')[0]['state'] == 'expired' and not meta[2].calls


def test_adapter_commit_before_bridge_crash_retries_safely(meta, setup, monkeypatch):
    bind(setup)
    p = envelope('领取工单 '+str(setup[3][0]))
    post(meta, p)
    original = meta[1].call_adapter
    def interrupted(*args, **kwargs):
        response = original(*args, **kwargs)
        if args[1] == 'claim':
            raise RuntimeError('Bridge crashed after successful adapter call')
        return response
    monkeypatch.setattr(meta[1], 'call_adapter', interrupted)
    with pytest.raises(RuntimeError):
        meta[1].process_one()
    assert rows(meta, 'inbox')[0]['state'] == 'pending'
    monkeypatch.setattr(meta[1], 'call_adapter', original)
    meta[1].process_one(); meta[1].send_one()
    assert len(rows(meta, 'outbox')) == 1 and len(meta[2].calls) == 1
    assert rows(meta, 'inbox')[0]['http_status'] == 200


def test_backend_unavailable_keeps_durable_message_for_retry(meta, setup, monkeypatch):
    import httpx
    bind(setup)
    post(meta, envelope('我的身份'))
    original = meta[1].call_adapter
    monkeypatch.setattr(meta[1], 'call_adapter', lambda *a, **k: httpx.Response(503))
    with pytest.raises(RuntimeError):
        meta[1].process_one()
    assert rows(meta, 'inbox')[0]['state'] == 'pending' and not rows(meta, 'outbox')
    monkeypatch.setattr(meta[1], 'call_adapter', original)
    meta[1].process_one(); meta[1].send_one()
    assert len(meta[2].calls) == 1


def test_valid_batched_messages_and_worker_serialization(meta, setup):
    bind(setup)
    first = envelope('我的身份')
    first['entry'][0]['changes'][0]['value']['messages'].extend(
        envelope('本组织工单')['entry'][0]['changes'][0]['value']['messages'])
    assert post(meta, first).json()['text_messages'] == 2
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(pool.map(lambda _: meta[1].process_one(), range(2)))
    meta[1].send_one(); meta[1].send_one()
    assert len(meta[2].calls) == 2 and not meta[1].send_one()
    assert all(call[1]['to'] == PHONE for call in meta[2].calls)
    assert meta[1].path.stat().st_mode & 0o777 == 0o600
