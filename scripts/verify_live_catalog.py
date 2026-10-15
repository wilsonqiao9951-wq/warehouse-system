"""Check the local HTTP API using a temporary account; leave no account behind."""
import json
from pathlib import Path
from uuid import uuid4
import httpx
from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models import Organization,User,UserRole

ROOT=Path(__file__).resolve().parents[1]

def run():
    base='http://127.0.0.1:8000/api'
    org_id=user_id=None
    with SessionLocal() as db:
        organization=Organization(name='Temporary API verification',slug='verify-'+uuid4().hex)
        db.add(organization);db.flush();org_id=organization.id
        user=User(name='Temporary verification',email=uuid4().hex+'@example.invalid',organization_id=org_id,role=UserRole.ADMIN,is_active=True)
        db.add(user);db.commit();user_id=user.id
    try:
        token,_=create_access_token(user_id,org_id)
        headers={'Authorization':'Bearer '+token}
        with httpx.Client(timeout=20) as client:
            assert client.get(base+'/catalog/parts').status_code==401
            assert client.get(base+'/catalog/models/viper-3').status_code==401
            pilot=client.get(base+'/catalog/models/viper-3',headers=headers)
            pilot.raise_for_status();pilot=pilot.json()
            assert pilot['official_part_count']==143 and len(pilot['sections'])==8
            assert all(s['id'].startswith('Viper 3 Flavor|') for s in pilot['sections'])
            section=pilot['sections'][0]
            linked=client.get(base+'/catalog/models/viper-3/parts',params={'section_id':section['id'],'limit':100},headers=headers)
            linked.raise_for_status();linked=linked.json()
            assert linked['total']==len(section['part_ids'])
            assert all(r['organization_part'] is None and r['field_associations']==[] for r in linked['items'])
            assert client.get(base+'/catalog/models/viper-3/parts',params={'section_id':'Viper 4 Flavor|Cladding Assembly'},headers=headers).status_code==404
            added=json.loads((ROOT/'data/organized/viper3_added_parts.json').read_text())
            for part in added:
                response=client.get(base+'/catalog/parts',params={'q':part['part_number'],'limit':100},headers=headers)
                response.raise_for_status()
                assert any(r['catalog_id']==part['catalog_id'] for r in response.json()['items'])
                response=client.get(base+'/catalog/models/viper-3/parts',params={'q':part['part_number'],'limit':100},headers=headers)
                response.raise_for_status()
                served=next(r for r in response.json()['items'] if r['catalog_id']==part['catalog_id'])
                assert served['official_associations'] and all(a['section_id'].startswith('Viper 3 Flavor|') for a in served['official_associations'])
                assert served['field_associations']==[] and served['work_order_usage']['actual_usage_count']==0
            counts={}
            for kind in ['parts','manuals','equipment']:
                response=client.get(base+'/catalog/'+kind,headers=headers);response.raise_for_status()
                counts[kind]=response.json()['total']
            recovery=json.loads((ROOT/'data/verification/image_recovery.json').read_text())
            images=[]
            source=json.loads((ROOT/'parts_index.json').read_text())
            for recovered in recovery:
                number=source[recovered['source_index']]['part_number']
                response=client.get(base+'/catalog/parts',params={'q':number,'limit':100},headers=headers);response.raise_for_status()
                row=next(r for r in response.json()['items'] if r['_organization']['source_index']==recovered['source_index'])
                assert row['image_url']==recovered['patch']['image_url']
                images.append({'source_index':recovered['source_index'],'served_image_matches':True})
            for title in ['8000 Crew-Serve','8100 Crew-Serve','7100 Ice Combo','23308 Drop-In']:
                response=client.get(base+'/catalog/manuals',params={'q':title,'limit':100},headers=headers);response.raise_for_status()
                manual=next(r for r in response.json()['items'] if r.get('title')==title)
                assert isinstance(manual['equipment_models'],list) and len(manual['equipment_models'])==1
            enrichment_path=ROOT/'data/verification/field_enrichment.json'
            model_checks=[]
            if enrichment_path.exists():
                enrichment=json.loads(enrichment_path.read_text())
                for field in ('name','description','fits_equipment_models'):
                    decision=next(d for d in enrichment if field in d['patch'] and d['status']=='confirmed' and not d.get('classification'))
                    number=source[decision['source_index']]['part_number']
                    response=client.get(base+'/catalog/parts',params={'q':number,'limit':100},headers=headers);response.raise_for_status()
                    served=next(r for r in response.json()['items'] if r['_organization']['source_index']==decision['source_index'])
                    assert served[field]==decision['patch'][field]
                recent_models=[d for d in enrichment if d['status']=='confirmed' and d['patch'].get('fits_equipment_models') and not d.get('classification')][-10:]
                for decision in recent_models:
                    index=decision['source_index']
                    number=source[index]['part_number']
                    models=decision['patch']['fits_equipment_models']
                    response=client.get(base+'/catalog/parts',params={'q':number,'limit':100},headers=headers)
                    response.raise_for_status()
                    served=next(r for r in response.json()['items'] if r['_organization']['source_index']==index)
                    assert served['fits_equipment_models']==models
                    response=client.get(base+'/catalog/parts',params={'q':number+' '+models[0],'limit':100},headers=headers)
                    response.raise_for_status()
                    assert any(r['_organization']['source_index']==index for r in response.json()['items'])
                    model_checks.append({'source_index':index,'models':models,'model_search_verified':True})
            for number in ['3508959','3508178']:
                result=client.get(base+'/catalog/parts',params={'q':number},headers=headers).json()
                assert any('/product/'+number+'/' in str(r['page_url']) for r in result['items'])
            identity_checks=[]
            identity_path=ROOT/'data/verification/identity_review_round4.json'
            if identity_path.exists():
                for decision in json.loads(identity_path.read_text()):
                    if decision['status']!='confirmed':continue
                    index=decision['source_index']
                    kind='equipment' if decision.get('classification')=='equipment' else 'parts'
                    response=client.get(base+'/catalog/'+kind,params={'q':source[index]['part_number'],'limit':100},headers=headers)
                    response.raise_for_status()
                    served=next(r for r in response.json()['items'] if r['_organization']['source_index']==index)
                    assert served['page_url']==decision['patch']['page_url']
                    if kind=='equipment':assert served['stock_import_candidate'] is False
                    assert any(v.get('status')=='confirmed' and v.get('evidence',{}).get('source_product_id')==decision['evidence']['source_product_id'] for v in served['verification'])
                    identity_checks.append({'source_index':index,'kind':kind,'verified':True})
            conflict=client.get(base+'/catalog/parts',params={'q':'CCP 146652'},headers=headers).json()['items'][0]
            source_checks=[]
            viper_repair_path=ROOT/'data/verification/viper_image_repairs.json'
            viper_image_checks=[]
            if viper_repair_path.exists():
                for repair in json.loads(viper_repair_path.read_text()):
                    response=client.get(base+'/catalog/parts',params={'q':repair['part_number'],'limit':100},headers=headers)
                    response.raise_for_status()
                    served=next(r for r in response.json()['items'] if r['_organization']['source_index']==repair['source_index'])
                    assert served['image_url']==repair['image_url']
                    viper_image_checks.append(repair['source_index'])
            freestyle_image_checks=[]
            freestyle_path=ROOT/'data/verification/freestyle_image_repairs.json'
            if freestyle_path.exists():
                for repair in json.loads(freestyle_path.read_text()):
                    response=client.get(base+'/catalog/parts',params={'q':repair['part_number'],'limit':100},headers=headers)
                    response.raise_for_status()
                    served=next(r for r in response.json()['items'] if r['_organization']['source_index']==repair['source_index'])
                    assert served['image_url']==repair['image_url']
                    freestyle_image_checks.append(repair['source_index'])
            supplemental_checks=[]
            supplement_path=ROOT/'data/verification/official_supplement.json'
            if supplement_path.exists():
                supplements=json.loads(supplement_path.read_text())
                organized=json.loads((ROOT/'data/organized/parts_catalog.json').read_text())
                newest_images=sorted([d for d in supplements if 'image_url' in d['patch']],key=lambda d:d.get('evidence',{}).get('image_check',{}).get('checked_at',''))[-20:]
                attachments=[d for d in supplements if 'digital_assets' in d['patch']]
                for decision in newest_images+attachments:
                    index=decision['source_index']
                    classification=organized[index]['_organization']['classification']
                    kind='equipment' if classification=='equipment' else 'manuals' if classification=='manual_section' else 'parts'
                    response=client.get(base+'/catalog/'+kind,params={'q':source[index]['part_number'],'limit':100},headers=headers)
                    response.raise_for_status()
                    served=next(r for r in response.json()['items'] if r['_organization']['source_index']==index)
                    assert all(served.get(field)==value for field,value in decision['patch'].items())
                    supplemental_checks.append({'source_index':index,'verified':True})
            source_path=ROOT/'data/verification/source_review_round5.json'
            if source_path.exists():
                for decision in json.loads(source_path.read_text()):
                    if decision['status']!='confirmed':continue
                    index=decision['source_index']
                    kind='manuals' if decision.get('classification')=='manual_section' else 'parts'
                    response=client.get(base+'/catalog/'+kind,params={'q':source[index]['part_number'],'limit':100},headers=headers)
                    response.raise_for_status()
                    served=next(r for r in response.json()['items'] if r['_organization']['source_index']==index)
                    assert served['page_url']==decision['patch']['page_url']
                    if kind=='manuals':
                        assert served['stock_import_candidate'] is False
                        response=client.get(base+'/catalog/parts',params={'q':source[index]['part_number'],'limit':100},headers=headers)
                        response.raise_for_status()
                        assert not any(r['_organization']['source_index']==index for r in response.json()['items'])
                    source_checks.append({'source_index':index,'kind':kind,'verified':True})
            assert conflict['page_url'] is None
            assert client.post(base+'/catalog/parts/'+conflict['catalog_id']+'/import',headers=headers).status_code==422
        result={'api_counts':counts,'recovered_images_verified':len(images),'manual_model_arrays_verified':4,'recent_model_queries_verified':len(model_checks),'model_checks':model_checks,'identity_queries_verified':len(identity_checks),'identity_checks':identity_checks,'unauthenticated_request_rejected':True,'conflict_import_rejected':True,'checks':images}
        result.update(source_queries_verified=len(source_checks),source_checks=source_checks)
        result.update(supplement_queries_verified=len(supplemental_checks),supplement_checks=supplemental_checks)
        result['viper3_pilot']={'official_parts':pilot['official_part_count'],'sections':len(pilot['sections']),'section_queries_verified':True,'other_flavor_section_rejected':True,'unauthenticated_rejected':True}
        result['viper3_pilot']['new_parts_queries_verified']=len(added)
        result['viper_images_restored_verified']=len(viper_image_checks)
        result['freestyle_images_restored_verified']=len(freestyle_image_checks)
        (ROOT/'data/verification/live_api_check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(json.dumps({k:v for k,v in result.items() if k!='checks'},ensure_ascii=False))
    finally:
        with SessionLocal() as db:
            if user_id:db.delete(db.get(User,user_id))
            if org_id:db.delete(db.get(Organization,org_id))
            db.commit()

if __name__=='__main__':run()
