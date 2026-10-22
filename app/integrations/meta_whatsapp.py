"""Meta bridge preparation. No production startup is provided."""
import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from app.integrations.meta_delivery import DeliveryLifecycle, SCHEMA, SendRejected, extract_statuses


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class StateStore:
    def __init__(self, state_path):
        self.path = Path(state_path)

    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.executescript('''
        CREATE TABLE IF NOT EXISTS inbox (
          id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'pending', http_status INTEGER);
        CREATE TABLE IF NOT EXISTS outbox (
          id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
          provider_message_id TEXT, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS confirmations (
          sender TEXT NOT NULL, phrase TEXT NOT NULL, draft TEXT NOT NULL,
          PRIMARY KEY(sender,phrase));
        ''')
        db.executescript(SCHEMA)
        db.execute('BEGIN IMMEDIATE')
        try:
            # Upgrade pre-ledger rows without discarding accepted/uncertain history.
            db.execute('''INSERT OR IGNORE INTO delivery_attempts
                SELECT 'legacy-' || o.id, o.id, o.state, o.provider_message_id, 0, NULL
                FROM outbox o WHERE o.state != 'pending'
                AND NOT EXISTS (SELECT 1 FROM delivery_attempts a WHERE a.outbox_id=o.id)''')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()


class Bridge(StateStore, DeliveryLifecycle):
    """Durable inbox/outbox; dependencies are injected, never discovered from secrets."""

    def __init__(self, *, state_path, adapter, sender, channel_secret,
                 provider_id='simulation', recipient_id='simulation-line'):
        if len(channel_secret) < 32:
            raise ValueError('Dedicated channel secret must have at least 32 characters')
        self.path = Path(state_path)
        self.adapter = adapter  # HTTP client interface, tests use TestClient
        self.sender = sender  # send(payload, key) -> provider message ID
        self.secret = channel_secret
        self.provider = provider_id
        self.recipient = recipient_id
        with self.transaction():
            pass

    def accept(self, messages, statuses=()):
        # A whole webhook batch is persisted atomically before HTTP 200.
        with self.transaction() as db:
            for message in messages:
                encoded = canonical(message)
                fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
                old = db.execute('SELECT fingerprint FROM inbox WHERE id=?', (message['id'],)).fetchone()
                if old and old['fingerprint'] != fingerprint:
                    raise HTTPException(409, 'Message ID reused with different content')
                db.execute('INSERT OR IGNORE INTO inbox(id,fingerprint,payload) VALUES(?,?,?)',
                           (message['id'], fingerprint, encoded))

            self.accept_statuses(db, statuses)

    def command(self, message, db):
        text = message['text']
        if text.startswith('绑定 '):
            return 'bind', {'binding_code': text[3:]}
        if text == '我的身份':
            return 'query', {'query': {'resource': 'identity'}}
        if text == '本组织工单':
            return 'query', {'query': {'resource': 'work_orders', 'scope': 'all'}}
        if text.startswith('查询 '):
            return 'query', {'query': json.loads(text[3:])}
        if re.fullmatch(r'领取工单 [1-9][0-9]*', text):
            return 'claim', {'work_order_id': int(text.split(' ')[1])}
        if text.startswith('反馈 '):
            args = json.loads(text[3:])
            if not isinstance(args, dict) or set(args) != {'work_order_id', 'claim_version', 'report'}:
                raise ValueError('Invalid feedback command')
            return 'report_draft', args
        if text.startswith('确认提交 '):
            row = db.execute('SELECT draft FROM confirmations WHERE sender=? AND phrase=?',
                             (message['sender'], text)).fetchone()
            if row:
                return 'report_confirm', {'draft_id': row['draft']}
        raise ValueError('Unsupported command')

    def call_adapter(self, message, action, arguments, *, suffix=''):
        # Identity is exclusively derived from a verified Meta envelope.
        body = canonical({'provider_id': self.provider, 'recipient_id': self.recipient,
                          'sender_id': message['sender'], 'event_id': message['id'] + suffix,
                          'chat_type': 'individual', 'action': action,
                          'user_text': message['text'], 'arguments': arguments}).encode()
        stamp = str(int(time.time()))
        signature = hmac.new(self.secret.encode(), stamp.encode() + b'.' + body, hashlib.sha256).hexdigest()
        return self.adapter.post('/api/channels/whatsapp/events', content=body, headers={
            'Content-Type': 'application/json', 'X-Channel-Timestamp': stamp,
            'X-Channel-Signature': 'sha256=' + signature})

    def process_one(self):
        # SQLite serializes workers; rollback allows adapter idempotency to recover a crash.
        with self.transaction() as db:
            row = db.execute("SELECT * FROM inbox WHERE state='pending' ORDER BY rowid LIMIT 1").fetchone()
            if not row:
                return False
            message = json.loads(row['payload'])
            if time.time() - message['timestamp'] > 86400:
                db.execute("UPDATE inbox SET state='expired' WHERE id=?", (row['id'],))
                return True
            try:
                action, arguments = self.command(message, db)
            except (ValueError, TypeError):
                db.execute("UPDATE inbox SET state='rejected',http_status=422 WHERE id=?", (row['id'],))
                return True
            if action != 'bind':
                authorization = self.call_adapter(message, 'query', {'query': {'resource': 'identity'}}, suffix=':delivery')
                if authorization.status_code >= 500:
                    raise RuntimeError('Authorization check unavailable')
                if authorization.status_code != 200:
                    db.execute("UPDATE inbox SET state='rejected',http_status=? WHERE id=?",
                               (authorization.status_code, row['id']))
                    return True
            response = self.call_adapter(message, action, arguments)
            if response.status_code >= 500:
                raise RuntimeError('Adapter unavailable; leave message pending')
            db.execute("UPDATE inbox SET state='processed',http_status=? WHERE id=?",
                       (response.status_code, row['id']))
            # Authorization failures never generate a private or misleading reply.
            if response.status_code != 200:
                return True
            result = response.json()
            reply = result.get('reply_to', {})
            if (reply.get('recipient_id') != message['sender'] or
                    reply.get('provider_id') != self.provider or reply.get('chat_type') != 'individual'):
                raise RuntimeError('Adapter returned an inconsistent reply identity')
            if action == 'bind':
                authorization = self.call_adapter(message, 'query', {'query': {'resource': 'identity'}}, suffix=':delivery')
                if authorization.status_code != 200:
                    raise RuntimeError('New binding authorization check failed')
            data = result['data']
            if action == 'report_draft':
                db.execute('INSERT OR IGNORE INTO confirmations VALUES(?,?,?)',
                           (message['sender'], data['confirmation_text'], data['draft_id']))
            text = canonical(data)
            if len(text) > 4000:
                text = '查询结果过长，请缩小查询范围后重试。'
            payload = {'messaging_product': 'whatsapp', 'recipient_type': 'individual',
                       'to': message['sender'], 'type': 'text', 'text': {'body': text}}
            db.execute('INSERT OR IGNORE INTO outbox(id,payload,expires) VALUES(?,?,?)',
                       (row['id'], canonical(payload), message['timestamp'] + 86400))
            return True

    def send_one(self):
        with self.transaction() as db:
            row = db.execute("SELECT * FROM outbox WHERE state='pending' ORDER BY rowid LIMIT 1").fetchone()
            if not row:
                return False
            message = json.loads(db.execute('SELECT payload FROM inbox WHERE id=?', (row['id'],)).fetchone()[0])
            if time.time() >= row['expires']:
                db.execute("UPDATE outbox SET state='expired' WHERE id=?", (row['id'],))
                return True
            # Do not send queued private replies after a binding was revoked.
            check = self.call_adapter(message, 'query', {'query': {'resource': 'identity'}}, suffix=':delivery')
            if check.status_code >= 500:
                raise RuntimeError('Authorization check unavailable')
            if check.status_code != 200:
                db.execute("UPDATE outbox SET state='cancelled' WHERE id=?", (row['id'],))
                return True
            attempt_id = self.begin_attempt(db, row)
        # Commit sending BEFORE external I/O. An interrupted/ambiguous send is never auto-retried.
        # This deliberately does not promise exactly-once delivery over an external API.
        try:
            provider_id = self.sender.send(json.loads(row['payload']), key=attempt_id)
            if not isinstance(provider_id, str) or not provider_id:
                raise ValueError('Missing send receipt')
        except SendRejected as exc:
            self.finish_attempt(attempt_id, failure='failed', error=str(exc))
            return True
        except Exception:
            self.finish_attempt(attempt_id, failure='uncertain', error='transport_or_receipt_unknown')
            return True
        self.finish_attempt(attempt_id, provider_id=provider_id)
        return True


