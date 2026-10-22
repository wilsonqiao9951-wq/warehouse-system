"""Single-host worker and private state operations. No live transport configuration."""
import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from contextlib import closing

from app.integrations.meta_whatsapp import StateStore, canonical


class WorkerBusy(ValueError):
    pass


class WorkerLock:
    """OS releases this advisory lock on process death. Never unlink the lock file."""
    def __init__(self, path):
        canonical_path = Path(path).resolve()
        if canonical_path.exists() and canonical_path.stat().st_nlink != 1:
            raise ValueError('Hard-linked state files are not supported')
        self.path = canonical_path.with_name(canonical_path.name + '.worker.lock')
        self.fd = None

    def __enter__(self):
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.fchmod(self.fd, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.fd)
            self.fd = None
            raise WorkerBusy('Worker or maintenance already owns this state file')
        return self

    def __exit__(self, *args):
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)
        self.fd = None


RUNTIME_SCHEMA = '''
CREATE TABLE IF NOT EXISTS worker_control (
 id INTEGER PRIMARY KEY CHECK(id=1), token TEXT NOT NULL, pid INTEGER NOT NULL,
 state TEXT NOT NULL, heartbeat REAL NOT NULL, stop_requested INTEGER NOT NULL DEFAULT 0,
 consecutive_errors INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS worker_audit (
 id INTEGER PRIMARY KEY, token TEXT NOT NULL, event TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS maintenance_audit (
 id INTEGER PRIMARY KEY, action TEXT NOT NULL, operator TEXT NOT NULL,
 detail TEXT NOT NULL, created REAL NOT NULL);
'''


