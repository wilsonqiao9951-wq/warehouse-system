from sqlalchemy import select,func
from app.core.config import settings
from app.models import Organization,Part,Warehouse,InventoryTransaction,TransactionType
from app.services.muse_discovery import FAMILIES,model_rows


def test_manifest_guide_and_discovery_auth(client,monkeypatch):
    manifest=client.get('/api/muse').json()
    assert manifest['contract_version']=='1.5' and manifest['guide_path']=='/api/muse/guide'
    guide=client.get(manifest['guide_path']).json()
    assert guide['support_handoff']['response_trace_header']=='X-Request-ID'
    assert client.get('/api/muse/guide').headers.get('X-Request-ID')
    assert {r[:-6] for r in manifest['query_resources'] if r.endswith('_parts') and r!='model_parts'}==set(FAMILIES)
    assert guide['contract_version']==manifest['contract_version']
    assert set(guide['query_contracts'])<=set(manifest['query_resources'])
    schema=client.get('/openapi.json').json()['components']['schemas']['MuseQuery']
    assert set(guide['query_contracts'])<=set(schema['properties']['resource']['enum'])
    monkeypatch.setattr(settings,'rbac_enforce',True)
    for payload in [{'resource':'families'},{'resource':'models'},{'resource':'model','family_id':'bargun','model_id':'magnum'},{'resource':'model_parts','family_id':'bargun','model_id':'magnum'}]:
        assert client.post('/api/muse/query',json=payload).status_code==401
    assert client.get('/api/muse/guide').status_code==200


def test_discovery_pagination_search_and_ambiguous_candidates(client):
    families=client.post('/api/muse/query',json={'resource':'families'}).json()['items']
    assert {r['family_id'] for r in families}==set(FAMILIES)
    first=client.post('/api/muse/query',json={'resource':'models','limit':7}).json()
    seen=[]
    for skip in range(0,first['total'],7):
        page=client.post('/api/muse/query',json={'resource':'models','limit':7,'skip':skip}).json()
        seen.extend((r['family_id'],r['model_id']) for r in page['items'])
    assert len(seen)==len(set(seen))==len(model_rows())
    result=client.post('/api/muse/query',json={'resource':'models','q':'Viper 3'}).json()
    assert {r['family_id'] for r in result['items']}=={'viper3','cornelius'}
    assert result['selection_required'] and not result['automatic_model_selection']
    for row in result['items']:
        detail=client.post('/api/muse/query',json=row['detail_query']);detail.raise_for_status()
        assert detail.json()['selection']=={'family_id':row['family_id'],'model_id':row['model_id']}
    result=client.post('/api/muse/query',json={'resource':'models','family_id':'bargun','q':'Mark IV 10'}).json()
    assert [r['model_id'] for r in result['items']]==['mark-iv-10-button']
    assert client.post('/api/muse/query',json={'resource':'models','q':'no-such-machine'}).json()['total']==0


def test_unified_queries_preserve_every_family_contract(client):
    for family in FAMILIES:
        model=next(r for r in model_rows() if r['family_id']==family)
        for resource,suffix in [('model','model'),('model_parts','parts')]:
            args={'family_id':family,'model_id':model['model_id'],'limit':2}
            generic=client.post('/api/muse/query',json={'resource':resource,**args});generic.raise_for_status()
            legacy=client.post('/api/muse/query',json={'resource':family+'_'+suffix,'model_id':model['model_id'],'limit':2});legacy.raise_for_status()
            expected=legacy.json();expected['selection']={'family_id':family,'model_id':model['model_id']}
            assert generic.json()==expected


def test_unified_queries_reject_unknown_and_cross_model_selection(client):
    for payload in [{'resource':'model'},{'resource':'model_parts','family_id':'bargun'},{'resource':'models','family_id':'../../private'}]:
        assert client.post('/api/muse/query',json=payload).status_code==422
    for family,mid in [('bargun','viper-3'),('viper3','viper-4'),('bargun','Mark IV 10 Button')]:
        assert client.post('/api/muse/query',json={'resource':'model_parts','family_id':family,'model_id':mid}).status_code==404
    other=client.post('/api/muse/query',json={'resource':'model','family_id':'bargun','model_id':'mark-iv-12-button'}).json()
    assert client.post('/api/muse/query',json={'resource':'model_parts','family_id':'bargun','model_id':'mark-iv-10-button','section_id':other['sections'][0]['id']}).status_code==404


def test_unified_inventory_is_tenant_scoped_and_queries_do_not_write(client):
    detail=client.post('/api/muse/query',json={'resource':'model','family_id':'bargun','model_id':'magnum'}).json()
    cid=detail['part_ids'][0]
    local=client.post('/api/catalog/parts/'+cid+'/import').json()
    with client.app.state.testing_session_local() as db:
        db.add(Organization(id=2,name='Foreign',slug='foreign-discovery'));db.flush()
        own=Warehouse(organization_id=1,name='Own',code='OWN');foreign=Warehouse(organization_id=2,name='Foreign',code='FOREIGN')
        part=Part(organization_id=2,part_number=local['part_number'],name='Foreign')
        db.add_all([own,foreign,part]);db.flush()
        db.add_all([InventoryTransaction(organization_id=1,part_id=local['id'],to_warehouse_id=own.id,transaction_type=TransactionType.INBOUND,quantity=3),InventoryTransaction(organization_id=2,part_id=part.id,to_warehouse_id=foreign.id,transaction_type=TransactionType.INBOUND,quantity=99)]);db.commit()
        counts=[db.scalar(select(func.count()).select_from(cls)) for cls in [Part,InventoryTransaction]]
    result=client.post('/api/muse/query',json={'resource':'model_parts','family_id':'bargun','model_id':'magnum','q':local['part_number'],'organization_id':2}).json()
    row=next(r for r in result['items'] if r['part_number']==local['part_number'])
    assert result['organization_id']==1 and row['organization_part']['stock_quantity']==3
    assert all(p['warehouse_name']=='Own' for p in row['organization_part']['positions'])
    assert not row['cross_model_compatibility_confirmed']
    with client.app.state.testing_session_local() as db:
        assert counts==[db.scalar(select(func.count()).select_from(cls)) for cls in [Part,InventoryTransaction]]
