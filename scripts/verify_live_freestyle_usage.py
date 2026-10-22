"""Real Bearer checks of reported use and explicit verification for all eight models."""
import json
from uuid import uuid4
from sqlalchemy import delete,select,func
import httpx
from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models import Organization,User,UserRole,Part,Warehouse,Equipment,WorkOrder,WorkOrderPart,PartMachineAssociation,AuditLog
from app.services.freestyle_chain import graph
from scripts.enrich_catalog_fields import OUT

def run():
    org_ids=[]
    try:
        cases=[]
        with SessionLocal() as db:
            for label in ('pilot','foreign'):
                org=Organization(name='Temporary Freestyle '+label,slug='verify-'+uuid4().hex);db.add(org);db.flush();org_ids.append(org.id)
            org,foreign=org_ids
            user=User(organization_id=org,name='Verification',email=uuid4().hex+'@example.invalid',role=UserRole.ADMIN,is_active=True);w=Warehouse(organization_id=org,code='TEST',name='Temporary');db.add_all([user,w]);db.flush()
            for mid,model in graph()['models'].items():
                p=Part(organization_id=org,part_number='TEMP-'+mid+'-'+uuid4().hex,name='Test usage');fp=Part(organization_id=foreign,part_number='FOREIGN-'+uuid4().hex,name='Foreign')
                db.add_all([p,fp]);db.flush();other=next(k for k in graph()['models'] if k!=mid)
                for m,tenant,part,installed in [(model['official_model'],org,p.id,'yes'),(mid,org,p.id,'no'),(other,org,p.id,'yes'),(model['official_model'],foreign,fp.id,'yes')]:
                    order=WorkOrder(organization_id=tenant,ticket_number='VERIFY-'+uuid4().hex,machine_type=m);db.add(order);db.flush();db.add(WorkOrderPart(organization_id=tenant,work_order_id=order.id,part_id=part,warehouse_id=w.id,quantity=2,installed=installed))
                cases.append((mid,p.id,p.part_number,fp.id))
            db.commit();uid=user.id
        token,_=create_access_token(uid,org);headers={'Authorization':'Bearer '+token};base='http://127.0.0.1:8000/api/catalog/freestyle/models';verified=[]
        with httpx.Client(timeout=20) as client:
            for mid,pid,number,fid in cases:
                url=base+'/'+mid
                assert client.get(url+f'/parts/{pid}/usage').status_code==401
                response=client.get(url+'/parts',params={'q':number},headers=headers);response.raise_for_status();row=response.json()['items'][0]
                assert row['official_associations']==[] and row['field_associations']==[]
                assert row['work_order_usage']['actual_usage_count']==1 and row['work_order_usage']['actual_used_quantity']==2 and row['work_order_usage']['material_record_count']==2
                assert row['cross_model_compatibility_confirmed'] is False
                response=client.get(url+f'/parts/{pid}/usage',params={'skip':1,'limit':1},headers=headers);response.raise_for_status();assert response.json()['total']==2 and len(response.json()['items'])==1
                assert client.get(url+f'/parts/{fid}/usage',headers=headers).status_code==404
                assert client.post(url+'/field-verifications',json={'part_id':fid},headers=headers).status_code==404
                response=client.post(url+'/field-verifications',json={'part_id':pid},headers=headers);response.raise_for_status();assert response.json()['confirmed_count']==1
                response=client.get(url+'/parts',params={'q':number},headers=headers);response.raise_for_status();row=response.json()['items'][0]
                assert row['official_associations']==[] and row['field_associations'][0]['source']=='field_verified' and row['work_order_usage']['actual_usage_count']==1
                verified.append(mid)
        result={'models_verified':verified,'source_separation':True,'reported_usage_not_fitment':True,'other_model_and_tenant_excluded':True,'non_installed_not_counted':True,'pagination_verified':True,'explicit_verification_and_audit':True,'anonymous_rejected':True}
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.organization_id==org,AuditLog.action=='verify_freestyle_part'))==8
        (OUT/'freestyle_usage_api_check.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    finally:
        if org_ids:
            with SessionLocal() as db:
                for model in (AuditLog,WorkOrderPart,PartMachineAssociation,WorkOrder,Equipment,Part,Warehouse,User,Organization):
                    field=model.id if model is Organization else model.organization_id
                    db.execute(delete(model).where(field.in_(org_ids)))
                db.commit()
if __name__=='__main__':run()
