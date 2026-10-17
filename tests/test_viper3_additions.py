import json
from app.services.catalog import entries,DATA_ROOT
from app.services.model_chain import graph


def test_all_seventeen_additions_are_unique_importable_and_in_viper3_sections(client):
    additions=json.loads((DATA_ROOT/'data/organized/viper3_added_parts.json').read_text())
    assert len(additions)==17
    catalog=list(entries('parts'));ids={r['catalog_id'] for r in catalog};numbers=[r['part_number'] for r in catalog]
    graph_ids={cid for s in graph()['sections'] for cid in s['part_ids']}
    for row in additions:
        cid=row['catalog_id'];assert cid in ids and cid in graph_ids
        assert numbers.count(row['part_number'])==1
        response=client.get('/api/catalog/models/viper-3/parts',params={'q':row['part_number']})
        assert response.status_code==200
        served=next(r for r in response.json()['items'] if r['catalog_id']==cid)
        assert all(a['section_id'].startswith('Viper 3 Flavor|') for a in served['official_associations'])
        assert served['field_associations']==[] and served['work_order_usage']['actual_usage_count']==0
        first=client.post(f'/api/catalog/parts/{cid}/import');second=client.post(f'/api/catalog/parts/{cid}/import')
        assert first.status_code==200 and second.json()['id']==first.json()['id']
        joined=client.get('/api/catalog/models/viper-3/parts',params={'q':row['part_number']}).json()['items'][0]
        assert joined['organization_part']['part_id']==first.json()['id']
        assert joined['organization_part']['stock_quantity']==0
    assert not any(r['part_number']=='3506751' and r['catalog_id'].startswith('official-viper3-') for r in catalog)
