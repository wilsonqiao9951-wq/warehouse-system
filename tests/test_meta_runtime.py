import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from app.integrations.meta_runtime import Operations, Worker, WorkerLock, WorkerBusy, restore
from app.integrations.meta_whatsapp import Bridge
from scripts.meta_worker import initialize, main
from test_whatsapp_adapter import setup, bind, SECRET
from test_meta_whatsapp import meta, dispatch, rows, envelope, post
from test_meta_delivery import queued, status, recover


def test_worker_drains_real_adapter_then_stops(meta, setup):
    bind(setup);post(meta,envelope('我的身份'))
    worker=Worker(meta[1],poll_seconds=.01)
    assert worker.run(max_cycles=2)['state']=='stopped'
    assert len(meta[2].calls)==1 and rows(meta,'outbox')[0]['state']=='accepted'
    monitor=worker.operations.monitor()
    assert monitor['worker']['state']=='stopped' and not monitor['lock_held']
    assert '15550000001' not in json.dumps(monitor)
    worker.run(max_cycles=1)
    assert len(meta[2].calls)==1


def test_lock_excludes_worker_recovery_backup_and_cleanup(meta,setup,tmp_path):
    oid=queued(meta,setup);meta[2].fail=True;meta[1].send_one()
    ops=Operations(meta[1].path)
    with WorkerLock(meta[1].path):
        with pytest.raises(WorkerBusy):Worker(meta[1]).run(max_cycles=1)
        with pytest.raises(WorkerBusy):recover(meta,oid,accept_duplicate_risk=True)
        with pytest.raises(WorkerBusy):ops.backup(tmp_path/'backup.db',operator='test')
        with pytest.raises(WorkerBusy):ops.cleanup(confirmation=ops.cleanup_plan()['confirmation'],backup_path=tmp_path/'cleanup.db',operator='test')
    assert not (tmp_path/'backup.db').exists()


def test_stop_requested_during_processing_prevents_next_send(meta,setup,monkeypatch):
    bind(setup);post(meta,envelope('我的身份'))
    worker=Worker(meta[1],poll_seconds=.01)
    original=meta[1].process_one
    def process():
        result=original();worker.operations.stop();return result
    monkeypatch.setattr(meta[1],'process_one',process)
    worker.run(max_cycles=3)
    assert not meta[2].calls and rows(meta,'outbox')[0]['state']=='pending'
    monkeypatch.setattr(meta[1],'process_one',original)
    Worker(meta[1],poll_seconds=.01).run(max_cycles=1)
    assert len(meta[2].calls)==1


def test_worker_transient_error_is_bounded_and_sanitized(meta,setup,monkeypatch):
    bind(setup);post(meta,envelope('我的身份'))
    original=meta[1].process_one;calls=[]
    def failing():
        calls.append(1)
        if len(calls)==1:raise RuntimeError('SECRET BODY MUST NOT BE RECORDED')
        return original()
    monkeypatch.setattr(meta[1],'process_one',failing)
    worker=Worker(meta[1],poll_seconds=.01,max_backoff=.02)
    worker.run(max_cycles=2)
    assert len(calls)==2 and len(meta[2].calls)==1
    assert 'SECRET BODY' not in json.dumps(worker.operations.monitor())
    assert worker.operations.monitor()['worker']['consecutive_errors']==0


def test_interrupted_send_remains_held_after_worker_restart(meta,setup):
    queued(meta,setup);meta[2].crash=True
    with pytest.raises(KeyboardInterrupt):Worker(meta[1]).run(max_cycles=1)
    assert rows(meta,'outbox')[0]['state']=='sending'
    meta[2].crash=False
    Worker(meta[1]).run(max_cycles=1)
    assert len(meta[2].calls)==1
    assert Operations(meta[1].path).monitor()['counts']['outbox']['sending']==1


