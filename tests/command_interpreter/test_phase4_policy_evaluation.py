import v2.core.command_interpreter as interpreter


def _set_phase_flags(*, phase3: bool, phase4: bool, explanation: bool) -> None:
    interpreter.set_phase3_enabled(phase3)
    interpreter.set_phase4_enabled(phase4)
    interpreter.set_phase4_explanation_enabled(explanation)


def test_known_intents_produce_expected_policy_decisions():
    _set_phase_flags(phase3=False, phase4=True, explanation=False)
    try:
        chat = interpreter.interpret_utterance("what is a cool thing to drink?")
        assert chat["lane"] == "CHAT"
        assert chat["policy"]["allowed"] is True
        assert chat["policy"]["risk_level"] == "low"
        assert chat["requires_approval"] is False

        plan = interpreter.interpret_utterance("create an empty text file in your home directory")
        assert plan["lane"] == "PLAN"
        assert plan["policy"]["allowed"] is True
        assert plan["policy"]["risk_level"] == "medium"
        assert plan["requires_approval"] is True
    finally:
        _set_phase_flags(phase3=False, phase4=False, explanation=False)


def test_unknown_intent_defaults_to_denied_and_requires_approval(monkeypatch):
    baseline = interpreter._interpret_phase3("what is a cool thing to drink?")
    custom = dict(baseline)
    custom["intent"] = "unknown.intent"

    monkeypatch.setattr(interpreter, "_interpret_phase3", lambda _utterance: custom)
    _set_phase_flags(phase3=False, phase4=True, explanation=False)
    try:
        result = interpreter.interpret_utterance("ignored")
    finally:
        _set_phase_flags(phase3=False, phase4=False, explanation=False)

    assert result["intent"] == "unknown.intent"
    assert result["policy"]["allowed"] is False
    assert result["policy"]["risk_level"] == "critical"
    assert result["requires_approval"] is True


def test_explanation_failure_does_not_change_policy_outcome(monkeypatch):
    utterance = "create an empty text file in your home directory"
    _set_phase_flags(phase3=False, phase4=True, explanation=False)
    deterministic = interpreter.interpret_utterance(utterance)

    monkeypatch.setattr(interpreter, "_call_llm_for_policy_reason", lambda _e, _p: "not-json")
    _set_phase_flags(phase3=False, phase4=True, explanation=True)
    try:
        explained = interpreter.interpret_utterance(utterance)
    finally:
        _set_phase_flags(phase3=False, phase4=False, explanation=False)

    assert explained["lane"] == deterministic["lane"]
    assert explained["policy"]["allowed"] == deterministic["policy"]["allowed"]
    assert explained["policy"]["risk_level"] == deterministic["policy"]["risk_level"]
    assert explained["requires_approval"] == deterministic["requires_approval"]
    assert explained["policy"]["reason"] == deterministic["policy"]["reason"]


def test_phase4_disable_returns_phase3_output_unchanged():
    utterance = "help me understand billy configuration"
    _set_phase_flags(phase3=False, phase4=False, explanation=False)
    phase3_output = interpreter._interpret_phase3(utterance)
    result = interpreter.interpret_utterance(utterance)

    assert result == phase3_output
