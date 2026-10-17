"""Stateless, self-describing entry point for independently operated Muse clients."""
from typing import Annotated,Literal
from fastapi import APIRouter,Depends,Header,HTTPException,Query
from pydantic import BaseModel,Field,model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.rbac import Actor,get_current_actor
from app.models import Part
from app.services.catalog import search
from app.services import model_chain,freestyle_chain
from app.services import symptoms

muse_router=APIRouter(prefix='/muse',tags=['Muse integration'])
RESOURCES=['catalog','freestyle_models','freestyle_model','freestyle_parts','freestyle_usage','viper3_model','viper3_parts','viper3_usage','identity','work_orders','repair_guidance','symptoms','followups','followup_stats','repair_recurrences','repair_statistics','quest_models','quest_model','quest_parts','abs_models','abs_model','abs_parts','ed_models','ed_model','ed_parts','md_models','md_model','md_parts','df_models','df_model','df_parts','db_models','db_model','db_parts','icecombo_models','icecombo_model','icecombo_parts','crewserve_models','crewserve_model','crewserve_parts','selfserve_models','selfserve_model','selfserve_parts']

@muse_router.get('')
def manifest():
    return {'name':'myCoke shared backend','contract_version':'1.4','repair_statistics_path':'/api/muse/repair-statistics','followup_stats_path':'/api/muse/followups/stats','repair_recurrences_path':'/api/muse/followups/recurrences','followups_path':'/api/muse/followups','followup_schedule_path':'/api/muse/reports/{report_id}/followup-schedule','symptoms_path':'/api/muse/symptoms','symptom_resolve_path':'/api/muse/symptoms/resolve','api_base_path':'/api','query_path':'/api/muse/query','openapi_path':'/openapi.json','interactive_docs_path':'/docs','authentication':{'type':'Bearer','login_path':'/api/auth/login','identity_path':'/api/auth/me','per_technician_identity_required':True,'shared_admin_credentials_allowed':False,'device_headers':['X-Device-Id','X-Device-Token','X-Device-Name'],'token_expiry':'Use expires_in from login; sign in again when expired'},'query_resources':RESOURCES,'frontend':{'existing_ui_requires_its_own_host':True,'agent_can_render_api_results':True,'new_model_features_in_existing_ui':False},'rules':['Use current signed-in technician identity; organization is resolved server-side.','Official associations, field observations, explicit field verification and reported actual use are distinct evidence.','Shared catalog references never establish cross-model fitment.','Query is read-only. Writes use documented REST endpoints and existing role/device/claim restrictions.','Do not store passwords or tokens in shared project descriptions, GitHub issues or logs.'],'write_contracts':{'freestyle_verification':'POST /api/catalog/freestyle/models/{model_id}/field-verifications','viper3_verification':'POST /api/catalog/models/viper-3/field-verifications','catalog_import':'POST /api/catalog/parts/{catalog_id}/import','other_operations':'Use /openapi.json; existing authorization and work-order ownership rules apply.'}}

class MuseQuery(BaseModel):
    resource: Literal['catalog','freestyle_models','freestyle_model','freestyle_parts','freestyle_usage','viper3_model','viper3_parts','viper3_usage','identity','work_orders','repair_guidance','symptoms','followups','followup_stats','repair_recurrences','repair_statistics','quest_models','quest_model','quest_parts','abs_models','abs_model','abs_parts','ed_models','ed_model','ed_parts','md_models','md_model','md_parts','df_models','df_model','df_parts','db_models','db_model','db_parts','icecombo_models','icecombo_model','icecombo_parts','crewserve_models','crewserve_model','crewserve_parts','selfserve_models','selfserve_model','selfserve_parts']
    work_order_id: int | None=Field(None,gt=0)
    followup_status: Literal['open','due','upcoming','awaiting_review','completed','overdue','late','recurred','all']='open'
    status: str | None=Field(None,max_length=50)
    scope: Literal['mine','available','all']='mine'
    symptom_code: str=Field('',max_length=80)
    symptom_codes: list[Annotated[str,Field(min_length=1,max_length=80)]]=Field(default_factory=list,max_length=20)
    symptom_text: str=Field('',max_length=5000)
    kind: Literal['parts','manuals','equipment']='parts'
    machine_model: str=Field('',max_length=255)
    model_id: str | None=Field(None,max_length=40)
    part_id: int | None=Field(None,gt=0)
    section_id: str | None=Field(None,max_length=255)
    q: str=Field('',max_length=200)
    skip: int=Field(0,ge=0)
    limit: int=Field(25,ge=1,le=100)
    @model_validator(mode='after')
    def required_arguments(self):
        if self.resource=='repair_guidance' and self.work_order_id is None:raise ValueError('work_order_id is required')
        if self.resource in {'freestyle_model','freestyle_parts','freestyle_usage','quest_model','quest_parts','abs_model','abs_parts','ed_model','ed_parts','md_model','md_parts','df_model','df_parts','db_model','db_parts','icecombo_model','icecombo_parts','crewserve_model','crewserve_parts','selfserve_model','selfserve_parts'} and not self.model_id:raise ValueError('model_id is required')
        if self.resource in {'freestyle_usage','viper3_usage'} and self.part_id is None:raise ValueError('part_id is required')
        return self

