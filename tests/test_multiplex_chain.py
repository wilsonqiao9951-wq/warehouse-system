import json
from app.services.catalog import DATA_ROOT,entries
from app.models import Part,Organization,Warehouse,InventoryTransaction,TransactionType


def test_multiplex_additions_and_exact_model_sections(client):
    additions=json.loads((DATA_ROOT/'data/organized/multiplex_added_parts.json').read_text())
    assert len(additions)==130 and len({r['catalog_id'] for r in entries('parts')})==len(entries('parts'))
    ids={r['catalog_id'] for r in additions};byid={r['catalog_id']:r for r in entries('parts')}
    assert ids<=set(byid)
    for mid,total in [('138-eda2', 17), ('146f', 8), ('148-edp', 9), ('37f', 64), ('37k', 80), ('37t', 83), ('44g-series', 90), ('44k04-44kx04', 53), ('44k22-44kx22', 48), ('44mr04-44mx04', 77), ('50-series-control-panel', 18), ('50erc-44erc', 89), ('50g-series', 103), ('50ma04-50max04-50mr04', 60), ('72', 51), ('aph3-apkv3', 15), ('mcd-37', 70), ('old-style', 11), ('s-250m', 36), ('sc180', 10), ('wbk10', 33), ('wbk8', 13), ('wbk9', 11)]:
        model=client.get(f'/api/catalog/multiplex/models/{mid}').json()
        assert model['manufacturer']=='MULTIPLEX' and model['manufacturer_evidence']['identity_confirmed']
        r=client.get(f'/api/catalog/multiplex/models/{mid}/parts?limit=100');r.raise_for_status();data=r.json()
        assert data['total']==total and len(data['items'])==min(total,100)
        for row in data['items']:
            assert row['official_associations'] and all(a['model']=={'138-eda2': '138 EDA2', '146f': '146F', '148-edp': '148 EDP', '37f': '37F', '37k': '37K', '37t': '37T', '44g-series': '44G Series', '44k04-44kx04': '44K04 / 44KX04', '44k22-44kx22': '44K22 / 44KX22', '44mr04-44mx04': '44MR04 / 44MX04', '50-series-control-panel': '50 Series Control Panel', '50erc-44erc': '50ERC / 44ERC', '50g-series': '50G Series', '50ma04-50max04-50mr04': '50MA04 / 50MAX04 / 50MR04', '72': '72', 'aph3-apkv3': 'APH3 / APKV3', 'mcd-37': 'MCD 37', 'old-style': 'Old Style', 's-250m': 'S-250M', 'sc180': 'SC180', 'wbk10': 'WBK10', 'wbk8': 'WBK8', 'wbk9': 'WBK9'}[mid] for a in row['official_associations'])
            assert not row['cross_model_compatibility_confirmed']
        for section in model['sections']:
            seen=set()
            for skip in range(0,len(section['part_ids']),100):
                subset=client.get(f'/api/catalog/multiplex/models/{mid}/parts',params={'section_id':section['id'],'skip':skip,'limit':100}).json()
                seen.update(r['catalog_id'] for r in subset['items'])
            assert seen==set(section['part_ids'])
        gateway=client.post('/api/muse/query',json={'resource':'multiplex_parts','model_id':mid,'limit':100});gateway.raise_for_status();assert gateway.json()==data
    assert client.get('/api/catalog/multiplex/models/37t/parts',params={'section_id':'37K|Invalid foreign section'}).status_code==404
    assert client.get('/api/catalog/multiplex/models/3.0').status_code==404
    assert client.post('/api/muse/query',json={'resource':'multiplex_parts'}).status_code==422


def test_multiplex_import_idempotency_and_inventory_tenant_isolation(client):
    added=json.loads((DATA_ROOT/'data/organized/multiplex_added_parts.json').read_text())[0]
    audit=next(r for r in json.loads((DATA_ROOT/'data/organized/multiplex_parts_catalog.json').read_text())['parts'] if r['part_number']==added['part_number'])
    row=next(r for r in entries('parts') if r['part_number']==audit['part_number'])
    r=client.post('/api/catalog/parts/'+row['catalog_id']+'/import');r.raise_for_status();first=r.json()
    again=client.post('/api/catalog/parts/'+row['catalog_id']+'/import');again.raise_for_status();assert again.json()==first or again.json()['part_id']==first['part_id']
    mid={'138 EDA2': '138-eda2', '146F': '146f', '148 EDP': '148-edp', '37F': '37f', '37K': '37k', '37T': '37t', '44G Series': '44g-series', '44K04 / 44KX04': '44k04-44kx04', '44K22 / 44KX22': '44k22-44kx22', '44MR04 / 44MX04': '44mr04-44mx04', '50 Series Control Panel': '50-series-control-panel', '50ERC / 44ERC': '50erc-44erc', '50G Series': '50g-series', '50MA04 / 50MAX04 / 50MR04': '50ma04-50max04-50mr04', '72': '72', 'APH3 / APKV3': 'aph3-apkv3', 'MCD 37': 'mcd-37', 'Old Style': 'old-style', 'S-250M': 's-250m', 'SC180': 'sc180', 'WBK10': 'wbk10', 'WBK8': 'wbk8', 'WBK9': 'wbk9'}[audit['models'][0]]
    with client.app.state.testing_session_local() as db:
        db.add(Organization(id=2,name='Other',slug='other'));db.flush()
        p=Part(organization_id=2,part_number=row['part_number'],name='FOREIGN');w=Warehouse(organization_id=2,name='FOREIGN',code='FOREIGN');db.add_all([p,w]);db.flush()
        db.add(InventoryTransaction(organization_id=2,part_id=p.id,to_warehouse_id=w.id,transaction_type=TransactionType.INBOUND,quantity=99));db.commit()
    result=client.get(f'/api/catalog/multiplex/models/{mid}/parts',params={'q':row['part_number']}).json()['items'][0]
    assert result['organization_part']['stock_quantity']==0 and not result['organization_part']['positions']

def test_multiplex_brand_boundary_and_coverage(client):
    r=client.get('/api/catalog/multiplex/models');r.raise_for_status()
    assert len(r.json()['items'])==23
    for foreign in ('8000','9000','viper3','ed-150','tj-150'):
        assert client.get('/api/catalog/multiplex/models/'+foreign).status_code==404
    for resource in ('multiplex_models','multiplex_model'):
        payload={'resource':resource,'model_id':'37t'}
        r=client.post('/api/muse/query',json=payload);r.raise_for_status()

    r=client.get('/api/catalog/multiplex/coverage');r.raise_for_status()
    assert r.json()['mycoke_model_count']==23
    assert r.json()['worldwide_all_series_complete'] is False
    q=client.post('/api/muse/query',json={'resource':'multiplex_coverage'})
    q.raise_for_status();assert q.json()==r.json()
