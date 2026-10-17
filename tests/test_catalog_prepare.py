import json
from scripts import prepare_catalog


def test_prepare_preserves_source_and_records_transformations(tmp_path, monkeypatch):
    rows = [{'part_number': 'CCP-1234', 'name': ' Valve ', 'image_url': 'placeholder', 'fits_equipment_models': '', 'parents': ['a','a']}]
    for kind, values in [('parts',rows),('manuals',[{'title':'Guide','manual_pdf_url':'https://example.com/guide.pdf'}])]:
        (tmp_path / f'{kind}_index.json').write_text(json.dumps(values))
    source = (tmp_path / 'parts_index.json').read_bytes()
    monkeypatch.setattr(prepare_catalog, 'ROOT',tmp_path)
    monkeypatch.setattr(prepare_catalog, 'OUT',tmp_path / 'organized')
    prepare_catalog.prepare()
    row = json.loads((tmp_path / 'organized/parts_catalog.json').read_text())[0]
    assert row['name'] == 'Valve'
    assert row['image_url'] is None
    assert row['fits_equipment_models'] == []
    assert row['parents'] == ['a']
    assert row['normalized_part_number'] == 'CCP 1234'
    assert row['_organization']['unusable_url_fields'] == ['image_url']
    assert (tmp_path / 'parts_index.json').read_bytes() == source


def test_single_model_string_is_wrapped_without_guessing(tmp_path, monkeypatch):
    (tmp_path / 'parts_index.json').write_text('[]')
    (tmp_path / 'manuals_index.json').write_text(json.dumps([{'title':'Guide','equipment_models':'Model A / Model B'}]))
    monkeypatch.setattr(prepare_catalog,'ROOT',tmp_path)
    monkeypatch.setattr(prepare_catalog,'OUT',tmp_path / 'organized')
    prepare_catalog.prepare()
    row=json.loads((tmp_path / 'organized/manuals_catalog.json').read_text())[0]
    assert row['equipment_models']==['Model A / Model B']
