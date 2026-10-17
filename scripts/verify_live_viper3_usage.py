"""Validate usage joins over real Bearer HTTP with removable test organizations."""
import json
from uuid import uuid4
import httpx
from sqlalchemy import select,delete,func
from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models import Organization,User,UserRole,Part,Warehouse,Equipment,WorkOrder,WorkOrderPart,PartMachineAssociation
from scripts.enrich_catalog_fields import OUT

def run():
    org_ids=[]
    try:
        with SessionLocal() as db:
            for label in ('pilot','foreign'):
                org=Organization(name='Temporary '+label,slug='verify-'+uuid4().hex);db.add(org);db.flush();org_ids.append(org.id)
            org,foreign=org_ids
            user=User(organization_id=org,name='Temporary verification',email=uuid4().hex+'@example.invalid',role=UserRole.ADMIN,is_active=True)
            part=Part(organization_id=org,part_number='TEMP-USAGE-'+uuid4().hex,name='Usage test')
            fp=Part(organization_id=foreign,part_number='FOREIGN-'+uuid4().hex,name='Foreign usage')
            wh=Warehouse(organization_id=org,code='TEST',name='Temporary warehouse');db.add_all([user,part,fp,wh]);db.flush()
            for n,(model,tenant,used_part,installed) in enumerate([('Viper 3 Flavor',org,part.id,'yes'),('Viper 3',org,part.id,'no'),('Viper 2',org,part.id,'yes'),('Viper 4',org,part.id,'yes'),('Viper 3',foreign,fp.id,'yes')]):
                order=WorkOrder(organization_id=tenant,ticket_number='VERIFY-'+uuid4().hex,machine_type=model);db.add(order);db.flush()
                db.add(WorkOrderPart(organization_id=tenant,work_order_id=order.id,part_id=used_part,warehouse_id=wh.id,quantity=2,installed=installed))
            db.commit();uid,pid,fid,number=user.id,part.id,fp.id,part.part_number
        token,_=create_access_token(uid,org);headers={'Authorization':'Bearer '+token};base='http://127.0.0.1:8000/api/catalog/models/viper-3'
        with httpx.Client(timeout=20) as client:
            assert client.get(base+'/parts/'+str(pid)+'/usage').status_code==401
            response=client.get(base+'/parts',params={'q':number},headers=headers);response.raise_for_status();row=response.json()['items'][0]
            assert row['official_associations']==[] and row['field_associations']==[]
            usage=row['work_order_usage'];assert usage['material_record_count']==2 and usage['actual_used_quantity']==2 and usage['actual_usage_count']==1
            assert usage['compatibility_confirmed'] is False
            response=client.get(base+'/parts/'+str(pid)+'/usage',params={'limit':1,'skip':1},headers=headers);response.raise_for_status()
            assert response.json()['total']==2 and len(response.json()['items'])==1
            assert client.get(base+'/parts/'+str(fid)+'/usage',headers=headers).status_code==404
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(PartMachineAssociation).where(PartMachineAssociation.organization_id==org))==0
        result={'actual_usage_separate':True,'non_installed_not_counted':True,'other_flavors_excluded':True,'other_organization_excluded':True,'pagination_verified':True,'unauthenticated_rejected':True,'no_automatic_field_verification':True}
        (OUT/'viper3_usage_api_check.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    finally:
        if org_ids:
            with SessionLocal() as db:
                for model in (WorkOrderPart,PartMachineAssociation,WorkOrder,Equipment,Part,Warehouse,User,Organization):
                    field=model.id if model is Organization else model.organization_id
                    db.execute(delete(model).where(field.in_(org_ids)))
                db.commit()
if __name__=='__main__':run()
