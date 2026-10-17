"""Recheck named Viper candidates; names alone never confirm a model."""
import asyncio,json
from datetime import datetime,timezone
from hashlib import sha256
import httpx
from scripts.enrich_catalog_fields import ROOT,OUT,parse,inspect
from scripts.audit_viper_parts import canonical

async def run():
    candidates=json.loads((OUT/'viper_parts_pending.json').read_text())['name_only_viper_candidates']
    raw=json.loads((ROOT/'parts_index.json').read_text());rows=json.loads((ROOT/'data/organized/parts_catalog.json').read_text());cache=OUT/'viper3_candidate_pages';cache.mkdir(exist_ok=True);sem=asyncio.Semaphore(4)
    async with httpx.AsyncClient(timeout=20,follow_redirects=True) as client:
        async def check(candidate):
            i=candidate['source_index'];url=rows[i]['page_url'];e={'url':url,'checked_at':datetime.now(timezone.utc).isoformat()}
            async with sem:
                try:
                    response=await client.get(url);p=parse(response.text) if response.status_code==200 else {};e.update(http_status=response.status_code,source_product_id=p.get('id'))
                    result=inspect(raw[i],i,p,e)
                    if p:
                        file=cache/f'{i}.html';file.write_text(response.text);e.update(file=str(file.relative_to(OUT)),body_sha256=sha256(response.content).hexdigest())
                    refs=result.get('equipment_reference_evidence',[])
                    confirmed=[r for r in refs if canonical(r['equipment_model'])=='Viper 3 Flavor'] if result['status']=='confirmed' else []
                    # inspect does not emit model evidence when the raw field was already populated.
                    if result['status']=='confirmed' and not refs:
                        for group in p.get('propertySets',[]):
                            if group.get('label')=='Parts Manuals Referencing This Part':
                                for ref in group.get('references') or []:
                                    if canonical(ref.get('id','').split('|')[0])=='Viper 3 Flavor':confirmed.append({'source_reference_id':ref['id'],'equipment_model':'Viper 3 Flavor'})
                    return {'source_index':i,'part_number':raw[i]['part_number'],'identity_status':result['status'],'viper3_status':'confirmed' if confirmed else 'pending','viper3_references':confirmed,'evidence':e,'reason':'Explicit official Viper 3 manual reference' if confirmed else 'No explicit verified Viper 3 manual reference; name is not compatibility evidence'}
                except httpx.HTTPError as exc:return {'source_index':i,'part_number':raw[i]['part_number'],'viper3_status':'pending','evidence':e,'reason':type(exc).__name__}
        results=await asyncio.gather(*(check(c) for c in candidates))
    (OUT/'viper3_candidate_review.json').write_text(json.dumps(results,ensure_ascii=False,indent=2));print({'checked':len(results),'viper3_confirmed':sum(r['viper3_status']=='confirmed' for r in results)})
if __name__=='__main__':asyncio.run(run())
