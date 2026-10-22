"""Build exact Viper 3 official section/part edges from verified page snapshots."""
import json
from hashlib import sha256
from scripts.enrich_catalog_fields import ROOT,OUT,parse
from scripts.enrich_reverse_manual_refs import key,part_links
from app.services.catalog import entries

MODEL='Viper 3 Flavor'
def run():
    rows=entries('parts')
    targets={key(r['page_url']):r for r in rows if r.get('page_url') and r['_organization']['classification']=='part_candidate'}
    checks=json.loads((OUT/'manual_reference_checks.json').read_text());sections={};equipment=[]
    for e in checks:
        if e['status']!='confirmed':continue
        p=parse((OUT/e['file']).read_text());id=p['id']
        if id!=MODEL and not id.startswith(MODEL+'|'):continue
        if sha256((OUT/e['file']).read_bytes()).hexdigest()!=e['body_sha256']:raise ValueError('Page evidence changed')
        if id==MODEL:
            equipment.append({'id':id,'page_url':e['url'],'evidence':e})
            candidates=[ref for g in p.get('propertySets',[]) if g.get('referenceProperty')=='parts_manual_section_reference' for ref in g.get('references') or []]
        else:candidates=[{'id':id,'properties':[prop for g in p.get('propertySets',[]) for prop in g.get('properties',[])]}]
        for ref in candidates:
            sid=ref['id']
            if not sid.startswith(MODEL+'|'):continue
            section=sections.setdefault(sid,{'id':sid,'title':sid.split('|',1)[1],'part_ids':[],'evidence':[]})
            section['evidence'].append(e)
            for url in part_links([ref]):
                row=targets.get(key(url))
                if row:
                    cid=row['catalog_id']
                    if cid not in section['part_ids']:section['part_ids'].append(cid)
    graph={'model_id':'viper-3','official_model':MODEL,'equipment':equipment,'sections':list(sections.values()),'policy':'Exact Viper 3 model and exact official part links; shared parts are allowed only if explicitly listed for Viper 3.'}
    (ROOT/'data/organized/viper3_graph.json').write_text(json.dumps(graph,ensure_ascii=False,indent=2))
    print({'sections':len(sections),'unique_parts':len({cid for s in sections.values() for cid in s['part_ids']})})
if __name__=='__main__':run()
