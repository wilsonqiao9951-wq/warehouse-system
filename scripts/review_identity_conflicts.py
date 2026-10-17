"""Recheck only quarantined identities against fresh official page evidence."""
import asyncio
from datetime import datetime,timezone
from hashlib import sha256
import json
import httpx
from scripts.enrich_catalog_fields import ROOT,OUT,parse,inspect

async def run():
    path=OUT/'field_enrichment.json'
    decisions=json.loads(path.read_text())
    raw=json.loads((ROOT/'parts_index.json').read_text())
    selected=[d for d in decisions if d['status']=='quarantined']
    cache=OUT/'identity_pages';cache.mkdir(exist_ok=True)
    semaphore=asyncio.Semaphore(4)
    async with httpx.AsyncClient(timeout=20,follow_redirects=True) as client:
        async def check(previous):
            i=previous['source_index'];url=raw[i]['page_url']
            evidence={'url':url,'checked_at':datetime.now(timezone.utc).isoformat()}
            async with semaphore:
                try:
                    response=await client.get(url)
                    evidence.update(http_status=response.status_code,final_url=str(response.url))
                    product=parse(response.text) if response.status_code==200 else {}
                    if product:
                        saved=cache/f'{i}.html';saved.write_text(response.text)
                        evidence.update(file=f'identity_pages/{i}.html',source_product_id=product.get('id'),body_sha256=sha256(response.content).hexdigest())
                    result=inspect(raw[i],i,product,evidence)
                    fields={p['property']:p['values'] for g in product.get('propertySets',[]) for p in g.get('properties',[])}
                    result['identity_fields']={'material_number':fields.get('material_number',[]),'legacy_material_number':fields.get('legacy_material_number',[]),'original_name':raw[i].get('name')}
                    if result['status']=='confirmed':result['patch']['page_url']=str(response.url)
                    return result
                except Exception as exc:
                    result=inspect(raw[i],i,{},evidence);result['reason']=type(exc).__name__+': '+str(exc);return result
        reviewed=await asyncio.gather(*(check(d) for d in selected))
    updated={d['source_index']:d for d in reviewed if d['status']=='confirmed'}
    path.write_text(json.dumps([updated.get(d['source_index'],d) for d in decisions],ensure_ascii=False,indent=2))
    (OUT/'identity_review_round4.json').write_text(json.dumps(reviewed,ensure_ascii=False,indent=2))
    print(json.dumps({'checked':len(reviewed),'confirmed':len(updated),'retained_pending':len(reviewed)-len(updated),'model_fields_filled':sum(bool(d['patch'].get('fits_equipment_models')) for d in reviewed)},ensure_ascii=False))

if __name__=='__main__':asyncio.run(run())
