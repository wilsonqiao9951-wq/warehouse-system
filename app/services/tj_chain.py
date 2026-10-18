"""Official TJ associations with tenant-scoped inventory, without fitment inference."""
import json
from functools import lru_cache
from sqlalchemy import select
from app.models import Part
from app.services.catalog import DATA_ROOT,entries
from app.services.model_chain import inventory

@lru_cache(maxsize=1)
def graph():
    return json.loads((DATA_ROOT/'data/organized/tj_graph.json').read_text())

@lru_cache(maxsize=1)
def associations():
    return {r['part_number']:r['official_associations'] for r in json.loads((DATA_ROOT/'data/organized/tj_parts_catalog.json').read_text())['parts']}


def parts(db,org,model_id,section_id=None,q='',skip=0,limit=25):
    model=graph()['models'][model_id]
    section=next((s for s in model['sections'] if s['id']==section_id),None)
    ids=set(section['part_ids'] if section else model['part_ids'])
    terms=q.casefold().split()
    rows=sorted([r for r in entries('parts') if r['catalog_id'] in ids and all(t in (r['part_number']+' '+r['name']).casefold() for t in terms)],key=lambda r:r['part_number'])
    total=len(rows);rows=rows[skip:skip+limit]
    local={p.part_number:p for p in db.scalars(select(Part).where(Part.organization_id==org,Part.part_number.in_([r['part_number'] for r in rows])))}
    stocks=inventory(db,org,[p.id for p in local.values()]);items=[]
    for r in rows:
        p=local.get(r['part_number']);positions=stocks.get(p.id,[]) if p else []
        items.append({**{k:r.get(k) for k in ['catalog_id','part_number','name','description','page_url','image_url','manufacturer','manufacturer_part','cona_material_number']},'official_associations':[a for a in associations()[r['part_number']] if a['model']==model['official_model'] and (section_id is None or a['section_id']==section_id)],'organization_part':{'part_id':p.id,'stock_quantity':sum(x['quantity'] for x in positions),'positions':positions} if p else None,'cross_model_compatibility_confirmed':False})
    return {'model_id':model_id,'official_model':model['official_model'],'organization_id':org,'total':total,'skip':skip,'limit':limit,'items':items,'policy':graph()['policy']}
