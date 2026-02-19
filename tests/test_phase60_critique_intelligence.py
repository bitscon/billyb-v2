from __future__ import annotations

import v2.core.runtime as runtime_mod


def _seed_plan(runtime: runtime_mod.BillyRuntime) -> None:
    runtime.run_turn(
        "plan a safe rollout for nginx service updates",
        {"trace_id": "trace-phase60-seed-plan"},
    )


def test_phase60_critique_is_offered_not_forced():
    runtime = runtime_mod.BillyRuntime(config={})
    _seed_plan(runtime)

    offered = runtime.run_turn(
        "this looks good",
        {"trace_id": "trace-phase60-offer"},
    )
    assert offered["status"] == "success"
    assert offered["mode"] == "interactive_prompt"
    assert offered["interactive_prompt_type"] == "critique_depth"

    fresh_runtime = runtime_mod.BillyRuntime(config={})
    not_forced = fresh_runtime.run_turn(
        "plan a safe rollout for nginx service updates",
        {"trace_id": "trace-phase60-not-forced"},
    )
    assert not_forced["status"] == "success"
    assert not_forced["mode"] == "advisory"


def test_phase60_structured_critique_sections_render():
    runtime = runtime_mod.BillyRuntime(config={})
    _seed_plan(runtime)

    runtime.run_turn("anything i'm missing?", {"trace_id": "trace-phase60-offer-2"})
    critique = runtime.run_turn("full stress test", {"trace_id": "trace-phase60-full"})

    assert critique["status"] == "success"
    assert critique["mode"] == "advisory"

    final_output = critique["final_output"]
    assert isinstance(final_output.get("key_risks"), list) and final_output["key_risks"]
    assert isinstance(final_output.get("hidden_assumptions"), list) and final_output["hidden_assumptions"]
    assert isinstance(final_output.get("goal_constraint_tensions"), list) and final_output["goal_constraint_tensions"]
    assert isinstance(final_output.get("failure_modes"), list) and final_output["failure_modes"]
    assert isinstance(final_output.get("mitigation_options"), list) and final_output["mitigation_options"]

    rendered = str(final_output.get("rendered_advisory", ""))
    assert "Key Risks:" in rendered
    assert "Hidden Assumptions:" in rendered
    assert "Goal or Constraint Tensions:" in rendered
    assert "Failure Modes:" in rendered
    assert "Mitigation Options:" in rendered


def test_phase60_critique_uses_goal_and_constraint_context():
    runtime = runtime_mod.BillyRuntime(config={})

    goal_capture = runtime.run_turn(
        "goal: keep rollout reliability high",
        {"trace_id": "trace-phase60-goal-capture"},
    )
    assert goal_capture["interactive_prompt_type"] == "goal_record_capture"
    runtime.run_turn("yes", {"trace_id": "trace-phase60-goal-confirm"})

    constraint_capture = runtime.run_turn(
        "constraint: no downtime",
        {"trace_id": "trace-phase60-constraint-capture"},
    )
    assert constraint_capture["interactive_prompt_type"] == "constraint_record_capture"
    runtime.run_turn("yes", {"trace_id": "trace-phase60-constraint-confirm"})

    _seed_plan(runtime)
    runtime.run_turn("thoughts?", {"trace_id": "trace-phase60-offer-3"})
    critique = runtime.run_turn("quick check", {"trace_id": "trace-phase60-quick"})

    tensions = critique["final_output"].get("goal_constraint_tensions", [])
    assert isinstance(tensions, list) and tensions
    options = critique["final_output"].get("options", [])
    assert any("Goal fit:" in str(item.get("alignment", "")) for item in options)
    assert any("Constraint fit:" in str(item.get("alignment", "")) for item in options)


def test_phase60_assumptions_not_auto_changed_and_fragility_reported():
    runtime = runtime_mod.BillyRuntime(config={})

    assumption_capture = runtime.run_turn(
        "assumption: deployment window is always stable",
        {"trace_id": "trace-phase60-assumption-capture"},
    )
    assert assumption_capture["interactive_prompt_type"] == "assumption_record_capture"
    runtime.run_turn("yes", {"trace_id": "trace-phase60-assumption-confirm"})

    before = [dict(item) for item in runtime._session_assumptions]
    _seed_plan(runtime)
    runtime.run_turn("does this make sense?", {"trace_id": "trace-phase60-offer-4"})
    critique = runtime.run_turn("assumption review", {"trace_id": "trace-phase60-assumption-review"})

    after = runtime._session_assumptions
    assert after == before
    fragility = critique["final_output"].get("assumption_fragility", [])
    assert isinstance(fragility, list) and fragility
    assert all(item.get("suggested_actions") == ["confirm", "revise", "hedge"] for item in fragility)


def test_phase60_follow_up_is_bounded_and_execution_boundaries_unchanged():
    runtime = runtime_mod.BillyRuntime(config={})
    _seed_plan(runtime)

    runtime.run_turn("this looks good", {"trace_id": "trace-phase60-offer-5"})
    critique = runtime.run_turn("full stress test", {"trace_id": "trace-phase60-full-2"})

    assert critique["final_output"]["continuation_question"].endswith("?")
    assert critique["final_output"]["continuation_question"] == (
        "Do you want to revise the plan, explore an alternative, or accept risk and proceed?"
    )

    blocked_advance = runtime.run_turn("continue", {"trace_id": "trace-phase60-blocked-advance"})
    assert not (
        isinstance(blocked_advance.get("final_output"), dict)
        and isinstance(blocked_advance["final_output"].get("plan_progress"), dict)
        and blocked_advance["final_output"]["plan_progress"].get("advanced") is True
    )

    runtime.run_turn("accept risk and proceed", {"trace_id": "trace-phase60-accept"})
    explicit_advance = runtime.run_turn("continue", {"trace_id": "trace-phase60-explicit-advance"})
    assert isinstance(explicit_advance.get("final_output"), dict)
    assert isinstance(explicit_advance["final_output"].get("plan_progress"), dict)
    assert explicit_advance["final_output"]["plan_progress"].get("advanced") is True

    execution_attempt = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase60-exec"},
    )
    governed_action = runtime.run_turn("create a file", {"trace_id": "trace-phase60-governed"})

    assert execution_attempt["status"] == "error"
    assert execution_attempt["mode"] == "aci_intent_gatekeeper"
    assert execution_attempt["final_output"]["type"] == "refusal"

    assert governed_action["status"] == "success"
    assert governed_action["mode"] == "aci_intent_gatekeeper"
    assert governed_action["final_output"]["type"] in {"proposal", "clarification"}