def test_monitor_backlog_unknown_callbacks_and_stale_worker(meta,setup):
    post(meta,envelope('我的身份',stamp=int(time.time())-600))
    status(meta,'read',mid='unknown-message')
    ops=Operations(meta[1].path)
    with ops.transaction() as db:
        db.execute("INSERT INTO worker_control VALUES(1,'stale',123,'running',0,0,0)")
    result=ops.monitor()
    assert {'inbox_backlog','callback_attention','worker_interrupted','heartbeat_stale'}<=set(result['alerts'])
    assert result['counts']['delivery_events']['unmatched']==1


def test_backup_restore_preserves_dedup_audits_and_held_sends(meta,setup,tmp_path):
    oid=queued(meta,setup);meta[2].fail=True;meta[1].send_one();recover(meta,oid,action='cancel')
    ops=Operations(meta[1].path)
    result=ops.backup(tmp_path/'backup.db',operator='simulation-admin')
    assert result['integrity']=='ok' and (tmp_path/'backup.db').stat().st_mode&0o777==0o600
    restored=tmp_path/'restored.db'
    with pytest.raises(ValueError):restore(result['path'],restored,sha256='wrong')
    restore(result['path'],restored,sha256=result['sha256'])
    with sqlite3.connect(restored) as db:
        assert db.execute('SELECT COUNT(*) FROM delivery_audit').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM delivery_attempts').fetchone()[0]==1
    bridge=Bridge(state_path=restored,adapter=setup[0],sender=meta[2],channel_secret=SECRET)
    assert not bridge.send_one() and not bridge.process_one()
    with pytest.raises(ValueError):restore(result['path'],restored,sha256=result['sha256'])
    with pytest.raises(FileExistsError):ops.backup(result['path'],operator='test')


def aged_completed(meta,setup):
    bind(setup);p=envelope('我的身份')
    post(meta,p);meta[1].process_one();meta[1].send_one();status(meta,'read')
    oid=rows(meta,'outbox')[0]['id']
    # Preserve original envelope/fingerprint for replay tests; age both consistently.
    original=p['entry'][0]['changes'][0]['value']['messages'][0]
    original['timestamp']=str(int(time.time())-40*86400)
    from app.integrations.meta_whatsapp import extract_messages,canonical
    import hashlib
    message=extract_messages(p,waba_id='test-waba',phone_number_id='test-line')[0]
    with meta[1].transaction() as db:
        db.execute('UPDATE inbox SET payload=?,fingerprint=? WHERE id=?',
                   (canonical(message),hashlib.sha256(canonical(message).encode()).hexdigest(),oid))
    return oid,p


def test_cleanup_redacts_only_text_keeps_dedup_late_status_and_audit(meta,setup,tmp_path):
    oid,p=aged_completed(meta,setup);ops=Operations(meta[1].path)
    before=rows(meta,'inbox')[0]['fingerprint']
    plan=ops.cleanup_plan();assert len(plan['candidates'])==1
    result=ops.cleanup(confirmation=plan['confirmation'],backup_path=tmp_path/'pre-clean.db',operator='simulation-admin')
    assert result['redacted']==1
    assert json.loads(rows(meta,'inbox')[0]['payload'])['text']==''
    assert rows(meta,'inbox')[0]['fingerprint']==before
    assert len(rows(meta,'delivery_attempts'))==1 and len(rows(meta,'delivery_events'))==1
    assert len(rows(meta,'maintenance_audit'))==1
    assert post(meta,p).status_code==200
    assert not meta[1].process_one() and not meta[1].send_one()
    assert status(meta,'delivered').status_code==200 and rows(meta,'outbox')[0]['state']=='read'
    assert not ops.cleanup_plan()['candidates']


def test_cleanup_stale_confirmation_and_backup_failure_never_mutate(meta,setup,tmp_path):
    oid,_=aged_completed(meta,setup);ops=Operations(meta[1].path);plan=ops.cleanup_plan()
    with pytest.raises(OSError):ops.cleanup(confirmation=plan['confirmation'],backup_path=tmp_path/'missing'/'b.db',operator='test')
    with pytest.raises(ValueError):ops.cleanup(confirmation='stale',backup_path=tmp_path/'backup.db',operator='test')
    assert json.loads(rows(meta,'inbox')[0]['payload'])['text']=='我的身份'
    with pytest.raises(ValueError):ops.cleanup_plan(1)


