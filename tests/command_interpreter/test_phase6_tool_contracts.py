import v2.core.command_interpreter as interpreter


def _set_flags(*, phase3: bool, phase4: bool, phase4_explain: bool, phase5: bool) -> None:
    interpreter.set_phase3_enabled(phase3)
    interpreter.set_phase4_enabled(phase4)
    interpreter.set_phase4_explanation_enabled(phase4_explain)
    interpreter.set_phase5_enabled(phase5)


def _action_request() -> str:
    return "create an empty text file in your home directory"


def test_intents_map_to_exactly_one_tool_contract():
    registry = interpreter.get_tool_contract_registry()

    assert "plan.create_empty_file" in registry
    assert "plan.user_action_request" in registry
    assert len(registry) == len(set(registry.keys()))
    for intent, contract in registry.items():
        assert contract.intent == intent
        assert contract.tool_name
        assert isinstance(contract.side_effects, bool)


def test_unknown_intent_cannot_resolve_tool_contract():
    assert interpreter._resolve_tool_contract("plan.unknown_intent") is None


def test_execution_cannot_occur_without_phase5_approval():
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True)
    try:
        response = interpreter.process_user_message(_action_request())
        assert response["type"] == "approval_required"
        assert response["executed"] is False
        assert interpreter.get_tool_invocations() == []
        assert interpreter.get_execution_events() == []
    finally:
        _set_flags(phase3=False, phase4=False, phase4_explain=False, phase5=False)
        interpreter.reset_phase5_state()


def test_approved_execution_invokes_stub_backend_exactly_once():
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True)
    try:
        interpreter.process_user_message(_action_request())
        response = interpreter.process_user_message("approve")
        assert response["type"] == "executed"
        assert response["executed"] is True

        invocations = interpreter.get_tool_invocations()
        assert len(invocations) == 1
        assert invocations[0]["intent"] == "plan.create_empty_file"
        assert invocations[0]["tool_name"] == "stub.filesystem.create_empty_file"
    finally:
        _set_flags(phase3=False, phase4=False, phase4_explain=False, phase5=False)
        interpreter.reset_phase5_state()


def test_execution_events_are_recorded_and_auditable():
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True)
    try:
        interpreter.process_user_message(_action_request())
        response = interpreter.process_user_message("approve")
        assert response["type"] == "executed"
        events = interpreter.get_execution_events()
        assert len(events) == 1

        event = events[0]
        assert isinstance(event["event_id"], str) and event["event_id"]
        assert isinstance(event["action_id"], str) and event["action_id"]
        assert isinstance(event["executed_at"], str) and event["executed_at"]
        assert event["status"] == "executed_stub"
        assert event["tool_contract"]["tool_name"] == "stub.filesystem.create_empty_file"
        assert event["tool_contract"]["intent"] == "plan.create_empty_file"
        assert event["tool_result"]["status"] == "stubbed"
    finally:
        _set_flags(phase3=False, phase4=False, phase4_explain=False, phase5=False)
        interpreter.reset_phase5_state()


def test_missing_tool_contract_fails_safely_after_approval(monkeypatch):
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True)
    try:
        monkeypatch.setattr(interpreter, "_resolve_tool_contract", lambda _intent: None)
        interpreter.process_user_message(_action_request())
        response = interpreter.process_user_message("approve")
        assert response["type"] == "execution_rejected"
        assert response["executed"] is False
        assert interpreter.get_execution_events() == []
        assert interpreter.get_tool_invocations() == []
    finally:
        _set_flags(phase3=False, phase4=False, phase4_explain=False, phase5=False)
        interpreter.reset_phase5_state()
