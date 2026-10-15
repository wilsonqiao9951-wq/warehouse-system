"""Bounded, resumable source-backed enrichment; no inferred compatibility."""
import argparse
import asyncio
from collections import Counter
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import httpx
from scripts.audit_catalog import ROOT,identifier,valid_url

OUT=ROOT/'data/verification'

def parse(text):
    match=re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',text)
    return json.loads(match.group(1))['props']['pageProps'].get('product',{}) if match else {}


def inspect(raw,index,p,evidence):
    result={'source_index':index,'source_sha256':sha256(json.dumps(raw,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),'patch':{},'status':'unresolved','reason':'Source identity not confirmed','evidence':evidence}
    same_id = identifier(p.get('id')) == identifier(raw.get('part_number'))
    # Scoped alias check for the Viper family: hyphenated path IDs vs displayed resource IDs.
    viper_alias = str(raw.get('part_number','')).startswith('Viper') and str(p.get('id','')).startswith('Viper') and re.sub(r'[^a-z0-9]', '', str(raw.get('part_number')).lower()) == re.sub(r'[^a-z0-9]', '', str(p.get('id')).lower())
    # Salsify encodes the resource separator '|' as 'or' in path identifiers.
    raw_id=str(raw.get('part_number') or '')
    displayed_id=str(p.get('id') or '')
    core_fields={prop['property']:prop['values'] for group in p.get('propertySets',[]) for prop in group.get('properties',[])}
    catalog_types=[v for prop in p.get('filterProperties',[]) if prop and prop.get('property')=='catalog_type_filter' for v in prop.get('values',[])]
    # CCP aliases require both an exact official legacy ID and the same numeric suffix.
    legacy_alias=(raw_id.isdigit() and displayed_id=='CCP '+raw_id and raw_id in core_fields.get('legacy_material_number',[]))
    # Equipment names may qualify a model number; require the complete original name.
    equipment_alias=(catalog_types==['Parts Manuals'] and displayed_id==raw.get('name') and displayed_id.startswith(raw_id+' (') and displayed_id.endswith(')'))
    normalize_piece=lambda value: re.sub(r'[^a-z0-9]', '', value.lower())
    section_alias=False
    if '|' in displayed_id and 'or' in raw_id:
        left,right=displayed_id.split('|',1)
        section_alias=any(normalize_piece(raw_id[:match.start()])==normalize_piece(left) and normalize_piece(raw_id[match.end():])==normalize_piece(right) for match in re.finditer('or',raw_id))
    if not (same_id or viper_alias or section_alias or legacy_alias or equipment_alias):
        result['patch']['stock_import_candidate']=False
        if p.get('id'):
            result.update(status='quarantined',patch={'stock_import_candidate':False},reason='Product ID differs; no facts copied and stock import blocked')
        return result
    fields={prop['property']:prop['values'] for group in p.get('propertySets',[]) for prop in group.get('properties',[])}
    filters={prop['property']:prop['values'] for prop in p.get('filterProperties',[]) if prop}
    patch=result['patch']
    if filters.get('catalog_type_filter')==['Parts Manuals']:
        patch.update(entry_type='equipment',stock_import_candidate=False)
        result['classification']='equipment'
    elif '|' in str(p.get('id')) and fields.get('equipment_category'):
        patch.update(entry_type='manual',stock_import_candidate=False)
        result['classification']='manual_section'
    subtitle=p.get('listSubtitle')
    title=p.get('listTitle')
    if not raw.get('name') and isinstance(subtitle,str) and subtitle.strip():patch['name']=subtitle.strip()
    elif not raw.get('name') and isinstance(title,str) and identifier(title)!=identifier(raw.get('part_number')):patch['name']=title.strip()
    if not raw.get('description') and isinstance(subtitle,str) and subtitle.strip():patch['description']=subtitle.strip()
    if not raw.get('description') and 'description' not in patch:
        descriptions=fields.get('material_long_description') or []
        if descriptions and isinstance(descriptions[0],str) and descriptions[0].strip():
            patch['description']=descriptions[0].strip()
    refs=[]
    for group in p.get('propertySets',[]):
        if group.get('label')!='Parts Manuals Referencing This Part':continue
        for reference in group.get('references') or []:
            rid=reference.get('id')
            if isinstance(rid,str) and rid:
                links=[v for prop in reference.get('properties',[]) if prop.get('property')=='unified_catalog_manual_link' for v in prop.get('values',[])]
                refs.append({'source_reference_id':rid,'equipment_model':rid.split('|',1)[0].strip(),'source_link_markup':links})
    if not raw.get('fits_equipment_models') and refs:
        patch['fits_equipment_models']=list(dict.fromkeys(r['equipment_model'] for r in refs))
        result['equipment_reference_evidence']=refs
    result.update(status='confirmed',reason=('Exact official legacy ID and CCP numeric suffix matched' if legacy_alias else 'Full original equipment name and qualified model number matched' if equipment_alias else 'Verified section path/display alias matched' if section_alias else 'Scoped Viper path alias matched' if viper_alias and not same_id else 'Exact product ID matched') + '; missing fields copied from subtitle, long description or explicit part-manual references')
    return result

async def run(limit, supplemental=False):
    OUT.mkdir(parents=True,exist_ok=True)
    raw=json.loads((ROOT/'parts_index.json').read_text())
    organized=json.loads((ROOT/'data/organized/parts_catalog.json').read_text())
    path=OUT/'field_enrichment.json'
    prior=json.loads(path.read_text()) if path.exists() else []
    done={r['source_index'] for r in prior}
    candidates=[r for r in organized if r['_organization']['classification'] in {'part_candidate','needs_classification'} and not all(r.get(k) for k in ('name','description','fits_equipment_models')) and r.get('verification_status')!='requires_authenticated_identity_check']
    if supplemental:
        candidates=[r for r in organized if not all(r.get(k) for k in ('image_url','manufacturer','manufacturer_part','cona_material_number','status','description','fits_equipment_models')) and r.get('verification_status')!='requires_authenticated_identity_check']
    candidates.sort(key=lambda r:(bool(r.get('name')),bool(r.get('description')),r['_organization']['source_index']))
    selected=[r for r in candidates if r['_organization']['source_index'] not in done][:limit]
    cache=OUT/'field_pages';cache.mkdir(exist_ok=True)
    sem=asyncio.Semaphore(4)
    async with httpx.AsyncClient(timeout=15,follow_redirects=True) as client:
        async def check(row):
            i=row['_organization']['source_index'];u=row.get('page_url');saved=cache/f'{i}.html'
            evidence={'url':u,'checked_at':datetime.now(timezone.utc).isoformat()}
            async with sem:
                try:
                    if not valid_url(u):return inspect(raw[i],i,{},evidence)
                    if saved.exists():
                        text=saved.read_text();p=parse(text)
                        evidence.update(file=f'field_pages/{i}.html',source_product_id=p.get('id'),body_sha256=sha256(text.encode()).hexdigest(),cached=True)
                        return inspect(raw[i],i,p,evidence)
                    response=await client.get(u);evidence.update(http_status=response.status_code,final_url=str(response.url))
                    p=parse(response.text) if response.status_code==200 else {}
                    if p:
                        saved.write_text(response.text);evidence.update(file=f'field_pages/{i}.html',source_product_id=p.get('id'),body_sha256=sha256(response.content).hexdigest())
                    return inspect(raw[i],i,p,evidence)
                except Exception as exc:
                    result=inspect(raw[i],i,{},evidence);result['reason']=type(exc).__name__+': '+str(exc);return result
        finished=[]
        async def checkpointed(row):
            result=await check(row)
            finished.append(result)
            if len(finished)%100==0:
                temporary=path.with_suffix('.checkpoint.tmp')
                temporary.write_text(json.dumps(prior+finished,ensure_ascii=False,indent=2))
                temporary.replace(path)
            return result
        results=await asyncio.gather(*(checkpointed(row) for row in selected))
    for result in results:
        if result['status']=='confirmed':
            cached=cache/f"{result['source_index']}.html"
            if cached.exists():
                refreshed=inspect(raw[result['source_index']],result['source_index'],parse(cached.read_text()),result['evidence'])
                result.update(refreshed)
    prior.extend(results);path.write_text(json.dumps(prior,ensure_ascii=False,indent=2))
    summary={'this_batch':len(results),'total_checked':len(prior),'status':dict(Counter(r['status'] for r in results)),'fields_filled':dict(Counter(k for r in results for k in r['patch'])),'remaining_unchecked':len(candidates)-len(done & {r['_organization']['source_index'] for r in candidates})-len(results)}
    (OUT/'field_enrichment_progress.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int,default=240);parser.add_argument('--supplemental',action='store_true');args=parser.parse_args();asyncio.run(run(args.limit,args.supplemental))
