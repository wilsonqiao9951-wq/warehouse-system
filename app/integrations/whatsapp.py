"""Provider-neutral signed WhatsApp adapter. Disabled by default, never a Meta webhook parser."""
import hashlib,hmac,json,os,re,secrets,sqlite3,time
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4
from fastapi import FastAPI,Depends,HTTPException,Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel,ConfigDict,Field,ValidationError
from sqlalchemy import select
from app.core.database import get_db
from app.core.rbac import Actor,get_current_actor,require_roles,require_work_order_write_scope
from app.models import Organization,User,UserRole,UserDevice,WorkOrder,AuditLog
from app.api.muse import MuseQuery,RepairReportCreate,query,submit_report
from app.api.routes import claim_work_order

READ_RESOURCES={'identity','work_orders','repair_guidance','symptoms','followups','followup_stats','repair_recurrences','repair_statistics'}
def digest(value):return hashlib.sha256(value.encode()).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)

class Invitation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    user_id:int=Field(gt=0)
    sender_id:str=Field(pattern=r'^[1-9][0-9]{5,19}$')

class PilotInvitation(Invitation):
    reason:str=Field(min_length=10,max_length=500)
    expires_in:int=Field(default=604800,ge=60,le=2592000)

class Message(BaseModel):
    model_config=ConfigDict(extra='forbid')
    provider_id:str=Field(min_length=1,max_length=100)
    recipient_id:str=Field(min_length=1,max_length=100)
    sender_id:str=Field(pattern=r'^[1-9][0-9]{5,19}$')
    event_id:str=Field(min_length=8,max_length=200)
    chat_type:Literal['individual']
    action:Literal['bind','query','claim','report_draft','report_confirm']
    user_text:str=Field('',max_length=5000)
    arguments:dict=Field(default_factory=dict)

class Store:
    def __init__(self,path):self.path=Path(path)
    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR,0o600);os.close(fd);self.path.chmod(0o600)
        c=sqlite3.connect(self.path,timeout=30);c.row_factory=sqlite3.Row
        c.executescript('''
        CREATE TABLE IF NOT EXISTS pilot_members(sender TEXT PRIMARY KEY,user_id INTEGER NOT NULL,org_id INTEGER NOT NULL,expires REAL NOT NULL,active INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS pilot_audit(id INTEGER PRIMARY KEY,org_id INTEGER NOT NULL,operator_id INTEGER NOT NULL,user_id INTEGER NOT NULL,action TEXT NOT NULL,reason TEXT NOT NULL,created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS bindings(sender TEXT PRIMARY KEY,user_id INTEGER NOT NULL,org_id INTEGER NOT NULL,device_id INTEGER NOT NULL,token_hash TEXT NOT NULL,expires REAL NOT NULL,active INTEGER NOT NULL DEFAULT 0,revoked INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY,sender TEXT NOT NULL,fingerprint TEXT NOT NULL,result TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY,sender TEXT NOT NULL,user_id INTEGER NOT NULL,org_id INTEGER NOT NULL,work_order_id INTEGER NOT NULL,claim_version INTEGER NOT NULL,payload TEXT NOT NULL,confirmation TEXT NOT NULL,expires REAL NOT NULL);
        ''')
        c.execute('BEGIN IMMEDIATE')
        try:yield c;c.commit()
        except Exception:c.rollback();raise
        finally:c.close()

