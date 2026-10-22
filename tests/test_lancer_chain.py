import json
from app.services.catalog import DATA_ROOT,entries
from app.models import Part,Organization,Warehouse,InventoryTransaction,TransactionType


def test_lancer_additions_and_exact_model_sections(client):
    additions=json.loads((DATA_ROOT/'data/organized/lancer_added_parts.json').read_text())
    assert len(additions)==393 and len({r['catalog_id'] for r in entries('parts')})==len(entries('parts'))
    ids={r['catalog_id'] for r in additions};byid={r['catalog_id']:r for r in entries('parts')}
    assert ids<=set(byid)
    for mid,total in {'1-and-2-valve-tower-model-300': 22, '1500-prechiller-sonic': 40, '1500': 76, '1523-drop-in-series-1523-2206': 30, '22-inch-acib-bevariety': 129, '2300-drop-in-bevariety': 76, '2300-drop-in-series-2306-2308-2310': 62, '2300-drop-in-sabre-plug-in': 32, '2300-hp-drop-in': 7, '2300-ice-cooled-drop-in-bevariety': 13, '2300-sp-drop-in': 3, '23308-drop-in': 25, '23308-sonic-udm-bevariety': 106, '2400-free-standing-plug-in': 34, '2500': 71, '30-inch-acib-bevariety': 138, 'lancer-4500-44': 84, 'lancer-4500-ibd22-ibd30': 186, 'lancer-4500-ibd44': 84, 'remote-pump-assembly-bevariety': 22}.items():
        model=client.get(f'/api/catalog/lancer/models/{mid}').json()
        assert model['manufacturer']=='LANCER CORPORATION' and model['manufacturer_evidence']['identity_confirmed']
        r=client.get(f'/api/catalog/lancer/models/{mid}/parts?limit=100');r.raise_for_status();data=r.json()
        assert data['total']==total and len(data['items'])==min(total,100)
        for row in data['items']:
            assert row['official_associations'] and all(a['model']=={'1-and-2-valve-tower-model-300': '1 and 2 Valve Tower (Model 300)', '1500-prechiller-sonic': '1500 Prechiller (SONIC)', '1500': '1500', '1523-drop-in-series-1523-2206': '1523 Drop-In Series (1523 / 2206)', '22-inch-acib-bevariety': '22 INCH ACIB (Bevariety)', '2300-drop-in-bevariety': '2300 Drop-In (Bevariety)', '2300-drop-in-series-2306-2308-2310': '2300 Drop-In SERIES (2306-2308-2310)', '2300-drop-in-sabre-plug-in': '2300 Drop-In Sabre Plug-In', '2300-hp-drop-in': '2300 HP Drop In', '2300-ice-cooled-drop-in-bevariety': '2300 Ice Cooled Drop In (Bevariety)', '2300-sp-drop-in': '2300 SP Drop In', '23308-drop-in': '23308 Drop-In', '23308-sonic-udm-bevariety': '23308 - Sonic UDM (Bevariety)', '2400-free-standing-plug-in': '2400 Free Standing, Plug-in', '2500': '2500', '30-inch-acib-bevariety': '30 INCH ACIB (Bevariety)', 'lancer-4500-44': 'Lancer 4500 - 44', 'lancer-4500-ibd22-ibd30': 'Lancer 4500 IBD22, IBD30', 'lancer-4500-ibd44': 'Lancer 4500 IBD44', 'remote-pump-assembly-bevariety': 'Remote Pump Assembly (Bevariety)'}[mid] for a in row['official_associations'])
            assert not row['cross_model_compatibility_confirmed']
        for section in model['sections']:
            seen=set()
            for skip in range(0,len(section['part_ids']),100):
                subset=client.get(f'/api/catalog/lancer/models/{mid}/parts',params={'section_id':section['id'],'skip':skip,'limit':100}).json()
                seen.update(r['catalog_id'] for r in subset['items'])
            assert seen==set(section['part_ids'])
        gateway=client.post('/api/muse/query',json={'resource':'lancer_parts','model_id':mid,'limit':100});gateway.raise_for_status();assert gateway.json()==data
    foreign=client.get('/api/catalog/lancer/models/2500').json()['sections'][0]['id']
    assert client.get('/api/catalog/lancer/models/1500/parts',params={'section_id':foreign}).status_code==404
    assert client.post('/api/muse/query',json={'resource':'lancer_parts','model_id':'1500','section_id':foreign}).status_code==404
    assert client.get('/api/catalog/lancer/models/3.0').status_code==404
    assert client.post('/api/muse/query',json={'resource':'lancer_parts'}).status_code==422


