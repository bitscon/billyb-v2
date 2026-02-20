from __future__ import annotations

import v2.core.runtime as runtime_mod


def _confirm_assumption(runtime: runtime_mod.BillyRuntime, request: str, trace_prefix: str) -> None:
    capture = runtime.run_turn(request, {"trace_id": f"{trace_prefix}-capture"})
    assert capture["status"] == "success"
    assert capture["mode"] == "interactive_prompt"
    assert capture["interactive_prompt_type"] == "assumption_record_capture"
    confirm = runtime.run_turn("yes", {"trace_id": f"{trace_prefix}-confirm"})
    assert confirm["status"] == "success"
    assert confirm["mode"] == "interactive_response"


def _confirm_decision(runtime: runtime_mod.BillyRuntime, request: str, trace_prefix: str) -> None:
    capture = runtime.run_turn(request, {"trace_id": f"{trace_prefix}-capture"})
    assert capture["status"] == "success"
    assert capture["mode"] == "interactive_prompt"
    assert capture["interactive_prompt_type"] == "decision_record_capture"
    confirm = runtime.run_turn("yes", {"trace_id": f"{trace_prefix}-confirm"})
    assert confirm["status"] == "success"
    assert confirm["mode"] == "interactive_response"


def test_phase55_assumption_capture_requires_confirmation_before_store():
    runtime = runtime_mod.BillyRuntime(config={})

    capture = runtime.run_turn(
        "Assume this is just a local site.",
        {"trace_id": "trace-phase55-capture-1"},
    )

    assert capture["status"] == "success"
    assert capture["mode"] == "interactive_prompt"
    assert capture["interactive_prompt_active"] is True
    assert capture["interactive_prompt_type"] == "assumption_record_capture"
    assert runtime._session_assumptions == []

    decline = runtime.run_turn("no", {"trace_id": "trace-phase55-capture-2"})
    assert decline["status"] == "success"
    assert decline["mode"] == "interactive_response"
    assert runtime._session_assumptions == []


def test_phase55_assumption_is_referenced_in_later_responses():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_assumption(runtime, "Let's assume no CSS for now.", "trace-phase55-reference")

    advisory = runtime.run_turn(
        "I want to make a website and generate HTML now.",
        {"trace_id": "trace-phase55-reference-advisory"},
    )
    assert advisory["status"] == "success"
    assert advisory["mode"] == "advisory"
    assert "Based on our assumption (assumption_1):" in str(advisory["final_output"]["message"])

    conversational = runtime.run_turn("do something", {"trace_id": "trace-phase55-reference-conversation"})
    assert conversational["status"] == "success"
    assert conversational["mode"] == "conversation_layer"
    assert "Based on our assumption (assumption_1):" in str(conversational["final_output"])


def test_phase55_assumption_change_confirm_and_forget_behaviors():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_assumption(runtime, "Assume this is local-only.", "trace-phase55-change-initial")
    assert runtime._session_assumptions[0]["status"] == "active"

    change_capture = runtime.run_turn(
        "change that assumption to this may be deployed",
        {"trace_id": "trace-phase55-change-capture"},
    )
    assert change_capture["status"] == "success"
    assert change_capture["mode"] == "interactive_prompt"
    assert change_capture["interactive_prompt_type"] == "assumption_record_capture"
    runtime.run_turn("yes", {"trace_id": "trace-phase55-change-confirm"})

    assert len(runtime._session_assumptions) == 2
    assert runtime._session_assumptions[0]["status"] == "inactive"
    assert runtime._session_assumptions[1]["status"] == "active"

    confirm_latest = runtime.run_turn("confirm that assumption", {"trace_id": "trace-phase55-confirm-latest"})
    assert confirm_latest["status"] == "success"
    assert runtime._session_assumptions[1]["confirmed"] is True

    forget_latest = runtime.run_turn("forget that assumption", {"trace_id": "trace-phase55-forget-latest"})
    assert forget_latest["status"] == "success"
    assert runtime._session_assumptions[1]["status"] == "inactive"
    assert runtime._latest_active_assumption() is None

    clear_all = runtime.run_turn("clear assumptions", {"trace_id": "trace-phase55-clear-all"})
    assert clear_all["status"] == "success"
    assert runtime._latest_active_assumption() is None


def test_phase55_yes_assumption_works_can_be_recorded_explicitly():
    runtime = runtime_mod.BillyRuntime(config={})
    runtime.run_turn("Use a local-only setup for now.", {"trace_id": "trace-phase55-yes-seed"})
    capture = runtime.run_turn("yes, that assumption works", {"trace_id": "trace-phase55-yes-capture"})
    assert capture["status"] == "success"
    assert capture["mode"] == "interactive_prompt"
    assert capture["interactive_prompt_type"] == "assumption_record_capture"
    runtime.run_turn("yes", {"trace_id": "trace-phase55-yes-confirm"})

    assert runtime._session_assumptions
    assert "Confirm prior assumption:" in str(runtime._session_assumptions[-1]["summary"])


def test_phase55_assumptions_and_decisions_remain_distinct():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_assumption(runtime, "Assume this is local-only.", "trace-phase55-distinct-assumption")
    _confirm_decision(runtime, "Decision: use a minimal one-page website.", "trace-phase55-distinct-decision")

    assert runtime._session_assumptions
    assert runtime._session_decisions
    assert runtime._session_assumptions[0]["id"].startswith("assumption_")
    assert runtime._session_decisions[0]["id"].startswith("decision_")

    advisory = runtime.run_turn(
        "I want to make a website and generate HTML now.",
        {"trace_id": "trace-phase55-distinct-advisory"},
    )
    assert advisory["status"] == "success"
    assert advisory["mode"] == "advisory"
    message = str(advisory["final_output"]["message"])
    assert "Based on our assumption (assumption_1):" in message
    assert "Based on your earlier decision (decision_1):" in message


def test_phase55_safety_governance_and_canonical_declarations_unchanged():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_assumption(runtime, "Assume this is local-only.", "trace-phase55-safe-assumption")

    capability = runtime.run_turn("what can you execute?", {"trace_id": "trace-phase55-capability"})
    arming = runtime.run_turn("is execution armed?", {"trace_id": "trace-phase55-arming"})
    identity = runtime.run_turn("who are you?", {"trace_id": "trace-phase55-identity"})

    execution_attempt = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase55-exec"},
    )
    governed_action = runtime.run_turn("create a file", {"trace_id": "trace-phase55-governed"})

    assert capability["status"] == "success"
    assert capability["mode"] == "advisory"
    assert capability["final_output"]["type"] == "execution_capability_declaration"
    assert str(capability["final_output"]["message"]).startswith("No. Billy cannot execute this.")
    assert "Based on our assumption" not in str(capability["final_output"]["message"])

    assert arming["status"] == "success"
    assert arming["mode"] == "advisory"
    assert arming["final_output"]["type"] == "execution_arming_declaration"
    assert str(arming["final_output"]["message"]).startswith("Execution is disarmed.")
    assert "Based on our assumption" not in str(arming["final_output"]["message"])

    assert identity["status"] == "success"
    assert "I am Billy" in str(identity["final_output"])
    assert "Based on our assumption" not in str(identity["final_output"])

    assert execution_attempt["status"] == "error"
    assert execution_attempt["mode"] == "aci_intent_gatekeeper"
    assert execution_attempt["final_output"]["type"] == "refusal"

    assert governed_action["status"] == "success"
    assert governed_action["mode"] == "aci_intent_gatekeeper"
    assert governed_action["final_output"]["type"] in {"proposal", "clarification"}
