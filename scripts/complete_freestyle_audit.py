"""Complete the Freestyle audit from official product links; never infer fitment."""
import asyncio,json
from datetime import datetime,timezone
from hashlib import sha256
from collections import Counter
import httpx
from scripts.enrich_catalog_fields import ROOT,OUT,parse

async def run():
    path=ROOT/'data/organized/freestyle_parts_catalog.json';catalog=json.loads(path.read_text());catalog['parts']=[r for r in catalog['parts'] if r.get('source_index') is not None]
    pending=json.loads((OUT/'freestyle_parts_pending.json').read_text());raw=json.loads((ROOT/'parts_index.json').read_text())
    supplementary_path=OUT/'official_supplement.json';supp=json.loads(supplementary_path.read_text());supp_by={r['source_index']:r for r in supp}
    repair_path=OUT/'freestyle_image_repairs.json';new_path=OUT/'freestyle_new_official_parts.json'
    repairs=json.loads(repair_path.read_text()) if repair_path.exists() else [];new=[];checks=[];cache=OUT/'freestyle_new_pages';cache.mkdir(exist_ok=True);sem=asyncio.Semaphore(4)
    async with httpx.AsyncClient(timeout=20,follow_redirects=True) as client:
        for row in catalog['parts']:
            if row.get('image_url') and row.get('image_check',{}).get('valid'):continue
            product=parse((OUT/row['fresh_evidence']['file']).read_text());url=product.get('listImage')
            if not url or not url.startswith('https://images.salsify.com/'):continue
            try:response=await client.head(url)
            except httpx.HTTPError:continue
            ctype=response.headers.get('content-type','')
            if response.status_code!=200 or not ctype.startswith('image/'):continue
            row['image_url']=url;row['image_check']={'url':url,'http_status':200,'content_type':ctype,'valid':True};row['missing_fields']=[k for k in row['missing_fields'] if k!='image_url']
            index=row['source_index'];decision=supp_by.get(index)
            if decision is None:
                decision={'source_index':index,'source_sha256':sha256(json.dumps(raw[index],sort_keys=True,ensure_ascii=False).encode()).hexdigest(),'status':'confirmed','reason':'Official product identity and image type verified','patch':{}}
                supp_by[index]=decision
            decision['patch']['image_url']=url;decision['evidence']={**row['fresh_evidence'],'image_check':row['image_check']};repairs.append({'source_index':index,'part_number':row['part_number'],'image_url':url})
        refs={}
        for ref in pending['unmatched_manual_links']:refs.setdefault(ref['part_url'],[]).append(ref)
        async def check(url,associations):
            evidence={'url':url,'checked_at':datetime.now(timezone.utc).isoformat()};number=url.rstrip('/').split('/')[-1]
            async with sem:
                try:
                    saved=cache/(sha256(url.encode()).hexdigest()+'.html')
                    if saved.exists():text=saved.read_text();product=parse(text);evidence['cached']=True
                    else:
                        response=await client.get(url);evidence['http_status']=response.status_code
                        text=response.text;product=parse(text) if response.status_code==200 else {}
                    types=[v for prop in product.get('filterProperties',[]) if prop and prop.get('property')=='catalog_type_filter' for v in prop.get('values',[])]
                    if product.get('id')!=number or types!=['Parts Catalog']:
                        evidence.update(status='unresolved',source_product_id=product.get('id'),reason='Exact part product identity/type not confirmed');checks.append(evidence);return
                    saved.write_text(text);evidence.update(status='confirmed',source_product_id=product['id'],file=str(saved.relative_to(OUT)),body_sha256=sha256(saved.read_bytes()).hexdigest())
                    fields={p['property']:p['values'] for g in product.get('propertySets',[]) for p in g.get('properties',[])}
                    image=product.get('listImage');imagecheck=None
                    if image and image.startswith('https://images.salsify.com/'):
                        try:
                            head=await client.head(image);imagecheck={'url':image,'http_status':head.status_code,'content_type':head.headers.get('content-type',''),'valid':head.status_code==200 and head.headers.get('content-type','').startswith('image/')}
                        except httpx.HTTPError as exc:imagecheck={'url':image,'valid':False,'error':type(exc).__name__}
                        if not imagecheck['valid']:image=None
                    else:image=None
                    row={'catalog_id':None,'source_index':None,'part_number':number,'name':product.get('listSubtitle') or number,'description':(fields.get('material_long_description') or [product.get('listSubtitle')])[0],'image_url':image,'page_url':url,'manufacturer':(fields.get('manufacturer_name_display') or [None])[0],'manufacturer_part':(fields.get('manufacturer_part_display') or [None])[0],'cona_material_number':(fields.get('cona_material_number') or [None])[0],'models':sorted({a['model'] for a in associations}),'shared_across_official_models':len({a['model'] for a in associations})>1,'official_associations':associations,'source_status':'confirmed','fresh_evidence':evidence,'image_check':imagecheck,'main_catalog_indexed':False,'stock_import_candidate':False,'compatibility_policy':'Official model/section link only, not field verification or cross-model compatibility'}
                    row['missing_fields']=[k for k in ('description','image_url','manufacturer','manufacturer_part','cona_material_number') if not row.get(k)];new.append(row);checks.append(evidence)
                except httpx.HTTPError as exc:evidence.update(status='unresolved',reason=type(exc).__name__);checks.append(evidence)
                if len(checks)%50==0:(OUT/'freestyle_new_checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2))
        await asyncio.gather(*(check(url,associations) for url,associations in refs.items()))
    for row in catalog['parts']:row['main_catalog_indexed']=True
    prior_new={r['part_number']:r for r in json.loads(new_path.read_text())} if new_path.exists() else {}
    prior_new.update({r['part_number']:r for r in new});new=list(prior_new.values())
    catalog['parts'].extend(sorted(new,key=lambda r:r['part_number']));parts=catalog['parts'];s=catalog['summary']
    resolved_urls={r['page_url'] for r in new};remaining=[r for r in pending['unmatched_manual_links'] if r['part_url'] not in resolved_urls]
    by_url={r['page_url'].rstrip('/'):r for r in parts};normalized=[];unresolved=[]
    for ref in remaining:
        original=ref['part_url'];url=original.replace('%20/','/');part=by_url.get(url.rstrip('/'))
        if url!=original and part:
            evidence={**ref,'part_url':url,'original_part_url':original,'link_normalization':'Trailing encoded space removed; exact verified product URL matched'}
            if evidence not in part['official_associations']:part['official_associations'].append(evidence)
            part['models']=sorted(set(part['models'])|{ref['model']});part['shared_across_official_models']=len(part['models'])>1;normalized.append(evidence)
        else:unresolved.append(ref)
    remaining=unresolved
    s.update(unique_parts=len(parts),new_official_parts=len(new),restored_images=len(repairs),source_status=dict(Counter(r['source_status'] for r in parts)),shared_parts=sum(p['shared_across_official_models'] for p in parts),missing_fields=dict(Counter(k for r in parts for k in r['missing_fields'])),image_checks=dict(Counter('valid' if r['image_check']['valid'] else 'unavailable' for r in parts if r['image_check'])),original_unmatched_manual_links=s.get('original_unmatched_manual_links',s['unmatched_manual_links']),unmatched_manual_links=len({(r['model'],r['part_url']) for r in remaining}))
    for model in s['per_model']:s['per_model'][model]['parts']=sum(model in r['models'] for r in parts)
    path.write_text(json.dumps(catalog,ensure_ascii=False,indent=2));(OUT/'freestyle_parts_audit_summary.json').write_text(json.dumps(s,ensure_ascii=False,indent=2))
    supplementary_path.write_text(json.dumps(list(supp_by.values()),ensure_ascii=False,indent=2))
    (OUT/'freestyle_image_repairs.json').write_text(json.dumps(repairs,ensure_ascii=False,indent=2));(OUT/'freestyle_new_official_parts.json').write_text(json.dumps(new,ensure_ascii=False,indent=2));(OUT/'freestyle_new_checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2))
    pending.update(normalized_official_links=normalized or pending.get('normalized_official_links',[]),unmatched_manual_links=remaining,new_parts_pending_main_catalog=[{'part_number':r['part_number'],'models':r['models'],'page_url':r['page_url']} for r in new],unavailable_images=[r for r in parts if r['image_check'] and not r['image_check']['valid']]);(OUT/'freestyle_parts_pending.json').write_text(json.dumps(pending,ensure_ascii=False,indent=2));print(json.dumps(s,ensure_ascii=False))
if __name__=='__main__':asyncio.run(run())
