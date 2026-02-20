from __future__ import annotations

import v2.core.runtime as runtime_mod


def _confirm_role(runtime: runtime_mod.BillyRuntime, request: str, trace_prefix: str) -> None:
    capture = runtime.run_turn(request, {"trace_id": f"{trace_prefix}-capture"})
    assert capture["status"] == "success"
    assert capture["mode"] == "interactive_prompt"
    assert capture["interactive_prompt_type"] == "role_framing_capture"
    confirm = runtime.run_turn("yes", {"trace_id": f"{trace_prefix}-confirm"})
    assert confirm["status"] == "success"


def test_phase52_role_capture_requires_confirmation_before_store():
    runtime = runtime_mod.BillyRuntime(config={})

    capture = runtime.run_turn(
        "act like a senior engineer",
        {"trace_id": "trace-phase52-capture-1"},
    )

    assert capture["status"] == "success"
    assert capture["mode"] == "interactive_prompt"
    assert capture["interactive_prompt_active"] is True
    assert capture["interactive_prompt_type"] == "role_framing_capture"
    assert runtime._session_role is None

    decline = runtime.run_turn("no", {"trace_id": "trace-phase52-capture-2"})
    assert decline["status"] == "success"
    assert decline["mode"] == "interactive_response"
    assert runtime._session_role is None


def test_phase52_role_applies_to_conversation_and_advisory_framing():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_role(runtime, "act like a senior engineer", "trace-phase52-apply")

    conversational = runtime.run_turn("do something", {"trace_id": "trace-phase52-apply-convo"})
    assert conversational["status"] == "success"
    assert conversational["mode"] == "conversation_layer"
    assert str(conversational["final_output"]).startswith("Senior Engineer framing:")

    advisory = runtime.run_turn(
        "I want to make a website and generate HTML now.",
        {"trace_id": "trace-phase52-apply-advisory"},
    )
    assert advisory["status"] == "success"
    assert advisory["mode"] == "advisory"
    assert str(advisory["final_output"]["message"]).startswith("Senior Engineer perspective:")
    assert str(advisory["final_output"]["continuation_question"]).startswith(
        "From a senior engineer perspective,"
    )


def test_phase52_reset_role_clears_session_role():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_role(runtime, "explain this as a teacher", "trace-phase52-reset")
    assert runtime._session_role == "teacher"

    reset = runtime.run_turn("reset role", {"trace_id": "trace-phase52-reset-clear"})
    assert reset["status"] == "success"
    assert runtime._session_role is None

    advisory = runtime.run_turn(
        "I want to make a website and generate HTML now.",
        {"trace_id": "trace-phase52-reset-advisory"},
    )
    assert advisory["status"] == "success"
    assert advisory["mode"] == "advisory"
    assert not str(advisory["final_output"]["message"]).startswith("Teacher perspective:")
    assert not str(advisory["final_output"]["continuation_question"]).startswith(
        "From a teacher perspective,"
    )


def test_phase52_override_replaces_role_after_confirmation():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_role(runtime, "explain this as a teacher", "trace-phase52-override-initial")
    assert runtime._session_role == "teacher"

    override_prompt = runtime.run_turn(
        "switch to architect mode",
        {"trace_id": "trace-phase52-override-prompt"},
    )
    assert override_prompt["status"] == "success"
    assert override_prompt["mode"] == "interactive_prompt"
    assert override_prompt["interactive_prompt_type"] == "role_framing_capture"
    runtime.run_turn("yes", {"trace_id": "trace-phase52-override-confirm"})

    assert runtime._session_role == "architect"
    follow_up = runtime.run_turn("do something", {"trace_id": "trace-phase52-override-check"})
    assert follow_up["status"] == "success"
    assert str(follow_up["final_output"]).startswith("Architect framing:")


def test_phase52_safety_governance_and_canonical_declarations_unchanged():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_role(runtime, "talk to me like a product manager", "trace-phase52-safe-role")

    capability = runtime.run_turn("what can you execute?", {"trace_id": "trace-phase52-capability"})
    arming = runtime.run_turn("is execution armed?", {"trace_id": "trace-phase52-arming"})
    identity = runtime.run_turn("who are you?", {"trace_id": "trace-phase52-identity"})

    execution_attempt = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase52-exec"},
    )
    governed_action = runtime.run_turn("create a file", {"trace_id": "trace-phase52-governed"})

    assert capability["status"] == "success"
    assert capability["mode"] == "advisory"
    assert capability["final_output"]["type"] == "execution_capability_declaration"
    assert str(capability["final_output"]["message"]).startswith("No. Billy cannot execute this.")
    assert "perspective:" not in str(capability["final_output"]["message"]).lower()

    assert arming["status"] == "success"
    assert arming["mode"] == "advisory"
    assert arming["final_output"]["type"] == "execution_arming_declaration"
    assert str(arming["final_output"]["message"]).startswith("Execution is disarmed.")
    assert "perspective:" not in str(arming["final_output"]["message"]).lower()

    assert identity["status"] == "success"
    assert "I am Billy" in str(identity["final_output"])
    assert "framing:" not in str(identity["final_output"]).lower()

    assert execution_attempt["status"] == "error"
    assert execution_attempt["mode"] == "aci_intent_gatekeeper"
    assert execution_attempt["final_output"]["type"] == "refusal"

    assert governed_action["status"] == "success"
    assert governed_action["mode"] == "aci_intent_gatekeeper"
    assert governed_action["final_output"]["type"] in {"proposal", "clarification"}
