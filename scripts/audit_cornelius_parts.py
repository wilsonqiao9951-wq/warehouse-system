"""Fresh, source-preserving CORNELIUS audit. Does not modify main catalog or inventory."""
import asyncio,json
from collections import defaultdict,Counter
from datetime import datetime,timezone
from hashlib import sha256
from urllib.parse import unquote
import httpx
from scripts.enrich_catalog_fields import ROOT,OUT,parse
from scripts.enrich_reverse_manual_refs import part_links
from app.services.catalog import entries
MODEL_IDS={'2 Flavor (3H.P.) - V4': '2-flavor-3h-p-v4', '3 Valve Tower (Ceramic)': '3-valve-tower-ceramic', 'Appex 6': 'appex-6', 'Automated Beverage System (ABS 1.0)': 'automated-beverage-system-abs-1-0', 'Automated Beverage System (ABS 2.0)': 'automated-beverage-system-abs-2-0', 'CB2323 / CB1522 / CB3023 (IntelliCarb Units) Golden Corral': 'cb2323-cb1522-cb3023-golden-corral', 'CI2000 Plus': 'ci2000-plus', 'DB 150': 'db-150', 'DB 200 / 275 Standard': 'db-200-275-standard', 'DF 150': 'df-150', 'DF 200/250': 'df-200-250', 'ED 150': 'ed-150', 'ED 200/250': 'ed-200-250', 'ED 300': 'ed-300', 'IDC255 Pro Fast Gate': 'idc255-pro-fast-gate', 'TJ 150': 'tj-150', 'TJ 45 / TJ 90': 'tj-45-tj-90', 'Viper 2 Flavor': 'viper-2-flavor', 'Viper 3 Flavor': 'viper-3-flavor', 'Viper 4 Flavor': 'viper-4-flavor', 'Viper Carts': 'viper-carts', "Backroom Package (McDonald's)": 'backroom-package-mcdonald-s', 'CB1522 18in SABRE TOWER': 'cb1522-18in-sabre-tower', 'CB1522D': 'cb1522d', 'CB2323 SABRE 23in TOWER W/CDD': 'cb2323-sabre-23in-tower-w-cdd', "CB2323-8vlv (Wendy's)": 'cb2323-8vlv-wendy-s', 'CB2323L SELF CLOSING LID': 'cb2323l-self-closing-lid', 'CB2323L SLIDING LID': 'cb2323l-sliding-lid', 'CC2323 TOWER W/ SLIDING LID': 'cc2323-tower-w-sliding-lid', 'CC2323L SELF CLOSING LID': 'cc2323l-self-closing-lid', 'CI2000 (Plus)': 'ci2000-plus-parenthesized', 'DB 275 - BCP Pneumatic Ice Gate': 'db-275-bcp-pneumatic-ice-gate', 'Energize 6': 'energize-6', 'Leopard': 'leopard', 'Prism': 'prism', 'Quest 2000': 'quest-2000', 'Quest 4000': 'quest-4000', 'SFV - 1': 'sfv-1'}
ROOT_URLS={'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/2-Flavor-(3H-P-)-V4/2-Flavor-(3H-P-)-V4/': '2 Flavor (3H.P.) - V4', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/3-Valve-Tower-(Ceramic)/3-Valve-Tower-(Ceramic)/': '3 Valve Tower (Ceramic)', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Appex-6/Appex-6/': 'Appex 6', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Automated-Beverage-System-(ABS-1-0)/Automated-Beverage-System-(ABS-1-0)/': 'Automated Beverage System (ABS 1.0)', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Automated-Beverage-System-(ABS-2-0)/Automated-Beverage-System-(ABS-2-0)/': 'Automated Beverage System (ABS 2.0)', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/CB2323-CB1522-CB3023-(IntelliCarb-Units)-Golden-Corral/CB2323-CB1522-CB3023-(IntelliCarb-Units)-Golden-Corral/': 'CB2323 / CB1522 / CB3023 (IntelliCarb Units) Golden Corral', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/CI2000-Plus/CI2000-Plus/': 'CI2000 Plus', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/DB-150/DB-150/': 'DB 150', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/DB-200-275-Standard/DB-200-275-Standard/': 'DB 200 / 275 Standard', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/DF-150/DF-150/': 'DF 150', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/DF-200250/DF-200250/': 'DF 200/250', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/ED-150/ED-150/': 'ED 150', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/ED-200250/ED-200250/': 'ED 200/250', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/ED-300/ED-300/': 'ED 300', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/IDC255-Pro-Fast-Gate/IDC255-Pro-Fast-Gate/': 'IDC255 Pro Fast Gate', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/TJ-150/TJ-150/': 'TJ 150', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/TJ-45-TJ-90/TJ-45-TJ-90/': 'TJ 45 / TJ 90', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Viper-2-Flavor/Viper-2-Flavor/': 'Viper 2 Flavor', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Viper-3-Flavor/Viper-3-Flavor/': 'Viper 3 Flavor', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Viper-4-Flavor/Viper-4-Flavor/': 'Viper 4 Flavor', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Viper-Carts/Viper-Carts/': 'Viper Carts', "https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Backroom-Package-(McDonald's)/Backroom-Package-(McDonald's)/": "Backroom Package (McDonald's)", 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/CB1522-18in-SABRE-TOWER/CB1522-18in-SABRE-TOWER/': 'CB1522 18in SABRE TOWER', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/CB1522D/CB1522D/': 'CB1522D', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/CB2323-SABRE-23in-TOWER-WCDD/CB2323-SABRE-23in-TOWER-WCDD/': 'CB2323 SABRE 23in TOWER W/CDD', "https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/CB2323-8vlv-(Wendy's)/CB2323-8vlv-(Wendy's)/": "CB2323-8vlv (Wendy's)", 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/CB2323L-SELF-CLOSING-LID/CB2323L-SELF-CLOSING-LID/': 'CB2323L SELF CLOSING LID', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/CB2323L-SLIDING-LID/CB2323L-SLIDING-LID/': 'CB2323L SLIDING LID', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/CC2323-TOWER-W-SLIDING-LID/CC2323-TOWER-W-SLIDING-LID/': 'CC2323 TOWER W/ SLIDING LID', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/CC2323L-SELF-CLOSING-LID/CC2323L-SELF-CLOSING-LID/': 'CC2323L SELF CLOSING LID', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/CI2000-(Plus)/CI2000-(Plus)/': 'CI2000 (Plus)', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/DB-275-BCP-Pneumatic-Ice-Gate/DB-275-BCP-Pneumatic-Ice-Gate/': 'DB 275 - BCP Pneumatic Ice Gate', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Energize-6orBRP-Stand/Energize-6orBRP-Stand/': 'Energize 6|BRP Stand', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/LeopardorLeopard-ERV-Accessories/LeopardorLeopard-ERV-Accessories/': 'Leopard|Leopard ERV Accessories', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/PrismorExploded-View/PrismorExploded-View/': 'Prism|Exploded View', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Quest-2000orBOTTLE-ADAPTER-ASSEMBLY/Quest-2000orBOTTLE-ADAPTER-ASSEMBLY/': 'Quest 2000|BOTTLE ADAPTER ASSEMBLY', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Quest-4000orBOTTLE-ADAPTER-ASSEMBLY/Quest-4000orBOTTLE-ADAPTER-ASSEMBLY/': 'Quest 4000|BOTTLE ADAPTER ASSEMBLY', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/SFV-1orExploded-View/SFV-1orExploded-View/': 'SFV - 1|Exploded View'}
MODELS=tuple(MODEL_IDS)
DEST=OUT/'cornelius_20261018'

