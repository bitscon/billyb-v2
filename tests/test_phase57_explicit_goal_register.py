from __future__ import annotations

import v2.core.runtime as runtime_mod


def _confirm_goal(runtime: runtime_mod.BillyRuntime, request: str, trace_prefix: str) -> None:
    capture = runtime.run_turn(request, {"trace_id": f"{trace_prefix}-capture"})
    assert capture["status"] == "success"
    assert capture["mode"] == "interactive_prompt"
    assert capture["interactive_prompt_type"] == "goal_record_capture"
    confirm = runtime.run_turn("yes", {"trace_id": f"{trace_prefix}-confirm"})
    assert confirm["status"] == "success"
    assert confirm["mode"] == "interactive_response"


def test_phase57_goal_capture_requires_confirmation_before_store():
    runtime = runtime_mod.BillyRuntime(config={})

    capture = runtime.run_turn(
        "Goal: create a simple one-page website.",
        {"trace_id": "trace-phase57-capture-1"},
    )
    assert capture["status"] == "success"
    assert capture["mode"] == "interactive_prompt"
    assert capture["interactive_prompt_active"] is True
    assert capture["interactive_prompt_type"] == "goal_record_capture"
    assert runtime._session_goals == []

    decline = runtime.run_turn("no", {"trace_id": "trace-phase57-capture-2"})
    assert decline["status"] == "success"
    assert decline["mode"] == "interactive_response"
    assert runtime._session_goals == []


def test_phase57_goal_reference_and_list():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_goal(runtime, "Goal: create a simple one-page website.", "trace-phase57-reference")

    listed = runtime.run_turn("list goals", {"trace_id": "trace-phase57-list"})
    assert listed["status"] == "success"
    assert listed["mode"] == "conversation_layer"
    assert "Active goals (priority order):" in str(listed["final_output"])
    assert "goal_1" in str(listed["final_output"])

    advisory = runtime.run_turn(
        "I want to make a website and generate HTML now.",
        {"trace_id": "trace-phase57-reference-advisory"},
    )
    assert advisory["status"] == "success"
    assert advisory["mode"] == "advisory"
    assert "This advances your goal (goal_1):" in str(advisory["final_output"]["message"])


def test_phase57_goal_misalignment_prompts_clarification():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_goal(runtime, "Goal: create a simple one-page website.", "trace-phase57-misalignment")

    misaligned = runtime.run_turn(
        "Plan a SQL migration strategy.",
        {"trace_id": "trace-phase57-misalignment-turn"},
    )
    assert misaligned["status"] == "success"
    assert misaligned["mode"] == "conversation_layer"
    assert "Goal misalignment detected." in str(misaligned["final_output"])
    assert "update the goal or proceed anyway" in str(misaligned["final_output"]).lower()
    assert misaligned.get("goal_misalignment", {}).get("goal_id") == "goal_1"


def test_phase57_goal_update_reorder_remove_and_clear_lifecycle():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_goal(runtime, "Goal: create a simple one-page website.", "trace-phase57-lifecycle-1")
    _confirm_goal(runtime, "Goal: learn HTML basics.", "trace-phase57-lifecycle-2")
    assert len([g for g in runtime._session_goals if g.get("status") == "active"]) == 2

    reordered = runtime.run_turn("prioritize that goal", {"trace_id": "trace-phase57-lifecycle-reorder"})
    assert reordered["status"] == "success"
    listed = runtime.run_turn("list goals", {"trace_id": "trace-phase57-lifecycle-list-1"})
    assert listed["status"] == "success"
    assert "1. goal_2" in str(listed["final_output"])

    update_capture = runtime.run_turn(
        "update that goal to publish a simple landing page",
        {"trace_id": "trace-phase57-lifecycle-update-capture"},
    )
    assert update_capture["status"] == "success"
    assert update_capture["mode"] == "interactive_prompt"
    assert update_capture["interactive_prompt_type"] == "goal_record_capture"
    runtime.run_turn("yes", {"trace_id": "trace-phase57-lifecycle-update-confirm"})

    active_ids = [str(g.get("id", "")) for g in runtime._session_goals if g.get("status") == "active"]
    assert "goal_3" in active_ids
    assert len(active_ids) == 2

    removed = runtime.run_turn("remove that goal", {"trace_id": "trace-phase57-lifecycle-remove"})
    assert removed["status"] == "success"
    goal_3 = next(g for g in runtime._session_goals if str(g.get("id", "")) == "goal_3")
    assert goal_3["status"] == "inactive"

    cleared = runtime.run_turn("clear goals", {"trace_id": "trace-phase57-lifecycle-clear"})
    assert cleared["status"] == "success"
    assert runtime._latest_active_goal() is None

    listed_final = runtime.run_turn("list goals", {"trace_id": "trace-phase57-lifecycle-list-2"})
    assert listed_final["status"] == "success"
    assert "No active goals are recorded" in str(listed_final["final_output"])


def test_phase57_safety_governance_and_canonical_declarations_unchanged():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_goal(runtime, "Goal: create a simple one-page website.", "trace-phase57-safe-goal")

    capability = runtime.run_turn("what can you execute?", {"trace_id": "trace-phase57-capability"})
    arming = runtime.run_turn("is execution armed?", {"trace_id": "trace-phase57-arming"})
    identity = runtime.run_turn("who are you?", {"trace_id": "trace-phase57-identity"})

    execution_attempt = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase57-exec"},
    )
    governed_action = runtime.run_turn("create a file", {"trace_id": "trace-phase57-governed"})

    assert capability["status"] == "success"
    assert capability["mode"] == "advisory"
    assert capability["final_output"]["type"] == "execution_capability_declaration"
    assert str(capability["final_output"]["message"]).startswith("No. Billy cannot execute this.")
    assert "goal" not in str(capability["final_output"]["message"]).lower()

    assert arming["status"] == "success"
    assert arming["mode"] == "advisory"
    assert arming["final_output"]["type"] == "execution_arming_declaration"
    assert str(arming["final_output"]["message"]).startswith("Execution is disarmed.")
    assert "goal" not in str(arming["final_output"]["message"]).lower()

    assert identity["status"] == "success"
    assert "I am Billy" in str(identity["final_output"])
    assert "goal" not in str(identity["final_output"]).lower()

    assert execution_attempt["status"] == "error"
    assert execution_attempt["mode"] == "aci_intent_gatekeeper"
    assert execution_attempt["final_output"]["type"] == "refusal"

    assert governed_action["status"] == "success"
    assert governed_action["mode"] == "aci_intent_gatekeeper"
    assert governed_action["final_output"]["type"] in {"proposal", "clarification"}