def extract_messages(payload, *, waba_id, phone_number_id):
    """Validate the entire batch before writing; ignore status-only/unsupported media events."""
    messages = []
    if not isinstance(payload, dict) or payload.get('object') != 'whatsapp_business_account':
        raise ValueError('Invalid object')
    entries = payload.get('entry')
    if not isinstance(entries, list):
        raise ValueError('Invalid entries')
    for entry in entries:
        if entry['id'] != waba_id:
            raise HTTPException(403, 'Wrong business account')
        for change in entry['changes']:
            if change['field'] != 'messages':
                continue
            value = change['value']
            if (value.get('messaging_product') != 'whatsapp' or
                    value['metadata']['phone_number_id'] != phone_number_id):
                raise HTTPException(403, 'Wrong channel')
            for message in value.get('messages', []):
                if message['type'] != 'text':
                    continue
                sender, mid, text = message['from'], message['id'], message['text']['body']
                stamp = int(message['timestamp'])
                if (not isinstance(sender, str) or not re.fullmatch(r'[1-9][0-9]{5,19}', sender) or
                        not isinstance(mid, str) or not 8 <= len(mid) <= 180 or
                        not isinstance(text, str) or not 1 <= len(text) <= 5000):
                    raise ValueError('Invalid message')
                if stamp > time.time() + 300:
                    raise ValueError('Future message')
                messages.append({'id': mid, 'sender': sender, 'text': text, 'timestamp': stamp})
    return messages


