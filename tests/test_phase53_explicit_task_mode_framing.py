from __future__ import annotations

import v2.core.runtime as runtime_mod


def _confirm_task_mode(runtime: runtime_mod.BillyRuntime, request: str, trace_prefix: str) -> None:
    capture = runtime.run_turn(request, {"trace_id": f"{trace_prefix}-capture"})
    assert capture["status"] == "success"
    assert capture["mode"] == "interactive_prompt"
    assert capture["interactive_prompt_type"] == "task_mode_capture"
    confirm = runtime.run_turn("yes", {"trace_id": f"{trace_prefix}-confirm"})
    assert confirm["status"] == "success"


def test_phase53_task_mode_capture_requires_confirmation_before_store():
    runtime = runtime_mod.BillyRuntime(config={})

    capture = runtime.run_turn(
        "let's brainstorm",
        {"trace_id": "trace-phase53-capture-1"},
    )

    assert capture["status"] == "success"
    assert capture["mode"] == "interactive_prompt"
    assert capture["interactive_prompt_active"] is True
    assert capture["interactive_prompt_type"] == "task_mode_capture"
    assert runtime._session_task_mode is None

    decline = runtime.run_turn("no", {"trace_id": "trace-phase53-capture-2"})
    assert decline["status"] == "success"
    assert decline["mode"] == "interactive_response"
    assert runtime._session_task_mode is None


def test_phase53_task_mode_applies_to_conversation_and_advisory_structure():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_task_mode(
        runtime,
        "walk me through this step by step",
        "trace-phase53-apply",
    )

    conversational = runtime.run_turn("do something", {"trace_id": "trace-phase53-apply-convo"})
    assert conversational["status"] == "success"
    assert conversational["mode"] == "conversation_layer"
    assert str(conversational["final_output"]).startswith("Step-by-step mode:")

    advisory = runtime.run_turn(
        "I want to make a website and generate HTML now.",
        {"trace_id": "trace-phase53-apply-advisory"},
    )
    assert advisory["status"] == "success"
    assert advisory["mode"] == "advisory"
    assert str(advisory["final_output"]["message"]).startswith("Step-by-step mode:")
    assert advisory["final_output"]["continuation_question"] == "Ready for the next step?"


def test_phase53_task_mode_reset_clears_session_mode():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_task_mode(runtime, "critique this idea", "trace-phase53-reset")
    assert runtime._session_task_mode == "critique"

    reset = runtime.run_turn("reset task mode", {"trace_id": "trace-phase53-reset-clear"})
    assert reset["status"] == "success"
    assert runtime._session_task_mode is None

    advisory = runtime.run_turn(
        "I want to make a website and generate HTML now.",
        {"trace_id": "trace-phase53-reset-advisory"},
    )
    assert advisory["status"] == "success"
    assert advisory["mode"] == "advisory"
    assert not str(advisory["final_output"]["message"]).startswith("Critique mode:")
    assert advisory["final_output"]["continuation_question"] != "Want a deeper critique pass focused on risks?"


def test_phase53_task_mode_override_replaces_mode_after_confirmation():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_task_mode(runtime, "let's brainstorm", "trace-phase53-override-initial")
    assert runtime._session_task_mode == "brainstorm"

    override_prompt = runtime.run_turn(
        "switch to compare options mode",
        {"trace_id": "trace-phase53-override-prompt"},
    )
    assert override_prompt["status"] == "success"
    assert override_prompt["mode"] == "interactive_prompt"
    assert override_prompt["interactive_prompt_type"] == "task_mode_capture"
    runtime.run_turn("yes", {"trace_id": "trace-phase53-override-confirm"})

    assert runtime._session_task_mode == "compare_options"
    follow_up = runtime.run_turn("do something", {"trace_id": "trace-phase53-override-check"})
    assert follow_up["status"] == "success"
    assert str(follow_up["final_output"]).startswith("Compare-options mode:")


def test_phase53_safety_governance_and_canonical_declarations_unchanged():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_task_mode(
        runtime,
        "summarize and recommend",
        "trace-phase53-safe-mode",
    )

    capability = runtime.run_turn("what can you execute?", {"trace_id": "trace-phase53-capability"})
    arming = runtime.run_turn("is execution armed?", {"trace_id": "trace-phase53-arming"})
    identity = runtime.run_turn("who are you?", {"trace_id": "trace-phase53-identity"})

    execution_attempt = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase53-exec"},
    )
    governed_action = runtime.run_turn("create a file", {"trace_id": "trace-phase53-governed"})

    assert capability["status"] == "success"
    assert capability["mode"] == "advisory"
    assert capability["final_output"]["type"] == "execution_capability_declaration"
    assert str(capability["final_output"]["message"]).startswith("No. Billy cannot execute this.")
    assert "mode:" not in str(capability["final_output"]["message"]).lower()

    assert arming["status"] == "success"
    assert arming["mode"] == "advisory"
    assert arming["final_output"]["type"] == "execution_arming_declaration"
    assert str(arming["final_output"]["message"]).startswith("Execution is disarmed.")
    assert "mode:" not in str(arming["final_output"]["message"]).lower()

    assert identity["status"] == "success"
    assert "I am Billy" in str(identity["final_output"])
    assert "mode:" not in str(identity["final_output"]).lower()

    assert execution_attempt["status"] == "error"
    assert execution_attempt["mode"] == "aci_intent_gatekeeper"
    assert execution_attempt["final_output"]["type"] == "refusal"

    assert governed_action["status"] == "success"
    assert governed_action["mode"] == "aci_intent_gatekeeper"
    assert governed_action["final_output"]["type"] in {"proposal", "clarification"}
