import v2.core.command_interpreter as interpreter


def _set_flags(
    *,
    phase3: bool,
    phase4: bool,
    phase4_explain: bool,
    phase5: bool,
    phase8: bool,
) -> None:
    interpreter.set_phase3_enabled(phase3)
    interpreter.set_phase4_enabled(phase4)
    interpreter.set_phase4_explanation_enabled(phase4_explain)
    interpreter.set_phase5_enabled(phase5)
    interpreter.set_phase8_enabled(phase8)
    interpreter.set_phase8_approval_mode("step")


def _teardown() -> None:
    _set_flags(phase3=False, phase4=False, phase4_explain=False, phase5=False, phase8=False)
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()


def test_natural_language_action_routes_to_governed_approval_not_rejected():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        response = interpreter.process_user_message("save that joke in a text file in your home directory")
        assert response["type"] == "approval_required"
        assert response["executed"] is False
        assert response["envelope"]["lane"] == "PLAN"
        assert "interaction rejected" not in response.get("message", "").lower()
        assert interpreter.get_execution_events() == []
    finally:
        _teardown()


def test_legacy_rejection_strings_never_appear_in_conversational_path():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        responses = [
            interpreter.process_user_message("save that joke in a text file in your home directory"),
            interpreter.process_user_message("engineer mode"),
            interpreter.process_user_message("/engineer"),
            interpreter.process_user_message("qzv blorp"),
        ]
    finally:
        _teardown()

    for response in responses:
        text = str(response.get("message", "")).lower()
        assert "interaction rejected" not in text
        assert "explicit governed trigger" not in text


def test_engineer_mode_is_deprecated_but_does_not_block_followup_execution():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        info = interpreter.process_user_message("engineer mode")
        assert info["type"] == "mode_info"
        assert info["executed"] is False
        assert "deprecated" in info["message"].lower()
        assert "approvals are requested automatically" in info["message"].lower()

        routed = interpreter.process_user_message("save that joke in a text file in your home directory")
        assert routed["type"] == "approval_required"
        assert routed["executed"] is False
    finally:
        _teardown()


def test_engineer_slash_is_deprecated_but_does_not_block_followup_execution():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        info = interpreter.process_user_message("/engineer")
        assert info["type"] == "mode_info"
        assert info["executed"] is False
        assert "deprecated" in info["message"].lower()

        routed = interpreter.process_user_message("save that joke in a text file in your home directory")
        assert routed["type"] == "approval_required"
        assert routed["executed"] is False
    finally:
        _teardown()


def test_ambiguous_input_routes_to_clarify_without_execution():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        response = interpreter.process_user_message("qzv blorp")
        assert response["type"] == "no_action"
        assert response["executed"] is False
        assert response["envelope"]["lane"] == "CLARIFY"
        assert interpreter.get_execution_events() == []
    finally:
        _teardown()


def test_no_execution_occurs_without_explicit_approval():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        response = interpreter.process_user_message("save that joke in a text file in your home directory")
        assert response["type"] == "approval_required"
        assert response["executed"] is False
        assert interpreter.get_execution_events() == []
        assert interpreter.get_tool_invocations() == []
    finally:
        _teardown()


def test_phase9_transcript_regression_inputs_route_governed():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        first = interpreter.process_user_message("save that joke in a text file in your home directory")
        assert first["type"] == "approval_required"
        assert first["executed"] is False

        # Reset pending state to verify independent routing behavior for follow-up transcript lines.
        interpreter.reset_phase5_state()

        second = interpreter.process_user_message("engineer mode")
        assert second["type"] == "mode_info"
        assert second["executed"] is False

        third = interpreter.process_user_message("/engineer")
        assert third["type"] == "mode_info"
        assert third["executed"] is False
    finally:
        _teardown()
