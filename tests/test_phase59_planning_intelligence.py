from __future__ import annotations

import v2.core.runtime as runtime_mod


def test_phase59_idea_decomposition_triggers_with_single_clarifying_question():
    runtime = runtime_mod.BillyRuntime(config={})

    result = runtime.run_turn(
        "I'm thinking about starting something around AI for small businesses",
        {"trace_id": "trace-phase59-idea-decomposition"},
    )

    assert result["status"] == "success"
    assert result["mode"] == "advisory"

    final_output = result["final_output"]
    assert final_output["idea_decomposition"] is True
    assert final_output["status"] == "clarification_required"
    assert 2 <= len(final_output["options"]) <= 4
    assert final_output["clarifying_question"].endswith("?")
    assert final_output["rendered_advisory"].count("?") == 1
    assert final_output["rendered_advisory"].rstrip().endswith(final_output["continuation_question"])
    assert runtime._active_plan_artifact is None


def test_phase59_planning_options_include_tradeoffs_and_alignment_fields():
    runtime = runtime_mod.BillyRuntime(config={})

    result = runtime.run_turn(
        "plan a safe rollout for nginx service updates",
        {"trace_id": "trace-phase59-tradeoff-options"},
    )

    assert result["status"] == "success"
    assert result["mode"] == "advisory"

    options = result["final_output"].get("options", [])
    assert isinstance(options, list) and len(options) >= 2
    for option in options:
        assert str(option.get("title", "")).strip()
        assert str(option.get("benefits", "")).strip()
        assert str(option.get("risks", "")).strip()
        assert str(option.get("effort", "")).strip()
        assert str(option.get("alignment", "")).strip()


def test_phase59_planning_depth_control_prompts_then_builds_selected_depth():
    runtime = runtime_mod.BillyRuntime(config={})

    prompted = runtime.run_turn(
        "I need a plan for next steps and I'm not sure which depth to choose",
        {"trace_id": "trace-phase59-depth-prompt"},
    )

    assert prompted["status"] == "success"
    assert prompted["mode"] == "interactive_prompt"
    assert prompted["interactive_prompt_type"] == "planning_depth"

    selected = runtime.run_turn(
        "step-by-step",
        {"trace_id": "trace-phase59-depth-select"},
    )

    assert selected["status"] == "success"
    assert selected["mode"] == "advisory"
    depth = selected["final_output"].get("planning_depth", {})
    assert depth.get("mode") == "step_by_step"


def test_phase59_plan_advancement_is_bounded_and_only_when_artifact_exists():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn(
        "plan repository cleanup with minimal risk",
        {"trace_id": "trace-phase59-plan-seed"},
    )

    first_advance = runtime.run_turn("ok", {"trace_id": "trace-phase59-advance-1"})
    second_advance = runtime.run_turn("that works", {"trace_id": "trace-phase59-advance-2"})

    assert first_advance["status"] == "success"
    assert first_advance["mode"] == "advisory"
    progress_1 = first_advance["final_output"]["plan_progress"]
    assert progress_1["advanced"] is True
    assert progress_1["current_step_index"] == 1

    progress_2 = second_advance["final_output"]["plan_progress"]
    assert progress_2["advanced"] is True
    assert progress_2["current_step_index"] == 2

    fresh_runtime = runtime_mod.BillyRuntime(config={})
    no_plan = fresh_runtime.run_turn("ok", {"trace_id": "trace-phase59-no-plan"})
    assert not (
        isinstance(no_plan.get("final_output"), dict)
        and isinstance(no_plan["final_output"].get("plan_progress"), dict)
    )


def test_phase59_execution_and_governed_boundaries_remain_unchanged():
    runtime = runtime_mod.BillyRuntime(config={})

    execution_attempt = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase59-exec"},
    )
    governed_action = runtime.run_turn("create a file", {"trace_id": "trace-phase59-governed"})

    assert execution_attempt["status"] == "error"
    assert execution_attempt["mode"] == "aci_intent_gatekeeper"
    assert execution_attempt["final_output"]["type"] == "refusal"

    assert governed_action["status"] == "success"
    assert governed_action["mode"] == "aci_intent_gatekeeper"
    assert governed_action["final_output"]["type"] in {"proposal", "clarification"}
