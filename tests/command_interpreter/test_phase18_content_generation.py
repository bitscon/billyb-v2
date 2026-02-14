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
    interpreter.set_tool_invoker(interpreter.StubToolInvoker())
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()


def test_simple_generation_routes_to_content_generation_and_returns_llm_output():
    interpreter.set_tool_invoker(interpreter.StubToolInvoker())
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        envelope = interpreter.interpret_utterance("Propose a simple HTML template for a homepage.")
        assert envelope["lane"] == "CONTENT_GENERATION"
        assert envelope["intent"] == "content_generation.draft"
        assert envelope["requires_approval"] is False

        governed = interpreter.process_user_message("Propose a simple HTML template for a homepage.")
        assert governed["type"] == "content_generation"
        assert governed["executed"] is False
        assert governed["capture_eligible"] is True
        assert governed["envelope"]["lane"] == "CONTENT_GENERATION"
        assert governed["message"] == ""

        turn = interpreter.process_conversational_turn(
            "Propose a simple HTML template for a homepage.",
            llm_responder=lambda _u, _e: "<html><body><h1>Home</h1></body></html>",
        )
        assert turn["response"] == "<html><body><h1>Home</h1></body></html>"
        assert turn["governed_result"]["type"] == "content_generation"
        assert turn["next_state"] == "ready_for_input"
    finally:
        _teardown()


def test_mixed_generation_and_execution_keywords_do_not_route_to_content_generation():
    interpreter.set_tool_invoker(interpreter.StubToolInvoker())
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        response = interpreter.process_user_message(
            'Generate a homepage template and write text "hello" to file notes.txt in my workspace'
        )
        assert response["type"] == "approval_required"
        assert response["envelope"]["lane"] == "PLAN"
        assert response["envelope"]["intent"] == "plan.user_action_request"
    finally:
        _teardown()


def test_generation_output_is_eligible_for_phase16_explicit_capture():
    interpreter.set_tool_invoker(interpreter.StubToolInvoker())
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase18-capture"
    generated_text = "<html><body><main>Landing</main></body></html>"
    try:
        first = interpreter.process_conversational_turn(
            "Propose a simple HTML template for a homepage.",
            session_id=session_id,
            llm_responder=lambda _u, _e: generated_text,
        )
        assert first["governed_result"]["type"] == "content_generation"

        captured = interpreter.process_conversational_turn(
            "capture this as homepage_template",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        governed = captured["governed_result"]
        assert governed["type"] == "content_captured"
        content_id = governed["captured_content"]["content_id"]

        stored = interpreter.get_captured_content_by_id(content_id)
        assert stored is not None
        assert stored["label"] == "homepage_template"
        assert stored["text"] == generated_text
        assert stored["source"] == "llm"
    finally:
        _teardown()


def test_content_generation_has_no_side_effects_or_approval_state():
    interpreter.set_tool_invoker(interpreter.StubToolInvoker())
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        turn = interpreter.process_conversational_turn(
            "Draft an onboarding email for new users.",
            llm_responder=lambda _u, _e: "Welcome to the platform.",
        )
        assert turn["governed_result"]["type"] == "content_generation"
        assert turn["governed_result"]["executed"] is False

        assert interpreter.get_pending_action() is None
        assert interpreter.get_pending_plan() is None
        assert interpreter.get_tool_invocations() == []
        assert interpreter.get_memory_events_last(10) == []
    finally:
        _teardown()


def test_ambiguous_generation_request_falls_back_to_clarify():
    interpreter.set_tool_invoker(interpreter.StubToolInvoker())
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        governed = interpreter.process_user_message("generate")
        assert governed["type"] == "no_action"
        assert governed["envelope"]["lane"] == "CLARIFY"
        assert "draft" in governed["envelope"]["next_prompt"].lower()

        turn = interpreter.process_conversational_turn(
            "generate",
            llm_responder=lambda _u, _e: "unused",
        )
        assert turn["governed_result"]["type"] == "no_action"
        assert turn["governed_result"]["envelope"]["lane"] == "CLARIFY"
        assert "draft" in turn["response"].lower()
    finally:
        _teardown()
