from scripts.audit_viper_parts import canonical


def test_viper_models_remain_separate_and_unknown_variants_not_inferred():
    assert canonical('Viper-3-Flavor')=='Viper 3 Flavor'
    assert canonical('Viper 2 Flavor')=='Viper 2 Flavor'
    assert canonical('Viper 4 Flavor')=='Viper 4 Flavor'
    assert canonical('Viper Carts')=='Viper Carts'
    assert canonical('Viper 3') is None
    assert canonical('Viper 3 Flavor|Cladding') is None
    assert canonical('Viper 3/4 Flavor') is None
