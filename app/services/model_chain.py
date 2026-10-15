"""Viper 3 pilot: source-separated associations and tenant-scoped inventory."""
from collections import defaultdict
from functools import lru_cache
import json
import re
from sqlalchemy import select
from app.models import Part,PartMachineAssociation,InventoryTransaction,Warehouse,StorageLocation,WorkOrder,WorkOrderPart,Equipment
from app.services.catalog import DATA_ROOT,entries

MODEL='Viper 3 Flavor'
def is_viper3(value):
    return re.sub(r'[\s-]+','',value or '').casefold() in {'viper3','viper3flavor'}

@lru_cache(maxsize=1)
def graph():
    return json.loads((DATA_ROOT/'data/organized/viper3_graph.json').read_text())

def inventory(db,org,part_ids):
    balances=defaultdict(int)
    if not part_ids:return {}
    for tx in db.scalars(select(InventoryTransaction).where(InventoryTransaction.organization_id==org,InventoryTransaction.part_id.in_(part_ids))):
        if tx.to_warehouse_id:balances[(tx.part_id,tx.to_warehouse_id,tx.to_location_id)]+=tx.quantity
        if tx.from_warehouse_id:balances[(tx.part_id,tx.from_warehouse_id,tx.from_location_id)]-=tx.quantity
    warehouses={w.id:w for w in db.scalars(select(Warehouse).where(Warehouse.organization_id==org))}
    locations={l.id:l for l in db.scalars(select(StorageLocation).where(StorageLocation.organization_id==org))}
    result=defaultdict(list)
    for (pid,wid,lid),quantity in balances.items():
        if wid not in warehouses or (lid and (lid not in locations or locations[lid].warehouse_id!=wid)):continue
        result[pid].append({'warehouse_id':wid,'warehouse_name':warehouses[wid].name,'location_id':lid,'location_code':locations[lid].code if lid else None,'quantity':quantity})
    return result

def work_order_usage(db,org,matches_model=is_viper3):
    """Reported material use, never an inferred compatibility confirmation."""
    equipment={e.id:e for e in db.scalars(select(Equipment).where(Equipment.organization_id==org))}
    orders={}
    for order in db.scalars(select(WorkOrder).where(WorkOrder.organization_id==org)):
        asset=equipment.get(order.equipment_id) if order.equipment_id else None
        if order.equipment_id and asset is None:continue
        models=[value for value in (order.machine_type,asset.model if asset else None) if value and value.strip()]
        # Both explicit models must agree. Missing/unknown/conflicting identities fail closed.
        if not models or not all(matches_model(model) for model in models):continue
        orders[order.id]=(order,asset)
    result=defaultdict(list)
    if not orders:return result
    local_ids=set(db.scalars(select(Part.id).where(Part.organization_id==org)))
    warehouse_ids=set(db.scalars(select(Warehouse.id).where(Warehouse.organization_id==org)))
    query=select(WorkOrderPart).where(WorkOrderPart.organization_id==org,WorkOrderPart.work_order_id.in_(orders)).order_by(WorkOrderPart.created_at.desc(),WorkOrderPart.id.desc())
    for usage in db.scalars(query):
        if usage.part_id not in local_ids or usage.warehouse_id not in warehouse_ids:continue
        order,asset=orders[usage.work_order_id]
        actual=usage.installed=='yes' and usage.quantity>0
        result[usage.part_id].append({'source':'actual_usage' if actual else 'work_order_material','usage_id':usage.id,'work_order_id':order.id,'ticket_number':order.ticket_number,'work_order_status':order.status,'equipment_id':order.equipment_id,'work_order_model':order.machine_type,'equipment_model':asset.model if asset else None,'quantity':usage.quantity,'installed':usage.installed,'warehouse_id':usage.warehouse_id,'recorded_at':usage.created_at,'is_actual_usage':actual,'compatibility_confirmed':False})
    return result

def usage_summary(records):
    actual=[r for r in records if r['is_actual_usage']]
    return {'material_record_count':len(records),'actual_usage_count':len(actual),'actual_used_quantity':sum(r['quantity'] for r in actual),'actual_work_order_count':len({r['work_order_id'] for r in actual}),'last_actual_usage_at':actual[0]['recorded_at'] if actual else None,'records':records[:20],'records_limit':20,'compatibility_confirmed':False}

def chain(db,org,section_id=None,q='',skip=0,limit=25):
    g=graph();sections=[s for s in g['sections'] if section_id is None or s['id']==section_id]
    edges=defaultdict(list)
    for s in sections:
        for cid in s['part_ids']:edges[cid].append({'source':'official','section_id':s['id'],'evidence':s['evidence']})
    catalog={r['catalog_id']:r for r in entries('parts')}
    local=list(db.scalars(select(Part).where(Part.organization_id==org)))
    by_number={p.part_number:p for p in local}
    observations=defaultdict(list)
    for a in db.scalars(select(PartMachineAssociation).where(PartMachineAssociation.organization_id==org)):
        if is_viper3(a.machine_model):observations[a.part_id].append({'source':'field_verified' if a.recognition_source=='field_verified' else 'field_observation','association_id':a.id,'confirmed_count':a.confirmed_count,'last_confirmed_at':a.last_confirmed_at,'photo_url':a.photo_url})
    usages=work_order_usage(db,org)
    stock=inventory(db,org,[p.id for p in local]);items=[];used=set()
    def local_data(p):
        positions=stock.get(p.id,[])
        return {'part_id':p.id,'part_number':p.part_number,'name':p.name,'is_active':p.is_active,'stock_quantity':sum(x['quantity'] for x in positions),'positions':positions}
    for cid,official in edges.items():
        row=catalog.get(cid)
        if not row:continue
        p=by_number.get(row['part_number'])
        if p:used.add(p.id)
        items.append({'catalog_id':cid,'part_number':row['part_number'],'name':row['name'],'image_url':row.get('image_url'),'page_url':row.get('page_url'),'official_associations':official,'field_associations':observations.get(p.id,[]) if p else [],'work_order_usage':usage_summary(usages.get(p.id,[]) if p else []),'organization_part':local_data(p) if p else None})
    if section_id is None:
        for p in local:
            if p.id in used or not (observations.get(p.id) or usages.get(p.id)):continue
            items.append({'catalog_id':None,'part_number':p.part_number,'name':p.name,'image_url':p.image_url,'page_url':None,'official_associations':[],'field_associations':observations[p.id],'work_order_usage':usage_summary(usages.get(p.id,[])),'organization_part':local_data(p)})
    terms=q.casefold().split();items=[r for r in items if all(t in (r['part_number']+' '+r['name']).casefold() for t in terms)]
    items.sort(key=lambda r:r['part_number'])
    return {'model_id':'viper-3','official_model':MODEL,'organization_id':org,'total':len(items),'skip':skip,'limit':limit,'items':items[skip:skip+limit],'compatibility_note':'Official manual association and field verification are separate evidence; neither implies compatibility with Viper 2 or Viper 4.'}
