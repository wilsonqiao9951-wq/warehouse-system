"""Verify all added parts and all model chains over real authenticated HTTP."""
import json
from uuid import uuid4
from sqlalchemy import select,delete
import httpx
from app.services.catalog import entries
from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models import Organization,User,UserRole
from scripts.enrich_catalog_fields import ROOT,OUT

def run():
    org_id=user_id=None
    try:
        with SessionLocal() as db:
            org=Organization(name='Temporary Freestyle check',slug='verify-'+uuid4().hex);db.add(org);db.flush();org_id=org.id
            user=User(organization_id=org_id,name='Temporary check',email=uuid4().hex+'@example.invalid',role=UserRole.ADMIN,is_active=True);db.add(user);db.commit();user_id=user.id
        token,_=create_access_token(user_id,org_id);headers={'Authorization':'Bearer '+token};base='http://127.0.0.1:8000/api/catalog';expected=json.loads((ROOT/'data/organized/freestyle_added_parts.json').read_text());ids={r['catalog_id'] for r in expected}
        with httpx.Client(timeout=30) as client:
            assert client.get(base+'/freestyle/models').status_code==401
            response=client.get(base+'/parts',headers=headers);response.raise_for_status();total=response.json()['total'];found=set()
            positions=[i for i,r in enumerate(entries('parts')) if r['catalog_id'] in ids]
            assert len(positions)==len(ids)
            for skip in range(min(positions),max(positions)+1,100):
                response=client.get(base+'/parts',params={'skip':skip,'limit':100},headers=headers);response.raise_for_status();found.update(r['catalog_id'] for r in response.json()['items'] if r['catalog_id'] in ids)
            assert found==ids
            response=client.get(base+'/freestyle/models',headers=headers);response.raise_for_status();models=response.json()['items'];assert len(models)==8
            model_counts={};linked=set()
            for model in models:
                mid=model['model_id'];seen=set()
                detail=client.get(base+'/freestyle/models/'+mid,headers=headers);detail.raise_for_status();detail=detail.json()
                for skip in range(0,model['official_part_count'],100):
                    response=client.get(base+'/freestyle/models/'+mid+'/parts',params={'skip':skip,'limit':100},headers=headers);response.raise_for_status()
                    for row in response.json()['items']:
                        seen.add(row['catalog_id']);linked.add(row['catalog_id'])
                        assert row['cross_model_compatibility_confirmed'] is False
                        assert row['organization_part'] is None
                        assert all(a['model']==model['official_model'] for a in row['official_associations'])
                assert seen==set(detail['part_ids']);model_counts[mid]=len(seen)
                section=detail['sections'][0]
                response=client.get(base+'/freestyle/models/'+mid+'/parts',params={'section_id':section['id']},headers=headers);response.raise_for_status();assert response.json()['total']==len(section['part_ids'])
            assert ids<=linked
            assert client.get(base+'/freestyle/models/7100/parts',params={'section_id':'7000 Ice Combo|Refrigeration'},headers=headers).status_code==404
        result={'main_catalog_additions_verified':len(ids),'models':model_counts,'model_queries_verified':8,'all_additions_linked':True,'model_section_isolation':True,'cross_model_fitment_not_confirmed':True,'organization_inventory_empty_for_temporary_tenant':True,'unauthenticated_rejected':True}
        (OUT/'freestyle_integration_api_check.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    finally:
        if org_id:
            with SessionLocal() as db:
                if user_id:db.execute(delete(User).where(User.id==user_id))
                db.execute(delete(Organization).where(Organization.id==org_id));db.commit()
if __name__=='__main__':run()
