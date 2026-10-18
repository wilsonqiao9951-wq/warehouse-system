"""Validate MARMON / CORNELIUS evidence and generate stable supplemental IDs and exact-model graphs."""
import json
from hashlib import sha256
from scripts.enrich_catalog_fields import ROOT,OUT,parse
from app.services.catalog import entries

def run():
    directory=ROOT/'data/organized';audit=json.loads((directory/'cornelius_parts_catalog.json').read_text())
    existing={r['part_number']:r for r in entries('parts') if not r['catalog_id'].startswith('official-cornelius-')}
    additions=[];models={m:{'model_id':mid,'official_model':m,'sections':{},'part_ids':[]} for m,mid in [('2 Flavor (3H.P.) - V4', '2-flavor-3h-p-v4'), ('3 Valve Tower (Ceramic)', '3-valve-tower-ceramic'), ('Appex 6', 'appex-6'), ('Automated Beverage System (ABS 1.0)', 'automated-beverage-system-abs-1-0'), ('Automated Beverage System (ABS 2.0)', 'automated-beverage-system-abs-2-0'), ('CB2323 / CB1522 / CB3023 (IntelliCarb Units) Golden Corral', 'cb2323-cb1522-cb3023-golden-corral'), ('CI2000 Plus', 'ci2000-plus'), ('DB 150', 'db-150'), ('DB 200 / 275 Standard', 'db-200-275-standard'), ('DF 150', 'df-150'), ('DF 200/250', 'df-200-250'), ('ED 150', 'ed-150'), ('ED 200/250', 'ed-200-250'), ('ED 300', 'ed-300'), ('IDC255 Pro Fast Gate', 'idc255-pro-fast-gate'), ('TJ 150', 'tj-150'), ('TJ 45 / TJ 90', 'tj-45-tj-90'), ('Viper 2 Flavor', 'viper-2-flavor'), ('Viper 3 Flavor', 'viper-3-flavor'), ('Viper 4 Flavor', 'viper-4-flavor'), ('Viper Carts', 'viper-carts'), ("Backroom Package (McDonald's)", 'backroom-package-mcdonald-s'), ('CB1522 18in SABRE TOWER', 'cb1522-18in-sabre-tower'), ('CB1522D', 'cb1522d'), ('CB2323 SABRE 23in TOWER W/CDD', 'cb2323-sabre-23in-tower-w-cdd'), ("CB2323-8vlv (Wendy's)", 'cb2323-8vlv-wendy-s'), ('CB2323L SELF CLOSING LID', 'cb2323l-self-closing-lid'), ('CB2323L SLIDING LID', 'cb2323l-sliding-lid'), ('CC2323 TOWER W/ SLIDING LID', 'cc2323-tower-w-sliding-lid'), ('CC2323L SELF CLOSING LID', 'cc2323l-self-closing-lid'), ('CI2000 (Plus)', 'ci2000-plus-parenthesized'), ('DB 275 - BCP Pneumatic Ice Gate', 'db-275-bcp-pneumatic-ice-gate'), ('Energize 6', 'energize-6'), ('Leopard', 'leopard'), ('Prism', 'prism'), ('Quest 2000', 'quest-2000'), ('Quest 4000', 'quest-4000'), ('SFV - 1', 'sfv-1')]}
    checks=json.loads((OUT/'cornelius_20261018/manual_checks.json').read_text())
    for model in models:
        check=next((e for e in sorted(checks,key=lambda r:'|' in (r.get('source_product_id') or '')) if (e.get('source_product_id') or '').split('|')[0]==model and e.get('identity_confirmed')),None)
        if not check:raise ValueError('Manufacturer evidence missing: '+model)
        raw=(OUT/'cornelius_20261018'/check['file']).read_bytes()
        if sha256(raw).hexdigest()!=check['body_sha256']:raise ValueError('Manufacturer evidence hash mismatch')
        fields={f['property']:f['values'] for f in parse(raw.decode()).get('filterProperties',[]) if f}
        if fields.get('manufacturer_name_display')!=['MARMON / CORNELIUS']:raise ValueError('Manufacturer not Cornelius: '+model)
        models[model]['manufacturer']='MARMON / CORNELIUS'
        models[model]['category']=fields.get('equipment_category',[])
        models[model]['manufacturer_evidence']=check
        models[model]['manufacturer_evidence_scope']='manual_section' if '|' in check['source_product_id'] else 'equipment'
    for m,g in models.items():
        for sid in json.loads((directory/'cornelius'/f"{g['model_id']}.json").read_text())['sections']:g['sections'][sid]={'id':sid,'title':sid.split('|',1)[1],'part_ids':[]}
    for row in audit['parts']:
        e=row['fresh_evidence'];file=OUT/'cornelius_20261018'/e['file']
        if row['source_status']!='confirmed' or sha256(file.read_bytes()).hexdigest()!=e['body_sha256'] or parse(file.read_text()).get('id')!=row['part_number']:raise ValueError('Unverified MARMON / CORNELIUS product')
        for a in row['official_associations']:
            e2=a['manual_evidence'];page=OUT/'cornelius_20261018'/e2['file']
            if a['model'] not in models or a['section_id'] not in models[a['model']]['sections'] or sha256(page.read_bytes()).hexdigest()!=e2['body_sha256']:raise ValueError('Invalid section evidence')
        local=existing.get(row['part_number']);cid=local['catalog_id'] if local else 'official-cornelius-'+row['part_number']
        if not local:
            item={k:row.get(k) for k in ['part_number','name','description','page_url','image_url','manufacturer','manufacturer_part','cona_material_number']}
            item.update(catalog_id=cid,classification='part_candidate',entry_type='part',stock_import_candidate=True,fits_equipment_models=row['models'],official_associations=row['official_associations'],verification=[{'status':'confirmed','evidence':e,'reason':'Exact MARMON / CORNELIUS official part identity and chapter reference'}],_organization={'source_file':'cornelius_new_official_parts.json','source_index':None,'content_id':sha256(row['part_number'].encode()).hexdigest(),'classification':'part_candidate'})
            additions.append(item)
        for a in row['official_associations']:
            g=models[a['model']]
            if cid not in g['part_ids']:g['part_ids'].append(cid)
            section=g['sections'][a['section_id']]
            if cid not in section['part_ids']:section['part_ids'].append(cid)
    source=OUT/'cornelius_new_official_parts.json';source.write_text(json.dumps([r for r in audit['parts'] if r['part_number'] not in existing],ensure_ascii=False,indent=2))
    data=directory/'cornelius_added_parts.json';data.write_text(json.dumps(additions,ensure_ascii=False,indent=2))
    (directory/'cornelius_added_manifest.json').write_text(json.dumps({'source_file':source.name,'source_sha256':sha256(source.read_bytes()).hexdigest(),'data_sha256':sha256(data.read_bytes()).hexdigest(),'count':len(additions)},indent=2))
    for g in models.values():g['sections']=list(g['sections'].values());g['official_part_count']=len(g['part_ids'])
    (directory/'cornelius_graph.json').write_text(json.dumps({'models':{g['model_id']:g for g in models.values()},'policy':'Explicit official MARMON / CORNELIUS model/section associations only; never infer cross-model fitment.'},ensure_ascii=False,indent=2))
    print({'additions':len(additions),'models':{g['model_id']:g['official_part_count'] for g in models.values()}})
if __name__=='__main__':run()
