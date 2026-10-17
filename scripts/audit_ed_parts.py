"""Fresh, source-preserving ED audit. Does not modify main catalog or inventory."""
import asyncio,json
from collections import defaultdict,Counter
from datetime import datetime,timezone
from hashlib import sha256
from urllib.parse import unquote
import httpx
from scripts.enrich_catalog_fields import ROOT,OUT,parse
from scripts.enrich_reverse_manual_refs import part_links
from app.services.catalog import entries
MODELS=('ED 150','ED 200/250','ED 300')
MODEL_IDS=dict(zip(MODELS,('150','200-250','300')))
DEST=OUT/'ed_20261016'

async def run():
    DEST.mkdir(exist_ok=True);(DEST/'pages').mkdir(exist_ok=True)
    prior=json.loads((OUT/'manual_reference_checks.json').read_text())
    seeds={e['url']:e['source_product_id'] for e in prior if e.get('status')=='confirmed' and (e.get('source_product_id') or '').split('|')[0] in MODELS}
    main={r['part_number']:r for r in entries('parts')};sem=asyncio.Semaphore(4)
    async with httpx.AsyncClient(timeout=25,follow_redirects=True) as client:
        async def fetch(url):
            evidence={'url':url,'checked_at':datetime.now(timezone.utc).isoformat()}
            async with sem:
                try:
                    r=await client.get(url);file='pages/'+sha256(url.encode()).hexdigest()+'.html';(DEST/file).write_bytes(r.content)
                    p=parse(r.text) if r.status_code==200 else {}
                    evidence.update(http_status=r.status_code,final_url=str(r.url),source_product_id=p.get('id'),file=file,body_sha256=sha256(r.content).hexdigest())
                    return p,evidence
                except (httpx.HTTPError,ValueError) as exc:evidence['error']=type(exc).__name__;return {},evidence
        manuals=await asyncio.gather(*(fetch(url) for url in seeds))
        sections={m:set() for m in MODELS};relations=defaultdict(list);pending_manuals=[];manual_checks=[]
        for (url,expected),(p,e) in zip(seeds.items(),manuals):
            e['expected_id']=expected;e['identity_confirmed']=p.get('id')==expected;manual_checks.append(e)
            if not e['identity_confirmed']:pending_manuals.append(e);continue
            resources=[{'id':p['id'],'properties':[v for g in p.get('propertySets',[]) for v in g.get('properties',[])]}]
            resources.extend(r for g in p.get('propertySets',[]) if g.get('referenceProperty')=='parts_manual_section_reference' for r in g.get('references',[]) or [])
            for resource in resources:
                sid=resource.get('id','');model=sid.split('|')[0]
                if model not in MODELS:continue
                if '|' in sid:sections[model].add(sid)
                for link in part_links([resource]):
                    ref={'model':model,'section_id':sid if '|' in sid else None,'part_url':link,'manual_evidence':e}
                    if ref not in relations[link]:relations[link].append(ref)
        fetched=await asyncio.gather(*(fetch(url) for url in relations))
        parts={};pending=[]
        for (url,refs),(p,e) in zip(relations.items(),fetched):
            expected=unquote(url.rstrip('/').split('/')[-1]);types=[v for f in p.get('filterProperties',[]) if f and f.get('property')=='catalog_type_filter' for v in f.get('values',[])]
            e['identity_confirmed']=p.get('id')==expected and types==['Parts Catalog']
            if not e['identity_confirmed']:pending.append({'evidence':e,'associations':refs,'reason':'Exact product ID and Parts Catalog type not confirmed'});continue
            number=p['id'];fields={v['property']:v['values'] for g in p.get('propertySets',[]) for v in g.get('properties',[])}
            one=lambda key:next(iter(fields.get(key) or []),None)
            local=main.get(number)
            row=parts.setdefault(number,{'part_number':number,'catalog_id':local['catalog_id'] if local else None,'main_catalog_indexed':bool(local),'name':p.get('listSubtitle') or one('material_long_description'),'description':one('material_long_description') or p.get('listSubtitle'),'manufacturer':one('manufacturer_name_display'),'manufacturer_part':one('manufacturer_part_display'),'cona_material_number':one('cona_material_number'),'image_url':None,'page_url':url,'models':[],'official_associations':[],'fresh_evidence':e,'source_status':'confirmed','compatibility_confirmed':False,'policy':'Official chapter association only; no inferred fitment or inventory changes.'})
            row['official_associations'].extend(refs);row['models']=sorted({r['model'] for r in row['official_associations']})
            image=p.get('listImage')
            if image and image.startswith('https://images.salsify.com/'):
                try:
                    head=await client.head(image);row['image_check']={'url':image,'http_status':head.status_code,'content_type':head.headers.get('content-type','')}
                    if head.status_code==200 and head.headers.get('content-type','').startswith('image/'):row['image_url']=image
                except httpx.HTTPError as exc:row['image_check']={'url':image,'error':type(exc).__name__}
            row['missing_fields']=[k for k in ['name','description','manufacturer','manufacturer_part','cona_material_number','image_url'] if not row.get(k)]
    rows=sorted(parts.values(),key=lambda r:r['part_number'])
    summary={'checked_at':datetime.now(timezone.utc).isoformat(),'unique_parts':len(rows),'per_model':{m:{'parts':sum(m in r['models'] for r in rows),'sections':len(sections[m])} for m in MODELS},'shared_parts':sum(len(r['models'])>1 for r in rows),'main_catalog_indexed':sum(r['main_catalog_indexed'] for r in rows),'new_confirmed_parts':sum(not r['main_catalog_indexed'] for r in rows),'missing_fields':dict(Counter(k for r in rows for k in r['missing_fields'])),'manual_urls_checked':len(manuals),'pending_manual_urls':len(pending_manuals),'part_urls_checked':len(fetched),'pending_part_urls':len(pending)}
    target=ROOT/'data/organized/ed';target.mkdir(exist_ok=True)
    (ROOT/'data/organized/ed_parts_catalog.json').write_text(json.dumps({'summary':summary,'parts':rows},ensure_ascii=False,indent=2))
    for model in MODELS:
        selected=[{**r,'official_associations':[a for a in r['official_associations'] if a['model']==model]} for r in rows if model in r['models']]
        (target/(MODEL_IDS[model]+'.json')).write_text(json.dumps({'model':model,'sections':sorted(sections[model]),'parts':selected},ensure_ascii=False,indent=2))
    (DEST/'manual_checks.json').write_text(json.dumps(manual_checks,ensure_ascii=False,indent=2))
    (DEST/'pending.json').write_text(json.dumps({'manuals':pending_manuals,'part_links':pending,'new_parts_pending_main_catalog':[r['part_number'] for r in rows if not r['main_catalog_indexed']],'policy':'Retain unresolved records without inferred identity or compatibility.'},ensure_ascii=False,indent=2))
    (DEST/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':asyncio.run(run())
