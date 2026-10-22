import json
from app.services.catalog import DATA_ROOT,entries
from app.models import Part,Organization,Warehouse,InventoryTransaction,TransactionType


def test_db_additions_and_exact_model_sections(client):
    additions=json.loads((DATA_ROOT/'data/organized/db_added_parts.json').read_text())
    assert len(additions)==17 and len({r['catalog_id'] for r in entries('parts')})==len(entries('parts'))
    ids={r['catalog_id'] for r in additions};byid={r['catalog_id']:r for r in entries('parts')}
    assert ids<=set(byid)
    for mid,total in [('150',46),('200-275',48)]:
        model=client.get(f'/api/catalog/db/models/{mid}').json()
        r=client.get(f'/api/catalog/db/models/{mid}/parts?limit=100');r.raise_for_status();data=r.json()
        assert data['total']==total and len(data['items'])==min(total,100)
        for row in data['items']:
            assert row['official_associations'] and all(a['model']=={'150':'DB 150','200-275':'DB 200 / 275 Standard'}[mid] for a in row['official_associations'])
            assert not row['cross_model_compatibility_confirmed']
        for section in model['sections']:
            subset=client.get(f'/api/catalog/db/models/{mid}/parts',params={'section_id':section['id'],'limit':100}).json()
            assert {r['catalog_id'] for r in subset['items']}==set(section['part_ids'])
        gateway=client.post('/api/muse/query',json={'resource':'db_parts','model_id':mid,'limit':100});gateway.raise_for_status();assert gateway.json()==data
    assert client.get('/api/catalog/db/models/150/parts',params={'section_id':'DB 200 / 275 Standard|Invalid foreign section'}).status_code==404
    assert client.get('/api/catalog/db/models/3.0').status_code==404
    assert client.post('/api/muse/query',json={'resource':'db_parts'}).status_code==422


def test_db_import_idempotency_and_inventory_tenant_isolation(client):
    row=json.loads((DATA_ROOT/'data/organized/db_added_parts.json').read_text())[0]
    r=client.post('/api/catalog/parts/'+row['catalog_id']+'/import');r.raise_for_status();first=r.json()
    again=client.post('/api/catalog/parts/'+row['catalog_id']+'/import');again.raise_for_status();assert again.json()==first or again.json()['part_id']==first['part_id']
    mid={'DB 150':'150','DB 200 / 275 Standard':'200-275'}[row['fits_equipment_models'][0]]
    with client.app.state.testing_session_local() as db:
        db.add(Organization(id=2,name='Other',slug='other'));db.flush()
        p=Part(organization_id=2,part_number=row['part_number'],name='FOREIGN');w=Warehouse(organization_id=2,name='FOREIGN',code='FOREIGN');db.add_all([p,w]);db.flush()
        db.add(InventoryTransaction(organization_id=2,part_id=p.id,to_warehouse_id=w.id,transaction_type=TransactionType.INBOUND,quantity=99));db.commit()
    result=client.get(f'/api/catalog/db/models/{mid}/parts',params={'q':row['part_number']}).json()['items'][0]
    assert result['organization_part']['stock_quantity']==0 and not result['organization_part']['positions']