@muse_router.post('/query')
def query(payload: MuseQuery,db: Session=Depends(get_db),actor: Actor=Depends(get_current_actor)):
    r=payload.resource;org=actor.organization_id
    if r.startswith('quest'):
        from app.api.catalog import quest_models,quest_model,quest_parts
        if r=='quest_models':return quest_models(actor)
        if r=='quest_model':return quest_model(payload.model_id,actor)
        return quest_parts(payload.model_id,payload.section_id,payload.q,payload.skip,payload.limit,db,actor)
    if r.startswith('abs'):
        from app.api.catalog import abs_models,abs_model,abs_parts
        if r=='abs_models':return abs_models(actor)
        if r=='abs_model':return abs_model(payload.model_id,actor)
        return abs_parts(payload.model_id,payload.section_id,payload.q,payload.skip,payload.limit,db,actor)
    if r.startswith('ed'):
        from app.api.catalog import ed_models,ed_model,ed_parts
        if r=='ed_models':return ed_models(actor)
        if r=='ed_model':return ed_model(payload.model_id,actor)
        return ed_parts(payload.model_id,payload.section_id,payload.q,payload.skip,payload.limit,db,actor)
    if r.startswith('md'):
        from app.api.catalog import md_models,md_model,md_parts
        if r=='md_models':return md_models(actor)
        if r=='md_model':return md_model(payload.model_id,actor)
        return md_parts(payload.model_id,payload.section_id,payload.q,payload.skip,payload.limit,db,actor)
    if r.startswith('df'):
        from app.api.catalog import df_models,df_model,df_parts
        if r=='df_models':return df_models(actor)
        if r=='df_model':return df_model(payload.model_id,actor)
        return df_parts(payload.model_id,payload.section_id,payload.q,payload.skip,payload.limit,db,actor)
    if r.startswith('db'):
        from app.api.catalog import db_models,db_model,db_parts
        if r=='db_models':return db_models(actor)
        if r=='db_model':return db_model(payload.model_id,actor)
        return db_parts(payload.model_id,payload.section_id,payload.q,payload.skip,payload.limit,db,actor)
    if r.startswith('icecombo'):
        from app.api.catalog import icecombo_models,icecombo_model,icecombo_parts
        if r=='icecombo_models':return icecombo_models(actor)
        if r=='icecombo_model':return icecombo_model(payload.model_id,actor)
        return icecombo_parts(payload.model_id,payload.section_id,payload.q,payload.skip,payload.limit,db,actor)
    if r.startswith('crewserve'):
        from app.api.catalog import crewserve_models,crewserve_model,crewserve_parts
        if r=='crewserve_models':return crewserve_models(actor)
        if r=='crewserve_model':return crewserve_model(payload.model_id,actor)
        return crewserve_parts(payload.model_id,payload.section_id,payload.q,payload.skip,payload.limit,db,actor)
    if r.startswith('selfserve'):
        from app.api.catalog import selfserve_models,selfserve_model,selfserve_parts
        if r=='selfserve_models':return selfserve_models(actor)
        if r=='selfserve_model':return selfserve_model(payload.model_id,actor)
        return selfserve_parts(payload.model_id,payload.section_id,payload.q,payload.skip,payload.limit,db,actor)
    if r=='repair_statistics':return repair_statistics(payload.machine_model,payload.symptom_code,payload.skip,payload.limit,db,actor)
    if r=='followup_stats':return followup_stats(payload.scope,db,actor)
    if r=='repair_recurrences':return repair_recurrences(payload.scope,payload.skip,payload.limit,db,actor)
    if r=='followups':return followup_list(payload.followup_status,payload.scope,payload.skip,payload.limit,db,actor)
    if r=='identity':return {'user_id':actor.user_id,'organization_id':org,'role':actor.role,'authentication':actor.auth_method}
    if r=='work_orders':
        from app.api.routes import list_work_orders
        return list_work_orders(skip=payload.skip,limit=payload.limit,technician_id=None,status=payload.status,city=None,job_type=None,q=payload.q or None,date_from=None,date_to=None,scope=payload.scope,db=db,actor=actor)
    if r=='symptoms':return symptom_resolution_for_request(db,actor,payload.work_order_id,[payload.symptom_code,*payload.symptom_codes],payload.symptom_text)
    if r=='repair_guidance':return repair_guidance(payload.work_order_id,payload.symptom_code,db,actor,symptom_text=payload.symptom_text,symptom_codes=payload.symptom_codes)
    if r=='catalog':return search(payload.kind,payload.q,payload.skip,payload.limit)
    if r.startswith('freestyle'):
        g=freestyle_chain.graph()
        if r=='freestyle_models':return {'items':[{'model_id':m['model_id'],'official_model':m['official_model'],'official_part_count':m['official_part_count'],'section_count':len(m['sections'])} for m in g['models'].values()],'policy':g['policy']}
        model=g['models'].get(payload.model_id)
        if not model:raise HTTPException(404,'Freestyle model not found')
        if r=='freestyle_model':return model
        if payload.section_id and not any(s['id']==payload.section_id for s in model['sections']):raise HTTPException(404,'Section does not belong to current model')
        if r=='freestyle_parts':return freestyle_chain.parts(db,org,payload.model_id,payload.section_id,payload.q,payload.skip,payload.limit)
        records=freestyle_chain.model_usage(db,org,payload.model_id)
    else:
        g=model_chain.graph()
        if r=='viper3_model':return g
        if payload.section_id and not any(s['id']==payload.section_id for s in g['sections']):raise HTTPException(404,'Viper 3 section not found')
        if r=='viper3_parts':return model_chain.chain(db,org,payload.section_id,payload.q,payload.skip,payload.limit)
        records=model_chain.work_order_usage(db,org)
    part=db.scalar(select(Part).where(Part.id==payload.part_id,Part.organization_id==org))
    if not part:raise HTTPException(404,'Organization part not found')
    items=records.get(part.id,[]);summary=model_chain.usage_summary(items);summary.pop('records');summary.pop('records_limit')
    return {'part_id':part.id,'organization_id':org,'total':len(items),'skip':payload.skip,'limit':payload.limit,'summary':summary,'items':items[payload.skip:payload.skip+payload.limit],'cross_model_compatibility_confirmed':False}


