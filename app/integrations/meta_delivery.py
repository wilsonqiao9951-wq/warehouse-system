"""Graph transport and local delivery ledger. Never starts a live service."""
import hashlib
import json
import re
import time
import uuid

import httpx


class SendRejected(Exception):
    """Definite HTTP rejection, containing only a safe status/code summary."""


class GraphSender:
    def __init__(self, *, phone_number_id, api_version, token='', enabled=False, transport=None):
        if not re.fullmatch(r'[0-9]+', phone_number_id) or not re.fullmatch(r'v[0-9]+\.0', api_version):
            raise ValueError('Explicit Graph version and numeric phone ID required')
        self.url = f'https://graph.facebook.com/{api_version}/{phone_number_id}/messages'
        self.token, self.enabled, self.transport = token, enabled, transport

    def send(self, payload, *, key):
        if not self.enabled:
            raise SendRejected('Graph sending disabled')
        if not self.token:
            raise SendRejected('Graph token missing')
        # No redirects or HTTP auto-retries. A timeout/5xx may follow actual acceptance.
        with httpx.Client(transport=self.transport, timeout=httpx.Timeout(10, connect=3),
                          follow_redirects=False) as client:
            response = client.post(self.url, headers={'Authorization': 'Bearer '+self.token},
                                   json={**payload, 'biz_opaque_callback_data': key})
        if 400 <= response.status_code < 500:
            raise SendRejected(f'Graph HTTP {response.status_code}')
        if not 200 <= response.status_code < 300:
            raise RuntimeError('Graph acceptance unknown')
        data = response.json()
        messages = data.get('messages', [])
        if (len(messages) != 1 or not isinstance(messages[0].get('id'), str)
                or not 1 <= len(messages[0]['id']) <= 300):
            raise RuntimeError('Graph receipt missing or invalid')
        return messages[0]['id']


SCHEMA = '''
CREATE TABLE IF NOT EXISTS delivery_attempts (
 id TEXT PRIMARY KEY, outbox_id TEXT NOT NULL, state TEXT NOT NULL,
 provider_id TEXT UNIQUE, created REAL NOT NULL, error TEXT);
CREATE TABLE IF NOT EXISTS delivery_events (
 fingerprint TEXT PRIMARY KEY, payload TEXT NOT NULL, disposition TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS delivery_audit (
 id INTEGER PRIMARY KEY, outbox_id TEXT NOT NULL, action TEXT NOT NULL,
 operator TEXT NOT NULL, reason TEXT NOT NULL, previous TEXT NOT NULL, created REAL NOT NULL);
'''


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


