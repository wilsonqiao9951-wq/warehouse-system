import json
from app.services.catalog import DATA_ROOT, entries
from app.services.cornelius_chain import graph
from app.models import Part, Organization, Warehouse, InventoryTransaction, TransactionType

EXPECTED_COUNTS = {'2-flavor-3h-p-v4': 86, '3-valve-tower-ceramic': 6, 'appex-6': 21, 'automated-beverage-system-abs-1-0': 309, 'automated-beverage-system-abs-2-0': 216, 'cb2323-cb1522-cb3023-golden-corral': 56, 'ci2000-plus': 6, 'db-150': 46, 'db-200-275-standard': 48, 'df-150': 118, 'df-200-250': 164, 'ed-150': 158, 'ed-200-250': 200, 'ed-300': 91, 'idc255-pro-fast-gate': 101, 'tj-150': 29, 'tj-45-tj-90': 33, 'viper-2-flavor': 109, 'viper-3-flavor': 143, 'viper-4-flavor': 107, 'viper-carts': 3, 'backroom-package-mcdonald-s': 48, 'cb1522-18in-sabre-tower': 25, 'cb1522d': 25, 'cb2323-sabre-23in-tower-w-cdd': 34, 'cb2323-8vlv-wendy-s': 44, 'cb2323l-self-closing-lid': 20, 'cb2323l-sliding-lid': 36, 'cc2323-tower-w-sliding-lid': 27, 'cc2323l-self-closing-lid': 19, 'ci2000-plus-parenthesized': 6, 'db-275-bcp-pneumatic-ice-gate': 27, 'energize-6': 29, 'leopard': 6, 'prism': 51, 'quest-2000': 51, 'quest-4000': 63, 'sfv-1': 60}  # Filled from reviewed audit, fixed as a regression baseline.
EXPECTED_ADDITIONS = 264


def test_cornelius_catalog_models_sections_and_muse(client):
    additions=json.loads((DATA_ROOT/'data/organized/cornelius_added_parts.json').read_text())
    assert len(additions)==EXPECTED_ADDITIONS
    all_rows=entries('parts');ids={r['catalog_id'] for r in all_rows}
    assert len(ids)==len(all_rows) and {r['catalog_id'] for r in additions}<=ids
    models=client.get('/api/catalog/cornelius/models').json()['items']
    assert {m['model_id']:m['official_part_count'] for m in models}==EXPECTED_COUNTS
    for mid,total in EXPECTED_COUNTS.items():
        model=client.get('/api/catalog/cornelius/models/'+mid).json()
        assert model['manufacturer']=='MARMON / CORNELIUS' and model['manufacturer_evidence']['identity_confirmed']
        seen=set()
        for skip in range(0,total,100):
            response=client.get(f'/api/catalog/cornelius/models/{mid}/parts',params={'skip':skip,'limit':100});response.raise_for_status();data=response.json()
            assert data['total']==total
            for row in data['items']:
                seen.add(row['catalog_id'])
                assert not row['cross_model_compatibility_confirmed']
                assert row['official_associations'] and all(a['model']==model['official_model'] for a in row['official_associations'])
            gateway=client.post('/api/muse/query',json={'resource':'cornelius_parts','model_id':mid,'skip':skip,'limit':100});gateway.raise_for_status();assert gateway.json()==data
        assert seen==set(model['part_ids'])
        for section in model['sections']:
            found=set()
            for skip in range(0,len(section['part_ids']),100):
                data=client.get(f'/api/catalog/cornelius/models/{mid}/parts',params={'section_id':section['id'],'skip':skip,'limit':100}).json()
                found.update(r['catalog_id'] for r in data['items'])
                assert all(a['section_id']==section['id'] for r in data['items'] for a in r['official_associations'])
            assert found==set(section['part_ids'])


def test_cornelius_import_and_tenant_inventory(client):
    added=json.loads((DATA_ROOT/'data/organized/cornelius_added_parts.json').read_text())[0]
    url='/api/catalog/parts/'+added['catalog_id']+'/import'
    r=client.post(url);r.raise_for_status();local_id=r.json()['id']
    assert client.post(url).json()['id']==local_id
    mid=next(mid for mid,m in graph()['models'].items() if added['catalog_id'] in m['part_ids'])
    with client.app.state.testing_session_local() as db:
        db.add(Organization(id=2,name='Other',slug='cornelius-other'));db.flush()
        own=Warehouse(organization_id=1,name='Own',code='OWN');foreign=Warehouse(organization_id=2,name='Foreign',code='FOREIGN')
        part=Part(organization_id=2,part_number=added['part_number'],name='Foreign')
        db.add_all([own,foreign,part]);db.flush()
        db.add_all([InventoryTransaction(organization_id=1,part_id=local_id,to_warehouse_id=own.id,transaction_type=TransactionType.INBOUND,quantity=3),InventoryTransaction(organization_id=2,part_id=part.id,to_warehouse_id=foreign.id,transaction_type=TransactionType.INBOUND,quantity=99)]);db.commit()
    row=client.get(f'/api/catalog/cornelius/models/{mid}/parts',params={'q':added['part_number']}).json()['items'][0]
    assert row['organization_part']['stock_quantity']==3
    assert all(p['warehouse_name']=='Own' for p in row['organization_part']['positions'])


def test_cornelius_model_boundaries_preserve_viper3(client):
    foreign=client.get('/api/catalog/cornelius/models/viper-4-flavor').json()['sections'][0]['id']
    assert client.get('/api/catalog/cornelius/models/viper-3-flavor/parts',params={'section_id':foreign}).status_code==404
    assert client.post('/api/muse/query',json={'resource':'cornelius_parts','model_id':'viper-3-flavor','section_id':foreign}).status_code==404
    for mid in ['lancer-4500-44','37t','viper-2-3-4']:
        assert client.get('/api/catalog/cornelius/models/'+mid).status_code==404
    assert client.post('/api/muse/query',json={'resource':'cornelius_parts'}).status_code==422
    r=client.post('/api/muse/query',json={'resource':'cornelius_models'});r.raise_for_status();assert len(r.json()['items'])==38
    r=client.post('/api/muse/query',json={'resource':'cornelius_model','model_id':'viper-3-flavor'});r.raise_for_status();assert r.json()['official_model']=='Viper 3 Flavor'
    original=client.get('/api/catalog/models/viper-3').json()
    assert original['official_part_count']==143
    assert all(s['id'].startswith('Viper 3 Flavor|') for s in original['sections'])
