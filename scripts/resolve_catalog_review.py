"""Build evidence-backed overrides from the targeted source-page checks."""
import asyncio
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import httpx
from scripts.audit_catalog import ROOT, identifier

OUT = ROOT / 'data/verification'

def content_hash(row):
    return sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def product(path):
    text = path.read_text()
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',text)
    return json.loads(match.group(1))['props']['pageProps'].get('product',{}) if match else {}

async def run():
    rows = json.loads((ROOT / 'parts_index.json').read_text())
    checks = json.loads((OUT / 'link_checks.json').read_text())
    decisions = []
    for check in checks:
        i = check['source_index']; row = rows[i]
        decision = {'source_index':i,'source_sha256':content_hash(row),'patch':{},'status':'unresolved','reason':'No matching product identity','evidence':check}
        path = OUT / check.get('evidence_file','-')
        p = product(path) if path.is_file() and check.get('status') == 200 else {}
        same_id = identifier(p.get('id')) == identifier(row['part_number'])
        # One explicit, reviewed equipment alias: source slug versus display ID.
        viper_alias = row['part_number'] == 'Viper-3-Flavor' and p.get('id') == 'Viper 3 Flavor'
        if same_id or viper_alias:
            fields = {prop['property']:prop['values'] for group in p.get('propertySets',[]) for prop in group.get('properties',[])}
            filters = {prop['property']:prop['values'] for prop in p.get('filterProperties',[]) if prop}
            patch = decision['patch']
            patch.update(name=p.get('listTitle') or row.get('name'))
            for source,target in [('manufacturer_name_display','manufacturer'),('computed_status','status')]:
                if fields.get(source): patch[target]=fields[source][0]
            if filters.get('catalog_type_filter') == ['Parts Manuals']:
                patch.update(entry_type='equipment',stock_import_candidate=False)
                decision['classification']='equipment'
            elif '|' in str(p.get('id')) and fields.get('equipment_category'):
                patch.update(entry_type='manual',stock_import_candidate=False)
                decision['classification']='manual_section'
            elif row.get('entry_type') == 'equipment':
                decision['classification']='equipment'; patch['stock_import_candidate']=False
            decision.update(status='confirmed',reason='Exact source product ID matched; classification uses source category or existing equipment label')
        if i in {60,1792}:
            candidate = next(c for c in json.loads((OUT/'candidate_links.json').read_text()) if c['number']==row['part_number'])
            if candidate['status'] == 200 and identifier(candidate['id']) == identifier(row['part_number']):
                decision['patch']['page_url']=candidate['url']; decision.update(status='corrected',reason='Replacement product page independently matches original number and description',candidate_evidence=candidate)
        if i == 17249:
            decision['patch'].update(page_url=None,stock_import_candidate=False,official_reference_url='https://www.coca-colaparts.com/item-details/?op=pdf&item=146652',verification_status='requires_authenticated_identity_check')
            decision.update(status='quarantined',reason='Source page ID and description belong to a different product; CCP identity remains unverified')
        if decision['status'] == 'unresolved':
            decision['patch']['stock_import_candidate'] = False
            decision['classification'] = 'needs_classification'
        decisions.append(decision)
    semaphore=asyncio.Semaphore(4)
    async with httpx.AsyncClient(timeout=12,follow_redirects=True) as client:
        async def image_check(i,row):
            value=row.get('image_url')
            if not isinstance(value,str) or not value.startswith('IMGhttps://'):return None
            url=value[3:]
            async with semaphore:
                try:
                    response=await client.head(url)
                    ct=response.headers.get('content-type','')
                    valid=response.status_code==200 and ct.startswith('image/')
                    return {'source_index':i,'source_sha256':content_hash(row),'patch':{'image_url':url} if valid else {},'status':'corrected' if valid else 'unresolved','reason':'Removed IMG prefix; HEAD confirms image' if valid else 'Image candidate not confirmed','evidence':{'url':url,'status':response.status_code,'content_type':ct,'checked_at':datetime.now(timezone.utc).isoformat()}}
                except Exception as exc:
                    return {'source_index':i,'source_sha256':content_hash(row),'patch':{},'status':'unresolved','reason':'Image candidate request failed','evidence':{'url':url,'error':type(exc).__name__}}
        decisions.extend(d for d in await asyncio.gather(*(image_check(i,r) for i,r in enumerate(rows))) if d)
    recovery_path = OUT / 'image_recovery.json'
    if recovery_path.exists():
        recoveries = {r['source_index']: r for r in json.loads(recovery_path.read_text()) if r['status'] == 'corrected'}
        for decision in decisions:
            recovery = recoveries.get(decision['source_index'])
            if recovery and 'Image' in decision['reason']:
                if recovery['source_sha256'] != decision['source_sha256']:
                    raise ValueError('Stale image recovery evidence')
                decision.update(patch=recovery['patch'], status='corrected', reason=recovery['reason'], evidence=recovery)
    (OUT/'decisions.json').write_text(json.dumps(decisions,ensure_ascii=False,indent=2))
    print(dict(Counter(d['status'] for d in decisions)), 'classified',dict(Counter(d.get('classification') for d in decisions)))

if __name__ == '__main__':asyncio.run(run())
