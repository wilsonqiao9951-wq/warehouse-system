"""Verify proposed path/domain repairs before applying them to unresolved records."""
import asyncio
from datetime import datetime,timezone
from hashlib import sha256
import json
import httpx
from scripts.enrich_catalog_fields import ROOT,OUT,parse,inspect

async def run():
    path=OUT/'field_enrichment.json';decisions=json.loads(path.read_text())
    raw=json.loads((ROOT/'parts_index.json').read_text());reviewed=[]
    cache=OUT/'source_repair_pages';cache.mkdir(exist_ok=True)
    async with httpx.AsyncClient(timeout=20,follow_redirects=True) as client:
        for old in decisions:
            if old['status']!='unresolved':continue
            i=old['source_index'];original=raw[i]['page_url']
            url=original.replace('images.salsify.com','sites.salsify.com').replace('|','or')
            evidence={'url':url,'original_url':original,'checked_at':datetime.now(timezone.utc).isoformat()}
            try:
                response=await client.get(url);evidence.update(http_status=response.status_code,final_url=str(response.url))
                p=parse(response.text) if response.status_code==200 else {}
                if p:
                    (cache/f'{i}.html').write_text(response.text)
                    evidence.update(file=f'source_repair_pages/{i}.html',body_sha256=sha256(response.content).hexdigest(),source_product_id=p.get('id'))
                result=inspect(raw[i],i,p,evidence)
                if result['status']=='confirmed':result['patch']['page_url']=str(response.url)
            except Exception as exc:
                result=inspect(raw[i],i,{},evidence);result['reason']=type(exc).__name__+': '+str(exc)
            reviewed.append(result)
    confirmed={r['source_index']:r for r in reviewed if r['status']=='confirmed'}
    if reviewed:
        path.write_text(json.dumps([confirmed.get(d['source_index'],d) for d in decisions],ensure_ascii=False,indent=2))
        (OUT/'source_review_round5.json').write_text(json.dumps(reviewed,ensure_ascii=False,indent=2))
    print(json.dumps({'checked':len(reviewed),'confirmed':len(confirmed),'pending':len(reviewed)-len(confirmed)},ensure_ascii=False))

if __name__=='__main__':asyncio.run(run())
