"""Resolve audit-only unindexed official parts and restore proven image URLs."""
import asyncio,json
from datetime import datetime,timezone
from hashlib import sha256
import httpx
from scripts.enrich_catalog_fields import ROOT,OUT,parse

async def run():
    path=ROOT/'data/organized/viper_parts_catalog.json';catalog=json.loads(path.read_text());catalog['parts']=[r for r in catalog['parts'] if r.get('source_index') is not None];pending=json.loads((OUT/'viper_parts_pending.json').read_text());new=[];repairs=[]
    supplementary_path=OUT/'official_supplement.json';supp=json.loads(supplementary_path.read_text());supp_by={r['source_index']:r for r in supp}
    identities={r['source_index']:r for r in json.loads((OUT/'field_enrichment.json').read_text())}
    cache=OUT/'viper_new_pages';cache.mkdir(exist_ok=True)
    async with httpx.AsyncClient(timeout=20,follow_redirects=True) as client:
        for row in catalog['parts']:
            if row.get('image_url') and row.get('image_check',{}).get('valid'):continue
            product=parse((OUT/row['fresh_evidence']['file']).read_text());url=product.get('listImage')
            if not url or not url.startswith('https://images.salsify.com/'):continue
            response=await client.head(url);ctype=response.headers.get('content-type','')
            if response.status_code!=200 or not ctype.startswith('image/'):continue
            row['image_url']=url;row['image_check']={'url':url,'http_status':200,'content_type':ctype,'valid':True};row['missing_fields']=[k for k in row['missing_fields'] if k!='image_url']
            decision=supp_by.get(row['source_index'])
            if decision is None:decision={**identities[row['source_index']],'patch':{}};supp_by[row['source_index']]=decision
            decision['patch']['image_url']=url;decision['evidence']={**row['fresh_evidence'],'image_check':row['image_check']};repairs.append({'source_index':row['source_index'],'part_number':row['part_number'],'image_url':url})
        refs={}
        for ref in pending['unmatched_manual_links']:refs.setdefault(ref['part_url'],[]).append(ref)
        for url,associations in refs.items():
            response=await client.get(url);product=parse(response.text) if response.status_code==200 else {};number=url.rstrip('/').split('/')[-1]
            evidence={'url':url,'http_status':response.status_code,'source_product_id':product.get('id'),'checked_at':datetime.now(timezone.utc).isoformat()}
            if product.get('id')!=number:continue
            saved=cache/f'{number}.html';saved.write_text(response.text);evidence.update(file=str(saved.relative_to(OUT)),body_sha256=sha256(response.content).hexdigest())
            fields={p['property']:p['values'] for g in product.get('propertySets',[]) for p in g.get('properties',[])}
            image=product.get('listImage');imagecheck=None
            if image and image.startswith('https://images.salsify.com/'):
                head=await client.head(image);imagecheck={'url':image,'http_status':head.status_code,'content_type':head.headers.get('content-type',''),'valid':head.status_code==200 and head.headers.get('content-type','').startswith('image/')}
                if not imagecheck['valid']:image=None
            else:image=None
            row={'catalog_id':None,'source_index':None,'part_number':number,'name':product.get('listSubtitle') or number,'description':(fields.get('material_long_description') or [product.get('listSubtitle')])[0],'image_url':image,'page_url':url,'manufacturer':(fields.get('manufacturer_name_display') or [None])[0],'manufacturer_part':(fields.get('manufacturer_part_display') or [None])[0],'cona_material_number':(fields.get('cona_material_number') or [None])[0],'models':sorted({a['model'] for a in associations}),'shared_across_official_models':len({a['model'] for a in associations})>1,'official_associations':associations,'source_status':'confirmed','fresh_evidence':evidence,'image_check':imagecheck,'main_catalog_indexed':False,'stock_import_candidate':False,'compatibility_policy':'Official directory association, not field verification. New source record kept in Viper audit collection pending main catalog integration.'}
            row['missing_fields']=[k for k in ('description','image_url','manufacturer','manufacturer_part','cona_material_number') if not row.get(k)]
            new.append(row)
    catalog['parts']=[row for row in catalog['parts'] if row.get('source_index') is not None]
    for row in catalog['parts']:row['main_catalog_indexed']=True
    catalog['parts'].extend(new)
    from collections import Counter
    parts=catalog['parts'];s=catalog['summary'];s.update(unique_parts=len(parts),new_official_parts=len(new),restored_images=len(repairs),source_status=dict(Counter(r['source_status'] for r in parts)),shared_parts=sum(p['shared_across_official_models'] for p in parts),missing_fields=dict(Counter(k for r in parts for k in r['missing_fields'])),image_checks=dict(Counter('valid' if r['image_check']['valid'] else 'unavailable' for r in parts if r['image_check'])))
    for model in s['per_model']:s['per_model'][model]['parts']=sum(model in r['models'] for r in parts)
    path.write_text(json.dumps(catalog,ensure_ascii=False,indent=2));(OUT/'viper_parts_audit_summary.json').write_text(json.dumps(s,ensure_ascii=False,indent=2))
    supplementary_path.write_text(json.dumps(list(supp_by.values()),ensure_ascii=False,indent=2))
    (OUT/'viper_image_repairs.json').write_text(json.dumps(repairs,ensure_ascii=False,indent=2));(OUT/'viper_new_official_parts.json').write_text(json.dumps(new,ensure_ascii=False,indent=2));print(json.dumps(s,ensure_ascii=False))
if __name__=='__main__':asyncio.run(run())
