from scripts.audit_freestyle_parts import canonical


def test_freestyle_models_are_exact_and_generations_not_combined():
    assert canonical('7000 Ice Combo')=='7000 Ice Combo'
    assert canonical('7100 Ice Combo')=='7100 Ice Combo'
    assert canonical('8000 Crew-Serve')=='8000 Crew-Serve'
    assert canonical('8100 Crew-Serve')=='8100 Crew-Serve'
    assert canonical('9000 Self-Serve')=='9000 Self-Serve'
    assert canonical('9100 Self-Serve')=='9100 Self-Serve'
    assert canonical('4000 Flex Countertop')=='4000 Flex Countertop'
    assert canonical('3100 Counter Electric')=='3100 Counter Electric'
    assert canonical('7000/7100') is None
    assert canonical('Freestyle 9100') is None
    assert canonical('Viper 3 Flavor') is None
