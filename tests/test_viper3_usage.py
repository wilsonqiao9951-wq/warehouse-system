from app.models import Organization,Part,Warehouse,Equipment,WorkOrder,WorkOrderPart,PartMachineAssociation
from sqlalchemy import select,func
from app.services.model_chain import graph


def seed_usage(db,part,warehouse,ticket,model=None,equipment=None,org=1,installed='yes',quantity=2):
    order=WorkOrder(organization_id=org,ticket_number=ticket,machine_type=model,equipment_id=equipment)
    db.add(order);db.flush()
    item=WorkOrderPart(organization_id=org,part_id=part,warehouse_id=warehouse,work_order_id=order.id,quantity=quantity,installed=installed)
    db.add(item);db.flush();return item


def test_work_order_use_is_separate_and_filtered_by_model_and_tenant(client):
    p=client.post('/api/parts',json={'part_number':'USED-ONLY','name':'Used only'}).json()
    with client.app.state.testing_session_local() as db:
        db.add(Organization(id=2,name='Other',slug='other'));db.flush()
        w=Warehouse(organization_id=1,code='W',name='Main');fw=Warehouse(organization_id=2,code='F',name='Foreign')
        db.add_all([w,fw]);db.flush()
        asset3=Equipment(organization_id=1,model='Viper 3 Flavor');asset4=Equipment(organization_id=1,model='Viper 4 Flavor');foreign_asset=Equipment(organization_id=2,model='Viper 3 Flavor')
        db.add_all([asset3,asset4,foreign_asset]);db.flush()
        seed_usage(db,p['id'],w.id,'GOOD','Viper 3 Flavor')
        seed_usage(db,p['id'],w.id,'ASSET',equipment=asset3.id,quantity=3)
        seed_usage(db,p['id'],w.id,'NOT-INSTALLED','Viper 3',installed='no',quantity=7)
        for ticket,model,asset,org,warehouse in [('TWO','Viper 2',None,1,w.id),('FOUR','Viper 4',None,1,w.id),('UNKNOWN',None,None,1,w.id),('CONFLICT','Viper 3',asset4.id,1,w.id),('REVERSE-CONFLICT','Viper 4',asset3.id,1,w.id),('FOREIGN-ORDER','Viper 3',None,2,w.id),('FOREIGN-ASSET','Viper 3',foreign_asset.id,1,w.id),('FOREIGN-WH','Viper 3',None,1,fw.id)]:
            seed_usage(db,p['id'],warehouse,ticket,model,asset,org)
        db.commit()
    result=client.get('/api/catalog/models/viper-3/parts',params={'q':'USED-ONLY'}).json()['items'][0]
    assert result['official_associations']==[] and result['field_associations']==[]
    usage=result['work_order_usage']
    assert usage['material_record_count']==3 and usage['actual_usage_count']==2 and usage['actual_used_quantity']==5
    assert usage['compatibility_confirmed'] is False
    assert {r['ticket_number'] for r in usage['records']}=={'GOOD','ASSET','NOT-INSTALLED'}
    assert next(r for r in usage['records'] if r['ticket_number']=='NOT-INSTALLED')['source']=='work_order_material'
    assert client.get('/api/catalog/models/viper-3/parts',params={'section_id':graph()['sections'][0]['id'],'q':'USED-ONLY'}).json()['total']==0
    detail=client.get(f"/api/catalog/models/viper-3/parts/{p['id']}/usage",params={'skip':1,'limit':1}).json()
    assert detail['total']==3 and len(detail['items'])==1 and detail['summary']['actual_used_quantity']==5
    with client.app.state.testing_session_local() as db:
        assert db.scalar(select(func.count()).select_from(PartMachineAssociation))==0


def test_official_and_verified_evidence_survive_usage_join(client):
    cid=graph()['sections'][0]['part_ids'][0]
    p=client.post(f'/api/catalog/parts/{cid}/import').json()
    client.post('/api/catalog/models/viper-3/field-verifications',json={'part_id':p['id']})
    with client.app.state.testing_session_local() as db:
        w=Warehouse(organization_id=1,code='W',name='Main');db.add(w);db.flush()
        seed_usage(db,p['id'],w.id,'ALL-SOURCES','Viper 3');db.commit()
    row=client.get('/api/catalog/models/viper-3/parts',params={'q':p['part_number']}).json()['items'][0]
    assert row['official_associations']
    assert row['field_associations'][0]['source']=='field_verified'
    assert row['work_order_usage']['records'][0]['source']=='actual_usage'
    assert row['work_order_usage']['compatibility_confirmed'] is False


def test_foreign_part_detail_hidden_and_usage_preview_capped(client):
    with client.app.state.testing_session_local() as db:
        db.add(Organization(id=2,name='Other',slug='other'));db.flush()
        p=Part(organization_id=1,part_number='MANY',name='Many');fp=Part(organization_id=2,part_number='FOREIGN',name='Foreign')
        w=Warehouse(organization_id=1,code='W',name='Main');db.add_all([p,fp,w]);db.flush()
        for n in range(23):seed_usage(db,p.id,w.id,f'MANY-{n}','Viper 3')
        seed_usage(db,fp.id,w.id,'FOREIGN-PART','Viper 3')
        db.commit();pid,fid=p.id,fp.id
    assert client.get(f'/api/catalog/models/viper-3/parts/{fid}/usage').status_code==404
    assert client.get('/api/catalog/models/viper-3/parts',params={'q':'FOREIGN'}).json()['total']==0
    row=client.get('/api/catalog/models/viper-3/parts',params={'q':'MANY'}).json()['items'][0]
    assert row['work_order_usage']['material_record_count']==23 and len(row['work_order_usage']['records'])==20
    assert client.get(f'/api/catalog/models/viper-3/parts/{pid}/usage',params={'skip':20,'limit':10}).json()['total']==23