def test_cleanup_preserves_unresolved_attempts(meta,setup,tmp_path):
    oid,_=aged_completed(meta,setup);ops=Operations(meta[1].path)
    with meta[1].transaction() as db:
        db.execute("UPDATE delivery_attempts SET state='uncertain'")
    assert not ops.cleanup_plan()['candidates']


def wait_for(predicate, timeout=8):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if predicate():return
        time.sleep(.02)
    raise AssertionError('Timed out waiting for subprocess state')


def test_simulation_cli_process_lock_sigkill_restart_and_sigterm(tmp_path):
    path=tmp_path/'simulation.db';initialize(path);ops=Operations(path)
    args=[sys.executable,'-m','scripts.meta_worker','start','--state',str(path),'--simulation']
    first=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    second=third=None
    try:
        wait_for(lambda:ops.monitor()['lock_held'])
        second=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=8)
        assert second.returncode!=0 and b'already owns' in second.stderr
        first.kill();first.wait(timeout=8)
        assert 'worker_interrupted' in ops.monitor()['alerts']
        third=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        wait_for(lambda:ops.monitor()['worker']['pid']==third.pid)
        third.terminate();assert third.wait(timeout=8)==0
        assert ops.monitor()['worker']['state']=='stopped' and not ops.monitor()['lock_held']
        with ops.transaction() as db:
            assert db.execute("SELECT COUNT(*) FROM worker_audit WHERE event='interrupted'").fetchone()[0]==1
    finally:
        for proc in (first,third):
            if proc and proc.poll() is None:proc.kill();proc.wait()


def test_cli_defaults_no_live_start_and_control_stop(tmp_path,capsys):
    path=tmp_path/'simulation.db'
    with pytest.raises(SystemExit):main(['init','--state',str(path)])
    main(['init','--state',str(path),'--simulation']);capsys.readouterr()
    with pytest.raises(SystemExit):main(['start','--state',str(path)])
    with pytest.raises(FileExistsError):initialize(path)
    proc=subprocess.Popen([sys.executable,'-m','scripts.meta_worker','start','--state',str(path),'--simulation'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        ops=Operations(path);wait_for(lambda:bool(ops.monitor()['worker']) and ops.monitor()['worker']['pid']==proc.pid)
        assert ops.stop()['stop_requested']
        assert proc.wait(timeout=8)==0
    finally:
        if proc.poll() is None:proc.kill();proc.wait()


def test_canonical_alias_lock_and_hardlink_rejection(tmp_path):
    path=tmp_path/'real.sqlite';initialize(path)
    alias=tmp_path/'alias.db';alias.symlink_to(path)
    with WorkerLock(path):
        with pytest.raises(WorkerBusy):
            with WorkerLock(alias):pass
    hard=tmp_path/'hard.db';os.link(path,hard)
    with pytest.raises(ValueError):WorkerLock(hard)


def test_restore_inflight_state_stays_held(meta,setup,tmp_path):
    queued(meta,setup);meta[2].crash=True
    with pytest.raises(KeyboardInterrupt):meta[1].send_one()
    ops=Operations(meta[1].path);snapshot=ops.backup(tmp_path/'held.db',operator='simulation-op')
    restored=tmp_path/'restored-held.db';restore(snapshot['path'],restored,sha256=snapshot['sha256'])
    meta[2].crash=False
    bridge=Bridge(state_path=restored,adapter=setup[0],sender=meta[2],channel_secret=SECRET)
    Worker(bridge).run(max_cycles=1)
    assert len(meta[2].calls)==1
    assert Operations(restored).monitor()['counts']['outbox']['sending']==1
