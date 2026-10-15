"""Recover broken images from identity-matched source product pages."""
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import httpx
from scripts.audit_catalog import ROOT, identifier, valid_url

OUT = ROOT / 'data/verification'

async def run():
    rows=json.loads((ROOT/'parts_index.json').read_text())
    prior=json.loads((OUT/'decisions.json').read_text())
    targets=[d['source_index'] for d in prior if d['status']=='unresolved' and d['evidence'].get('url')]
    results=[]
    sem=asyncio.Semaphore(4)
    async with httpx.AsyncClient(timeout=15,follow_redirects=True) as client:
        async def check(index):
            row=rows[index]; url=row.get('page_url'); result={'source_index':index,'source_sha256':sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),'checked_at':datetime.now(timezone.utc).isoformat(),'url':url,'status':'unresolved','patch':{}}
            if not valid_url(url):return result
            async with sem:
                try:
                    response=await client.get(url)
                    result['http_status']=response.status_code
                    match=re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',response.text)
                    product=json.loads(match.group(1))['props']['pageProps'].get('product',{}) if match else {}
                    result['source_product_id']=product.get('id')
                    if response.status_code!=200 or identifier(product.get('id'))!=identifier(row['part_number']):
                        result['reason']='Source product identity not confirmed';return result
                    (OUT/f'image_source_{index}.html').write_text(response.text)
                    candidates=list(dict.fromkeys([product.get('listImage')]+[i.get('value') for i in product.get('images',[])]))
                    result['candidates']=[]
                    for candidate in candidates:
                        if not valid_url(candidate):continue
                        head=await client.head(candidate)
                        evidence={'url':candidate,'http_status':head.status_code,'content_type':head.headers.get('content-type','')}
                        result['candidates'].append(evidence)
                        if head.status_code==200 and evidence['content_type'].startswith('image/'):
                            result.update(status='corrected',patch={'image_url':candidate},reason='Source product ID matched and source-provided image HEAD validated');break
                    if result['status']=='unresolved':result['reason']='No usable image on matched source product'
                except Exception as exc:result['reason']=type(exc).__name__+': '+str(exc)
            return result
        results=await asyncio.gather(*(check(index) for index in targets))
        # Official CCP document endpoint, supplied in the user-provided handover.
        url='https://www.coca-colaparts.com/item-details/?op=pdf&item=146652'
        try:
            response=await client.get(url)
            ccp={'url':url,'http_status':response.status_code,'final_url':str(response.url),'content_type':response.headers.get('content-type',''),'checked_at':datetime.now(timezone.utc).isoformat()}
            if 'html' in ccp['content_type']:
                (OUT/'ccp_146652.html').write_text(response.text)
                ccp['excerpt']=re.sub('<[^>]+>',' ',response.text)[:1200]
            elif 'pdf' in ccp['content_type']:
                (OUT/'ccp_146652.pdf').write_bytes(response.content)
        except Exception as exc:ccp={'url':url,'error':type(exc).__name__+': '+str(exc)}
    (OUT/'image_recovery.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    (OUT/'ccp_identity_check.json').write_text(json.dumps(ccp,ensure_ascii=False,indent=2))
    from collections import Counter
    print('images',dict(Counter(r['status'] for r in results)));print('CCP',json.dumps(ccp,ensure_ascii=False)[:1700])

if __name__=='__main__':asyncio.run(run())
