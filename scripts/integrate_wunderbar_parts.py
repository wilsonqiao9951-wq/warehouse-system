"""Validate WUNDER-BAR evidence and generate stable supplemental IDs and exact-model graphs."""
import json
from hashlib import sha256
from scripts.enrich_catalog_fields import ROOT,OUT,parse
from app.services.catalog import entries

def run():
    directory=ROOT/'data/organized';audit=json.loads((directory/'wunderbar_parts_catalog.json').read_text())
    existing={r['part_number']:r for r in entries('parts') if not r['catalog_id'].startswith('official-wunderbar-')}
    additions=[];models={m:{'model_id':mid,'official_model':m,'sections':{},'part_ids':[]} for m,mid in [('(Crew) Space Saver Variety Tea Tower', 'crew-space-saver-variety-tea-tower'), ('(Crew) Variety Tea Tower (Space Saver)', 'crew-variety-tea-tower-space-saver'), ('(VTT) Variety Tea Tower', 'vtt-variety-tea-tower')]}
    checks=json.loads((OUT/'wunderbar_20261018/manual_checks.json').read_text())
    for model in models:
        check=next((e for e in checks if e.get('source_product_id')==model and e.get('identity_confirmed')),None)
        if not check:raise ValueError('Manufacturer evidence missing: '+model)
        raw=(OUT/'wunderbar_20261018'/check['file']).read_bytes()
        if sha256(raw).hexdigest()!=check['body_sha256']:raise ValueError('Manufacturer evidence hash mismatch')
        fields={f['property']:f['values'] for f in parse(raw.decode()).get('filterProperties',[]) if f}
        if fields.get('manufacturer_name_display')!=['WUNDER-BAR']:raise ValueError('Manufacturer not Wunder-Bar: '+model)
        models[model]['manufacturer']='WUNDER-BAR'
        models[model]['category']=fields.get('equipment_category',[])
        models[model]['manufacturer_evidence']=check
    for m,g in models.items():
        for sid in json.loads((directory/'wunderbar'/f"{g['model_id']}.json").read_text())['sections']:g['sections'][sid]={'id':sid,'title':sid.split('|',1)[1],'part_ids':[]}
    for row in audit['parts']:
        e=row['fresh_evidence'];file=OUT/'wunderbar_20261018'/e['file']
        if row['source_status']!='confirmed' or sha256(file.read_bytes()).hexdigest()!=e['body_sha256'] or parse(file.read_text()).get('id')!=row['part_number']:raise ValueError('Unverified WUNDER-BAR product')
        for a in row['official_associations']:
            e2=a['manual_evidence'];page=OUT/'wunderbar_20261018'/e2['file']
            if a['model'] not in models or a['section_id'] not in models[a['model']]['sections'] or sha256(page.read_bytes()).hexdigest()!=e2['body_sha256']:raise ValueError('Invalid section evidence')
        local=existing.get(row['part_number']);cid=local['catalog_id'] if local else 'official-wunderbar-'+row['part_number']
        if not local:
            item={k:row.get(k) for k in ['part_number','name','description','page_url','image_url','manufacturer','manufacturer_part','cona_material_number']}
            item.update(catalog_id=cid,classification='part_candidate',entry_type='part',stock_import_candidate=True,fits_equipment_models=row['models'],official_associations=row['official_associations'],verification=[{'status':'confirmed','evidence':e,'reason':'Exact WUNDER-BAR official part identity and chapter reference'}],_organization={'source_file':'wunderbar_new_official_parts.json','source_index':None,'content_id':sha256(row['part_number'].encode()).hexdigest(),'classification':'part_candidate'})
            additions.append(item)
        for a in row['official_associations']:
            g=models[a['model']]
            if cid not in g['part_ids']:g['part_ids'].append(cid)
            section=g['sections'][a['section_id']]
            if cid not in section['part_ids']:section['part_ids'].append(cid)
    source=OUT/'wunderbar_new_official_parts.json';source.write_text(json.dumps([r for r in audit['parts'] if r['part_number'] not in existing],ensure_ascii=False,indent=2))
    data=directory/'wunderbar_added_parts.json';data.write_text(json.dumps(additions,ensure_ascii=False,indent=2))
    (directory/'wunderbar_added_manifest.json').write_text(json.dumps({'source_file':source.name,'source_sha256':sha256(source.read_bytes()).hexdigest(),'data_sha256':sha256(data.read_bytes()).hexdigest(),'count':len(additions)},indent=2))
    for g in models.values():g['sections']=list(g['sections'].values());g['official_part_count']=len(g['part_ids'])
    (directory/'wunderbar_graph.json').write_text(json.dumps({'models':{g['model_id']:g for g in models.values()},'policy':'Explicit official WUNDER-BAR model/section associations only; never infer cross-model fitment.'},ensure_ascii=False,indent=2))
    print({'additions':len(additions),'models':{g['model_id']:g['official_part_count'] for g in models.values()}})
if __name__=='__main__':run()
