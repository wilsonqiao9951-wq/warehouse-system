import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from app.integrations.meta_delivery import GraphSender, SendRejected
from scripts.meta_delivery_recovery import LocalRecovery, main
from test_whatsapp_adapter import setup, bind, PHONE, OTHER
from test_meta_whatsapp import meta, dispatch, post, envelope, rows


def status(meta, state, *, mid=None, callback=None, recipient=PHONE, timestamp=None):
    payload = envelope('unused')
    value = payload['entry'][0]['changes'][0]['value']
    value.pop('messages')
    if mid is None:
        mid = rows(meta, 'delivery_attempts')[-1]['provider_id'] or 'wamid.uncertain'
    value['statuses'] = [{'id': mid, 'recipient_id': recipient, 'status': state,
                          'timestamp': str(timestamp or int(time.time()))}]
    if callback:
        value['statuses'][0]['biz_opaque_callback_data'] = callback
    if state == 'failed':
        value['statuses'][0]['errors'] = [{'code': 131026, 'message': 'DO NOT STORE PRIVATE PROVIDER ERROR'}]
    return post(meta, payload)


def queued(meta, setup):
    bind(setup); dispatch(meta, '我的身份')
    return rows(meta, 'outbox')[0]['id']


def recover(meta, oid, action='retry', **kw):
    snapshot = meta[1].inspect_delivery(oid)
    return meta[1].recover(oid, action=action, operator='simulation-operator',
                           reason='Reviewed synthetic provider evidence', confirmation=snapshot['confirmation'], **kw)


def test_graph_disabled_and_mock_success():
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(200, json={'messages': [{'id': 'wamid.receipt'}]})
    transport = httpx.MockTransport(handler)
    sender = GraphSender(phone_number_id='12345', api_version='v25.0', token='synthetic-token', transport=transport)
    with pytest.raises(SendRejected):
        sender.send({'to': PHONE}, key='attempt-test')
    assert not calls
    sender.enabled = True
    assert sender.send({'to': PHONE, 'type': 'text', 'text': {'body': 'synthetic'}}, key='attempt-test') == 'wamid.receipt'
    req = calls[0]
    assert str(req.url) == 'https://graph.facebook.com/v25.0/12345/messages'
    assert req.headers['Authorization'] == 'Bearer synthetic-token'
    assert json.loads(req.content)['biz_opaque_callback_data'] == 'attempt-test'
    assert req.extensions['timeout']['read'] == 10
    with pytest.raises(ValueError):
        GraphSender(phone_number_id='../evil', api_version='latest')


@pytest.mark.parametrize('code,body,error', [(400,{},SendRejected),(401,{},SendRejected),(429,{},SendRejected),
                                           (500,{},RuntimeError),(302,{},RuntimeError),(200,{},RuntimeError)])
def test_graph_errors_are_not_retried_or_leaked(code, body, error):
    calls=[]
    def handler(req):
        calls.append(req)
        return httpx.Response(code, json={**body, 'private': 'secret provider details'})
    sender=GraphSender(phone_number_id='123', api_version='v25.0', token='synthetic', enabled=True,
                       transport=httpx.MockTransport(handler))
    with pytest.raises(error) as exc:
        sender.send({'to':PHONE}, key='test')
    assert len(calls)==1 and 'secret provider details' not in str(exc.value)


def test_status_duplicates_out_of_order_failure_and_recipient_scope(meta, setup):
    queued(meta, setup); meta[1].send_one()
    stamp=int(time.time())
    assert status(meta,'read',timestamp=stamp).status_code==200
    assert status(meta,'read',timestamp=stamp).status_code==200
    assert status(meta,'sent',timestamp=int(time.time())-10).status_code==200
    assert status(meta,'delivered').status_code==200
    assert status(meta,'failed').status_code==200
    assert rows(meta,'outbox')[0]['state']=='read'
    assert len(rows(meta,'delivery_events'))==4
    assert status(meta,'read',recipient=OTHER).status_code==200
    assert rows(meta,'delivery_events')[-1]['disposition']=='conflict'
    assert 'DO NOT STORE' not in json.dumps(rows(meta,'delivery_events'))
    assert len(meta[2].calls)==1