class Operations(StateStore):
    def __init__(self, path):
        if not Path(path).is_file():
            raise ValueError('Existing private state database required')
        super().__init__(Path(path).resolve())
        with self.transaction() as db:
            # Individual DDL statements retain the parent's transaction.
            for statement in RUNTIME_SCHEMA.split(';'):
                if statement.strip():
                    db.execute(statement)

    def stop(self):
        with self.transaction() as db:
            db.execute("UPDATE worker_control SET stop_requested=1 WHERE id=1 AND state='running'")
            return {'stop_requested': bool(db.execute('SELECT changes()').fetchone()[0])}

    def monitor(self):
        now = time.time()
        with self.transaction() as db:
            counts = {table: dict(db.execute(f'SELECT {field},COUNT(*) FROM {table} GROUP BY {field}'))
                      for table, field in [('inbox','state'), ('outbox','state'),
                                           ('delivery_attempts','state'), ('delivery_events','disposition')]}
            out_pending = db.execute("SELECT expires FROM outbox WHERE state='pending'").fetchall()
            out_age = max([now-(r[0]-86400) for r in out_pending] or [0])
            pending = db.execute("SELECT payload FROM inbox WHERE state='pending'").fetchall()
            age = max([now-json.loads(r[0])['timestamp'] for r in pending] or [0])
            row = db.execute('SELECT * FROM worker_control WHERE id=1').fetchone()
            worker = dict(row) if row else None
            problems = [dict(r) for r in db.execute("SELECT id,state FROM outbox WHERE state IN ('sending','uncertain','failed') ORDER BY rowid LIMIT 100")]
        try:
            with WorkerLock(self.path):
                locked = False
        except WorkerBusy:
            locked = True
        alerts = []
        if worker and (worker['state']=='interrupted' or (worker['state']=='running' and not locked)):
            alerts.append('worker_interrupted')
        if worker and worker['state']=='running' and now-worker['heartbeat']>60:
            alerts.append('heartbeat_stale')
        if counts['inbox'].get('pending',0) >= 100 or age > 300:
            alerts.append('inbox_backlog')
        if counts['outbox'].get('pending',0) >= 100 or out_age > 300:
            alerts.append('outbox_backlog')
        if worker and worker['consecutive_errors']:
            alerts.append('worker_errors')
        if not locked and (pending or out_pending):
            alerts.append('queue_without_worker')
        if problems:
            alerts.append('delivery_attention')
        if counts['delivery_events'].get('unmatched',0) or counts['delivery_events'].get('conflict',0):
            alerts.append('callback_attention')
        free = shutil.disk_usage(self.path.parent).free
        if free < 256*1024*1024:
            alerts.append('disk_low')
        return {'counts': counts, 'oldest_pending_seconds': max(0,int(age)),
                'oldest_outbox_pending_seconds': max(0,int(out_age)), 'worker': worker,
                'lock_held': locked, 'alerts': alerts, 'delivery_attention': problems,
                'database_bytes': self.path.stat().st_size, 'free_disk_bytes': free}

    def _backup(self, destination):
        target = Path(destination).resolve()
        if target == self.path:
            raise ValueError('Backup must be a new separate file')
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        try:
            with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True)) as source:
                with closing(sqlite3.connect(target)) as dest:
                    source.backup(dest)
                    if dest.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise ValueError('Backup integrity check failed')
            return {'path': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                    'bytes': target.stat().st_size, 'integrity': 'ok'}
        except BaseException:
            target.unlink(missing_ok=True)
            raise

    def backup(self, destination, *, operator):
        if not operator.strip():
            raise ValueError('Operator required')
        with WorkerLock(self.path):
            result = self._backup(destination)
            with self.transaction() as db:
                db.execute('INSERT INTO maintenance_audit(action,operator,detail,created) VALUES(?,?,?,?)',
                           ('backup', operator, canonical(result), time.time()))
            return result

    def _plan(self, db, retention_days):
        if type(retention_days) is not int or retention_days < 7:
            raise ValueError('Minimum completed-payload retention is seven days')
        cutoff = time.time() - retention_days*86400
        items = []
        for row in db.execute("SELECT i.id,i.payload,i.state,o.state AS outbound,o.payload AS reply FROM inbox i LEFT JOIN outbox o ON o.id=i.id WHERE i.state!='pending'"):
            payload = json.loads(row['payload'])
            if payload.get('redacted') or payload['timestamp'] >= cutoff:
                continue
            if row['outbound'] not in (None, 'delivered', 'read', 'cancelled', 'expired'):
                continue
            # Keep all unresolved attempt material for manual reconciliation.
            if db.execute("SELECT 1 FROM delivery_attempts WHERE outbox_id=? AND state IN ('sending','uncertain','accepted','sent')", (row['id'],)).fetchone():
                continue
            items.append({'id': row['id'], 'digest': hashlib.sha256((row['payload']+(row['reply'] or '')).encode()).hexdigest()})
        result = {'retention_days': retention_days, 'candidates': sorted(items,key=lambda x:x['id']),
                  'policy': 'redact_completed_text_only_v1'}
        result['confirmation'] = hashlib.sha256(canonical(result).encode()).hexdigest()
        return result

    def cleanup_plan(self, retention_days=30):
        with self.transaction() as db:
            return self._plan(db, retention_days)

    def cleanup(self, *, retention_days=30, confirmation, backup_path, operator):
        if not operator.strip():
            raise ValueError('Operator required')
        with WorkerLock(self.path):
            backup = self._backup(backup_path)
            with self.transaction() as db:
                plan = self._plan(db, retention_days)
                if plan['confirmation'] != confirmation:
                    raise ValueError('Cleanup candidates changed; inspect again (backup retained)')
                for item in plan['candidates']:
                    row = db.execute('SELECT payload FROM inbox WHERE id=?', (item['id'],)).fetchone()
                    payload = json.loads(row[0]);payload['text']='';payload['redacted']=True
                    db.execute('UPDATE inbox SET payload=? WHERE id=?', (canonical(payload),item['id']))
                    row = db.execute('SELECT payload FROM outbox WHERE id=?', (item['id'],)).fetchone()
                    if row:
                        reply=json.loads(row[0]);reply['text']={'body':''};reply['redacted']=True
                        db.execute('UPDATE outbox SET payload=? WHERE id=?', (canonical(reply),item['id']))
                result={'redacted': len(plan['candidates']), 'backup':backup, 'retention_days':retention_days}
                db.execute('INSERT INTO maintenance_audit(action,operator,detail,created) VALUES(?,?,?,?)',
                           ('cleanup',operator,canonical(result),time.time()))
                return result