async def run(resume=False):
    DEST.mkdir(exist_ok=True);(DEST/'pages').mkdir(exist_ok=True)
    cache={};image_cache={}
    if resume and (DEST/'manual_checks.json').exists():
        cache.update({r['url']:r for r in json.loads((DEST/'manual_checks.json').read_text())})
        previous=json.loads((ROOT/'data/organized/cornelius_parts_catalog.json').read_text())['parts']
        cache.update({r['fresh_evidence']['url']:r['fresh_evidence'] for r in previous})
        image_cache={r['part_number']:r for r in previous}
    prior=json.loads((OUT/'manual_reference_checks.json').read_text())
    seeds={e['url']:e['source_product_id'] for e in prior if e.get('status')=='confirmed' and (e.get('source_product_id') or '').split('|')[0] in MODELS}
    seeds.update(ROOT_URLS)
    main={r['part_number']:r for r in entries('parts')};sem=asyncio.Semaphore(4)
    async with httpx.AsyncClient(timeout=25,follow_redirects=True) as client:
        async def fetch(url):
            saved=cache.get(url)
            if saved and saved.get('http_status')==200 and saved.get('file'):
                age=(datetime.now(timezone.utc)-datetime.fromisoformat(saved['checked_at'])).total_seconds()
                file=DEST/saved['file']
                if 0<=age<3600 and file.exists() and sha256(file.read_bytes()).hexdigest()==saved['body_sha256']:
                    return parse(file.read_text()),dict(saved)
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
            row['_image_candidate']=p.get('listImage')
        async def check_image(row):
            image=row.pop('_image_candidate',None)
            old=image_cache.get(row['part_number'],{})
            old_check=old.get('image_check',{})
            recent=old_check.get('checked_at') and 0<=(datetime.now(timezone.utc)-datetime.fromisoformat(old_check['checked_at'])).total_seconds()<3600
            if image and recent and old_check.get('url')==image:
                row['image_check']=old_check;row['image_url']=old.get('image_url')
            elif image and image.startswith('https://images.salsify.com/'):
                async with sem:
                    try:
                        head=await client.head(image)
                        row['image_check']={'url':image,'checked_at':datetime.now(timezone.utc).isoformat(),'http_status':head.status_code,'content_type':head.headers.get('content-type','')}
                        if head.status_code==200 and head.headers.get('content-type','').startswith('image/'):row['image_url']=image
                    except httpx.HTTPError as exc:row['image_check']={'url':image,'error':type(exc).__name__}
            row['missing_fields']=[k for k in ['name','description','manufacturer','manufacturer_part','cona_material_number','image_url'] if not row.get(k)]
        await asyncio.gather(*(check_image(row) for row in parts.values()))
    rows=sorted(parts.values(),key=lambda r:r['part_number'])
    summary={'checked_at':datetime.now(timezone.utc).isoformat(),'unique_parts':len(rows),'per_model':{m:{'parts':sum(m in r['models'] for r in rows),'sections':len(sections[m])} for m in MODELS},'shared_parts':sum(len(r['models'])>1 for r in rows),'main_catalog_indexed':sum(r['main_catalog_indexed'] for r in rows),'new_confirmed_parts':sum(not r['main_catalog_indexed'] for r in rows),'missing_fields':dict(Counter(k for r in rows for k in r['missing_fields'])),'manual_urls_checked':len(manuals),'pending_manual_urls':len(pending_manuals),'part_urls_checked':len(fetched),'pending_part_urls':len(pending)}
    target=ROOT/'data/organized/cornelius';target.mkdir(exist_ok=True)
    (ROOT/'data/organized/cornelius_parts_catalog.json').write_text(json.dumps({'summary':summary,'parts':rows},ensure_ascii=False,indent=2))
    for model in MODELS:
        selected=[{**r,'official_associations':[a for a in r['official_associations'] if a['model']==model]} for r in rows if model in r['models']]
        (target/(MODEL_IDS[model]+'.json')).write_text(json.dumps({'model':model,'sections':sorted(sections[model]),'parts':selected},ensure_ascii=False,indent=2))
    (DEST/'manual_checks.json').write_text(json.dumps(manual_checks,ensure_ascii=False,indent=2))
    (DEST/'pending.json').write_text(json.dumps({'manuals':pending_manuals,'part_links':pending,'new_parts_pending_main_catalog':[r['part_number'] for r in rows if not r['main_catalog_indexed']],'policy':'Retain unresolved records without inferred identity or compatibility.'},ensure_ascii=False,indent=2))
    (DEST/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--resume',action='store_true',help='Reuse hash-verified snapshots and image checks younger than one hour');args=parser.parse_args();asyncio.run(run(args.resume))
