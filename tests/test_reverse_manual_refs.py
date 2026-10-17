from scripts.enrich_reverse_manual_refs import key,part_links


def test_manual_link_matching_preserves_product_and_host_identity():
    assert key('https://sites.salsify.com/product/123/123/')==key('https://sites.salsify.com/product/123/123')
    assert key('https://sites.salsify.com/product/123/123')!=key('https://sites.salsify.com/product/124/124')
    assert key('https://sites.salsify.com/product/123/123')!=key('https://images.salsify.com/product/123/123')


def test_only_explicit_part_list_links_are_extracted():
    groups=[{'properties':[{'property':'unified_catalog_part_link','values':['<a href="https://sites.salsify.com/product/123/123">123</a>']},{'property':'unified_equipment_section_reference_link','values':['<a href="https://sites.salsify.com/product/model/model">Model</a>']}]}]
    assert list(part_links(groups))==['https://sites.salsify.com/product/123/123']
