import json
from app.services.catalog import DATA_ROOT, entries
from app.services.bargun_chain import graph
from app.models import Part, Organization, Warehouse, InventoryTransaction, TransactionType

EXPECTED_COUNTS = {'bargun-button-caps': 43, 'magnum': 155, 'mark-iv-10-button': 165, 'mark-iv-12-button': 159, 'mark-iv-14-button': 149, 'mark-iv-3-button-energy-tea': 69, 'rattler': 160, 'rattler-ii': 156, 's2-5-10-button': 99, 's2-5-12-button': 88, 's2-5-14-button': 96}
EXPECTED_ADDITIONS = 292


def test_bargun_catalog_models_sections_and_muse(client):
    additions=json.loads((DATA_ROOT/'data/organized/bargun_added_parts.json').read_text())
    assert len(additions)==EXPECTED_ADDITIONS
    all_rows=entries('parts');ids={r['catalog_id'] for r in all_rows}
    assert len(ids)==len(all_rows) and {r['catalog_id'] for r in additions}<=ids
    models=client.get('/api/catalog/bargun/models').json()['items']
    assert {m['model_id']:m['official_part_count'] for m in models}==EXPECTED_COUNTS
    for mid,total in EXPECTED_COUNTS.items():
        model=client.get('/api/catalog/bargun/models/'+mid).json()
        assert model['manufacturer']==('TAPRITE-FASSCO MFG.  INC.' if mid in {'rattler','rattler-ii','magnum'} else 'WUNDER-BAR')
        assert model['category']==['Bargun'] and model['manufacturer_evidence']['identity_confirmed']
        seen=set()
        for skip in range(0,total,100):
            response=client.get(f'/api/catalog/bargun/models/{mid}/parts',params={'skip':skip,'limit':100});response.raise_for_status();data=response.json()
            assert data['total']==total
            for row in data['items']:
                seen.add(row['catalog_id'])
                assert not row['cross_model_compatibility_confirmed']
                assert row['official_associations'] and all(a['model']==model['official_model'] for a in row['official_associations'])
            gateway=client.post('/api/muse/query',json={'resource':'bargun_parts','model_id':mid,'skip':skip,'limit':100});gateway.raise_for_status();assert gateway.json()==data
        assert seen==set(model['part_ids'])
        for section in model['sections']:
            found=set()
            for skip in range(0,len(section['part_ids']),100):
                data=client.get(f'/api/catalog/bargun/models/{mid}/parts',params={'section_id':section['id'],'skip':skip,'limit':100}).json()
                found.update(r['catalog_id'] for r in data['items'])
                assert all(a['section_id']==section['id'] for r in data['items'] for a in r['official_associations'])
            assert found==set(section['part_ids'])


def test_bargun_import_and_tenant_inventory(client):
    added=json.loads((DATA_ROOT/'data/organized/bargun_added_parts.json').read_text())[0]
    url='/api/catalog/parts/'+added['catalog_id']+'/import'
    r=client.post(url);r.raise_for_status();local_id=r.json()['id']
    assert client.post(url).json()['id']==local_id
    mid=next(mid for mid,m in graph()['models'].items() if added['catalog_id'] in m['part_ids'])
    with client.app.state.testing_session_local() as db:
        db.add(Organization(id=2,name='Other',slug='bargun-other'));db.flush()
        own=Warehouse(organization_id=1,name='Own',code='OWN');foreign=Warehouse(organization_id=2,name='Foreign',code='FOREIGN')
        part=Part(organization_id=2,part_number=added['part_number'],name='Foreign')
        db.add_all([own,foreign,part]);db.flush()
        db.add_all([InventoryTransaction(organization_id=1,part_id=local_id,to_warehouse_id=own.id,transaction_type=TransactionType.INBOUND,quantity=3),InventoryTransaction(organization_id=2,part_id=part.id,to_warehouse_id=foreign.id,transaction_type=TransactionType.INBOUND,quantity=99)]);db.commit()
    row=client.get(f'/api/catalog/bargun/models/{mid}/parts',params={'q':added['part_number']}).json()['items'][0]
    assert row['organization_part']['stock_quantity']==3
    assert all(p['warehouse_name']=='Own' for p in row['organization_part']['positions'])


def test_bargun_model_boundaries(client):
    foreign=client.get('/api/catalog/bargun/models/mark-iv-12-button').json()['sections'][0]['id']
    assert client.get('/api/catalog/bargun/models/mark-iv-10-button/parts',params={'section_id':foreign}).status_code==404
    assert client.post('/api/muse/query',json={'resource':'bargun_parts','model_id':'mark-iv-10-button','section_id':foreign}).status_code==404
    for mid in ['lancer-4500-44','37t','viper-3-flavor']:
        assert client.get('/api/catalog/bargun/models/'+mid).status_code==404
    assert client.post('/api/muse/query',json={'resource':'bargun_parts'}).status_code==422
    r=client.post('/api/muse/query',json={'resource':'bargun_models'});r.raise_for_status();assert len(r.json()['items'])==11
    r=client.post('/api/muse/query',json={'resource':'bargun_model','model_id':'mark-iv-10-button'});r.raise_for_status();assert r.json()['official_model']=='Mark IV 10 Button'


def test_bargun_section_discovery_stays_on_official_site_and_same_model():
    from scripts.audit_bargun_parts import sibling_sections
    base='https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/'
    product={'id':'Mark IV 10 Button|Handle','propertySets':[{'properties':[{'property':'unified_equipment_section_reference_link','values':[f'<a href="{base}valid/valid">New Drip Cup Assembly</a><a href="https://example.com/foreign">Foreign</a><a href="{base}other/other">Mark IV 12 Button|Handle</a>']}]}]}
    assert list(sibling_sections(product))==[(base+'valid/valid','Mark IV 10 Button|New Drip Cup Assembly')]
