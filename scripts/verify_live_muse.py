"""Verify separate technician/admin identities and reviewed-case feedback over HTTP."""
import json,os,secrets
from uuid import uuid4
from hashlib import sha256
from concurrent.futures import ThreadPoolExecutor
import httpx
from sqlalchemy import delete,select,func
from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models import Organization,User,UserRole,UserDevice,WorkOrder,RepairCaseReport,AuditLog,Part,Warehouse,InventoryTransaction,TransactionType
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
            number='VERIFY-'+uuid4().hex
            part=Part(organization_id=org,part_number=number,name='Temporary verified-case part')
            foreign_part=Part(organization_id=foreign,part_number=number,name='Other organization part')
            warehouse=Warehouse(organization_id=org,code='VERIFY-'+uuid4().hex,name='Temporary warehouse '+uuid4().hex)
            foreign_warehouse=Warehouse(organization_id=foreign,code='VERIFY-'+uuid4().hex,name='Temporary warehouse '+uuid4().hex)
            db.add_all([part,foreign_part,warehouse,foreign_warehouse]);db.flush();pid=part.id;foreign_pid=foreign_part.id
            db.add_all([InventoryTransaction(organization_id=org,part_id=pid,transaction_type=TransactionType.INBOUND,quantity=3,to_warehouse_id=warehouse.id),InventoryTransaction(organization_id=foreign,part_id=foreign_pid,transaction_type=TransactionType.INBOUND,quantity=99,to_warehouse_id=foreign_warehouse.id)])
            jobs=[WorkOrder(organization_id=org,ticket_number='VERIFY-'+uuid4().hex,machine_type='9100 Self-Serve',problem_description='出液量小') for _ in range(2)]
            fj=WorkOrder(organization_id=foreign,ticket_number='VERIFY-'+uuid4().hex,machine_type='9100 Self-Serve');db.add_all(jobs+[fj]);db.commit();aid,tid=admin.id,tech.id;faid=foreign_admin.id;prior,current=[j.id for j in jobs];foreign_job=fj.id
        at,_=create_access_token(aid,org);tt,_=create_access_token(tid,org,device_id)
        ft,_=create_access_token(faid,foreign)
        ah={'Authorization':'Bearer '+at};fh={'Authorization':'Bearer '+ft};th={'Authorization':'Bearer '+tt,'X-Device-Token':device_token};base=os.environ.get('MYCOKE_VERIFY_BASE_URL','http://127.0.0.1:8000/api').rstrip('/')
        with httpx.Client(timeout=20) as client:
            assert client.get(base+'/muse').status_code==200 and client.get(base+'/muse/guide').status_code==200
            r=client.get(base+'/muse/symptoms');r.raise_for_status();assert r.json()['version']=='1.0' and len(r.json()['items'])==13
            assert client.post(base+'/muse/query',json={'resource':'work_orders'}).status_code==401
            assert client.post(base+'/muse/symptoms/resolve',json={'work_order_id':current}).status_code==401
            r=client.get(base+f'/muse/work-orders/{current}/symptoms',headers=th);r.raise_for_status();assert r.json()['canonical_codes']==['low_flow'] and r.json()['source']=='work_order_problem_description'
            assert client.get(base+f'/muse/work-orders/{foreign_job}/symptoms',headers=th).status_code==404
            r=client.post(base+'/muse/symptoms/resolve',json={'symptom_text':'没有漏水，只是怀疑流量小'},headers=th);r.raise_for_status();assert r.json()['needs_confirmation'] and not r.json()['canonical_codes']
            r=client.post(base+'/muse/query',json={'resource':'work_orders','scope':'available'},headers=th);r.raise_for_status();assert prior in [j['id'] for j in r.json()] and foreign_job not in [j['id'] for j in r.json()]
            r=client.post(base+'/muse/query',json={'resource':'work_orders','scope':'all'},headers=th);r.raise_for_status();assert {j['id'] for j in r.json()}=={prior,current}
            r=client.post(base+f'/work-orders/{prior}/claim',headers=th);r.raise_for_status();th['X-Claim-Version']=str(r.json()['claim_version'])
            r=client.post(base+'/muse/query',json={'resource':'work_orders','scope':'mine'},headers=th);r.raise_for_status();assert [j['id'] for j in r.json()]==[prior]
            payload={'symptom_codes':['出液量小'],'steps':['Recorded diagnostic checks'],'outcome':'resolved','result_notes':'Measured flow restored','part_ids':[pid]}
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
            alias_retry=client.post(base+f'/muse/work-orders/{prior}/reports',json={**payload,'symptom_codes':['LOW_FLOW']},headers=th);alias_retry.raise_for_status();assert alias_retry.json()['report_id']==rid and alias_retry.json()['replayed']
            conflict=client.post(base+f'/muse/work-orders/{prior}/reports',json={**payload,'outcome':'unresolved'},headers=th);assert conflict.status_code==409
            with SessionLocal() as db:
                assert db.scalar(select(func.count()).select_from(RepairCaseReport).where(RepairCaseReport.organization_id==org))==1
                assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.organization_id==org,AuditLog.action=='submit_repair_case'))==1
            assert client.post(base+f'/work-orders/{foreign_job}/claim',headers=th).status_code==404
            assert client.post(base+f'/muse/work-orders/{foreign_job}/reports',json=payload,headers=th).status_code==404
            assert client.post(base+f'/muse/reports/{rid}/review',json={'decision':'approved'},headers=fh).status_code==404
            r=client.post(base+'/muse/query',json={'resource':'work_orders','scope':'all'},headers=fh);r.raise_for_status();assert [j['id'] for j in r.json()]==[foreign_job]
            r=client.post(base+f'/muse/work-orders/{foreign_job}/reports',json={**payload,'part_ids':[foreign_pid]},headers={**fh,'Idempotency-Key':th['Idempotency-Key']});r.raise_for_status();assert r.json()['report_id']!=rid
            def guidance():
                r=client.post(base+'/muse/query',json={'resource':'repair_guidance','work_order_id':current,'symptom_code':'LOW_FLOW'},headers=th);r.raise_for_status();return r.json()['reviewed_guidance']
            assert guidance()['reviewed_resolved_case_count']==0
            assert client.post(base+f'/muse/reports/{rid}/review',json={'decision':'approved'},headers=th).status_code==403
            r=client.post(base+f'/muse/reports/{rid}/review',json={'decision':'approved'},headers=ah);r.raise_for_status();result=guidance();assert result['reviewed_resolved_case_count']==1
            candidate=result['part_candidates'][0]
            fallback=client.post(base+'/muse/query',json={'resource':'repair_guidance','work_order_id':current},headers=th);fallback.raise_for_status();assert fallback.json()['symptom_resolution']['source']=='work_order_problem_description' and fallback.json()['reviewed_guidance']['cases'][0]['case_id']==rid
            ambiguous=client.post(base+'/muse/query',json={'resource':'repair_guidance','work_order_id':current,'symptom_text':'没有漏水，只是怀疑流量小'},headers=th);ambiguous.raise_for_status();assert not ambiguous.json()['reviewed_guidance']['cases']
            assert candidate['part_id']==pid and candidate['available_quantity']==3 and candidate['availability']=='in_stock'
            assert candidate['source_case_ids']==[rid] and candidate['needs_more_evidence'] and result['needs_more_evidence']
            assert not candidate['compatibility_confirmed'] and not candidate['inventory_reserved'] and not candidate['automatically_selected']
            assert result['suggested_checks'][0]['source_case_ids']==[rid]
            r=client.get(base+f'/muse/reports/{rid}',headers=th);r.raise_for_status();assert r.json()['guidance_eligible'] and r.json()['part_ids']==[pid]
            assert r.json()['symptom_resolution']['raw_codes']==['出液量小'] and r.json()['symptom_resolution']['canonical_codes']==['low_flow']
            assert client.get(base+f'/muse/reports/{rid}',headers=fh).status_code==404
            assert client.get(base+f'/work-orders/{current}/part-recommendations',headers=th).json()==[]
            r=client.get(base+f'/work-orders/{current}/part-recommendations',params={'symptom_code':'LOW_FLOW'},headers=th);r.raise_for_status();assert r.json()[0]['recommended_quantity'] is None and r.json()[0]['available_quantity']==3
            assert client.get(base+f'/muse/work-orders/{foreign_job}/guidance',headers=th).status_code==404
        result={'discovery_and_guide':True,'symptom_taxonomy_discovery':True,'work_order_symptom_resolution':True,'ambiguous_text_requires_confirmation':True,'symptom_alias_idempotent_retry':True,'feedback_original_symptoms_preserved':True,'guidance_from_work_order_symptoms':True,'technician_work_order_query':True,'work_order_all_mine_available_scopes':True,'device_bound_claim_and_report':True,'concurrent_report_retry':True,'single_report_and_submission_audit':True,'idempotent_report_retry':True,'changed_retry_rejected':True,'pending_not_learned':True,'technician_cannot_review':True,'admin_review_enables_same_model_case':True,'sourced_checks_and_part_recommendation':True,'organization_inventory_not_foreign_stock':True,'single_case_evidence_caution':True,'source_report_access_scoped':True,'legacy_recommendation_uses_reviewed_evidence':True,'no_automatic_quantity_fitment_or_inventory_use':True,'other_organization_excluded':True,'cross_org_claim_report_and_review_rejected':True,'idempotency_key_tenant_scoped':True,'anonymous_rejected':True,'engine':'reviewed_case_retrieval','model_training_performed':False}
        from pathlib import Path
        output=Path(os.environ.get('MYCOKE_VERIFY_REPORT_PATH',str(OUT/'muse_api_check.json')))
        output.write_text(json.dumps(result,indent=2));print(json.dumps(result))
    finally:
        if org_ids:
            with SessionLocal() as db:
                for model in (RepairCaseReport,AuditLog,InventoryTransaction,WorkOrder,UserDevice,Warehouse,Part,User,Organization):
                    field=model.id if model is Organization else model.organization_id;db.execute(delete(model).where(field.in_(org_ids)))
                db.commit()
if __name__=='__main__':run()
