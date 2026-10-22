"""Publish explicit coverage, keeping manufacturer documents out of approved part links."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def build():
    graph=json.loads((ROOT/'data/organized/multiplex_graph.json').read_text())
    discovery=json.loads((ROOT/'data/verification/multiplex_brand_discovery.json').read_text())
    models=list(graph['models'].values())
    coverage={'scope':'All 23 equipment groups explicitly labelled MULTIPLEX in the current myCoke manual-reference index; not worldwide manufacturer completeness.','mycoke_model_count':len(models),'mycoke_model_ids':[m['model_id'] for m in models],'mycoke_confirmed_unique_parts':len({p for m in models for p in m['part_ids']}),'mycoke_sections':sum(len(m['sections']) for m in models),'worldwide_all_series_complete':False,'manufacturer_discovery':discovery,'policy':'Discovered documents are pending part-row/model review; no automatic compatibility, inventory or cross-brand joins.'}
    (ROOT/'data/organized/multiplex_coverage.json').write_text(json.dumps(coverage,ensure_ascii=False,indent=2))
    print({'models':len(models),'brand_pages':len(discovery['pages']),'pending_document_links':len(discovery['documents'])})
if __name__=='__main__':build()
