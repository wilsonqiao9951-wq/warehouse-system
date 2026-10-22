from app.services.model_chain import graph,is_viper3
from app.services.catalog import entries
from app.models import Organization,Part,Warehouse,StorageLocation,InventoryTransaction,TransactionType,PartMachineAssociation


def test_model_identity_and_sections_exclude_other_flavor_counts(client):
    assert is_viper3('Viper-3-Flavor') and is_viper3('Viper 3')
    assert not is_viper3('Viper 2 Flavor') and not is_viper3('Viper 4 Flavor')
    result=client.get('/api/catalog/models/viper-3').json()
    assert result['official_part_count']==143 and len(result['sections'])==8
    assert all(s['id'].startswith('Viper 3 Flavor|') for s in result['sections'])
    assert client.get('/api/catalog/models/viper-3/parts',params={'section_id':'Viper 4 Flavor|Cladding Assembly'}).status_code==404


def test_chain_joins_scoped_inventory_and_separates_field_verification(client):
    cid=graph()['sections'][0]['part_ids'][0]
    imported=client.post(f'/api/catalog/parts/{cid}/import').json();pid=imported['id']
    with client.app.state.testing_session_local() as db:
        db.add(Organization(id=2,name='Other',slug='other'));db.flush()
        w=Warehouse(organization_id=1,code='MAIN',name='Main');db.add(w);db.flush()
        loc=StorageLocation(organization_id=1,warehouse_id=w.id,code='A-1');db.add(loc);db.flush()
        db.add(InventoryTransaction(organization_id=1,part_id=pid,transaction_type=TransactionType.INBOUND,quantity=5,to_warehouse_id=w.id,to_location_id=loc.id))
        db.add(InventoryTransaction(organization_id=1,part_id=pid,transaction_type=TransactionType.OUTBOUND,quantity=2,from_warehouse_id=w.id,from_location_id=loc.id))
        foreign=Part(organization_id=2,part_number=imported['part_number'],name='Foreign');db.add(foreign);db.flush()
        db.add(PartMachineAssociation(organization_id=2,part_id=foreign.id,machine_model='Viper 3 Flavor',recognition_source='field_verified'))
        db.add(PartMachineAssociation(organization_id=1,part_id=pid,machine_model='Viper 4 Flavor',recognition_source='field_verified'))
        db.commit();foreign_id=foreign.id
    response=client.get('/api/catalog/models/viper-3/parts',params={'q':imported['part_number']}).json()
    row=next(r for r in response['items'] if r['catalog_id']==cid)
    assert row['official_associations'] and row['field_associations']==[]
    assert row['organization_part']['stock_quantity']==3
    assert row['organization_part']['positions'][0]['location_code']=='A-1'
    assert client.post('/api/catalog/models/viper-3/field-verifications',json={'part_id':foreign_id}).status_code==404
    assert client.post('/api/catalog/models/viper-3/field-verifications',json={'part_id':pid}).status_code==200
    row=client.get('/api/catalog/models/viper-3/parts',params={'q':imported['part_number']}).json()['items'][0]
    assert row['field_associations'][0]['source']=='field_verified'
    assert row['official_associations']


def test_observation_is_not_verification_and_local_only_part_is_not_official(client):
    p=client.post('/api/parts',json={'part_number':'FIELD-ONLY','name':'Field only'}).json()
    with client.app.state.testing_session_local() as db:
        db.add(PartMachineAssociation(organization_id=1,part_id=p['id'],machine_model='Viper 3',recognition_source='employee_photo'));db.commit()
    r=client.get('/api/catalog/models/viper-3/parts',params={'q':'FIELD-ONLY'}).json()['items'][0]
    assert r['official_associations']==[] and r['field_associations'][0]['source']=='field_observation'
    assert client.get('/api/catalog/models/viper-3/parts',params={'section_id':graph()['sections'][0]['id'],'q':'FIELD-ONLY'}).json()['total']==0


def test_verification_requires_authorized_actor_and_records_audit(client):
    from app.core.config import settings
    from app.models import User,UserRole,AuditLog
    from sqlalchemy import select
    p=client.post('/api/parts',json={'part_number':'VERIFIED-PART','name':'Verified'}).json()
    with client.app.state.testing_session_local() as db:
        warehouse=User(organization_id=1,name='Warehouse',email='warehouse@example.invalid',role=UserRole.WAREHOUSE,is_active=True)
        engineer=User(organization_id=1,name='Engineer',email='engineer@example.invalid',role=UserRole.ENGINEER,is_active=True)
        db.add_all([warehouse,engineer]);db.commit();wid,eid=warehouse.id,engineer.id
    settings.rbac_enforce=True
    try:
        url='/api/catalog/models/viper-3/field-verifications'
        assert client.post(url,json={'part_id':p['id']}).status_code==401
        assert client.post(url,headers={'X-User-Id':str(wid)},json={'part_id':p['id']}).status_code==403
        for count in (1,2):
            response=client.post(url,headers={'X-User-Id':str(eid)},json={'part_id':p['id']})
            assert response.status_code==200 and response.json()['confirmed_count']==count
        with client.app.state.testing_session_local() as db:
            logs=list(db.scalars(select(AuditLog).where(AuditLog.action=='verify_viper3_part')))
            assert len(logs)==2 and all(log.user_id==eid for log in logs)
    finally:settings.rbac_enforce=False