def create_app(*,enabled=False,signing_secret='',provider_id='simulation',recipient_id='simulation-line',state_path='artifacts/whatsapp/channel.sqlite3',pilot_required=False):
    if enabled and len(signing_secret)<32:raise ValueError('A dedicated random signing secret of at least 32 characters is required')
    app=FastAPI(title='WhatsApp channel adapter (provider-neutral)',version='0.1',docs_url=None,redoc_url=None)
    store=Store(state_path)
    @app.middleware('http')
    async def gate(request,call_next):
        if request.url.path!='/health' and not enabled:return __import__('fastapi').responses.JSONResponse({'detail':'Channel disabled'},status_code=503)
        return await call_next(request)
    @app.get('/health')
    def health():return {'enabled':enabled,'provider_id':provider_id,'external_provider_connected':False}

    def audit(db,actor,action,entity_id):
        db.add(AuditLog(organization_id=actor.organization_id,user_id=actor.user_id,action=action,entity_type='whatsapp_binding',entity_id=entity_id,metadata_json='{}'));db.commit()

    def pilot_check(c,sender,user_id,org_id):
        if not pilot_required:return
        row=c.execute('SELECT * FROM pilot_members WHERE sender=?',(sender,)).fetchone()
        if not row or not row['active'] or row['expires']<=time.time() or row['user_id']!=user_id or row['org_id']!=org_id:
            raise HTTPException(403,'Pilot authorization required')

    @app.put('/api/channels/whatsapp/pilots')
    def grant_pilot(payload:PilotInvitation,db=Depends(get_db),actor=Depends(get_current_actor)):
        require_roles(actor,UserRole.ADMIN)
        if actor.auth_method!='bearer':raise HTTPException(401,'Personal administrator login required')
        user=db.scalar(select(User).where(User.id==payload.user_id,User.organization_id==actor.organization_id,User.is_active.is_(True)))
        if not user or user.role!=UserRole.ENGINEER:raise HTTPException(404,'Active organization engineer not found')
        with store.transaction() as c:
            old=c.execute('SELECT * FROM pilot_members WHERE sender=?',(payload.sender_id,)).fetchone()
            binding=c.execute('SELECT * FROM bindings WHERE sender=?',(payload.sender_id,)).fetchone()
            if any(r and (r['org_id']!=actor.organization_id or r['user_id']!=user.id) for r in (old,binding)):
                raise HTTPException(409,'Sender already reserved')
            if old is None or not old['active'] or old['expires']<=time.time():
                c.execute('UPDATE bindings SET active=0,revoked=1 WHERE sender=?',(payload.sender_id,))
            expires=time.time()+payload.expires_in
            c.execute('INSERT OR REPLACE INTO pilot_members VALUES(?,?,?,?,1)',(payload.sender_id,user.id,actor.organization_id,expires))
            c.execute('INSERT INTO pilot_audit(org_id,operator_id,user_id,action,reason,created) VALUES(?,?,?,?,?,?)',
                      (actor.organization_id,actor.user_id,user.id,'grant',payload.reason,time.time()))
        return {'approved':True,'expires_at':expires,'binding_required':True}

    @app.delete('/api/channels/whatsapp/pilots/{sender_id}')
    def revoke_pilot(sender_id:str,reason:str,db=Depends(get_db),actor=Depends(get_current_actor)):
        require_roles(actor,UserRole.ADMIN)
        if actor.auth_method!='bearer':raise HTTPException(401,'Personal administrator login required')
        if not 10<=len(reason.strip())<=500:raise HTTPException(422,'A reason of 10–500 characters is required')
        with store.transaction() as c:
            row=c.execute('SELECT * FROM pilot_members WHERE sender=? AND org_id=?',(sender_id,actor.organization_id)).fetchone()
            if not row:raise HTTPException(404,'Pilot authorization not found')
            c.execute('UPDATE pilot_members SET active=0 WHERE sender=?',(sender_id,))
            c.execute('UPDATE bindings SET active=0,revoked=1 WHERE sender=? AND org_id=?',(sender_id,actor.organization_id))
            c.execute('INSERT INTO pilot_audit(org_id,operator_id,user_id,action,reason,created) VALUES(?,?,?,?,?,?)',
                      (actor.organization_id,actor.user_id,row['user_id'],'revoke',reason,time.time()))
        return {'revoked':True,'new_binding_required':True}

    @app.post('/api/channels/whatsapp/bindings')
    def invite(payload:Invitation,db=Depends(get_db),actor=Depends(get_current_actor)):
        require_roles(actor,UserRole.ADMIN)
        if actor.auth_method!='bearer':raise HTTPException(401,'Personal administrator login required')
        user=db.scalar(select(User).where(User.id==payload.user_id,User.organization_id==actor.organization_id,User.is_active.is_(True)))
        if not user or user.role!=UserRole.ENGINEER:raise HTTPException(404,'Active organization engineer not found')
        with store.transaction() as c:
            pilot_check(c,payload.sender_id,user.id,actor.organization_id)
            existing=c.execute('SELECT * FROM bindings WHERE sender=?',(payload.sender_id,)).fetchone()
            if existing and (existing['org_id']!=actor.organization_id or (not existing['revoked'] and (existing['active'] or existing['expires']>=time.time()))):raise HTTPException(409,'Sender already reserved')
            if existing:c.execute('DELETE FROM bindings WHERE sender=?',(payload.sender_id,))
            token=secrets.token_urlsafe(32);device=UserDevice(organization_id=actor.organization_id,user_id=user.id,device_id='wa-'+uuid4().hex,device_token_hash=digest(secrets.token_urlsafe(48)),device_name='WhatsApp verified channel')
            db.add(device);db.commit();db.refresh(device)
            c.execute('INSERT INTO bindings(sender,user_id,org_id,device_id,token_hash,expires) VALUES(?,?,?,?,?,?)',(payload.sender_id,user.id,actor.organization_id,device.id,digest(token),time.time()+600))
            audit(db,actor,'whatsapp_binding_invited',user.id)
        return {'binding_code':token,'expires_in':600,'sender_id':payload.sender_id,'instruction':'Deliver this short-lived code to the intended technician. Only a signed event from the pre-registered sender can redeem it.'}

    @app.delete('/api/channels/whatsapp/bindings/{sender_id}')
    def revoke(sender_id:str,db=Depends(get_db),actor=Depends(get_current_actor)):
        require_roles(actor,UserRole.ADMIN)
        if actor.auth_method!='bearer':raise HTTPException(401,'Personal administrator login required')
        with store.transaction() as c:
            b=c.execute('SELECT * FROM bindings WHERE sender=? AND org_id=?',(sender_id,actor.organization_id)).fetchone()
            if not b:raise HTTPException(404,'Binding not found')
            c.execute('UPDATE bindings SET active=0,revoked=1 WHERE sender=?',(sender_id,))
            device=db.get(UserDevice,b['device_id'])
            if device:device.is_active=False
            audit(db,actor,'whatsapp_binding_revoked',b['user_id'])
        return {'revoked':True}

    def bound_actor(c,db,sender,allow_pending=False):
        b=c.execute('SELECT * FROM bindings WHERE sender=?',(sender,)).fetchone()
        if not b or b['revoked'] or (not allow_pending and not b['active']):raise HTTPException(403,'Sender not bound')
        pilot_check(c,sender,b['user_id'],b['org_id'])
        user=db.get(User,b['user_id']);org=db.get(Organization,b['org_id']);device=db.get(UserDevice,b['device_id'])
        if not user or not user.is_active or user.role!=UserRole.ENGINEER or user.organization_id!=b['org_id'] or not org or not org.is_active or not device or not device.is_active or device.revoked_at is not None or device.user_id!=user.id or device.organization_id!=org.id:raise HTTPException(403,'Binding no longer authorized')
        db.info['organization_id']=org.id
        return b,Actor(user.id,user.role,org.id,auth_method='whatsapp_signed',device_id=device.device_id,device_record_id=device.id,device_verified=True)

    @app.post('/api/channels/whatsapp/events',openapi_extra={'requestBody':{'required':True,'content':{'application/json':{'schema':Message.model_json_schema()}}}})
    async def event(request:Request,db=Depends(get_db)):
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>32768:raise HTTPException(413,'Event too large')
        stamp=request.headers.get('x-channel-timestamp','');sig=request.headers.get('x-channel-signature','')
        try:fresh=abs(time.time()-int(stamp))<=300
        except ValueError:fresh=False
        expected=hmac.new(signing_secret.encode(),stamp.encode()+b'.'+bytes(body),hashlib.sha256).hexdigest()
        if not fresh or not hmac.compare_digest(sig,'sha256='+expected):raise HTTPException(401,'Invalid or expired signature')
        try:m=Message.model_validate_json(body)
        except ValidationError:raise HTTPException(422,'Invalid message envelope')
        if m.provider_id!=provider_id or m.recipient_id!=recipient_id:raise HTTPException(403,'Channel identity mismatch')
        fields={'bind':{'binding_code'},'query':{'query'},'claim':{'work_order_id'},'report_draft':{'work_order_id','claim_version','report'},'report_confirm':{'draft_id'}}
        if set(m.arguments)!=fields[m.action]:raise HTTPException(422,'Unexpected or missing action arguments')
        for key in ('binding_code','draft_id'):
            if key in m.arguments and (not isinstance(m.arguments[key],str) or not 1<=len(m.arguments[key])<=128):raise HTTPException(422,'Invalid code or draft identifier')
        with store.transaction() as c:
            b,actor=bound_actor(c,db,m.sender_id,allow_pending=m.action=='bind')
            fingerprint=digest(canonical(m.model_dump())+':'+str(b['device_id']))
            old=c.execute('SELECT * FROM events WHERE event_id=?',(m.event_id,)).fetchone()
            if old and (old['sender']!=m.sender_id or old['fingerprint']!=fingerprint):raise HTTPException(409,'Event ID reused with different content')
            a=m.arguments
            if m.action=='bind':
                if old:return json.loads(old['result'])|{'replayed':True}
                if b['active'] or b['expires']<time.time() or not isinstance(a['binding_code'],str) or not hmac.compare_digest(b['token_hash'],digest(a['binding_code'])):raise HTTPException(403,'Binding code invalid or consumed')
                c.execute('UPDATE bindings SET active=1,token_hash=? WHERE sender=?',('',m.sender_id));audit(db,actor,'whatsapp_binding_activated',actor.user_id)
                result={'bound':True,'user_id':actor.user_id,'organization_id':actor.organization_id}
            elif m.action=='query':
                try:
                    if not isinstance(a['query'],dict) or set(a['query'])-set(MuseQuery.model_fields):raise ValueError()
                    q=MuseQuery.model_validate(a['query'])
                    if q.resource not in READ_RESOURCES:raise ValueError()
                except (ValueError,ValidationError):raise HTTPException(422,'Unsupported query')
                # Never serve cached private results after permission/state changes.
                result=query(q,db,actor)
            elif m.action=='claim':
                if type(a['work_order_id']) is not int or a['work_order_id']<1:raise HTTPException(422,'Invalid work order')
                if m.user_text!=f"领取工单 {a['work_order_id']}":raise HTTPException(422,'Explicit technician claim command required')
                result=claim_work_order(a['work_order_id'],db,actor)
            elif m.action=='report_draft':
                if type(a['claim_version']) is not int or type(a['work_order_id']) is not int or a['work_order_id']<1:raise HTTPException(422,'Invalid work order/version')
                actor.claim_version=a['claim_version'];require_work_order_write_scope(db,actor,a['work_order_id'])
                try:
                    if not isinstance(a['report'],dict) or set(a['report'])-set(RepairReportCreate.model_fields):raise ValueError()
                    report=RepairReportCreate.model_validate(a['report'])
                except (ValidationError,ValueError):raise HTTPException(422,'Invalid report')
                if old:return json.loads(old['result'])|{'replayed':True}
                did=uuid4().hex;confirmation='确认提交 '+secrets.token_hex(8)
                c.execute('INSERT INTO drafts VALUES(?,?,?,?,?,?,?,?,?)',(did,m.sender_id,actor.user_id,actor.organization_id,a['work_order_id'],a['claim_version'],canonical(report.model_dump()),confirmation,time.time()+900))
                result={'draft_id':did,'work_order_id':a['work_order_id'],'report':report.model_dump(),'confirmation_required':True,'confirmation_text':confirmation,'expires_in':900,'submitted':False}
            else:
                d=c.execute('SELECT * FROM drafts WHERE id=? AND sender=? AND user_id=? AND org_id=?',(a['draft_id'],m.sender_id,actor.user_id,actor.organization_id)).fetchone()
                if not d:raise HTTPException(404,'Draft not found')
                if m.user_text!=d['confirmation']:raise HTTPException(422,'Exact technician confirmation required')
                if not old and d['expires']<time.time():raise HTTPException(410,'Draft expired')
                actor.claim_version=d['claim_version']
                # Stable per-draft key survives duplicate events and adapter crash after backend commit.
                result=submit_report(d['work_order_id'],RepairReportCreate.model_validate_json(d['payload']),db,actor,idempotency_key='wa-draft-'+d['id'])
            response={'reply_to':{'provider_id':provider_id,'recipient_id':m.sender_id,'chat_type':'individual'},'event_id':m.event_id,'replayed':bool(old),'data':jsonable_encoder(result),'delivery_status':'not_sent'}
            # Cache only mutations. Queries are always re-evaluated and do not store private results.
            saved=response if m.action!='query' else {'event_id':m.event_id}
            c.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?)',(m.event_id,m.sender_id,fingerprint,canonical(saved)))
            return response
    return app
