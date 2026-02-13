import v2.core.command_interpreter as interpreter


def _set_flags(*, phase3: bool, phase4: bool, phase4_explain: bool, phase5: bool, phase8: bool) -> None:
    interpreter.set_phase3_enabled(phase3)
    interpreter.set_phase4_enabled(phase4)
    interpreter.set_phase4_explanation_enabled(phase4_explain)
    interpreter.set_phase5_enabled(phase5)
    interpreter.set_phase8_enabled(phase8)
    interpreter.set_phase8_approval_mode("step")


def _action_request() -> str:
    return "create an empty text file in your home directory"


def _teardown() -> None:
    _set_flags(phase3=False, phase4=False, phase4_explain=False, phase5=False, phase8=False)
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()


def test_memory_advisory_summary_refers_to_history_correctly(monkeypatch):
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        # success: explicit empty file intent
        interpreter.process_user_message(_action_request())
        success_result = interpreter.process_user_message("approve")
        assert success_result["type"] == "executed"

        # success: generic action request intent
        interpreter.process_user_message("create a project note")
        success_generic = interpreter.process_user_message("approve")
        assert success_generic["type"] == "executed"

        # failure: unresolved contract
        monkeypatch.setattr(interpreter, "_resolve_tool_contract", lambda _intent: None)
        interpreter.process_user_message(_action_request())
        failed_result = interpreter.process_user_message("approve")
        assert failed_result["type"] == "execution_rejected"

        summary = interpreter.get_memory_advisory_summary(limit=20)
        assert summary["type"] == "memory_advisory_summary"
        assert summary["advisory_only"] is True
        assert summary["events_considered"] == 3
        assert summary["outcomes"]["success_count"] == 2
        assert summary["outcomes"]["failure_count"] == 1
        assert summary["outcomes"]["success_rate"] == 0.67
        intents = {item["intent"] for item in summary["by_intent"]}
        assert "plan.create_empty_file" in intents
        assert "plan.user_action_request" in intents
        assert all(suggestion.startswith("Suggestion:") for suggestion in summary["suggestions"])
    finally:
        _teardown()


def test_advisory_does_not_change_policy_or_append_memory():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        baseline = interpreter.interpret_utterance(_action_request())
        memory_before = interpreter.get_memory_events_last(50)
        report = interpreter.get_memory_advisory_report(limit=20)
        after = interpreter.interpret_utterance(_action_request())
        memory_after = interpreter.get_memory_events_last(50)

        assert report["advisory_only"] is True
        assert baseline["policy"] == after["policy"]
        assert baseline["requires_approval"] == after["requires_approval"]
        assert memory_before == memory_after
        assert interpreter.get_pending_action() is None
        assert interpreter.get_pending_plan() is None
    finally:
        _teardown()


def test_advisory_context_does_not_enable_unapproved_action():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        _report = interpreter.get_memory_advisory_report(limit=10)
        execution_events_before = len(interpreter.get_execution_events())
        tool_invocations_before = len(interpreter.get_tool_invocations())

        response = interpreter.process_user_message(_action_request())
        assert response["type"] == "approval_required"
        assert response["executed"] is False
        assert len(interpreter.get_execution_events()) == execution_events_before
        assert len(interpreter.get_tool_invocations()) == tool_invocations_before
    finally:
        _teardown()


def test_llm_advisory_output_is_structured_and_contextual():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        interpreter.process_user_message(_action_request())
        interpreter.process_user_message("approve")

        report = interpreter.get_memory_advisory_report(
            limit=10,
            llm_explainer=lambda summary, patterns: {
                "explanation": (
                    f"Based on {summary['events_considered']} event(s), "
                    f"{patterns['events_considered']} event(s) were reviewed for patterns."
                ),
                "suggestions": [
                    "Review repeated intents before approving high-risk actions.",
                    "Keep explicit approvals in place for all state-changing tasks.",
                ],
            },
        )

        llm_context = report["llm_context"]
        assert isinstance(llm_context["explanation"], str)
        assert "event(s)" in llm_context["explanation"]
        assert isinstance(llm_context["suggestions"], list)
        assert len(llm_context["suggestions"]) == 2
        assert all(text.startswith("Suggestion:") for text in llm_context["suggestions"])
        assert "advisory only" in report["safety_note"].lower()
    finally:
        _teardown()
