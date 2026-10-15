"""Read-only official model chains and organization-specific inventory."""
import json
import re
from collections import defaultdict
from functools import lru_cache
from sqlalchemy import select
from app.models import Part,PartMachineAssociation
from app.services.catalog import DATA_ROOT,entries
from app.services.model_chain import inventory,work_order_usage,usage_summary

@lru_cache(maxsize=1)
def graph():
    return json.loads((DATA_ROOT/'data/organized/freestyle_graph.json').read_text())

@lru_cache(maxsize=1)
def associations():
    data=json.loads((DATA_ROOT/'data/organized/freestyle_parts_catalog.json').read_text())
    return {r['part_number']:r['official_associations'] for r in data['parts']}

def matches_model(value,model_id):
    normalize=lambda v:re.sub(r'[\s-]+','',str(v or '')).casefold()
    model=graph()['models'][model_id]
    return normalize(value) in {normalize(model['official_model']),model_id,'freestyle'+model_id}


def model_usage(db,org,model_id):
    return work_order_usage(db,org,lambda value:matches_model(value,model_id))


def parts(db,org,model_id,section_id=None,q='',skip=0,limit=25):
    model=graph()['models'][model_id]
    section=next((s for s in model['sections'] if s['id']==section_id),None)
    ids=set(section['part_ids'] if section is not None else model['part_ids'])
    local=list(db.scalars(select(Part).where(Part.organization_id==org)))
    by_number={p.part_number:p for p in local}
    observations=defaultdict(list)
    for a in db.scalars(select(PartMachineAssociation).where(PartMachineAssociation.organization_id==org)):
        if matches_model(a.machine_model,model_id):observations[a.part_id].append({'source':'field_verified' if a.recognition_source=='field_verified' else 'field_observation','association_id':a.id,'confirmed_count':a.confirmed_count,'last_confirmed_at':a.last_confirmed_at,'photo_url':a.photo_url})
    usages=model_usage(db,org,model_id)
    rows=[r for r in entries('parts') if r['catalog_id'] in ids]
    used={r['part_number'] for r in rows}
    if section_id is None:
        rows.extend({'catalog_id':None,'part_number':p.part_number,'name':p.name,'image_url':p.image_url,'page_url':None} for p in local if p.part_number not in used and (observations.get(p.id) or usages.get(p.id)))
    terms=q.casefold().split();rows=[r for r in rows if all(t in (r['part_number']+' '+r['name']).casefold() for t in terms)]
    rows.sort(key=lambda r:r['part_number']);total=len(rows);rows=rows[skip:skip+limit]
    stock=inventory(db,org,[by_number[r['part_number']].id for r in rows if r['part_number'] in by_number]);items=[]
    for row in rows:
        p=by_number.get(row['part_number']);positions=stock.get(p.id,[]) if p else []
        official=[a for a in associations().get(row['part_number'],[]) if a['model']==model['official_model'] and (section_id is None or a.get('section_id')==section_id)] if row['catalog_id'] in ids else []
        items.append({'catalog_id':row['catalog_id'],'part_number':row['part_number'],'name':row['name'],'page_url':row.get('page_url'),'image_url':row.get('image_url'),'official_associations':official,'field_associations':observations.get(p.id,[]) if p else [],'work_order_usage':usage_summary(usages.get(p.id,[]) if p else []),'cross_model_compatibility_confirmed':False,'organization_part':{'part_id':p.id,'stock_quantity':sum(r['quantity'] for r in positions),'positions':positions} if p else None})
    return {'model_id':model_id,'official_model':model['official_model'],'organization_id':org,'total':total,'skip':skip,'limit':limit,'items':items,'policy':'Official associations, field observations/verification and reported work-order use are independent evidence; no cross-model compatibility is inferred.'}
