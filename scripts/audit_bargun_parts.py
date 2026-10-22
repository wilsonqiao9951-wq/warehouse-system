"""Fresh, source-preserving BARGUN audit. Does not modify main catalog or inventory."""
import asyncio,json
from collections import defaultdict,Counter
from datetime import datetime,timezone
from hashlib import sha256
from urllib.parse import unquote
from html.parser import HTMLParser
import httpx
from scripts.enrich_catalog_fields import ROOT,OUT,parse
from scripts.enrich_reverse_manual_refs import part_links
from app.services.catalog import entries
MODEL_IDS={'Bargun Button Caps': 'bargun-button-caps', 'Magnum': 'magnum', 'Mark IV 10 Button': 'mark-iv-10-button', 'Mark IV 12 Button': 'mark-iv-12-button', 'Mark IV 14 Button': 'mark-iv-14-button', 'Mark IV 3 Button Energy / Tea': 'mark-iv-3-button-energy-tea', 'Rattler': 'rattler', 'Rattler II': 'rattler-ii', 'S2.5 10 Button': 's2-5-10-button', 'S2.5 12 Button': 's2-5-12-button', 'S2.5 14 Button': 's2-5-14-button'}
SOURCE_SEEDS={'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Mark-IV-3-Button-Energy-TeaorHandle-Exploded-Parts-View/Mark-IV-3-Button-Energy-TeaorHandle-Exploded-Parts-View': 'Mark IV 3 Button Energy / Tea|Handle Exploded Parts View', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Rattler-IIorHANDLE-ASSEMBLY/Rattler-IIorHANDLE-ASSEMBLY': 'Rattler II|HANDLE ASSEMBLY', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/MagnumorHANDLE-ASSEMBLY/MagnumorHANDLE-ASSEMBLY': 'Magnum|HANDLE ASSEMBLY', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/RattlerorHANDLE-ASSEMBLY/RattlerorHANDLE-ASSEMBLY': 'Rattler|HANDLE ASSEMBLY', "https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/MagnumorACCESSORIES-(CONT'D)/MagnumorACCESSORIES-(CONT'D)": "Magnum|ACCESSORIES (CONT'D)", 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/MagnumorFLOW-CONTROL-MODULE-ASSEMBLY/MagnumorFLOW-CONTROL-MODULE-ASSEMBLY': 'Magnum|FLOW CONTROL MODULE ASSEMBLY', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Mark-IV-10-ButtonorHandle-Assembly/Mark-IV-10-ButtonorHandle-Assembly': 'Mark IV 10 Button|Handle Assembly', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Mark-IV-12-ButtonorHandle-Assembly/Mark-IV-12-ButtonorHandle-Assembly': 'Mark IV 12 Button|Handle Assembly', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Mark-IV-14-ButtonorHandle-Assembly/Mark-IV-14-ButtonorHandle-Assembly': 'Mark IV 14 Button|Handle Assembly', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Rattler-IIorFLOW-CONTROL-MODULE-ASSEMBLY/Rattler-IIorFLOW-CONTROL-MODULE-ASSEMBLY': 'Rattler II|FLOW CONTROL MODULE ASSEMBLY', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/MagnumorComplete-Taprite-Bargun-Listings/MagnumorComplete-Taprite-Bargun-Listings': 'Magnum|Complete Taprite Bargun Listings', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Rattler-IIorMANIFOLD-ASSEMBLY/Rattler-IIorMANIFOLD-ASSEMBLY': 'Rattler II|MANIFOLD ASSEMBLY', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Mark-IV-10-ButtonorManifold-Assembly/Mark-IV-10-ButtonorManifold-Assembly': 'Mark IV 10 Button|Manifold Assembly', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Rattler-IIorCOMPLETE-ASSEMBLIES/Rattler-IIorCOMPLETE-ASSEMBLIES': 'Rattler II|COMPLETE ASSEMBLIES', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/RattlerorComplete-Bargun-Assemblies/RattlerorComplete-Bargun-Assemblies': 'Rattler|Complete Bargun Assemblies', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Mark-IV-3-Button-Energy-TeaorManifold-Exploded-Parts-View/Mark-IV-3-Button-Energy-TeaorManifold-Exploded-Parts-View': 'Mark IV 3 Button Energy / Tea|Manifold Exploded Parts View', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/S2-5-10-ButtonorKITS-and-MISC--PARTS/S2-5-10-ButtonorKITS-and-MISC--PARTS': 'S2.5 10 Button|KITS & MISC. PARTS', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/MagnumorMANIFOLD-ASSEMBLY/MagnumorMANIFOLD-ASSEMBLY': 'Magnum|MANIFOLD ASSEMBLY', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/S2-5-12-ButtonorKITS-and-MISC--PARTS/S2-5-12-ButtonorKITS-and-MISC--PARTS': 'S2.5 12 Button|KITS & MISC. PARTS', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Rattler-IIorDRIP-TRAY-ASSEMBLY/Rattler-IIorDRIP-TRAY-ASSEMBLY': 'Rattler II|DRIP TRAY ASSEMBLY', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/MagnumorACCESSORIES/MagnumorACCESSORIES': 'Magnum|ACCESSORIES', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/RattlerorDrip-Cup-Assembly/RattlerorDrip-Cup-Assembly': 'Rattler|Drip Cup Assembly', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/S2-5-10-ButtonorMANIFOLD-WFLOW-CONTROL/S2-5-10-ButtonorMANIFOLD-WFLOW-CONTROL': 'S2.5 10 Button|MANIFOLD W/FLOW CONTROL', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/S2-5-14-Buttonor14-BUTTON-HANDLE/S2-5-14-Buttonor14-BUTTON-HANDLE': 'S2.5 14 Button|14 BUTTON HANDLE', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/S2-5-10-Buttonor10-BUTTON-HANDLE/S2-5-10-Buttonor10-BUTTON-HANDLE': 'S2.5 10 Button|10 BUTTON HANDLE', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/S2-5-12-Buttonor12-BUTTON-POST-MIX-HANDLE/S2-5-12-Buttonor12-BUTTON-POST-MIX-HANDLE': 'S2.5 12 Button|12 BUTTON POST- MIX HANDLE', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/S2-5-14-ButtonorMANIFOLD-WFLOW-CONTROL/S2-5-14-ButtonorMANIFOLD-WFLOW-CONTROL': 'S2.5 14 Button|MANIFOLD W/FLOW CONTROL', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Mark-IV-12-ButtonorManifold-Assembly/Mark-IV-12-ButtonorManifold-Assembly': 'Mark IV 12 Button|Manifold Assembly', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Mark-IV-14-ButtonorManifold-Assembly/Mark-IV-14-ButtonorManifold-Assembly': 'Mark IV 14 Button|Manifold Assembly', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/S2-5-12-ButtonorMANIFOLD-WFLOW-CONTROL/S2-5-12-ButtonorMANIFOLD-WFLOW-CONTROL': 'S2.5 12 Button|MANIFOLD W/FLOW CONTROL', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Mark-IV-10-ButtonorButton-Caps/Mark-IV-10-ButtonorButton-Caps': 'Mark IV 10 Button|Button Caps', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Mark-IV-12-ButtonorButton-Caps/Mark-IV-12-ButtonorButton-Caps': 'Mark IV 12 Button|Button Caps', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Mark-IV-14-ButtonorButton-Caps/Mark-IV-14-ButtonorButton-Caps': 'Mark IV 14 Button|Button Caps', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Bargun-Button-CapsorButton-Caps/Bargun-Button-CapsorButton-Caps': 'Bargun Button Caps|Button Caps', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/RattlerorFLOW-CONTROL-MODULE-ASSEMBLY/RattlerorFLOW-CONTROL-MODULE-ASSEMBLY': 'Rattler|FLOW CONTROL MODULE ASSEMBLY', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/RattlerorMANIFOLD-ASSEMBLY/RattlerorMANIFOLD-ASSEMBLY': 'Rattler|MANIFOLD ASSEMBLY', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Mark-IV-10-ButtonorDrip-Cup-Assembly/Mark-IV-10-ButtonorDrip-Cup-Assembly': 'Mark IV 10 Button|Drip Cup Assembly', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Mark-IV-10-ButtonorNew-Drip-Cup-Assembly/Mark-IV-10-ButtonorNew-Drip-Cup-Assembly': 'Mark IV 10 Button|New Drip Cup Assembly', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Mark-IV-12-ButtonorNew-Drip-Cup-Assembly/Mark-IV-12-ButtonorNew-Drip-Cup-Assembly': 'Mark IV 12 Button|New Drip Cup Assembly', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Mark-IV-14-ButtonorNew-Drip-Cup-Assembly/Mark-IV-14-ButtonorNew-Drip-Cup-Assembly': 'Mark IV 14 Button|New Drip Cup Assembly', 'https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/Bargun-Button-Caps/Bargun-Button-Caps/': 'Bargun Button Caps'}
MODELS=tuple(MODEL_IDS)
DEST=OUT/'bargun_20261018'

