import json
from sqlalchemy import select,func
from app.models import Organization,Part,Warehouse,InventoryTransaction,TransactionType,PartMachineAssociation
from app.services.catalog import DATA_ROOT,entries
from app.services.freestyle_chain import graph


def test_all_543_added_parts_have_stable_unique_ids_and_model_edges(client):
    additions=json.loads((DATA_ROOT/'data/organized/freestyle_added_parts.json').read_text())
    assert len(additions)==543
    all_parts=list(entries('parts'));by_number={r['part_number']:r for r in all_parts}
    assert len(by_number)==len(all_parts)
    for row in additions:
        assert by_number[row['part_number']]['catalog_id']==row['catalog_id']
        assert row['catalog_id'].startswith('official-freestyle-')
        assert 0<len(row['name'])<=255 and len(row['part_number'])<=120
        for model in row['fits_equipment_models']:
            assert row['catalog_id'] in graph()['models'][model.split()[0]]['part_ids']


def test_all_eight_model_queries_match_only_explicit_relations(client):
    models=client.get('/api/catalog/freestyle/models').json()['items'];assert len(models)==8
    for summary in models:
        model=client.get('/api/catalog/freestyle/models/'+summary['model_id']).json()
        ids=set()
        for skip in range(0,summary['official_part_count'],100):
            result=client.get('/api/catalog/freestyle/models/'+summary['model_id']+'/parts',params={'limit':100,'skip':skip}).json()
            assert result['total']==summary['official_part_count']
            for row in result['items']:
                ids.add(row['catalog_id']);assert row['cross_model_compatibility_confirmed'] is False
                assert row['official_associations'] and all(a['model']==model['official_model'] for a in row['official_associations'])
        assert ids==set(model['part_ids'])
        section=model['sections'][0]
        response=client.get('/api/catalog/freestyle/models/'+summary['model_id']+'/parts',params={'section_id':section['id'],'limit':100}).json()
        assert response['total']==len(section['part_ids'])
    assert client.get('/api/catalog/freestyle/models/7100/parts',params={'section_id':'7000 Ice Combo|Refrigeration'}).status_code==404
    assert client.get('/api/catalog/freestyle/models/9999').status_code==404


def test_added_part_import_is_idempotent_and_inventory_is_tenant_scoped(client):
    row=json.loads((DATA_ROOT/'data/organized/freestyle_added_parts.json').read_text())[0];cid=row['catalog_id'];mid=row['fits_equipment_models'][0].split()[0]
    first=client.post(f'/api/catalog/parts/{cid}/import');assert first.status_code==200
    assert client.post(f'/api/catalog/parts/{cid}/import').json()['id']==first.json()['id']
    pid=first.json()['id']
    with client.app.state.testing_session_local() as db:
        db.add(Organization(id=2,name='Other',slug='other'));db.flush()
        fp=Part(organization_id=2,part_number=row['part_number'],name='Foreign')
        w=Warehouse(organization_id=1,code='MAIN',name='Main');fw=Warehouse(organization_id=2,code='OTHER',name='Other')
        db.add_all([fp,w,fw]);db.flush()
        db.add(InventoryTransaction(organization_id=1,part_id=pid,to_warehouse_id=w.id,transaction_type=TransactionType.INBOUND,quantity=3))
        db.add(InventoryTransaction(organization_id=2,part_id=fp.id,to_warehouse_id=fw.id,transaction_type=TransactionType.INBOUND,quantity=99));db.commit()
    served=client.get(f'/api/catalog/freestyle/models/{mid}/parts',params={'q':row['part_number']}).json()['items'][0]
    assert served['organization_part']['part_id']==pid and served['organization_part']['stock_quantity']==3
    assert all(x['warehouse_name']!='Other' for x in served['organization_part']['positions'])
    with client.app.state.testing_session_local() as db:
        assert db.scalar(select(func.count()).select_from(PartMachineAssociation))==0