def restore(backup, destination, *, sha256):
    source=Path(backup).resolve();dest=Path(destination).resolve()
    if hashlib.sha256(source.read_bytes()).hexdigest() != sha256:
        raise ValueError('Backup checksum mismatch')
    if dest.exists():
        raise ValueError('Restore destination must not exist')
    # New database only; never overwrite or switch a running worker's database.
    with WorkerLock(dest):
        fd=os.open(dest,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        try:
            with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src:
                if src.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                    raise ValueError('Invalid backup')
                with closing(sqlite3.connect(dest)) as target:
                    src.backup(target)
                    if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                        raise ValueError('Restored state integrity check failed')
            return {'path':str(dest),'integrity':'ok','worker_started':False}
        except BaseException:
            dest.unlink(missing_ok=True)
            raise


class Worker:
    def __init__(self, bridge, *, poll_seconds=1, max_backoff=30):
        if not 0.01 <= poll_seconds <= max_backoff <= 60:
            raise ValueError('Invalid bounded polling/backoff')
        self.bridge=bridge;self.operations=Operations(bridge.path)
        self.poll=poll_seconds;self.max_backoff=max_backoff
        self.stop_event=threading.Event()

    def request_stop(self, *unused):
        self.stop_event.set()

    def run(self, *, max_cycles=None):
        token=uuid.uuid4().hex
        with WorkerLock(self.bridge.path):
            with self.operations.transaction() as db:
                old=db.execute('SELECT token,state FROM worker_control WHERE id=1').fetchone()
                if old and old['state']=='running':
                    db.execute('INSERT INTO worker_audit(token,event,created) VALUES(?,?,?)',(old['token'],'interrupted',time.time()))
                db.execute("INSERT OR REPLACE INTO worker_control VALUES(1,?,?,'running',?,0,0)",(token,os.getpid(),time.time()))
                db.execute('INSERT INTO worker_audit(token,event,created) VALUES(?,?,?)',(token,'started',time.time()))
            cycles=errors=0;state='stopped'
            try:
                while not self.stop_event.is_set() and (max_cycles is None or cycles<max_cycles):
                    with self.operations.transaction() as db:
                        if db.execute('SELECT stop_requested FROM worker_control WHERE id=1').fetchone()[0]:
                            break
                    try:
                        processed=self.bridge.process_one()
                        with self.operations.transaction() as db:
                            stop_requested=db.execute('SELECT stop_requested FROM worker_control WHERE id=1').fetchone()[0]
                        if not self.stop_event.is_set() and not stop_requested:
                            processed=self.bridge.send_one() or processed
                        errors=0
                    except Exception:
                        # Never persist exception text: it may contain credentials or request bodies.
                        errors+=1;processed=False
                    cycles+=1
                    with self.operations.transaction() as db:
                        db.execute('UPDATE worker_control SET heartbeat=?,consecutive_errors=? WHERE token=?',(time.time(),errors,token))
                    delay=min(self.max_backoff,self.poll*2**min(errors,10)) if errors else (0 if processed else self.poll)
                    if max_cycles is None or cycles<max_cycles:
                        self.stop_event.wait(delay)
            except BaseException:
                state='interrupted'
                raise
            finally:
                with self.operations.transaction() as db:
                    db.execute('UPDATE worker_control SET state=?,heartbeat=? WHERE token=?',(state,time.time(),token))
                    db.execute('INSERT INTO worker_audit(token,event,created) VALUES(?,?,?)',(token,state,time.time()))
        return {'cycles':cycles,'state':state}
