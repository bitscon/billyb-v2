from __future__ import annotations

import copy

import v2.core.runtime as runtime_mod


def _confirm_goal(runtime: runtime_mod.BillyRuntime, request: str, trace_prefix: str) -> None:
    capture = runtime.run_turn(request, {"trace_id": f"{trace_prefix}-capture"})
    assert capture["status"] == "success"
    assert capture["mode"] == "interactive_prompt"
    assert capture["interactive_prompt_type"] == "goal_record_capture"
    confirm = runtime.run_turn("yes", {"trace_id": f"{trace_prefix}-confirm"})
    assert confirm["status"] == "success"
    assert confirm["mode"] == "interactive_response"


def _confirm_constraint(runtime: runtime_mod.BillyRuntime, request: str, trace_prefix: str) -> None:
    capture = runtime.run_turn(request, {"trace_id": f"{trace_prefix}-capture"})
    assert capture["status"] == "success"
    assert capture["mode"] == "interactive_prompt"
    assert capture["interactive_prompt_type"] == "constraint_record_capture"
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


def _confirm_assumption(runtime: runtime_mod.BillyRuntime, request: str, trace_prefix: str) -> None:
    capture = runtime.run_turn(request, {"trace_id": f"{trace_prefix}-capture"})
    assert capture["status"] == "success"
    assert capture["mode"] == "interactive_prompt"
    assert capture["interactive_prompt_type"] == "assumption_record_capture"
    confirm = runtime.run_turn("yes", {"trace_id": f"{trace_prefix}-confirm"})
    assert confirm["status"] == "success"
    assert confirm["mode"] == "interactive_response"


def test_phase58_unified_boundary_response_renders_required_sections():
    runtime = runtime_mod.BillyRuntime(config={})
    runtime.run_turn(
        "I want to make an html file called phase58.html",
        {"trace_id": "trace-phase58-seed"},
    )

    result = runtime.run_turn(
        "Explain the execution boundary",
        {"trace_id": "trace-phase58-sections"},
    )

    assert result["status"] == "success"
    assert result["mode"] == "advisory"
    assert result["execution_enabled"] is False
    assert result["advisory_only"] is True
    assert result["tool_calls"] == []

    final_output = result["final_output"]
    assert final_output["type"] == "execution_boundary_unification"
    assert final_output["contract_version"] == "phase58.execution_boundary_unification.v1"
    assert final_output["boundary_read_only"] is True
    assert final_output["execution_boundary_notice"] == "Billy cannot execute actions in this system."

    rendered = str(final_output.get("rendered_advisory", ""))
    assert "Executive Summary" in rendered
    assert "Capability Boundary" in rendered
    assert "Arming Boundary" in rendered
    assert "Readiness Boundary" in rendered
    assert "Intent Alignment" in rendered
    assert "Decision & Assumption Context" in rendered
    assert "Hypothetical Enablement (Conceptual Only)" in rendered
    assert "Execution Boundary Notice" in rendered


def test_phase58_boundary_unification_is_deterministic_and_side_effect_free():
    runtime = runtime_mod.BillyRuntime(config={})
    runtime.run_turn(
        "I want to make an html file called deterministic58.html",
        {"trace_id": "trace-phase58-deterministic-seed"},
    )
    _confirm_goal(runtime, "Goal: create a simple one-page website.", "trace-phase58-deterministic-goal")
    _confirm_constraint(runtime, "Constraint: no CSS.", "trace-phase58-deterministic-constraint")
    _confirm_decision(runtime, "Decision: use a single static page.", "trace-phase58-deterministic-decision")
    _confirm_assumption(runtime, "Assume this remains local-only.", "trace-phase58-deterministic-assumption")

    before_artifacts = copy.deepcopy(runtime._task_artifacts)
    before_goals = copy.deepcopy(runtime._session_goals)
    before_constraints = copy.deepcopy(runtime._session_constraints)
    before_decisions = copy.deepcopy(runtime._session_decisions)
    before_assumptions = copy.deepcopy(runtime._session_assumptions)

    first = runtime.run_turn("why can't you execute?", {"trace_id": "trace-phase58-deterministic-1"})
    second = runtime.run_turn("why can't you execute?", {"trace_id": "trace-phase58-deterministic-2"})

    after_artifacts = copy.deepcopy(runtime._task_artifacts)
    after_goals = copy.deepcopy(runtime._session_goals)
    after_constraints = copy.deepcopy(runtime._session_constraints)
    after_decisions = copy.deepcopy(runtime._session_decisions)
    after_assumptions = copy.deepcopy(runtime._session_assumptions)

    assert first["status"] == "success"
    assert second["status"] == "success"
    assert first["final_output"] == second["final_output"]
    assert (
        first["final_output"]["boundary_fingerprint"]
        == second["final_output"]["boundary_fingerprint"]
    )
    assert before_artifacts == after_artifacts
    assert before_goals == after_goals
    assert before_constraints == after_constraints
    assert before_decisions == after_decisions
    assert before_assumptions == after_assumptions


