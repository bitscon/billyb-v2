import core.runtime as runtime_mod


def test_identity_guard_rewrites_third_person_references():
    runtime = runtime_mod.BillyRuntime(config={})
    raw = (
        "Billy must get approval. "
        "Billy can only do that if Chad agrees. "
        "Billy should wait."
    )
    normalized = runtime._identity_guard("irrelevant", raw)
    lowered = normalized.lower()

    assert "billy must" not in lowered
    assert "billy can only" not in lowered
    assert "billy should" not in lowered
    assert "I must" in normalized
    assert "I can only" in normalized
    assert "I should" in normalized
    assert "Chad" not in normalized
    assert "you" in normalized
