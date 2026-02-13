import json

import v2.core.command_interpreter as interpreter


def _enable_phase3():
    interpreter.set_phase3_enabled(True)


def _disable_phase3():
    interpreter.set_phase3_enabled(False)


def test_successful_extraction_populates_intent_and_entities(monkeypatch):
    utterance = "help me understand billy configuration"
    phase2 = interpreter._interpret_phase2(utterance)

    def _fake_call(_utterance, _envelope):
        return json.dumps(
            {
                "intent": "help.configure_billy",
                "entities": [
                    {"name": "subject", "value": "billy configuration"},
                ],
                "confidence": 0.91,
            }
        )

    monkeypatch.setattr(interpreter, "_call_llm_for_intent_json", _fake_call)
    _enable_phase3()
    try:
        actual = interpreter.interpret_utterance(utterance)
    finally:
        _disable_phase3()

    assert actual["lane"] == phase2["lane"]
    assert actual["intent"] == "help.configure_billy"
    assert actual["entities"] == [{"name": "subject", "value": "billy configuration"}]
    assert actual["confidence"] == 0.91
    assert actual["policy"]["allowed"] == phase2["policy"]["allowed"]
    assert actual["requires_approval"] == phase2["requires_approval"]


def test_invalid_json_triggers_retry(monkeypatch):
    utterance = "help me understand billy configuration"
    attempts = []
    responses = [
        "not-json",
        json.dumps(
            {
                "intent": "help.configure_billy",
                "entities": [],
                "confidence": 0.87,
            }
        ),
    ]

    def _fake_call(_utterance, _envelope):
        attempts.append(1)
        return responses[min(len(attempts) - 1, len(responses) - 1)]

    monkeypatch.setattr(interpreter, "_call_llm_for_intent_json", _fake_call)
    _enable_phase3()
    try:
        actual = interpreter.interpret_utterance(utterance)
    finally:
        _disable_phase3()

    assert len(attempts) == 2
    assert actual["intent"] == "help.configure_billy"
    assert actual["entities"] == []
    assert actual["confidence"] == 0.87


def test_repeated_failure_triggers_phase2_fallback(monkeypatch):
    utterance = "help me understand billy configuration"
    phase2 = interpreter._interpret_phase2(utterance)
    attempts = []

    def _fake_call(_utterance, _envelope):
        attempts.append(1)
        return "still-not-json"

    monkeypatch.setattr(interpreter, "_call_llm_for_intent_json", _fake_call)
    _enable_phase3()
    try:
        actual = interpreter.interpret_utterance(utterance)
    finally:
        _disable_phase3()

    assert len(attempts) == interpreter._PHASE3_MAX_RETRIES
    assert actual == phase2


def test_lane_is_never_altered_by_phase3(monkeypatch):
    utterance = "help me understand billy configuration"
    phase2 = interpreter._interpret_phase2(utterance)

    def _fake_call(_utterance, _envelope):
        return json.dumps(
            {
                "lane": "PLAN",
                "intent": "plan.force_change",
                "entities": [],
                "confidence": 0.95,
                "requires_approval": True,
                "policy": {"risk_level": "critical", "allowed": False, "reason": "force"},
            }
        )

    monkeypatch.setattr(interpreter, "_call_llm_for_intent_json", _fake_call)
    _enable_phase3()
    try:
        actual = interpreter.interpret_utterance(utterance)
    finally:
        _disable_phase3()

    assert actual["lane"] == phase2["lane"]
    assert actual["policy"]["allowed"] == phase2["policy"]["allowed"]
    assert actual["requires_approval"] == phase2["requires_approval"]


def test_phase3_disabled_returns_phase2_unchanged(monkeypatch):
    utterance = "help me understand billy configuration"
    phase2 = interpreter._interpret_phase2(utterance)

    def _should_not_call(_utterance, _envelope):
        raise AssertionError("LLM extraction should not run when Phase 3 is disabled.")

    monkeypatch.setattr(interpreter, "_call_llm_for_intent_json", _should_not_call)
    _disable_phase3()
    actual = interpreter.interpret_utterance(utterance)

    assert actual == phase2
