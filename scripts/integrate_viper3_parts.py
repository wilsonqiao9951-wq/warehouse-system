"""Integrate only verified Viper 3 additions without changing raw indices or IDs."""
import json
from hashlib import sha256
from scripts.enrich_catalog_fields import ROOT,OUT,parse

MODEL='Viper 3 Flavor'
def run():
    source=OUT/'viper_new_official_parts.json';records=json.loads(source.read_text());out=[]
    for row in records:
        if MODEL not in row['models']:continue
        evidence=row['fresh_evidence'];page=OUT/evidence['file']
        if row['source_status']!='confirmed' or sha256(page.read_bytes()).hexdigest()!=evidence['body_sha256']:raise ValueError('Unverified source')
        p=parse(page.read_text())
        if p['id']!=row['part_number']:raise ValueError('Product identity mismatch')
        refs=[ref for ref in row['official_associations'] if ref['model']==MODEL]
        item={k:row.get(k) for k in ('part_number','name','description','page_url','image_url','manufacturer','manufacturer_part','cona_material_number')}
        item.update(catalog_id='official-viper3-'+row['part_number'],classification='part_candidate',entry_type='part',stock_import_candidate=True,fits_equipment_models=[MODEL],official_associations=refs,verification=[{'status':'confirmed','evidence':evidence,'reason':'Exact official product ID and explicit Viper 3 section reference'}],_organization={'source_file':'viper_new_official_parts.json','source_index':None,'content_id':sha256(row['part_number'].encode()).hexdigest(),'classification':'part_candidate'})
        out.append(item)
    directory=ROOT/'data/organized';(directory/'viper3_added_parts.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
    manifest={'source_file':'viper_new_official_parts.json','source_sha256':sha256(source.read_bytes()).hexdigest(),'data_sha256':sha256((directory/'viper3_added_parts.json').read_bytes()).hexdigest(),'count':len(out)}
    (directory/'viper3_added_manifest.json').write_text(json.dumps(manifest,indent=2));print(manifest['count'])
if __name__=='__main__':run()
