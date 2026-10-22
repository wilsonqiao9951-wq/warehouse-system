import json
from app.services.catalog import DATA_ROOT, entries
from app.services.mccann_chain import graph
from app.models import Part, Organization, Warehouse, InventoryTransaction, TransactionType

EXPECTED_COUNTS = {'2-5-gallon':29,'20-gallon':31}
EXPECTED_ADDITIONS = 21


def test_mccann_catalog_models_sections_and_muse(client):
    additions=json.loads((DATA_ROOT/'data/organized/mccann_added_parts.json').read_text())
    assert len(additions)==EXPECTED_ADDITIONS
    all_rows=entries('parts');ids={r['catalog_id'] for r in all_rows}
    assert len(ids)==len(all_rows) and {r['catalog_id'] for r in additions}<=ids
    models=client.get('/api/catalog/mccann/models').json()['items']
    assert {m['model_id']:m['official_part_count'] for m in models}==EXPECTED_COUNTS
    for mid,total in EXPECTED_COUNTS.items():
        model=client.get('/api/catalog/mccann/models/'+mid).json()
        assert model['manufacturer']=='MCCANN MANUFACTURING' and model['manufacturer_evidence']['identity_confirmed']
        seen=set()
        for skip in range(0,total,100):
            response=client.get(f'/api/catalog/mccann/models/{mid}/parts',params={'skip':skip,'limit':100});response.raise_for_status();data=response.json()
            assert data['total']==total
            for row in data['items']:
                seen.add(row['catalog_id'])
                assert not row['cross_model_compatibility_confirmed']
                assert row['official_associations'] and all(a['model']==model['official_model'] for a in row['official_associations'])
            gateway=client.post('/api/muse/query',json={'resource':'mccann_parts','model_id':mid,'skip':skip,'limit':100});gateway.raise_for_status();assert gateway.json()==data
        assert seen==set(model['part_ids'])
        for section in model['sections']:
            found=set()
            for skip in range(0,len(section['part_ids']),100):
                data=client.get(f'/api/catalog/mccann/models/{mid}/parts',params={'section_id':section['id'],'skip':skip,'limit':100}).json()
                found.update(r['catalog_id'] for r in data['items'])
                assert all(a['section_id']==section['id'] for r in data['items'] for a in r['official_associations'])
            assert found==set(section['part_ids'])


def test_mccann_import_and_tenant_inventory(client):
    added=json.loads((DATA_ROOT/'data/organized/mccann_added_parts.json').read_text())[0]
    url='/api/catalog/parts/'+added['catalog_id']+'/import'
    r=client.post(url);r.raise_for_status();local_id=r.json()['id']
    assert client.post(url).json()['id']==local_id
    mid=next(mid for mid,m in graph()['models'].items() if added['catalog_id'] in m['part_ids'])
    with client.app.state.testing_session_local() as db:
        db.add(Organization(id=2,name='Other',slug='mccann-other'));db.flush()
        own=Warehouse(organization_id=1,name='Own',code='OWN');foreign=Warehouse(organization_id=2,name='Foreign',code='FOREIGN')
        part=Part(organization_id=2,part_number=added['part_number'],name='Foreign')
        db.add_all([own,foreign,part]);db.flush()
        db.add_all([InventoryTransaction(organization_id=1,part_id=local_id,to_warehouse_id=own.id,transaction_type=TransactionType.INBOUND,quantity=3),InventoryTransaction(organization_id=2,part_id=part.id,to_warehouse_id=foreign.id,transaction_type=TransactionType.INBOUND,quantity=99)]);db.commit()
    row=client.get(f'/api/catalog/mccann/models/{mid}/parts',params={'q':added['part_number']}).json()['items'][0]
    assert row['organization_part']['stock_quantity']==3
    assert all(p['warehouse_name']=='Own' for p in row['organization_part']['positions'])


def test_mccann_model_boundaries(client):
    foreign=client.get('/api/catalog/mccann/models/20-gallon').json()['sections'][0]['id']
    assert client.get('/api/catalog/mccann/models/2-5-gallon/parts',params={'section_id':foreign}).status_code==404
    assert client.post('/api/muse/query',json={'resource':'mccann_parts','model_id':'2-5-gallon','section_id':foreign}).status_code==404
    for mid in ['lancer-4500-44','37t','viper-3-flavor']:
        assert client.get('/api/catalog/mccann/models/'+mid).status_code==404
    assert client.post('/api/muse/query',json={'resource':'mccann_parts'}).status_code==422
    r=client.post('/api/muse/query',json={'resource':'mccann_models'});r.raise_for_status();assert len(r.json()['items'])==2
    r=client.post('/api/muse/query',json={'resource':'mccann_model','model_id':'2-5-gallon'});r.raise_for_status();assert r.json()['official_model']=='2.5 GALLON'
