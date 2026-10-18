import json
from app.services.catalog import DATA_ROOT,entries
from app.models import Part,Organization,Warehouse,InventoryTransaction,TransactionType


def test_series37_additions_and_exact_model_sections(client):
    additions=json.loads((DATA_ROOT/'data/organized/series37_added_parts.json').read_text())
    assert len(additions)==25 and len({r['catalog_id'] for r in entries('parts')})==len(entries('parts'))
    ids={r['catalog_id'] for r in additions};byid={r['catalog_id']:r for r in entries('parts')}
    assert ids<=set(byid)
    for mid,total in [('37t',83),('37f',64),('37k',80)]:
        model=client.get(f'/api/catalog/series37/models/{mid}').json()
        r=client.get(f'/api/catalog/series37/models/{mid}/parts?limit=100');r.raise_for_status();data=r.json()
        assert data['total']==total and len(data['items'])==min(total,100)
        for row in data['items']:
            assert row['official_associations'] and all(a['model']=={'37t':'37T','37f':'37F','37k':'37K'}[mid] for a in row['official_associations'])
            assert not row['cross_model_compatibility_confirmed']
        for section in model['sections']:
            seen=set()
            for skip in range(0,len(section['part_ids']),100):
                subset=client.get(f'/api/catalog/series37/models/{mid}/parts',params={'section_id':section['id'],'skip':skip,'limit':100}).json()
                seen.update(r['catalog_id'] for r in subset['items'])
            assert seen==set(section['part_ids'])
        gateway=client.post('/api/muse/query',json={'resource':'series37_parts','model_id':mid,'limit':100});gateway.raise_for_status();assert gateway.json()==data
    assert client.get('/api/catalog/series37/models/37t/parts',params={'section_id':'37K|Invalid foreign section'}).status_code==404
    assert client.get('/api/catalog/series37/models/3.0').status_code==404
    assert client.post('/api/muse/query',json={'resource':'series37_parts'}).status_code==422


def test_series37_import_idempotency_and_inventory_tenant_isolation(client):
    added=json.loads((DATA_ROOT/'data/organized/series37_added_parts.json').read_text())[0]
    audit=next(r for r in json.loads((DATA_ROOT/'data/organized/series37_parts_catalog.json').read_text())['parts'] if r['part_number']==added['part_number'])
    row=next(r for r in entries('parts') if r['part_number']==audit['part_number'])
    r=client.post('/api/catalog/parts/'+row['catalog_id']+'/import');r.raise_for_status();first=r.json()
    again=client.post('/api/catalog/parts/'+row['catalog_id']+'/import');again.raise_for_status();assert again.json()==first or again.json()['part_id']==first['part_id']
    mid={'37T':'37t','37F':'37f','37K':'37k'}[audit['models'][0]]
    with client.app.state.testing_session_local() as db:
        db.add(Organization(id=2,name='Other',slug='other'));db.flush()
        p=Part(organization_id=2,part_number=row['part_number'],name='FOREIGN');w=Warehouse(organization_id=2,name='FOREIGN',code='FOREIGN');db.add_all([p,w]);db.flush()
        db.add(InventoryTransaction(organization_id=2,part_id=p.id,to_warehouse_id=w.id,transaction_type=TransactionType.INBOUND,quantity=99));db.commit()
    result=client.get(f'/api/catalog/series37/models/{mid}/parts',params={'q':row['part_number']}).json()['items'][0]
    assert result['organization_part']['stock_quantity']==0 and not result['organization_part']['positions']