def test_lancer_import_idempotency_and_inventory_tenant_isolation(client):
    added=json.loads((DATA_ROOT/'data/organized/lancer_added_parts.json').read_text())[0]
    audit=next(r for r in json.loads((DATA_ROOT/'data/organized/lancer_parts_catalog.json').read_text())['parts'] if r['part_number']==added['part_number'])
    row=next(r for r in entries('parts') if r['part_number']==audit['part_number'])
    r=client.post('/api/catalog/parts/'+row['catalog_id']+'/import');r.raise_for_status();first=r.json()
    again=client.post('/api/catalog/parts/'+row['catalog_id']+'/import');again.raise_for_status();assert again.json()==first or again.json()['part_id']==first['part_id']
    mid={'1 and 2 Valve Tower (Model 300)': '1-and-2-valve-tower-model-300', '1500 Prechiller (SONIC)': '1500-prechiller-sonic', '1500': '1500', '1523 Drop-In Series (1523 / 2206)': '1523-drop-in-series-1523-2206', '22 INCH ACIB (Bevariety)': '22-inch-acib-bevariety', '2300 Drop-In (Bevariety)': '2300-drop-in-bevariety', '2300 Drop-In SERIES (2306-2308-2310)': '2300-drop-in-series-2306-2308-2310', '2300 Drop-In Sabre Plug-In': '2300-drop-in-sabre-plug-in', '2300 HP Drop In': '2300-hp-drop-in', '2300 Ice Cooled Drop In (Bevariety)': '2300-ice-cooled-drop-in-bevariety', '2300 SP Drop In': '2300-sp-drop-in', '23308 Drop-In': '23308-drop-in', '23308 - Sonic UDM (Bevariety)': '23308-sonic-udm-bevariety', '2400 Free Standing, Plug-in': '2400-free-standing-plug-in', '2500': '2500', '30 INCH ACIB (Bevariety)': '30-inch-acib-bevariety', 'Lancer 4500 - 44': 'lancer-4500-44', 'Lancer 4500 IBD22, IBD30': 'lancer-4500-ibd22-ibd30', 'Lancer 4500 IBD44': 'lancer-4500-ibd44', 'Remote Pump Assembly (Bevariety)': 'remote-pump-assembly-bevariety'}[audit['models'][0]]
    with client.app.state.testing_session_local() as db:
        db.add(Organization(id=2,name='Other',slug='other'));db.flush()
        p=Part(organization_id=2,part_number=row['part_number'],name='FOREIGN');w=Warehouse(organization_id=2,name='FOREIGN',code='FOREIGN');db.add_all([p,w]);db.flush()
        db.add(InventoryTransaction(organization_id=2,part_id=p.id,to_warehouse_id=w.id,transaction_type=TransactionType.INBOUND,quantity=99));db.commit()
    result=client.get(f'/api/catalog/lancer/models/{mid}/parts',params={'q':row['part_number']}).json()['items'][0]
    assert result['organization_part']['stock_quantity']==0 and not result['organization_part']['positions']

def test_lancer_brand_boundary(client):
    r=client.get('/api/catalog/lancer/models');r.raise_for_status()
    assert len(r.json()['items'])==20
    for foreign in ('8000','9000','viper3','ed-150','tj-150'):
        assert client.get('/api/catalog/lancer/models/'+foreign).status_code==404
    for resource in ('lancer_models','lancer_model'):
        payload={'resource':resource,'model_id':'1500'}
        r=client.post('/api/muse/query',json=payload);r.raise_for_status()