def test_callback_before_http_receipt_and_unknown_reconciliation(meta, setup):
    queued(meta, setup)
    class EarlySender:
        def send(self,payload,*,key):
            assert status(meta,'delivered',mid='wamid.early').status_code==200
            assert rows(meta,'delivery_events')[0]['disposition']=='unmatched'
            return 'wamid.early'
    meta[1].sender=EarlySender()
    meta[1].send_one()
    assert rows(meta,'outbox')[0]['state']=='delivered'
    assert rows(meta,'delivery_events')[0]['disposition']=='matched'


def test_timeout_reconciled_by_attempt_callback_without_resend(meta, setup):
    queued(meta, setup);meta[2].fail=True;meta[1].send_one()
    attempt=rows(meta,'delivery_attempts')[0]
    assert attempt['state']=='uncertain'
    assert status(meta,'sent',callback=attempt['id']).status_code==200
    assert rows(meta,'outbox')[0]['state']=='sent'
    assert status(meta,'delivered',mid='wamid.uncertain').status_code==200
    assert rows(meta,'outbox')[0]['state']=='delivered' and len(meta[2].calls)==1
    assert not meta[1].send_one()


def test_callback_during_send_not_overwritten_by_timeout(meta, setup):
    queued(meta, setup)
    class RacingSender:
        def send(self,payload,*,key):
            assert status(meta,'read',mid='wamid.race',callback=key).status_code==200
            raise TimeoutError()
    meta[1].sender=RacingSender();meta[1].send_one()
    assert rows(meta,'outbox')[0]['state']=='read'


def test_failed_retry_new_attempt_late_old_status_and_audit(meta, setup):
    oid=queued(meta, setup);meta[1].send_one()
    old=rows(meta,'delivery_attempts')[0]['provider_id']
    status(meta,'failed');assert rows(meta,'outbox')[0]['state']=='failed'
    recover(meta,oid);meta[1].send_one()
    new=rows(meta,'delivery_attempts')[-1]['provider_id']
    assert new!=old and len(meta[2].calls)==2
    status(meta,'failed',mid=old)
    assert rows(meta,'outbox')[0]['state']=='accepted'
    status(meta,'delivered',mid=new)
    status(meta,'sent',mid=old)
    assert rows(meta,'outbox')[0]['state']=='delivered'
    assert len(rows(meta,'delivery_audit'))==1
    with pytest.raises(ValueError):recover(meta,oid)


def test_late_delivery_cancels_pending_manual_retry(meta, setup):
    oid=queued(meta,setup);meta[1].send_one();status(meta,'failed')
    recover(meta,oid)
    status(meta,'delivered')
    assert not meta[1].send_one() and len(meta[2].calls)==1


def test_recovery_requires_fresh_confirmation_and_uncertainty_ack(meta, setup):
    oid=queued(meta,setup);meta[2].fail=True;meta[1].send_one()
    with pytest.raises(ValueError):recover(meta,oid)
    snap=meta[1].inspect_delivery(oid)
    status(meta,'failed',callback=rows(meta,'delivery_attempts')[0]['id'])
    with pytest.raises(ValueError):
        meta[1].recover(oid,action='retry',operator='op',reason='Synthetic evidence verified',confirmation=snap['confirmation'])
    recover(meta,oid);meta[2].fail=False;meta[1].send_one()
    assert len(meta[2].calls)==2


def test_uncertain_expiry_revocation_and_local_cancel(meta, setup):
    oid=queued(meta,setup);meta[2].fail=True;meta[1].send_one()
    recover(meta,oid,accept_duplicate_risk=True)
    setup[0].delete('/api/channels/whatsapp/bindings/'+PHONE,headers=setup[1])
    meta[1].send_one()
    assert rows(meta,'outbox')[0]['state']=='cancelled' and len(meta[2].calls)==1
    assert LocalRecovery(meta[1].path).inspect_delivery(oid)['message']['state']=='cancelled'


