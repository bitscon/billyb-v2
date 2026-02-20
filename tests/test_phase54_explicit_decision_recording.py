from __future__ import annotations

import v2.core.runtime as runtime_mod


def _confirm_decision(runtime: runtime_mod.BillyRuntime, request: str, trace_prefix: str) -> None:
    capture = runtime.run_turn(request, {"trace_id": f"{trace_prefix}-capture"})
    assert capture["status"] == "success"
    assert capture["mode"] == "interactive_prompt"
    assert capture["interactive_prompt_type"] == "decision_record_capture"
    confirm = runtime.run_turn("yes", {"trace_id": f"{trace_prefix}-confirm"})
    assert confirm["status"] == "success"
    assert confirm["mode"] == "interactive_response"


def test_phase54_decision_recording_requires_confirmation_before_store():
    runtime = runtime_mod.BillyRuntime(config={})

    capture = runtime.run_turn(
        "Decision: use a minimal one-page website with no CSS.",
        {"trace_id": "trace-phase54-capture-1"},
    )

    assert capture["status"] == "success"
    assert capture["mode"] == "interactive_prompt"
    assert capture["interactive_prompt_active"] is True
    assert capture["interactive_prompt_type"] == "decision_record_capture"
    assert runtime._session_decisions == []

    decline = runtime.run_turn("no", {"trace_id": "trace-phase54-capture-2"})
    assert decline["status"] == "success"
    assert decline["mode"] == "interactive_response"
    assert runtime._session_decisions == []


def test_phase54_decision_is_referenced_and_new_decisions_append():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_decision(
        runtime,
        "Decision: use a minimal one-page website with no CSS.",
        "trace-phase54-reference-1",
    )
    _confirm_decision(runtime, "Let's go with option B.", "trace-phase54-reference-2")

    assert len(runtime._session_decisions) == 2
    assert runtime._session_decisions[0]["id"] == "decision_1"
    assert runtime._session_decisions[1]["id"] == "decision_2"

    advisory = runtime.run_turn(
        "I want to make a website and generate HTML now.",
        {"trace_id": "trace-phase54-reference-advisory"},
    )
    assert advisory["status"] == "success"
    assert advisory["mode"] == "advisory"
    assert "Based on your earlier decision (decision_2):" in str(advisory["final_output"]["message"])

    conversational = runtime.run_turn("do something", {"trace_id": "trace-phase54-reference-conversation"})
    assert conversational["status"] == "success"
    assert conversational["mode"] == "conversation_layer"
    assert "Based on your earlier decision (decision_2):" in str(conversational["final_output"])


def test_phase54_forget_latest_and_clear_decisions():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_decision(runtime, "Decision: choose option A.", "trace-phase54-reset-1")
    _confirm_decision(runtime, "Decision: choose option B.", "trace-phase54-reset-2")
    assert len(runtime._session_decisions) == 2

    forget_one = runtime.run_turn("forget that decision", {"trace_id": "trace-phase54-reset-forget"})
    assert forget_one["status"] == "success"
    assert len(runtime._session_decisions) == 1
    assert runtime._session_decisions[0]["summary"] == "choose option A."

    clear_all = runtime.run_turn("clear decisions", {"trace_id": "trace-phase54-reset-clear"})
    assert clear_all["status"] == "success"
    assert runtime._session_decisions == []

    advisory = runtime.run_turn(
        "I want to make a website and generate HTML now.",
        {"trace_id": "trace-phase54-reset-advisory"},
    )
    assert advisory["status"] == "success"
    assert advisory["mode"] == "advisory"
    assert "Based on your earlier decision" not in str(advisory["final_output"]["message"])


def test_phase54_yes_thats_the_plan_can_be_recorded_explicitly():
    runtime = runtime_mod.BillyRuntime(config={})
    runtime.run_turn("use a minimal one-page site", {"trace_id": "trace-phase54-yes-seed"})
    capture = runtime.run_turn("yes, that's the plan", {"trace_id": "trace-phase54-yes-capture"})
    assert capture["status"] == "success"
    assert capture["mode"] == "interactive_prompt"
    assert capture["interactive_prompt_type"] == "decision_record_capture"
    runtime.run_turn("yes", {"trace_id": "trace-phase54-yes-confirm"})

    assert runtime._session_decisions
    assert "Confirm prior plan:" in str(runtime._session_decisions[-1]["summary"])


def test_phase54_safety_governance_and_canonical_declarations_unchanged():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_decision(
        runtime,
        "Decision: use a minimal one-page website with no CSS.",
        "trace-phase54-safe-decision",
    )

    capability = runtime.run_turn("what can you execute?", {"trace_id": "trace-phase54-capability"})
    arming = runtime.run_turn("is execution armed?", {"trace_id": "trace-phase54-arming"})
    identity = runtime.run_turn("who are you?", {"trace_id": "trace-phase54-identity"})

    execution_attempt = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase54-exec"},
    )
    governed_action = runtime.run_turn("create a file", {"trace_id": "trace-phase54-governed"})

    assert capability["status"] == "success"
    assert capability["mode"] == "advisory"
    assert capability["final_output"]["type"] == "execution_capability_declaration"
    assert str(capability["final_output"]["message"]).startswith("No. Billy cannot execute this.")
    assert "Based on your earlier decision" not in str(capability["final_output"]["message"])

    assert arming["status"] == "success"
    assert arming["mode"] == "advisory"
    assert arming["final_output"]["type"] == "execution_arming_declaration"
    assert str(arming["final_output"]["message"]).startswith("Execution is disarmed.")
    assert "Based on your earlier decision" not in str(arming["final_output"]["message"])

    assert identity["status"] == "success"
    assert "I am Billy" in str(identity["final_output"])
    assert "Based on your earlier decision" not in str(identity["final_output"])

    assert execution_attempt["status"] == "error"
    assert execution_attempt["mode"] == "aci_intent_gatekeeper"
    assert execution_attempt["final_output"]["type"] == "refusal"

    assert governed_action["status"] == "success"
    assert governed_action["mode"] == "aci_intent_gatekeeper"
    assert governed_action["final_output"]["type"] in {"proposal", "clarification"}
