"""Serve normalized, source-preserving catalog views; SQL owns inventory."""
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path

DATA_ROOT = Path(__file__).resolve().parents[2]

@lru_cache(maxsize=1)
def _catalogs() -> dict[str, tuple[dict, ...]]:
    directory = DATA_ROOT / 'data' / 'organized'
    manifest = json.loads((directory / 'manifest.json').read_text())
    for filename, metadata in manifest['sources'].items():
        if sha256((DATA_ROOT / filename).read_bytes()).hexdigest() != metadata['sha256']:
            raise RuntimeError('Catalog sources changed; rebuild organized views before serving')
    result = {'parts': [], 'manuals': [], 'equipment': []}
    for source_kind in ('parts', 'manuals'):
        rows = json.loads((directory / f'{source_kind}_catalog.json').read_text())
        for row in rows:
            metadata = row['_organization']
            # Preserve IDs already issued by the pre-normalization API.
            catalog_id = f"{metadata['source_index']}-{metadata['content_id'][:16]}"
            classification = metadata['classification']
            target = 'equipment' if classification == 'equipment' else 'manuals' if classification == 'manual_section' else source_kind
            entry = {**row, 'catalog_id': ('section-' if target == 'manuals' and source_kind == 'parts' else '') + catalog_id}
            entry['classification'] = classification
            entry['verification'] = metadata.get('verification', [])
            if target == 'manuals' and source_kind == 'parts':
                entry['title'] = row.get('name')
                entry['manual_type'] = 'parts_section'
            result[target].append(entry)
    for prefix in ('viper3','freestyle','quest','abs','ed','md','df','db','icecombo','crewserve'):
        additions=directory/(prefix+'_added_parts.json')
        if additions.exists():
            added_manifest=json.loads((directory/(prefix+'_added_manifest.json')).read_text())
            source=DATA_ROOT/'data/verification'/added_manifest['source_file']
            if sha256(source.read_bytes()).hexdigest()!=added_manifest['source_sha256'] or sha256(additions.read_bytes()).hexdigest()!=added_manifest['data_sha256']:
                raise RuntimeError('Viper 3 additions changed; rebuild verified additions')
            existing={r['part_number'] for r in result['parts']}
            for row in json.loads(additions.read_text()):
                if row['part_number'] in existing:raise RuntimeError('Duplicate supplemental part number')
                existing.add(row['part_number']);result['parts'].append(row)
    return {kind: tuple(rows) for kind, rows in result.items()}


def entries(kind: str) -> tuple[dict, ...]:
    return _catalogs()[kind]

@lru_cache(maxsize=3)
def _search_rows(kind: str):
    fields = ('part_number', 'name', 'title', 'description', 'cona_material_number',
              'legacy_id', 'manufacturer', 'manufacturer_part', 'fits_equipment_models',
              'equipment_models', 'symptom_keywords', 'category', 'parents', 'pdf_filename')
    return tuple((row, ' '.join(str(row.get(key) or '') for key in fields).casefold()) for row in entries(kind))


def search(kind: str, query: str, skip: int, limit: int) -> dict:
    terms = query.casefold().split()
    matches = [row for row, text in _search_rows(kind) if all(term in text for term in terms)]
    return {'total': len(matches), 'skip': skip, 'limit': limit, 'items': matches[skip:skip + limit]}