def test_active_send_lease_and_recovery_cli(meta, setup, capsys):
    oid=queued(meta,setup);meta[2].crash=True
    with pytest.raises(KeyboardInterrupt):meta[1].send_one()
    with pytest.raises(ValueError):recover(meta,oid,action='cancel')
    with meta[1].transaction() as db:db.execute('UPDATE delivery_attempts SET created=0')
    main(['--state',str(meta[1].path),'--id',oid])
    snap=json.loads(capsys.readouterr().out)
    assert 'payload' not in snap and 'confirmation' in snap
    main(['--state',str(meta[1].path),'--id',oid,'--action','cancel','--operator','simulation-op',
          '--reason','Synthetic stopped worker verified','--confirmation',snap['confirmation']])
    assert json.loads(capsys.readouterr().out)['message']['state']=='cancelled'
    assert not meta[1].send_one()


def test_status_signature_account_and_atomic_malformed_batch(meta, setup):
    queued(meta,setup);meta[1].send_one()
    p=envelope('unused');v=p['entry'][0]['changes'][0]['value'];v.pop('messages')
    v['statuses']=[{'id':rows(meta,'delivery_attempts')[0]['provider_id'],'recipient_id':PHONE,
                    'status':'read','timestamp':str(int(time.time()))}]
    assert post(meta,p,secret='wrong').status_code==401
    p['entry'][0]['id']='foreign';assert post(meta,p).status_code==403
    p['entry'][0]['id']='test-waba';v['statuses'].append({'status':'read'})
    assert post(meta,p).status_code==422
    assert not rows(meta,'delivery_events') and rows(meta,'outbox')[0]['state']=='accepted'


def test_graph_timeout_and_http_failure_classification_end_to_end(meta, setup):
    oid=queued(meta,setup)
    def timeout(req):raise httpx.ReadTimeout('synthetic timeout',request=req)
    meta[1].sender=GraphSender(phone_number_id='123',api_version='v25.0',token='synthetic',enabled=True,
                              transport=httpx.MockTransport(timeout))
    meta[1].send_one();assert rows(meta,'outbox')[0]['state']=='uncertain'
    recover(meta,oid,accept_duplicate_risk=True)
    meta[1].sender=GraphSender(phone_number_id='123',api_version='v25.0',token='synthetic',enabled=True,
                              transport=httpx.MockTransport(lambda _:httpx.Response(429,json={'error':{'code':130429}})))
    meta[1].send_one();assert rows(meta,'outbox')[0]['state']=='failed'
    assert not meta[1].send_one()


def test_recovery_expiry_and_concurrent_confirmation(meta, setup):
    oid=queued(meta,setup);meta[2].fail=True;meta[1].send_one()
    snap=meta[1].inspect_delivery(oid)
    def attempt(_):
        try:
            meta[1].recover(oid,action='retry',operator='simulation-op',reason='Synthetic evidence independently checked',
                            confirmation=snap['confirmation'],accept_duplicate_risk=True)
            return True
        except ValueError:return False
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(attempt,range(2)))==[False,True]
    assert len(rows(meta,'delivery_audit'))==1
    meta[1].send_one()
    with meta[1].transaction() as db:db.execute('UPDATE outbox SET expires=0')
    with pytest.raises(ValueError):recover(meta,oid,accept_duplicate_risk=True)
    recover(meta,oid,action='cancel')


def test_old_state_migrates_and_callback_conflict_is_quarantined(meta, setup):
    oid=queued(meta,setup);meta[1].send_one()
    mid=rows(meta,'delivery_attempts')[0]['provider_id']
    with meta[1].transaction() as db:db.execute('DROP TABLE delivery_attempts')
    snapshot=LocalRecovery(meta[1].path).inspect_delivery(oid)
    assert snapshot['attempts'][0]['id']=='legacy-'+oid
    assert status(meta,'delivered',mid=mid).status_code==200
    assert rows(meta,'outbox')[0]['state']=='delivered'
    assert status(meta,'read',mid=mid,callback='attempt-wrong').status_code==200
    assert rows(meta,'delivery_events')[-1]['disposition']=='conflict'
    assert rows(meta,'outbox')[0]['state']=='delivered'


def test_old_attempt_delivered_preserves_correct_receipt(meta, setup):
    oid=queued(meta,setup);meta[1].send_one();old=rows(meta,'delivery_attempts')[0]['provider_id']
    status(meta,'failed');recover(meta,oid);meta[1].send_one()
    status(meta,'delivered',mid=old)
    row=rows(meta,'outbox')[0]
    assert row['state']=='delivered' and row['provider_message_id']==old
    assert len(rows(meta,'delivery_attempts'))==2
