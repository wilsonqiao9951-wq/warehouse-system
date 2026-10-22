from scripts.enrich_catalog_fields import inspect


def test_fields_require_exact_identity_and_explicit_model_references():
    raw={'part_number':'123','name':'','description':'','fits_equipment_models':[]}
    product={'id':'123','listTitle':'123','listSubtitle':'VALVE FOR SOMETHING', 'propertySets':[{'label':'Parts Manuals Referencing This Part','references':[{'id':'Verified Model|Assembly','properties':[]}]}]}
    result=inspect(raw,0,product,{'url':'https://example.com/123'})
    assert result['patch']['name']=='VALVE FOR SOMETHING'
    assert result['patch']['description']=='VALVE FOR SOMETHING'
    assert result['patch']['fits_equipment_models']==['Verified Model']
    assert result['equipment_reference_evidence'][0]['source_reference_id']=='Verified Model|Assembly'
    product['id']='124'
    mismatch=inspect(raw,0,product,{})
    assert mismatch['status']=='quarantined'
    assert mismatch['patch']=={'stock_import_candidate':False}


def test_no_model_is_inferred_from_name_and_existing_fields_are_preserved():
    raw={'part_number':'123','name':'Existing name','description':'Existing description','fits_equipment_models':[]}
    result=inspect(raw,0,{'id':'123','listSubtitle':'VIPER MOTOR','propertySets':[]},{})
    assert result['patch']=={}


def test_section_slug_alias_requires_both_model_and_section_to_match():
    raw={'part_number':'Viper-3-FlavororFoam-PackDrive-Assembly','name':'Resource'}
    product={'id':'Viper 3 Flavor|Foam Pack/Drive Assembly','propertySets':[{'properties':[{'property':'equipment_category','values':['Frozen']}]}]}
    result=inspect(raw,0,product,{})
    assert result['status']=='confirmed'
    assert result['classification']=='manual_section'
    assert result['patch']['stock_import_candidate'] is False
    product['id']='Viper 4 Flavor|Foam Pack/Drive Assembly'
    assert inspect(raw,0,product,{})['status']=='quarantined'


def test_all_previous_identity_conflicts_are_confirmed_sections():
    import json
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    reviews=json.loads((root/'data/verification/identity_review_round2.json').read_text())
    assert len(reviews)==26
    for review in reviews:
        assert review['status']=='confirmed'
        assert review['classification']=='manual_section'
        assert review['patch']['stock_import_candidate'] is False


def test_unreachable_source_does_not_fill_fields_or_allow_import():
    result=inspect({'part_number':'123','name':'Existing'},0,{}, {'http_status':404})
    assert result['status']=='unresolved'
    assert result['patch']=={'stock_import_candidate':False}


def test_ccp_alias_requires_exact_legacy_and_numeric_identity():
    raw={'part_number':'958174','name':'CCP 958174 DROPPER'}
    p={'id':'CCP 958174','propertySets':[{'properties':[{'property':'legacy_material_number','values':['958174']}]}]}
    assert inspect(raw,0,p,{})['status']=='confirmed'
    p['propertySets'][0]['properties'][0]['values']=['958175']
    assert inspect(raw,0,p,{})['status']=='quarantined'
    p['id']='CCP 958175'
    assert inspect(raw,0,p,{})['status']=='quarantined'


def test_equipment_qualification_requires_full_name_and_manual_type():
    raw={'part_number':'C77006','name':'C77006 (Bevariety and Freestyle)'}
    p={'id':raw['name'],'filterProperties':[{'property':'catalog_type_filter','values':['Parts Manuals']}]}
    r=inspect(raw,0,p,{})
    assert r['status']=='confirmed' and r['classification']=='equipment'
    assert r['patch']['stock_import_candidate'] is False
    p['id']='C77006 (Different Model)'
    assert inspect(raw,0,p,{})['status']=='quarantined'
    p['id']=raw['name'];p['filterProperties']=[]
    assert inspect(raw,0,p,{})['status']=='quarantined'
