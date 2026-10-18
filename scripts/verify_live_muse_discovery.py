"""Verify the unified Muse contract over authenticated HTTP without operational writes."""
import json,os
from pathlib import Path
from uuid import uuid4
import httpx
from sqlalchemy import delete
from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models import Organization,User,UserRole
from app.services.catalog import DATA_ROOT
from app.services.muse_discovery import FAMILIES


def run():
    org_id=user_id=None
    try:
        with SessionLocal() as db:
            org=Organization(name='Temporary Muse discovery',slug='verify-'+uuid4().hex);db.add(org);db.flush();org_id=org.id
            user=User(organization_id=org_id,name='Temporary check',email=uuid4().hex+'@example.invalid',role=UserRole.ENGINEER,is_active=True);db.add(user);db.commit();user_id=user.id
        token,_=create_access_token(user_id,org_id)
        base=os.environ.get('MYCOKE_VERIFY_BASE_URL','http://127.0.0.1:8000/api').rstrip('/')
        with httpx.Client(timeout=30,headers={'Authorization':'Bearer '+token}) as client:
            manifest=client.get(base+'/muse');manifest.raise_for_status();assert manifest.json()['contract_version']=='1.5'
            guide=client.get(base+'/muse/guide');guide.raise_for_status();assert guide.json()['contract_version']=='1.5'
            with httpx.Client() as anonymous:
                assert anonymous.get(base+'/muse/guide').status_code==200
                assert anonymous.post(base+'/muse/query',json={'resource':'families'}).status_code==401
            families=client.post(base+'/muse/query',json={'resource':'families'});families.raise_for_status()
            assert {r['family_id'] for r in families.json()['items']}==set(FAMILIES)
            seen=set();skip=0
            while True:
                page=client.post(base+'/muse/query',json={'resource':'models','skip':skip,'limit':25});page.raise_for_status();page=page.json()
                seen.update((r['family_id'],r['model_id']) for r in page['items']);skip+=len(page['items'])
                if skip>=page['total']:break
                assert page['items']
            assert len(seen)==skip
            for family in families.json()['items']:
                models=client.post(base+'/muse/query',json=family['models_query']);models.raise_for_status();row=models.json()['items'][0]
                model=client.post(base+'/muse/query',json=row['detail_query']);model.raise_for_status()
                parts=client.post(base+'/muse/query',json={**row['parts_query'],'limit':3});parts.raise_for_status();parts=parts.json()
                assert parts['selection']=={'family_id':row['family_id'],'model_id':row['model_id']}
                assert parts['organization_id']==org_id and all(r['organization_part'] is None for r in parts['items'])
            ambiguous=client.post(base+'/muse/query',json={'resource':'models','q':'Viper 3'}).json()
            assert {r['family_id'] for r in ambiguous['items']}=={'viper3','cornelius'} and not ambiguous['automatic_model_selection']
            assert client.post(base+'/muse/query',json={'resource':'model_parts','family_id':'viper3','model_id':'viper-4'}).status_code==404
            assert client.post(base+'/muse/query',json={'resource':'model_parts','model_id':'magnum'}).status_code==422
        result={'contract_version':'1.5','families_verified':len(FAMILIES),'model_groups_verified':len(seen),'all_families_authenticated_parts_queries':True,'empty_inventory_for_temporary_tenant':True,'ambiguous_models_not_auto_selected':True,'anonymous_rejected':True,'public_guide':True}
        Path(os.environ.get('MYCOKE_MUSE_DISCOVERY_REPORT_PATH',str(DATA_ROOT/'data/verification/muse_discovery_api_check.json'))).write_text(json.dumps(result,indent=2));print(json.dumps(result))
    finally:
        if org_id:
            with SessionLocal() as db:
                if user_id:db.execute(delete(User).where(User.id==user_id))
                db.execute(delete(Organization).where(Organization.id==org_id));db.commit()
if __name__=='__main__':run()