class DeliveryLifecycle:
    """Uses the bridge's private SQLite transaction; no public administration endpoint."""

    def begin_attempt(self, db, row):
        aid = 'attempt-' + uuid.uuid4().hex
        db.execute('INSERT INTO delivery_attempts VALUES(?,?,?,?,?,?)',
                   (aid, row['id'], 'sending', None, time.time(), None))
        db.execute("UPDATE outbox SET state='sending' WHERE id=?", (row['id'],))
        return aid

    def finish_attempt(self, aid, *, provider_id=None, failure=None, error=None):
        with self.transaction() as db:
            attempt = db.execute('SELECT * FROM delivery_attempts WHERE id=?', (aid,)).fetchone()
            state = 'accepted' if provider_id else failure
            # A callback may arrive while the HTTP response is in flight. Never regress it.
            if attempt['state'] in {'sending', 'uncertain'}:
                db.execute('UPDATE delivery_attempts SET state=? WHERE id=?', (state, aid))
            if provider_id:
                if attempt['provider_id'] and attempt['provider_id'] != provider_id:
                    db.execute("UPDATE delivery_attempts SET error='receipt_conflict' WHERE id=?", (aid,))
                else:
                    db.execute('UPDATE delivery_attempts SET provider_id=? WHERE id=?', (provider_id, aid))
            if error and not attempt['error']:
                db.execute('UPDATE delivery_attempts SET error=? WHERE id=?', (error, aid))
            self.reconcile(db)
            self.refresh(db, attempt['outbox_id'])

    def refresh(self, db, oid):
        attempts = db.execute('SELECT * FROM delivery_attempts WHERE outbox_id=? ORDER BY rowid', (oid,)).fetchall()
        if not attempts:
            return
        current = db.execute('SELECT state FROM outbox WHERE id=?', (oid,)).fetchone()[0]
        states = {a['state'] for a in attempts}
        # Delivery of ANY attempt prevents retry and outranks late failure notifications.
        state = 'read' if 'read' in states else 'delivered' if 'delivered' in states else attempts[-1]['state']
        evidence = next((a for a in reversed(attempts) if a['state'] == state), attempts[-1])
        if current in {'cancelled', 'expired'} and state not in {'read', 'delivered'}:
            state = current
        # Keep an explicitly authorized retry pending unless delivery evidence cancels it.
        if current == 'pending' and state not in {'read', 'delivered'}:
            return
        db.execute('UPDATE outbox SET state=?,provider_message_id=? WHERE id=?',
                   (state, evidence['provider_id'], oid))

    def accept_statuses(self, db, statuses):
        for status in statuses:
            payload = encode(status)
            fingerprint = hashlib.sha256(payload.encode()).hexdigest()
            db.execute('INSERT OR IGNORE INTO delivery_events VALUES(?,?,?)', (fingerprint, payload, 'unmatched'))
        self.reconcile(db)

    def reconcile(self, db):
        for event in db.execute("SELECT * FROM delivery_events WHERE disposition='unmatched'").fetchall():
            s = json.loads(event['payload'])
            a = db.execute('SELECT * FROM delivery_attempts WHERE provider_id=?', (s['id'],)).fetchone()
            if not a and s.get('callback'):
                a = db.execute('SELECT * FROM delivery_attempts WHERE id=?', (s['callback'],)).fetchone()
            if not a:
                continue
            outbox = db.execute('SELECT payload FROM outbox WHERE id=?', (a['outbox_id'],)).fetchone()
            conflict = (json.loads(outbox[0])['to'] != s['recipient_id'] or
                        (a['provider_id'] and a['provider_id'] != s['id']) or
                        (s.get('callback') and s['callback'] != a['id']))
            disposition = 'conflict' if conflict else 'matched'
            if not conflict:
                old, new = a['state'], s['status']
                rank = {'sent': 1, 'delivered': 2, 'read': 3}
                if old in {'delivered', 'read'}:
                    new = max((old, new), key=lambda x: rank.get(x, 0))
                elif old == 'failed' and new == 'sent':
                    new = old
                db.execute('UPDATE delivery_attempts SET state=?,provider_id=?,error=? WHERE id=?',
                           (new, s['id'], encode(s.get('error_codes', [])) if s['status']=='failed' else a['error'], a['id']))
                self.refresh(db, a['outbox_id'])
            db.execute('UPDATE delivery_events SET disposition=? WHERE fingerprint=?', (disposition, event['fingerprint']))

    def recovery_snapshot(self, db, oid):
        row = db.execute('SELECT id,state,expires,provider_message_id FROM outbox WHERE id=?', (oid,)).fetchone()
        if not row:
            raise ValueError('Unknown outbox message')
        attempts = [dict(a) for a in db.execute('SELECT * FROM delivery_attempts WHERE outbox_id=? ORDER BY rowid', (oid,))]
        result = {'message': dict(row), 'attempts': attempts}
        result['confirmation'] = hashlib.sha256(encode(result).encode()).hexdigest()
        return result

    def inspect_events(self):
        with self.transaction() as db:
            result = []
            for row in db.execute("SELECT * FROM delivery_events ORDER BY rowid DESC LIMIT 100"):
                event = json.loads(row['payload'])
                result.append({'fingerprint': row['fingerprint'], 'disposition': row['disposition'],
                               'provider_id': event['id'], 'attempt_id': event.get('callback'),
                               'status': event['status'], 'timestamp': event['timestamp'],
                               'error_codes': event.get('error_codes', [])})
            return result

    def inspect_delivery(self, oid=None):
        with self.transaction() as db:
            if oid:
                return self.recovery_snapshot(db, oid)
            return [dict(r) for r in db.execute('SELECT id,state,expires FROM outbox ORDER BY rowid DESC LIMIT 100')]

    def recover(self, oid, *, action, operator, reason, confirmation, accept_duplicate_risk=False):
        if action not in {'cancel', 'retry'} or not operator.strip() or len(reason.strip()) < 10:
            raise ValueError('Action, operator and meaningful evidence/reason required')
        from app.integrations.meta_runtime import WorkerLock
        with WorkerLock(self.path), self.transaction() as db:
            snapshot = self.recovery_snapshot(db, oid)
            if confirmation != snapshot['confirmation']:
                raise ValueError('State changed; inspect again')
            state = snapshot['message']['state']
            if state not in {'failed', 'uncertain', 'sending'}:
                raise ValueError('Only failed or unresolved messages can be recovered')
            attempts = snapshot['attempts']
            if state == 'sending' and (not attempts or time.time()-attempts[-1]['created'] < 300):
                raise ValueError('Sending lease active; stop the worker and wait before recovery')
            if action == 'retry':
                if snapshot['message']['expires'] <= time.time():
                    raise ValueError('Reply window expired')
                if state in {'uncertain', 'sending'} and not accept_duplicate_risk:
                    raise ValueError('Uncertain delivery: explicit duplicate-risk acknowledgement required')
            db.execute('INSERT INTO delivery_audit(outbox_id,action,operator,reason,previous,created) VALUES(?,?,?,?,?,?)',
                       (oid, action, operator, reason, encode(snapshot), time.time()))
            db.execute('UPDATE outbox SET state=? WHERE id=?', ('pending' if action=='retry' else 'cancelled', oid))


def extract_statuses(payload):
    """Called only AFTER common envelope identity validation and platform signature."""
    result = []
    for entry in payload['entry']:
        for change in entry['changes']:
            if change['field'] != 'messages':
                continue
            for s in change['value'].get('statuses', []):
                if s.get('status') not in {'sent', 'delivered', 'read', 'failed'}:
                    continue
                mid, recipient = s['id'], s['recipient_id']
                stamp = int(s['timestamp'])
                callback = s.get('biz_opaque_callback_data')
                if (not isinstance(mid, str) or not 1 <= len(mid) <= 300 or
                        not isinstance(recipient, str) or not re.fullmatch(r'[1-9][0-9]{5,19}', recipient) or
                        stamp < 0 or stamp > time.time()+300 or
                        (callback is not None and (not isinstance(callback, str) or len(callback)>200))):
                    raise ValueError('Invalid status')
                result.append({'id': mid, 'recipient_id': recipient, 'timestamp': stamp,
                               'status': s['status'], 'callback': callback,
                               'error_codes': [e['code'] for e in s.get('errors', []) if type(e.get('code')) is int]})
    return result