from typing import Annotated
from app.models import WorkOrder,RepairCaseReport,AuditLog,UserRole
from app.core.rbac import require_roles,require_work_order_scope,require_work_order_write_scope
from datetime import datetime,timezone
import json
from hashlib import sha256

class ActualRepairPart(BaseModel):
    part_id: int=Field(gt=0)
    quantity: float=Field(gt=0,allow_inf_nan=False)

class RepairFollowup(BaseModel):
    previous_report_id: int | None=Field(None,gt=0)
    recurrence: Literal['unknown','not_observed','recurred']='unknown'
    observation_days: int | None=Field(None,ge=0,le=36500)
    actual_parts: list[ActualRepairPart]=Field(default_factory=list,max_length=50)
    actual_parts_complete: bool=False

    @model_validator(mode='after')
    def validate_observation(self):
        if self.recurrence=='not_observed' and not self.observation_days:
            raise ValueError('No recurrence requires a positive observation period')
        ids=[p.part_id for p in self.actual_parts]
        if len(ids)!=len(set(ids)):raise ValueError('Duplicate actual part')
        return self

class RepairReportCreate(BaseModel):
    symptom_codes: list[Annotated[str,Field(min_length=1,max_length=80)]]=Field(default_factory=list,max_length=20)
    symptom_text: str=Field('',max_length=5000)
    steps: list[Annotated[str,Field(min_length=1,max_length=1000)]]=Field(min_length=1,max_length=50)
    outcome: Literal['resolved','partial','unresolved']
    repair_followup: RepairFollowup | None=None
    part_ids: list[Annotated[int,Field(gt=0)]]=Field(default_factory=list,max_length=50)
    result_notes: str=Field(min_length=1,max_length=5000)

class RepairReportReview(BaseModel):
    decision: Literal['approved','rejected']


class SymptomResolveRequest(BaseModel):
    symptom_codes: list[Annotated[str,Field(min_length=1,max_length=80)]]=Field(default_factory=list,max_length=20)
    symptom_text: str=Field('',max_length=5000)
    work_order_id: int | None=Field(None,gt=0)


