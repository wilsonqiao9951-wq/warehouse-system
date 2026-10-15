"""Verify separate technician/admin identities and reviewed-case feedback over HTTP."""
import json,os,secrets
from uuid import uuid4
from hashlib import sha256
from concurrent.futures import ThreadPoolExecutor
import httpx
from sqlalchemy import delete,select,func
from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models import Organization,User,UserRole,UserDevice,WorkOrder,RepairCaseReport,AuditLog
from scripts.enrich_catalog_fields import OUT

def run():
    org_ids=[]
    try:
        with SessionLocal() as db:
            for label in ('team','other'):
                org=Organization(name='Temporary Muse '+label,slug='verify-'+uuid4().hex);db.add(org);db.flush();org_ids.append(org.id)
            org,foreign=org_ids
            admin=User(organization_id=org,name='Review administrator',email=uuid4().hex+'@example.invalid',role=UserRole.ADMIN,is_active=True)
            foreign_admin=User(organization_id=foreign,name='Other organization administrator',email=uuid4().hex+'@example.invalid',role=UserRole.ADMIN,is_active=True)
            tech=User(organization_id=org,name='Technician',email=uuid4().hex+'@example.invalid',role=UserRole.ENGINEER,is_active=True);db.add_all([admin,tech,foreign_admin]);db.flush()
            device_id='opf-'+uuid4().hex;device_token=secrets.token_urlsafe(32)
            device=UserDevice(organization_id=org,user_id=tech.id,device_id=device_id,device_token_hash=sha256(device_token.encode()).hexdigest());db.add(device)
            jobs=[WorkOrder(organization_id=org,ticket_number='VERIFY-'+uuid4().hex,machine_type='9100 Self-Serve') for _ in range(2)]
            fj=WorkOrder(organization_id=foreign,ticket_number='VERIFY-'+uuid4().hex,machine_type='9100 Self-Serve');db.add_all(jobs+[fj]);db.commit();aid,tid=admin.id,tech.id;faid=foreign_admin.id;prior,current=[j.id for j in jobs];foreign_job=fj.id
        at,_=create_access_token(aid,org);tt,_=create_access_token(tid,org,device_id)
        ft,_=create_access_token(faid,foreign)
        ah={'Authorization':'Bearer '+at};fh={'Authorization':'Bearer '+ft};th={'Authorization':'Bearer '+tt,'X-Device-Token':device_token};base=os.environ.get('MYCOKE_VERIFY_BASE_URL','http://127.0.0.1:8000/api').rstrip('/')
        with httpx.Client(timeout=20) as client:
            assert client.get(base+'/muse').status_code==200 and client.get(base+'/muse/guide').status_code==200
            assert client.post(base+'/muse/query',json={'resource':'work_orders'}).status_code==401
            r=client.post(base+'/muse/query',json={'resource':'work_orders','scope':'available'},headers=th);r.raise_for_status();assert prior in [j['id'] for j in r.json()] and foreign_job not in [j['id'] for j in r.json()]
            r=client.post(base+'/muse/query',json={'resource':'work_orders','scope':'all'},headers=th);r.raise_for_status();assert {j['id'] for j in r.json()}=={prior,current}
            r=client.post(base+f'/work-orders/{prior}/claim',headers=th);r.raise_for_status();th['X-Claim-Version']=str(r.json()['claim_version'])
            r=client.post(base+'/muse/query',json={'resource':'work_orders','scope':'mine'},headers=th);r.raise_for_status();assert [j['id'] for j in r.json()]==[prior]
            payload={'symptom_codes':['LOW_FLOW'],'steps':['Recorded diagnostic checks'],'outcome':'resolved','result_notes':'Measured flow restored','part_ids':[]}
            th['Idempotency-Key']='report-'+uuid4().hex
            def submit():
                r=client.post(base+f'/muse/work-orders/{prior}/reports',json=payload,headers=th);r.raise_for_status();return r.json()
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures=[pool.submit(submit) for _ in range(2)]
                submissions=[future.result() for future in futures]
            assert submissions[0]['report_id']==submissions[1]['report_id']
            assert sorted(r['replayed'] for r in submissions)==[False,True]
            rid=submissions[0]['report_id']
            retry=client.post(base+f'/muse/work-orders/{prior}/reports',json=payload,headers=th);retry.raise_for_status();assert retry.json()['report_id']==rid and retry.json()['replayed']
            conflict=client.post(base+f'/muse/work-orders/{prior}/reports',json={**payload,'outcome':'unresolved'},headers=th);assert conflict.status_code==409
            with SessionLocal() as db:
                assert db.scalar(select(func.count()).select_from(RepairCaseReport).where(RepairCaseReport.organization_id==org))==1
                assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.organization_id==org,AuditLog.action=='submit_repair_case'))==1
            assert client.post(base+f'/work-orders/{foreign_job}/claim',headers=th).status_code==404
            assert client.post(base+f'/muse/work-orders/{foreign_job}/reports',json=payload,headers=th).status_code==404
            assert client.post(base+f'/muse/reports/{rid}/review',json={'decision':'approved'},headers=fh).status_code==404
            r=client.post(base+'/muse/query',json={'resource':'work_orders','scope':'all'},headers=fh);r.raise_for_status();assert [j['id'] for j in r.json()]==[foreign_job]
            r=client.post(base+f'/muse/work-orders/{foreign_job}/reports',json=payload,headers={**fh,'Idempotency-Key':th['Idempotency-Key']});r.raise_for_status();assert r.json()['report_id']!=rid
            def guidance():
                r=client.post(base+'/muse/query',json={'resource':'repair_guidance','work_order_id':current,'symptom_code':'LOW_FLOW'},headers=th);r.raise_for_status();return r.json()['reviewed_guidance']
            assert guidance()['reviewed_resolved_case_count']==0
            assert client.post(base+f'/muse/reports/{rid}/review',json={'decision':'approved'},headers=th).status_code==403
            r=client.post(base+f'/muse/reports/{rid}/review',json={'decision':'approved'},headers=ah);r.raise_for_status();assert guidance()['reviewed_resolved_case_count']==1
            assert client.get(base+f'/muse/work-orders/{foreign_job}/guidance',headers=th).status_code==404
        result={'discovery_and_guide':True,'technician_work_order_query':True,'work_order_all_mine_available_scopes':True,'device_bound_claim_and_report':True,'concurrent_report_retry':True,'single_report_and_submission_audit':True,'idempotent_report_retry':True,'changed_retry_rejected':True,'pending_not_learned':True,'technician_cannot_review':True,'admin_review_enables_same_model_case':True,'other_organization_excluded':True,'cross_org_claim_report_and_review_rejected':True,'idempotency_key_tenant_scoped':True,'anonymous_rejected':True,'engine':'reviewed_case_retrieval','model_training_performed':False}
        from pathlib import Path
        output=Path(os.environ.get('MYCOKE_VERIFY_REPORT_PATH',str(OUT/'muse_api_check.json')))
        output.write_text(json.dumps(result,indent=2));print(json.dumps(result))
    finally:
        if org_ids:
            with SessionLocal() as db:
                for model in (RepairCaseReport,AuditLog,WorkOrder,UserDevice,User,Organization):
                    field=model.id if model is Organization else model.organization_id;db.execute(delete(model).where(field.in_(org_ids)))
                db.commit()
if __name__=='__main__':run()
