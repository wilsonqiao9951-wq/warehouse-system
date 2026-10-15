import json
from pathlib import Path
from scripts import audit_catalog


def test_audit_preserves_source_and_flags_conflicts(tmp_path, monkeypatch):
    parts = [
        {'part_number': ' CCP-1234 ', 'name': ' Valve ', 'page_url': 'https://example.com/CCP-1234', 'fits_equipment_models': [' Viper ', 'Viper', ''], 'parents': []},
        {'part_number': 'CCP 1234', 'name': '', 'page_url': 'javascript:bad', 'fits_equipment_models': ''},
    ]
    manuals = [{'title': 'Guide', 'page_url': 'https://example.com/model', 'equipment_models': ['Viper']}, {'title': 'Other', 'page_url': 'https://example.com/model'}]
    for kind, rows in [('parts', parts), ('manuals', manuals)]:
        (tmp_path / f'{kind}_index.json').write_text(json.dumps(rows))
    original = {p.name: p.read_bytes() for p in tmp_path.glob('*_index.json')}
    monkeypatch.setattr(audit_catalog, 'ROOT', tmp_path)
    monkeypatch.setattr(audit_catalog, 'OUT', tmp_path / 'reviewed')
    manifest = audit_catalog.run()
    assert manifest['datasets']['parts']['duplicate_number_groups'] == 1
    assert manifest['datasets']['manuals']['shared_page_groups'] == 1
    normalized = json.loads((tmp_path / 'reviewed/parts_normalized.json').read_text())
    assert normalized[0]['name'] == 'Valve'
    assert normalized[0]['fits_equipment_models'] == ['Viper']
    assert normalized[0]['normalized_part_number'] == 'CCP 1234'
    assert len(normalized) == len(parts)
    assert not any(flag == 'expected_array:fits_equipment_models' for flag in normalized[1]['quality_flags'])
    assert any(flag.startswith('invalid_or_unsafe_url') for flag in normalized[1]['quality_flags'])
    for name, content in original.items():
        assert (tmp_path / name).read_bytes() == content