def symptom_resolution_for_request(db,actor,work_order_id,codes,text):
    explicit=bool(any(c.strip() for c in codes) or text.strip())
    source='explicit_request'
    if work_order_id is not None:
        require_work_order_scope(db,actor,work_order_id)
        order=db.scalar(select(WorkOrder).where(WorkOrder.id==work_order_id,WorkOrder.organization_id==actor.organization_id))
        if not explicit:
            text=order.problem_description or ''
            source='work_order_problem_description'
    return symptoms.resolve(codes,text,source=source,work_order_id=work_order_id)


@muse_router.get('/symptoms')
def symptom_taxonomy():
    return symptoms.taxonomy()


@muse_router.post('/symptoms/resolve')
def resolve_symptom_request(payload: SymptomResolveRequest,db: Session=Depends(get_db),actor: Actor=Depends(get_current_actor)):
    return symptom_resolution_for_request(db,actor,payload.work_order_id,payload.symptom_codes,payload.symptom_text)


@muse_router.get('/work-orders/{work_order_id}/symptoms')
def work_order_symptoms(work_order_id: int,db: Session=Depends(get_db),actor: Actor=Depends(get_current_actor)):
    return symptom_resolution_for_request(db,actor,work_order_id,[],'')

@muse_router.post('/work-orders/{work_order_id}/reports')
def submit_report(work_order_id: int,payload: RepairReportCreate,db: Session=Depends(get_db),actor: Actor=Depends(get_current_actor),idempotency_key: str | None=Header(None,alias='Idempotency-Key',min_length=16,max_length=128,pattern=r'^[A-Za-z0-9_-]+$')):
    from app.services.repair_guidance import machine_model
    order=require_work_order_write_scope(db,actor,work_order_id)
    closure=payload.repair_followup.model_dump() if payload.repair_followup else None
    if closure:
        closure['actual_parts']=sorted(closure['actual_parts'],key=lambda p:p['part_id'])
        previous_id=closure['previous_report_id']
        if previous_id:
            previous=db.scalar(select(RepairCaseReport).where(RepairCaseReport.id==previous_id,RepairCaseReport.organization_id==actor.organization_id,RepairCaseReport.work_order_id==order.id))
            if not previous:raise HTTPException(404,'Previous report not found for this work order')
            if previous.machine_model!=machine_model(db,actor.organization_id,order):raise HTTPException(422,'Previous report model no longer matches work order')
            if set(symptoms.report_codes(previous))!=set(symptoms.resolve(payload.symptom_codes,payload.symptom_text)['canonical_codes']):
                raise HTTPException(422,'Follow-up must retain the previous report symptom codes')
    ids=set(payload.part_ids)
    actual_ids={p['part_id'] for p in closure['actual_parts']} if closure else set()
    if actual_ids:
        actual_found=set(db.scalars(select(Part.id).where(Part.organization_id==actor.organization_id,Part.id.in_(actual_ids))))
        if actual_ids!=actual_found:raise HTTPException(404,'Organization actual part not found')
    found=set(db.scalars(select(Part.id).where(Part.organization_id==actor.organization_id,Part.id.in_(ids)))) if ids else set()
    if ids!=found:raise HTTPException(404,'Organization part not found')
    classification=symptoms.resolve(payload.symptom_codes,payload.symptom_text,source='technician_report',work_order_id=order.id)
    codes=sorted(set(classification['canonical_codes'])|{s.strip().casefold() for s in classification['unknown_codes']})
    steps=[s.strip() for s in payload.steps if s.strip()]
    if not (any(s.strip() for s in payload.symptom_codes) or payload.symptom_text.strip()) or not steps or not payload.result_notes.strip():raise HTTPException(422,'Nonblank symptoms, steps and results are required')
    normalized={'work_order_id':order.id,'symptom_codes':codes,'steps':steps,'outcome':payload.outcome,'part_ids':sorted(ids),'result_notes':payload.result_notes.strip()}
    if closure is not None:normalized['repair_followup']=closure
    if payload.symptom_text:normalized['symptom_text']=payload.symptom_text
    fingerprint=sha256(json.dumps(normalized,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

    normalized.pop('symptom_text',None)

    def existing_report():
        if not idempotency_key:return None
        existing=db.scalar(select(RepairCaseReport).where(RepairCaseReport.organization_id==actor.organization_id,RepairCaseReport.idempotency_key==idempotency_key))
        if existing and (existing.submitted_by!=actor.user_id or existing.request_fingerprint!=fingerprint):
            raise HTTPException(409,'Idempotency key already used for another submission')
        return existing

    def response(report,replayed):
        current_model=machine_model(db,actor.organization_id,order)
        return {'report_id':report.id,'machine_model':report.machine_model,'review_status':report.review_status,'guidance_eligible':report.review_status=='approved' and report.outcome=='resolved' and (report.repair_followup or {}).get('recurrence')!='recurred' and bool(current_model and current_model==report.machine_model) and bool(symptoms.report_codes(report)),'replayed':replayed,'symptom_resolution':symptoms.report_resolution(report)}

    existing=existing_report()
    if existing:return response(existing,True)
    report=RepairCaseReport(organization_id=actor.organization_id,submitted_by=actor.user_id,machine_model=machine_model(db,actor.organization_id,order),review_status='pending',symptom_context=classification,idempotency_key=idempotency_key,request_fingerprint=fingerprint if idempotency_key else None,**normalized)
    try:
        db.add(report);db.flush();db.add(AuditLog(organization_id=actor.organization_id,user_id=actor.user_id,action='submit_repair_case',entity_type='repair_case_report',entity_id=report.id,metadata_json=json.dumps({'work_order_id':order.id})));db.commit()
    except IntegrityError:
        db.rollback()
        existing=existing_report()
        if existing:return response(existing,True)
        raise
    return response(report,False)

@muse_router.post('/reports/{report_id}/review')
def review_report(report_id: int,payload: RepairReportReview,db: Session=Depends(get_db),actor: Actor=Depends(get_current_actor)):
    from app.services.repair_guidance import machine_model
    require_roles(actor,UserRole.ADMIN,UserRole.MANAGER)
    report=db.scalar(select(RepairCaseReport).where(RepairCaseReport.id==report_id,RepairCaseReport.organization_id==actor.organization_id))
    if not report:raise HTTPException(404,'Report not found')
    report.review_status=payload.decision;report.reviewed_by=actor.user_id;report.reviewed_at=datetime.now(timezone.utc)
    db.add(AuditLog(organization_id=actor.organization_id,user_id=actor.user_id,action='review_repair_case',entity_type='repair_case_report',entity_id=report.id,metadata_json=json.dumps({'decision':payload.decision})));db.commit()
    order=db.scalar(select(WorkOrder).where(WorkOrder.id==report.work_order_id,WorkOrder.organization_id==actor.organization_id))
    current_model=machine_model(db,actor.organization_id,order) if order else None
    return {'report_id':report.id,'review_status':report.review_status,'guidance_eligible':report.review_status=='approved' and report.outcome=='resolved' and (report.repair_followup or {}).get('recurrence')!='recurred' and bool(current_model and current_model==report.machine_model) and bool(symptoms.report_codes(report))}

@muse_router.get('/work-orders/{work_order_id}/guidance')
def repair_guidance(work_order_id: int,symptom_code: str=Query('',max_length=80),db: Session=Depends(get_db),actor: Actor=Depends(get_current_actor),symptom_text: str=Query('',max_length=5000),symptom_codes: list[Annotated[str,Field(min_length=1,max_length=80)]] | None=Query(None,max_length=20)):
    from app.services.repair_guidance import guidance
    from app.api.routes import get_work_order_service_context
    from app.services.repair_guidance import historical_parts,machine_model
    require_work_order_scope(db,actor,work_order_id)
    order=db.scalar(select(WorkOrder).where(WorkOrder.id==work_order_id,WorkOrder.organization_id==actor.organization_id))
    context=get_work_order_service_context(work_order_id,history_limit=5,db=db,actor=actor)
    context['history']=[]
    history=historical_parts(db,actor.organization_id,order)
    classification=symptom_resolution_for_request(db,actor,work_order_id,[symptom_code,*(symptom_codes or [])],symptom_text)
    return {'symptom_resolution':classification,'work_order_context':context,'reviewed_guidance':guidance(db,actor.organization_id,order,classification['canonical_codes'],classification=classification),'historical_usage_candidates':history,'historical_usage_policy':'Prior usage is not proof of successful repair or fitment.'}


@muse_router.get('/reports')
def report_review_queue(review_status: Literal['pending','approved','rejected']='pending',skip: int=0,limit: int=25,db: Session=Depends(get_db),actor: Actor=Depends(get_current_actor)):
    require_roles(actor,UserRole.ADMIN,UserRole.MANAGER)
    if skip<0 or not 1<=limit<=100:raise HTTPException(422,'Invalid pagination')
    rows=db.scalars(select(RepairCaseReport).where(RepairCaseReport.organization_id==actor.organization_id,RepairCaseReport.review_status==review_status).order_by(RepairCaseReport.id.desc()).offset(skip).limit(limit)).all()
    return {'items':[{'report_id':r.id,'work_order_id':r.work_order_id,'submitted_by':r.submitted_by,'machine_model':r.machine_model,'symptom_codes':r.symptom_codes,'symptom_resolution':symptoms.report_resolution(r),'steps':r.steps,'outcome':r.outcome,'part_ids':r.part_ids,'result_notes':r.result_notes,'repair_followup':r.repair_followup,'review_status':r.review_status} for r in rows],'skip':skip,'limit':limit}


@muse_router.get('/reports/{report_id}')
def report_source(report_id: int,db: Session=Depends(get_db),actor: Actor=Depends(get_current_actor)):
    from app.services.repair_guidance import machine_model,_case_source
    report=db.scalar(select(RepairCaseReport).where(RepairCaseReport.id==report_id,RepairCaseReport.organization_id==actor.organization_id))
    if not report:raise HTTPException(404,'Report not found')
    privileged=actor.role in {UserRole.ADMIN,UserRole.MANAGER}
    own=actor.user_id is not None and report.submitted_by==actor.user_id
    if not privileged and not own and report.review_status!='approved':raise HTTPException(404,'Report not found')
    require_work_order_scope(db,actor,report.work_order_id)
    order=db.scalar(select(WorkOrder).where(WorkOrder.id==report.work_order_id,WorkOrder.organization_id==actor.organization_id))
    current_model=machine_model(db,actor.organization_id,order)
    return {**_case_source(report),'report_id':report.id,'part_ids':report.part_ids,
            'review_status':report.review_status,'current_machine_model':current_model,
            'model_evidence_current':bool(current_model and current_model==report.machine_model),
            'guidance_eligible':report.review_status=='approved' and report.outcome=='resolved' and (report.repair_followup or {}).get('recurrence')!='recurred' and bool(current_model and current_model==report.machine_model) and bool(symptoms.report_codes(report)),
            'symptom_resolution':symptoms.report_resolution(report),'compatibility_confirmed':False}


@muse_router.get('/guide')
def muse_guide():
    from fastapi.responses import PlainTextResponse
    from app.services.catalog import DATA_ROOT
    return PlainTextResponse((DATA_ROOT/'docs/MUSE_PROJECT_BRIEF.md').read_text())


class FollowupSchedule(BaseModel):
    due_at: datetime | None
    reason: str=Field(min_length=1,max_length=1000)

    @model_validator(mode='after')
    def timezone_required(self):
        if self.due_at is not None and self.due_at.utcoffset() is None:
            raise ValueError('due_at requires an explicit timezone')
        if not self.reason.strip():raise ValueError('A nonblank reason is required')
        return self


@muse_router.put('/reports/{report_id}/followup-schedule')
def schedule_followup(report_id:int,payload:FollowupSchedule,db:Session=Depends(get_db),actor:Actor=Depends(get_current_actor)):
    report=db.scalar(select(RepairCaseReport).where(RepairCaseReport.id==report_id,RepairCaseReport.organization_id==actor.organization_id))
    if not report:raise HTTPException(404,'Report not found')
    require_work_order_write_scope(db,actor,report.work_order_id)
    if report.review_status!='approved':raise HTTPException(409,'Schedule requires an approved source report')
    previous=report.followup_due_at
    report.followup_due_at=payload.due_at.astimezone(timezone.utc).replace(tzinfo=None) if payload.due_at else None
    db.add(AuditLog(organization_id=actor.organization_id,user_id=actor.user_id,action='schedule_repair_followup',entity_type='repair_case_report',entity_id=report.id,metadata_json=json.dumps({'previous_due_at':previous.isoformat() if previous else None,'due_at':report.followup_due_at.isoformat() if report.followup_due_at else None,'reason':payload.reason.strip()})))
    db.commit()
    return {'report_id':report.id,'work_order_id':report.work_order_id,'due_at':report.followup_due_at.replace(tzinfo=timezone.utc) if report.followup_due_at else None,'cancelled':report.followup_due_at is None,'source_path':f'/api/muse/reports/{report.id}','guidance_changed':False}


@muse_router.get('/followups')
def followup_list(status:Literal['open','due','upcoming','awaiting_review','completed','overdue','late','recurred','all']='open',scope:Literal['mine','available','all']='mine',skip:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=100),db:Session=Depends(get_db),actor:Actor=Depends(get_current_actor)):
    return _followup_data(status,scope,skip,limit,db,actor)


def _followup_data(status,scope,skip,limit,db,actor):
    require_roles(actor,UserRole.ADMIN,UserRole.MANAGER,UserRole.ENGINEER,UserRole.WAREHOUSE)
    now=datetime.now(timezone.utc)
    stmt=select(RepairCaseReport,WorkOrder).join(WorkOrder,WorkOrder.id==RepairCaseReport.work_order_id).where(RepairCaseReport.organization_id==actor.organization_id,WorkOrder.organization_id==actor.organization_id,RepairCaseReport.followup_due_at.is_not(None),RepairCaseReport.review_status=='approved')
    if scope=='mine':stmt=stmt.where(WorkOrder.claimed_by_id==actor.user_id) if actor.user_id else stmt.where(False)
    elif scope=='available':stmt=stmt.where(WorkOrder.claimed_by_id.is_(None),WorkOrder.is_locked.is_(False))
    rows=db.execute(stmt.order_by(RepairCaseReport.followup_due_at,RepairCaseReport.id)).all()
    work_ids={r.work_order_id for r,o in rows}
    reports=list(db.scalars(select(RepairCaseReport).where(RepairCaseReport.organization_id==actor.organization_id,RepairCaseReport.work_order_id.in_(work_ids)).order_by(RepairCaseReport.created_at.desc(),RepairCaseReport.id.desc()))) if work_ids else []
    from app.services.repair_guidance import machine_model
    items=[];counts={'due':0,'upcoming':0,'awaiting_review':0,'completed':0}
    for report,order in rows:
        children=[r for r in reports if r.work_order_id==report.work_order_id and (r.repair_followup or {}).get('previous_report_id')==report.id]
        approved=next((r for r in children if r.review_status=='approved'),None)
        pending=next((r for r in children if r.review_status=='pending'),None)
        due=report.followup_due_at.replace(tzinfo=timezone.utc)
        state='completed' if approved else 'awaiting_review' if pending else 'due' if due<=now else 'upcoming'
        counts[state]+=1
        accepted=[r for r in children if r.review_status in {'approved','pending'}]
        first=min(accepted,key=lambda r:(r.created_at,r.id)) if accepted else None
        submitted=first.created_at.replace(tzinfo=timezone.utc) if first else None
        timing='on_time' if submitted and submitted<=due else 'late' if submitted else 'overdue' if due<now else 'not_due'
        elapsed=max(0,int(((submitted or now)-due).total_seconds()))
        recurrence=(approved.repair_followup or {}).get('recurrence','unknown') if approved else 'unreviewed'
        if status!='all' and not (status=='open' and state!='completed') and status!=state and not (status=='overdue' and timing=='overdue') and not (status=='late' and timing=='late') and not (status=='recurred' and recurrence=='recurred'):continue
        visible=pending if pending and (actor.role in {UserRole.ADMIN,UserRole.MANAGER} or pending.submitted_by==actor.user_id) else None
        latest=approved or visible
        items.append({'report_id':report.id,'work_order_id':order.id,'ticket_number':order.ticket_number,'claimed_by_id':order.claimed_by_id,'machine_model':report.machine_model,'model_evidence_current':machine_model(db,actor.organization_id,order)==report.machine_model and report.machine_model is not None,'symptom_codes':sorted(symptoms.report_codes(report)),'due_at':due,'status':state,'submission_timing':timing,'submission_delay_seconds':elapsed,'overdue_days':elapsed//86400 if timing=='overdue' else 0,'first_accepted_submission_at':submitted,'reviewed_recurrence':recurrence,'followup_needed':timing=='overdue','review_pending':bool(pending and not approved),'is_overdue':timing=='overdue','review_overdue':due<now and state=='awaiting_review','reminder_required':state=='due','source_path':f'/api/muse/reports/{report.id}','followup_report_id':latest.id if latest else None,'followup_source_path':f'/api/muse/reports/{latest.id}' if latest else None,'submit_path':f'/api/muse/work-orders/{order.id}/reports','previous_report_id':report.id,'compatibility_confirmed':False})
    return {'items':items[skip:skip+limit] if limit is not None else items,'total':len(items),'skip':skip,'limit':limit,'counts':counts,'as_of':now,'timezone':'UTC','reminder_delivery':'query_only','policy':'Due status is computed on each query. Submit a linked report using existing claim/device permissions; only approved feedback affects repair guidance. No external messages are sent.'}


@muse_router.get('/followups/recurrences')
def repair_recurrences(scope:Literal['mine','available','all']='mine',skip:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=100),db:Session=Depends(get_db),actor:Actor=Depends(get_current_actor)):
    items=_reviewed_recurrences(scope,db,actor)
    return {'items':items[skip:skip+limit],'total':len(items),'skip':skip,'limit':limit,'distinct_work_order_count':len({r['work_order_id'] for r in items}),'policy':'Latest approved report per exact symptom-code set and work order; includes unscheduled follow-ups, excludes unreviewed recurrence.'}


def _reviewed_recurrences(scope,db,actor):
    require_roles(actor,UserRole.ADMIN,UserRole.MANAGER,UserRole.ENGINEER,UserRole.WAREHOUSE)
    stmt=select(RepairCaseReport,WorkOrder).join(WorkOrder,WorkOrder.id==RepairCaseReport.work_order_id).where(RepairCaseReport.organization_id==actor.organization_id,WorkOrder.organization_id==actor.organization_id,RepairCaseReport.review_status=='approved')
    if scope=='mine':stmt=stmt.where(WorkOrder.claimed_by_id==actor.user_id) if actor.user_id else stmt.where(False)
    elif scope=='available':stmt=stmt.where(WorkOrder.claimed_by_id.is_(None),WorkOrder.is_locked.is_(False))
    from app.services.repair_guidance import machine_model
    seen=set();items=[]
    for report,order in db.execute(stmt.order_by(RepairCaseReport.created_at.desc(),RepairCaseReport.id.desc())):
        key=(order.id,tuple(sorted(symptoms.report_codes(report))))
        if key in seen:continue
        seen.add(key)
        if (report.repair_followup or {}).get('recurrence')!='recurred':continue
        items.append({'report_id':report.id,'work_order_id':order.id,'ticket_number':order.ticket_number,'machine_model':report.machine_model,'model_evidence_current':bool(report.machine_model and machine_model(db,actor.organization_id,order)==report.machine_model),'symptom_codes':list(key[1]),'source_path':f'/api/muse/reports/{report.id}','previous_report_id':report.repair_followup.get('previous_report_id'),'observation_days':report.repair_followup.get('observation_days'),'outcome':report.outcome,'reviewed_at':report.reviewed_at,'compatibility_confirmed':False})
    return items


@muse_router.get('/followups/stats')
def followup_stats(scope:Literal['mine','available','all']='mine',db:Session=Depends(get_db),actor:Actor=Depends(get_current_actor)):
    data=_followup_data('all',scope,0,None,db,actor)
    items=data['items'];recurrences=_reviewed_recurrences(scope,db,actor)
    timing={s:sum(i['submission_timing']==s for i in items) for s in ['overdue','late','on_time','not_due']}
    return {'as_of':data['as_of'],'scope':scope,'organization_id':actor.organization_id,'scheduled_followup_count':len(items),'scheduled_work_order_count':len({i['work_order_id'] for i in items}),'status_counts':data['counts'],'submission_timing_counts':timing,'overdue_work_order_count':len({i['work_order_id'] for i in items if i['followup_needed']}),'reviewed_recurrence_count':len(recurrences),'reviewed_recurrence_work_order_count':len({i['work_order_id'] for i in recurrences}),'sources':{'overdue':'/api/muse/followups?status=overdue&scope='+scope,'late':'/api/muse/followups?status=late&scope='+scope,'recurrences':'/api/muse/followups/recurrences?scope='+scope},'definitions':{'timeliness':'First currently pending or approved direct follow-up submission versus current due time; rejected reports do not satisfy follow-up. Review waiting is not submission delay. Rescheduling recalculates timing; audit preserves previous deadlines.','population':'Scheduled counts include active schedules on approved source reports. Recurrences include unscheduled latest approved reports per work order and exact canonical symptom set. Counts are current state, not a historical cohort or success rate.','approval':'Pending recurrence is never counted as confirmed. Reporting and scheduling do not change guidance or compatibility.'}}


@muse_router.get('/repair-statistics')
def repair_statistics(machine_model:str=Query('',max_length=255),symptom_code:str=Query('',max_length=80),skip:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=100),db:Session=Depends(get_db),actor:Actor=Depends(get_current_actor)):
    require_roles(actor,UserRole.ADMIN,UserRole.MANAGER,UserRole.ENGINEER,UserRole.WAREHOUSE)
    from app.services.repair_statistics import summary
    return summary(db,actor.organization_id,machine_model,symptom_code,skip,limit)


@muse_router.get('/repair-statistics/cases')
def repair_statistics_cases(machine_model:str=Query(...,min_length=1,max_length=255),symptom_code:str=Query(...,min_length=1,max_length=80),skip:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=100),db:Session=Depends(get_db),actor:Actor=Depends(get_current_actor)):
    require_roles(actor,UserRole.ADMIN,UserRole.MANAGER,UserRole.ENGINEER,UserRole.WAREHOUSE)
    from app.services.repair_statistics import groups
    items,_,classification=groups(db,actor.organization_id,machine_model,symptom_code)
    cases=[source for item in items for source in item['source_cases']]
    return {'items':cases[skip:skip+limit],'total':len(cases),'skip':skip,'limit':limit,'symptom_resolution':classification}
