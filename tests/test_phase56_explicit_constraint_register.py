from __future__ import annotations

import v2.core.runtime as runtime_mod


def _confirm_constraint(runtime: runtime_mod.BillyRuntime, request: str, trace_prefix: str) -> None:
    capture = runtime.run_turn(request, {"trace_id": f"{trace_prefix}-capture"})
    assert capture["status"] == "success"
    assert capture["mode"] == "interactive_prompt"
    assert capture["interactive_prompt_type"] == "constraint_record_capture"
    confirm = runtime.run_turn("yes", {"trace_id": f"{trace_prefix}-confirm"})
    assert confirm["status"] == "success"
    assert confirm["mode"] == "interactive_response"


def test_phase56_constraint_capture_requires_confirmation_before_store():
    runtime = runtime_mod.BillyRuntime(config={})

    capture = runtime.run_turn("Constraint: no CSS.", {"trace_id": "trace-phase56-capture-1"})
    assert capture["status"] == "success"
    assert capture["mode"] == "interactive_prompt"
    assert capture["interactive_prompt_active"] is True
    assert capture["interactive_prompt_type"] == "constraint_record_capture"
    assert runtime._session_constraints == []

    decline = runtime.run_turn("no", {"trace_id": "trace-phase56-capture-2"})
    assert decline["status"] == "success"
    assert decline["mode"] == "interactive_response"
    assert runtime._session_constraints == []


def test_phase56_constraint_reference_and_list():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_constraint(runtime, "Constraint: one-page site only.", "trace-phase56-reference")

    listed = runtime.run_turn("list constraints", {"trace_id": "trace-phase56-list"})
    assert listed["status"] == "success"
    assert listed["mode"] == "conversation_layer"
    assert "Active constraints:" in str(listed["final_output"])
    assert "constraint_1" in str(listed["final_output"])

    advisory = runtime.run_turn(
        "I want to make a website and generate HTML now.",
        {"trace_id": "trace-phase56-reference-advisory"},
    )
    assert advisory["status"] == "success"
    assert advisory["mode"] == "advisory"
    assert "This respects your active constraint (constraint_1):" in str(advisory["final_output"]["message"])


def test_phase56_constraint_conflict_detection_prompts_clarification():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_constraint(runtime, "Constraint: no CSS.", "trace-phase56-conflict")

    conflict = runtime.run_turn(
        "Please add CSS styling and bootstrap.",
        {"trace_id": "trace-phase56-conflict-turn"},
    )
    assert conflict["status"] == "success"
    assert conflict["mode"] == "conversation_layer"
    assert "Constraint conflict detected." in str(conflict["final_output"])
    assert "revise or remove that constraint" in str(conflict["final_output"]).lower()
    assert conflict.get("constraint_conflict", {}).get("constraint_id") == "constraint_1"


def test_phase56_constraint_change_remove_and_clear_lifecycle():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_constraint(runtime, "Constraint: one-page site only.", "trace-phase56-lifecycle-initial")
    assert runtime._session_constraints[0]["status"] == "active"

    change_capture = runtime.run_turn(
        "change that constraint to local-only",
        {"trace_id": "trace-phase56-lifecycle-change-capture"},
    )
    assert change_capture["status"] == "success"
    assert change_capture["mode"] == "interactive_prompt"
    assert change_capture["interactive_prompt_type"] == "constraint_record_capture"
    runtime.run_turn("yes", {"trace_id": "trace-phase56-lifecycle-change-confirm"})

    assert len(runtime._session_constraints) == 2
    assert runtime._session_constraints[0]["status"] == "inactive"
    assert runtime._session_constraints[1]["status"] == "active"

    removed = runtime.run_turn("remove that constraint", {"trace_id": "trace-phase56-lifecycle-remove"})
    assert removed["status"] == "success"
    assert runtime._session_constraints[1]["status"] == "inactive"
    assert runtime._latest_active_constraint() is None

    cleared = runtime.run_turn("clear constraints", {"trace_id": "trace-phase56-lifecycle-clear"})
    assert cleared["status"] == "success"
    assert runtime._latest_active_constraint() is None

    listed = runtime.run_turn("list constraints", {"trace_id": "trace-phase56-lifecycle-list"})
    assert listed["status"] == "success"
    assert "No active constraints are recorded" in str(listed["final_output"])


def test_phase56_safety_governance_and_canonical_declarations_unchanged():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_constraint(runtime, "Constraint: local-only.", "trace-phase56-safe-constraint")

    capability = runtime.run_turn("what can you execute?", {"trace_id": "trace-phase56-capability"})
    arming = runtime.run_turn("is execution armed?", {"trace_id": "trace-phase56-arming"})
    identity = runtime.run_turn("who are you?", {"trace_id": "trace-phase56-identity"})

    execution_attempt = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase56-exec"},
    )
    governed_action = runtime.run_turn("create a file", {"trace_id": "trace-phase56-governed"})

    assert capability["status"] == "success"
    assert capability["mode"] == "advisory"
    assert capability["final_output"]["type"] == "execution_capability_declaration"
    assert str(capability["final_output"]["message"]).startswith("No. Billy cannot execute this.")
    assert "constraint" not in str(capability["final_output"]["message"]).lower()

    assert arming["status"] == "success"
    assert arming["mode"] == "advisory"
    assert arming["final_output"]["type"] == "execution_arming_declaration"
    assert str(arming["final_output"]["message"]).startswith("Execution is disarmed.")
    assert "constraint" not in str(arming["final_output"]["message"]).lower()

    assert identity["status"] == "success"
    assert "I am Billy" in str(identity["final_output"])
    assert "constraint" not in str(identity["final_output"]).lower()

    assert execution_attempt["status"] == "error"
    assert execution_attempt["mode"] == "aci_intent_gatekeeper"
    assert execution_attempt["final_output"]["type"] == "refusal"

    assert governed_action["status"] == "success"
    assert governed_action["mode"] == "aci_intent_gatekeeper"
    assert governed_action["final_output"]["type"] in {"proposal", "clarification"}