class SectionLinks(HTMLParser):
    def __init__(self):super().__init__();self.links=[];self.href=None;self.label=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a':self.href=dict(attrs).get('href');self.label=[]
    def handle_data(self,data):
        if self.href:self.label.append(data)
    def handle_endtag(self,tag):
        if tag=='a' and self.href:
            self.links.append((self.href,''.join(self.label).strip()));self.href=None

def sibling_sections(product):
    model=product.get('id','').split('|')[0]
    for group in product.get('propertySets',[]):
        for prop in group.get('properties',[]):
            if prop.get('property')!='unified_equipment_section_reference_link':continue
            for value in prop.get('values',[]):
                parser=SectionLinks();parser.feed(value)
                for url,label in parser.links:
                    if not url.startswith('https://sites.salsify.com/6a5099d3-63f2-40c2-a0e1-770febd242fe/473a3027-ad53-4a9f-9cf1-5711379a7b33/product/'):continue
                    expected=label if '|' in label else model+'|'+label
                    if label and expected.split('|')[0]==model:yield url,expected

async def run():
    DEST.mkdir(exist_ok=True);(DEST/'pages').mkdir(exist_ok=True)
    prior=json.loads((OUT/'manual_reference_checks.json').read_text())
    seeds=dict(SOURCE_SEEDS)
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
        # Follow only same-model section links explicitly listed on verified official pages.
        for _ in range(10):
            extra={}
            for (_,expected),(product,evidence) in zip(seeds.items(),manuals):
                if product.get('id')!=expected:continue
                for url,sid in sibling_sections(product):
                    if url not in seeds:extra[url]=sid
            if not extra:break
            more=await asyncio.gather(*(fetch(url) for url in extra));seeds.update(extra);manuals.extend(more)
        else:raise ValueError('Manual section discovery did not converge')
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
            if image and image.startswith('https://images.salsify.com/'):
                async with sem:
                    try:
                        head=await client.head(image);row['image_check']={'url':image,'checked_at':datetime.now(timezone.utc).isoformat(),'http_status':head.status_code,'content_type':head.headers.get('content-type','')}
                        if head.status_code==200 and head.headers.get('content-type','').startswith('image/'):row['image_url']=image
                    except httpx.HTTPError as exc:row['image_check']={'url':image,'error':type(exc).__name__}
            row['missing_fields']=[k for k in ['name','description','manufacturer','manufacturer_part','cona_material_number','image_url'] if not row.get(k)]
        await asyncio.gather(*(check_image(row) for row in parts.values()))
    rows=sorted(parts.values(),key=lambda r:r['part_number'])
    summary={'checked_at':datetime.now(timezone.utc).isoformat(),'unique_parts':len(rows),'per_model':{m:{'parts':sum(m in r['models'] for r in rows),'sections':len(sections[m])} for m in MODELS},'shared_parts':sum(len(r['models'])>1 for r in rows),'main_catalog_indexed':sum(r['main_catalog_indexed'] for r in rows),'new_confirmed_parts':sum(not r['main_catalog_indexed'] for r in rows),'missing_fields':dict(Counter(k for r in rows for k in r['missing_fields'])),'manual_urls_checked':len(manuals),'pending_manual_urls':len(pending_manuals),'part_urls_checked':len(fetched),'pending_part_urls':len(pending)}
    target=ROOT/'data/organized/bargun';target.mkdir(exist_ok=True)
    (ROOT/'data/organized/bargun_parts_catalog.json').write_text(json.dumps({'summary':summary,'parts':rows},ensure_ascii=False,indent=2))
    for model in MODELS:
        selected=[{**r,'official_associations':[a for a in r['official_associations'] if a['model']==model]} for r in rows if model in r['models']]
        (target/(MODEL_IDS[model]+'.json')).write_text(json.dumps({'model':model,'sections':sorted(sections[model]),'parts':selected},ensure_ascii=False,indent=2))
    (DEST/'manual_checks.json').write_text(json.dumps(manual_checks,ensure_ascii=False,indent=2))
    (DEST/'pending.json').write_text(json.dumps({'manuals':pending_manuals,'part_links':pending,'new_parts_pending_main_catalog':[r['part_number'] for r in rows if not r['main_catalog_indexed']],'policy':'Retain unresolved records without inferred identity or compatibility.'},ensure_ascii=False,indent=2))
    (DEST/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':asyncio.run(run())
