"""Build model-separated Freestyle graphs from verified audit relations."""
import json
from hashlib import sha256
from scripts.enrich_catalog_fields import ROOT,OUT,parse
from scripts.audit_freestyle_parts import MODELS,canonical
from app.services.catalog import entries

def run():
    catalog={r['part_number']:r for r in entries('parts')};audit=json.loads((ROOT/'data/organized/freestyle_parts_catalog.json').read_text());models={m:{'model_id':m.split()[0],'official_model':m,'sections':{},'part_ids':[]} for m in MODELS}
    for e in json.loads((OUT/'manual_reference_checks.json').read_text()):
        if e['status']!='confirmed':continue
        model=canonical(e['source_product_id'].split('|')[0])
        if not model:continue
        file=OUT/e['file']
        if sha256(file.read_bytes()).hexdigest()!=e['body_sha256']:raise ValueError('Manual evidence changed')
        product=parse(file.read_text());refs=[product['id']]+[ref['id'] for g in product.get('propertySets',[]) if g.get('referenceProperty')=='parts_manual_section_reference' for ref in g.get('references') or []]
        for sid in refs:
            if sid.startswith(model+'|'):models[model]['sections'].setdefault(sid,{'id':sid,'title':sid.split('|',1)[1],'part_ids':[]})
    for row in audit['parts']:
        item=catalog.get(row['part_number'])
        if not item:raise ValueError('Audited part not integrated: '+row['part_number'])
        for ref in row['official_associations']:
            model=ref['model'];g=models[model];cid=item['catalog_id']
            if cid not in g['part_ids']:g['part_ids'].append(cid)
            sid=ref.get('section_id')
            if sid and sid.startswith(model+'|'):
                section=g['sections'].setdefault(sid,{'id':sid,'title':sid.split('|',1)[1],'part_ids':[]})
                if cid not in section['part_ids']:section['part_ids'].append(cid)
    for model,g in models.items():g['sections']=list(g['sections'].values());g['official_part_count']=len(g['part_ids'])
    graph={'models':{g['model_id']:g for g in models.values()},'policy':'Explicit official directory references only. Cross-model fitment is not confirmed.'}
    target=ROOT/'data/organized/freestyle_graph.json';target.write_text(json.dumps(graph,ensure_ascii=False,indent=2));print({k:v['official_part_count'] for k,v in graph['models'].items()})
if __name__=='__main__':run()
