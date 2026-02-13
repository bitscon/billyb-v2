import v2.core.command_interpreter as interpreter


def _set_flags(*, phase3: bool, phase4: bool, phase4_explain: bool, phase5: bool, phase8: bool) -> None:
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


def test_freeform_reply_then_operational_request_reenters_governed_pipeline():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        first = interpreter.process_conversational_turn(
            "tell me a joke",
            llm_responder=lambda _u, _e: "Here is a joke.",
        )
        assert first["response"] == "Here is a joke."
        assert first["next_state"] == "ready_for_input"
        assert first["governed_result"]["type"] == "no_action"
        assert first["governed_result"]["envelope"]["lane"] == "CHAT"

        second = interpreter.process_conversational_turn(
            "save that joke in a text file in your home directory",
            llm_responder=lambda _u, _e: "unused",
        )
        governed = second["governed_result"]
        assert governed["type"] == "approval_required"
        assert governed["envelope"]["lane"] == "PLAN"
        assert second["next_state"] == "ready_for_input"
        assert "interaction rejected" not in second["response"].lower()
        assert interpreter.get_execution_events() == []
    finally:
        _teardown()


def test_llm_reply_does_not_create_terminal_mode(monkeypatch):
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        original = interpreter.process_user_message
        calls = {"count": 0}

        def _spy(utterance: str):
            calls["count"] += 1
            return original(utterance)

        monkeypatch.setattr(interpreter, "process_user_message", _spy)

        first = interpreter.process_conversational_turn(
            "tell me a joke",
            llm_responder=lambda _u, _e: "joke",
        )
        second = interpreter.process_conversational_turn(
            "save that joke in a text file in your home directory",
            llm_responder=lambda _u, _e: "unused",
        )

        assert calls["count"] == 2
        assert first["next_state"] == "ready_for_input"
        assert second["next_state"] == "ready_for_input"
        assert first["governed_result"]["type"] == "no_action"
        assert second["governed_result"]["type"] == "approval_required"
    finally:
        _teardown()


def test_ambiguous_input_after_llm_reply_routes_to_clarify():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        interpreter.process_conversational_turn(
            "tell me a joke",
            llm_responder=lambda _u, _e: "joke",
        )
        second = interpreter.process_conversational_turn(
            "qzv blorp",
            llm_responder=lambda _u, _e: "unused",
        )
        governed = second["governed_result"]
        assert governed["type"] == "no_action"
        assert governed["envelope"]["lane"] == "CLARIFY"
        assert second["next_state"] == "ready_for_input"
        assert "clarify" in second["response"].lower()
        assert "interaction rejected" not in second["response"].lower()
    finally:
        _teardown()


def test_deprecated_input_after_llm_reply_does_not_block_pipeline():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        interpreter.process_conversational_turn(
            "tell me a joke",
            llm_responder=lambda _u, _e: "joke",
        )
        deprecated = interpreter.process_conversational_turn(
            "/engineer",
            llm_responder=lambda _u, _e: "unused",
        )
        assert deprecated["governed_result"]["type"] == "mode_info"
        assert "deprecated" in deprecated["response"].lower()
        assert deprecated["next_state"] == "ready_for_input"

        routed = interpreter.process_conversational_turn(
            "save that joke in a text file in your home directory",
            llm_responder=lambda _u, _e: "unused",
        )
        assert routed["governed_result"]["type"] == "approval_required"
        assert routed["governed_result"]["envelope"]["lane"] == "PLAN"
        assert "interaction rejected" not in routed["response"].lower()
    finally:
        _teardown()