def create_app(*, enabled=False, bridge=None, app_secret='', verify_token='',
               waba_id='', phone_number_id=''):
    if enabled and (bridge is None or len(app_secret) < 32 or len(verify_token) < 32 or
                    not waba_id or not phone_number_id):
        raise ValueError('Explicit bridge and dedicated verification configuration required')
    app = FastAPI(title='Meta WhatsApp bridge preparation', docs_url=None, redoc_url=None)

    @app.middleware('http')
    async def gate(request, call_next):
        if request.url.path != '/health' and not enabled:
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail': 'Meta bridge disabled'}, status_code=503)
        return await call_next(request)

    @app.get('/health')
    def health():
        return {'enabled': enabled, 'live_transport_implemented': True,
                'live_transport_enabled': bool(bridge and getattr(bridge.sender, 'enabled', False))}

    @app.get('/webhooks/meta/whatsapp', response_class=PlainTextResponse)
    def verify(request: Request):
        q = request.query_params
        if q.get('hub.mode') != 'subscribe' or not hmac.compare_digest(q.get('hub.verify_token', '').encode(), verify_token.encode()):
            raise HTTPException(403, 'Invalid verification token')
        challenge = q.get('hub.challenge', '')
        if not challenge or len(challenge) > 256:
            raise HTTPException(422, 'Invalid challenge')
        return challenge

    @app.post('/webhooks/meta/whatsapp')
    async def receive(request: Request):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 262144:
                raise HTTPException(413, 'Webhook too large')
        expected = 'sha256=' + hmac.new(app_secret.encode(), bytes(raw), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(request.headers.get('x-hub-signature-256', '').encode(), expected.encode()):
            raise HTTPException(401, 'Invalid platform signature')
        try:
            payload = json.loads(raw)
            messages = extract_messages(payload, waba_id=waba_id, phone_number_id=phone_number_id)
            statuses = extract_statuses(payload)
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
            raise HTTPException(422, 'Invalid platform envelope')
        bridge.accept(messages, statuses)
        return {'accepted': True, 'text_messages': len(messages), 'status_events': len(statuses)}

    return app