def test_phase58_boundary_uses_current_session_state_and_readiness_blockers():
    runtime = runtime_mod.BillyRuntime(config={})
    _confirm_goal(runtime, "Goal: publish a simple one-page site.", "trace-phase58-state-goal")
    _confirm_constraint(runtime, "Constraint: local-only.", "trace-phase58-state-constraint")
    _confirm_decision(runtime, "Decision: keep rollout manual.", "trace-phase58-state-decision")
    _confirm_assumption(runtime, "Assume no CSS for now.", "trace-phase58-state-assumption")

    runtime._upsert_task_artifact(
        name="html_page",
        artifact_type="html_page",
        content={
            "filename": "broken_phase58.html",
            "html": "<html><body><p>broken",
            "include_style": False,
        },
        summary="Broken html for phase58 boundary checks.",
        source_mode="advisory",
    )
    boundary = runtime.run_turn(
        "what's blocking execution right now?",
        {"trace_id": "trace-phase58-state-query"},
    )

    assert boundary["status"] == "success"
    assert boundary["mode"] == "advisory"
    final_output = boundary["final_output"]

    readiness = final_output["readiness_boundary"]
    assert readiness["ready"] is False
    assert readiness["blocking_issues"]

    intent = final_output["intent_alignment"]
    assert intent["active_goals"]
    assert intent["active_constraints"]
    assert intent["goal_constraint_conflicts"]
    assert intent["goal_constraint_conflicts"][0]["goal_id"] == "goal_1"
    assert intent["goal_constraint_conflicts"][0]["constraint_id"] == "constraint_1"

    context = final_output["decision_assumption_context"]
    assert context["key_decisions"]
    assert context["key_assumptions"]
    assert context["key_decisions"][0]["id"] == "decision_1"
    assert context["key_assumptions"][0]["id"] == "assumption_1"


def test_phase58_governance_and_canonical_capability_arming_declarations_unchanged():
    runtime = runtime_mod.BillyRuntime(config={})

    boundary = runtime.run_turn("could this ever run?", {"trace_id": "trace-phase58-boundary"})
    capability = runtime.run_turn("what can you execute?", {"trace_id": "trace-phase58-capability"})
    arming = runtime.run_turn("is execution armed?", {"trace_id": "trace-phase58-arming"})

    execution_attempt = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase58-exec"},
    )
    governed_action = runtime.run_turn("create a file", {"trace_id": "trace-phase58-governed"})

    assert boundary["status"] == "success"
    assert boundary["mode"] == "advisory"
    assert boundary["final_output"]["type"] == "execution_boundary_unification"

    assert capability["status"] == "success"
    assert capability["mode"] == "advisory"
    assert capability["final_output"]["type"] == "execution_capability_declaration"
    assert str(capability["final_output"]["message"]).startswith("No. Billy cannot execute this.")

    assert arming["status"] == "success"
    assert arming["mode"] == "advisory"
    assert arming["final_output"]["type"] == "execution_arming_declaration"
    assert str(arming["final_output"]["message"]).startswith("Execution is disarmed.")

    assert execution_attempt["status"] == "error"
    assert execution_attempt["mode"] == "aci_intent_gatekeeper"
    assert execution_attempt["final_output"]["type"] == "refusal"

    assert governed_action["status"] == "success"
    assert governed_action["mode"] == "aci_intent_gatekeeper"
    assert governed_action["final_output"]["type"] in {"proposal", "clarification"}
