"""Source-backed Freestyle family part audit; preserve model-specific official evidence."""
import asyncio,json
from collections import Counter,defaultdict
from datetime import datetime,timezone
from hashlib import sha256
import re
import httpx
from scripts.enrich_catalog_fields import ROOT,OUT,parse,inspect
from scripts.enrich_reverse_manual_refs import key,part_links

MODELS=('3100 Counter Electric','4000 Flex Countertop','7000 Ice Combo','7100 Ice Combo','8000 Crew-Serve','8100 Crew-Serve','9000 Self-Serve','9100 Self-Serve')
def canonical(value):
    norm=lambda s:re.sub(r'[^a-z0-9]','',str(s).lower())
    return next((m for m in MODELS if norm(m)==norm(value)),None)

async def run():
    rows=json.loads((ROOT/'data/organized/parts_catalog.json').read_text());raw=json.loads((ROOT/'parts_index.json').read_text())
    by_url={key(r['page_url']):r for r in rows if r.get('page_url') and r['_organization']['classification']=='part_candidate'}
    decisions=json.loads((OUT/'field_enrichment.json').read_text());by_index={d['source_index']:d for d in decisions}
    checks=json.loads((OUT/'manual_reference_checks.json').read_text());relations=defaultdict(list);sections=defaultdict(set);unmatched=[]
    for e in checks:
        if e['status']!='confirmed':continue
        model=canonical(e['source_product_id'].split('|')[0])
        if not model:continue
        file=OUT/e['file']
        if sha256(file.read_bytes()).hexdigest()!=e['body_sha256']:raise ValueError('Source snapshot hash mismatch')
        p=parse(file.read_text());resources=[{'id':p['id'],'properties':[prop for g in p.get('propertySets',[]) for prop in g.get('properties',[])]}]
        for g in p.get('propertySets',[]):
            if g.get('referenceProperty')=='parts_manual_section_reference':resources.extend(g.get('references') or [])
        for resource in resources:
            sid=resource['id']
            if canonical(sid.split('|')[0])!=model:continue
            if '|' in sid:sections[model].add(sid)
            for url in part_links([resource]):
                row=by_url.get(key(url))
                ref={'model':model,'section_id':sid if '|' in sid else None,'part_url':url,'manual_evidence':e}
                if not row:unmatched.append(ref);continue
                i=row['_organization']['source_index']
                if ref not in relations[i]:relations[i].append(ref)
    for r in rows:
        if r['_organization']['classification']!='part_candidate':continue
        d=by_index.get(r['_organization']['source_index'])
        if not d or d['status']!='confirmed':continue
        for ref in d.get('equipment_reference_evidence',[]):
            model=canonical(ref['equipment_model'])
            if model:relations[d['source_index']].append({'model':model,'section_id':ref['source_reference_id'],'part_evidence':d['evidence']})
    cache=OUT/'freestyle_part_pages';cache.mkdir(exist_ok=True);sem=asyncio.Semaphore(4)
    async with httpx.AsyncClient(timeout=20,follow_redirects=True) as client:
        async def audit(index):
            r=rows[index];e={'url':r['page_url'],'checked_at':datetime.now(timezone.utc).isoformat()};status='unresolved';image=None
            async with sem:
                try:
                    response=await client.get(r['page_url']);p=parse(response.text) if response.status_code==200 else {}
                    e.update(http_status=response.status_code,final_url=str(response.url),source_product_id=p.get('id'))
                    status=inspect(raw[index],index,p,e)['status']
                    if status=='confirmed':
                        file=cache/f'{index}.html';file.write_text(response.text);e.update(file=str(file.relative_to(OUT)),body_sha256=sha256(response.content).hexdigest())
                    if r.get('image_url'):
                        head=await client.head(r['image_url']);image={'url':r['image_url'],'http_status':head.status_code,'content_type':head.headers.get('content-type',''),'valid':head.status_code==200 and head.headers.get('content-type','').startswith('image/')}
                except httpx.HTTPError as exc:e['error']=type(exc).__name__
            cid=f"{index}-{r['_organization']['content_id'][:16]}"
            models=sorted({v['model'] for v in relations[index]})
            return {'catalog_id':cid,'source_index':index,'part_number':r['part_number'],'name':r['name'],'description':r.get('description'),'image_url':r.get('image_url'),'page_url':r.get('page_url'),'manufacturer':r.get('manufacturer'),'manufacturer_part':r.get('manufacturer_part'),'cona_material_number':r.get('cona_material_number'),'models':models,'shared_across_official_models':len(models)>1,'official_associations':relations[index],'source_status':status,'fresh_evidence':e,'image_check':image,'missing_fields':[k for k in ('description','image_url','manufacturer','manufacturer_part','cona_material_number') if not r.get(k)],'compatibility_policy':'Official catalog association only; no automatic field verification or cross-model compatibility inference'}
        parts=await asyncio.gather(*(audit(i) for i in sorted(relations)))
    summary={'unique_parts':len(parts),'per_model':{m:{'parts':sum(m in p['models'] for p in parts),'sections':len(sections[m])} for m in MODELS},'source_status':dict(Counter(p['source_status'] for p in parts)),'shared_parts':sum(p['shared_across_official_models'] for p in parts),'missing_fields':dict(Counter(k for p in parts for k in p['missing_fields'])),'image_checks':dict(Counter('valid' if p['image_check']['valid'] else 'unavailable' for p in parts if p['image_check'])),'unmatched_manual_links':len({(x['model'],x['part_url']) for x in unmatched})}
    (ROOT/'data/organized/freestyle_parts_catalog.json').write_text(json.dumps({'summary':summary,'parts':parts},ensure_ascii=False,indent=2))
    (OUT/'freestyle_parts_audit_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    (OUT/'freestyle_parts_pending.json').write_text(json.dumps({'unconfirmed_parts':[p for p in parts if p['source_status']!='confirmed'],'unmatched_manual_links':unmatched,'unavailable_images':[p for p in parts if p['image_check'] and not p['image_check']['valid']]},ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':asyncio.run(run())
