"""Fill empty model relations using exact part links in verified manual pages."""
import json
from collections import Counter,defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from scripts.enrich_catalog_fields import ROOT,OUT,parse

class Links(HTMLParser):
    def __init__(self):super().__init__();self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a':
            href=dict(attrs).get('href')
            if href:self.links.append(href)

def key(url):
    p=urlsplit(url or '')
    return p.netloc.lower(),p.path.rstrip('/')

def part_links(groups):
    for group in groups:
        for prop in group.get('properties',[]):
            if prop.get('property')!='unified_catalog_part_link':continue
            for value in prop.get('values',[]):
                if isinstance(value,str):
                    parser=Links();parser.feed(value)
                    yield from parser.links

def run():
    rows=json.loads((ROOT/'data/organized/parts_catalog.json').read_text())
    ds=json.loads((OUT/'field_enrichment.json').read_text());by={d['source_index']:d for d in ds}
    targets={key(r['page_url']):r for r in rows if r.get('page_url') and not r.get('fits_equipment_models') and r['_organization']['classification']=='part_candidate' and r.get('verification_status')!='requires_authenticated_identity_check'}
    matches=defaultdict(list);manuals=0;pages=[]
    for row in rows:
        kind=row['_organization']['classification']
        if kind not in {'equipment','manual_section'}:continue
        d=by.get(row['_organization']['source_index']);file=d.get('evidence',{}).get('file') if d else None
        if not file or d['status']!='confirmed':continue
        product=parse((OUT/file).read_text())
        if product.get('id')!=d['evidence'].get('source_product_id'):continue
        pages.append((kind,product,d['evidence']))
    check_path=OUT/'manual_reference_checks.json'
    if check_path.exists():
        for evidence in json.loads(check_path.read_text()):
            if evidence['status']=='confirmed':
                product=parse((OUT/evidence['file']).read_text())
                pages.append((evidence.get('classification','equipment'),product,evidence))
    for kind,product,page_evidence in pages:
        manuals+=1
        sections=[(product['id'],product.get('propertySets',[]))]
        if kind=='equipment':
            for group in product.get('propertySets',[]):
                for ref in group.get('references') or []:
                    if group.get('referenceProperty')=='parts_manual_section_reference' and ref.get('id','').startswith(product['id']+'|'):
                        sections.append((ref['id'],[ref]))
        for section,groups in sections:
            model=section.split('|',1)[0]
            for url in part_links(groups):
                target=targets.get(key(url))
                if not target:continue
                index=target['_organization']['source_index']
                identity=by.get(index)
                if not identity or identity['status']!='confirmed':continue
                evidence={'equipment_model':model,'source_reference_id':section,'part_link':url,'manual_evidence':page_evidence}
                if evidence not in matches[index]:matches[index].append(evidence)
    output=[]
    for index,refs in sorted(matches.items()):
        d=by[index]
        output.append({'source_index':index,'source_sha256':d['source_sha256'],'status':'confirmed','reason':'Exact part URL explicitly listed in identity-verified official manual section','patch':{'fits_equipment_models':list(dict.fromkeys(r['equipment_model'] for r in refs))},'evidence':d['evidence'],'equipment_reference_evidence':refs})
    path=OUT/'reverse_manual_enrichment.json'
    if path.exists():
        prior={d['source_index']:d for d in json.loads(path.read_text())};prior.update({d['source_index']:d for d in output});output=list(prior.values())
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2))
    summary={'verified_manual_pages_examined':manuals,'parts_enriched':len(output),'model_relations':sum(len(d['patch']['fits_equipment_models']) for d in output)}
    (OUT/'reverse_manual_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary))

if __name__=='__main__':run()
