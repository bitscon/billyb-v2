from v2.billy_engineering.enforcement import detect_engineering_intent


def test_engineering_intent_explicit_only():
    assert detect_engineering_intent("/engineer build a thing") is True
    assert detect_engineering_intent("/plan build a thing") is False
    assert detect_engineering_intent("engineer this") is False
    assert detect_engineering_intent("Billy, engineer this") is False
    assert detect_engineering_intent("please implement X") is False
