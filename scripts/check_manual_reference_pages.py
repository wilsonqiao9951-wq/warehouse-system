"""Verify official equipment pages referenced by the collected manual index."""
import asyncio,json
from datetime import datetime,timezone
from hashlib import sha256
from urllib.parse import urlsplit,unquote
import httpx
from scripts.enrich_catalog_fields import ROOT,OUT,parse

async def run():
    rows=json.loads((ROOT/'data/organized/manuals_catalog.json').read_text())
    urls=sorted({url for r in rows for url in (r.get('equipment_page_urls') or [r.get('page_url')]) if url and urlsplit(url).netloc=='sites.salsify.com'})
    cache=OUT/'manual_reference_pages';cache.mkdir(exist_ok=True);sem=asyncio.Semaphore(4)
    async with httpx.AsyncClient(timeout=20,follow_redirects=True) as client:
        async def check(url):
            file=cache/(sha256(url.encode()).hexdigest()+'.html');e={'url':url,'checked_at':datetime.now(timezone.utc).isoformat()}
            async with sem:
                try:
                    response=await client.get(url);p=parse(response.text) if response.status_code==200 else {}
                    e.update(http_status=response.status_code,final_url=str(response.url),source_product_id=p.get('id'))
                    slug=unquote(urlsplit(str(response.url)).path.rstrip('/').split('/')[-1]);types=[v for prop in p.get('filterProperties',[]) if prop and prop.get('property')=='catalog_type_filter' for v in prop.get('values',[])]
                    fields={prop['property']:prop['values'] for g in p.get('propertySets',[]) for prop in g.get('properties',[])}
                    is_section='|' in str(p.get('id') or '') and bool(fields.get('equipment_category'))
                    if p and slug==p.get('slugifiedId') and (types==['Parts Manuals'] or is_section):
                        file.write_text(response.text);e.update(status='confirmed',classification='manual_section' if is_section else 'equipment',file=str(file.relative_to(OUT)),body_sha256=sha256(response.content).hexdigest())
                    else:e['status']='unresolved'
                except httpx.HTTPError as exc:e.update(status='unresolved',error=type(exc).__name__)
                return e
        results=await asyncio.gather(*(check(url) for url in urls))
    (OUT/'manual_reference_checks.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    print(json.dumps({'checked':len(results),'confirmed':sum(e['status']=='confirmed' for e in results)}))

if __name__=='__main__':asyncio.run(run())
