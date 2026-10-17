"""Fill absent fields from identity-verified official snapshots; HEAD-check images."""
import asyncio,json
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import httpx
from scripts.enrich_catalog_fields import ROOT,OUT,parse
from scripts.audit_catalog import valid_url

async def run():
    rows=json.loads((ROOT/'data/organized/parts_catalog.json').read_text())
    decisions=json.loads((OUT/'field_enrichment.json').read_text());by={d['source_index']:d for d in decisions}
    mapping={'manufacturer':'manufacturer_name_display','manufacturer_part':'manufacturer_part_display','cona_material_number':'cona_material_number','status':'computed_status'}
    selected=[]
    for row in rows:
        i=row['_organization']['source_index'];d=by.get(i)
        if not d or d['status']!='confirmed':continue
        filename=d.get('evidence',{}).get('file');file=OUT/filename if filename else None
        if not file or not file.exists():continue
        p=parse(file.read_text())
        if p.get('id')!=d['evidence'].get('source_product_id'):continue
        fields={v['property']:v['values'] for g in p.get('propertySets',[]) for v in g.get('properties',[])}
        patch={}
        for target,source in mapping.items():
            values=fields.get(source) or []
            if not row.get(target) and len(values)==1 and isinstance(values[0],str) and values[0].strip():patch[target]=values[0].strip()
        image=p.get('listImage') if not row.get('image_url') else None
        if image and (not valid_url(image) or not image.startswith('https://images.salsify.com/')):image=None
        if patch or image:selected.append((d,patch,image))
    sem=asyncio.Semaphore(8);output=[];image_counts=Counter()
    async with httpx.AsyncClient(timeout=15,follow_redirects=True) as client:
        async def check(item):
            d,patch,image=item;evidence=dict(d['evidence'])
            if image:
                async with sem:
                    try:
                        response=await client.head(image)
                        content_type=response.headers.get('content-type','')
                        evidence['image_check']={'url':image,'http_status':response.status_code,'content_type':content_type,'checked_at':datetime.now(timezone.utc).isoformat()}
                        if response.status_code==200 and content_type.startswith('image/'):
                            patch['image_url']=image;image_counts['confirmed']+=1
                        else:image_counts['unavailable']+=1
                    except httpx.HTTPError as exc:
                        evidence['image_check']={'url':image,'error':type(exc).__name__};image_counts['failed']+=1
            if patch:output.append({'source_index':d['source_index'],'source_sha256':d['source_sha256'],'status':'confirmed','reason':'Missing fields copied from identity-verified official properties; images verified by HTTP status and content type','patch':patch,'evidence':evidence})
        await asyncio.gather(*(check(item) for item in selected))
    previous_path=OUT/'official_supplement.json'
    if previous_path.exists():
        previous={d['source_index']:d for d in json.loads(previous_path.read_text())}
        for decision in output:
            old=previous.get(decision['source_index'])
            if old:decision['patch']={**old['patch'],**decision['patch']}
            previous[decision['source_index']]=decision
        output=list(previous.values())
    output.sort(key=lambda d:d['source_index'])
    (OUT/'official_supplement.json').write_text(json.dumps(output,ensure_ascii=False,indent=2))
    summary={'records_enriched':len(output),'fields_filled':dict(Counter(k for d in output for k in d['patch'])),'image_checks':dict(image_counts)}
    (OUT/'official_supplement_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__':asyncio.run(run())
