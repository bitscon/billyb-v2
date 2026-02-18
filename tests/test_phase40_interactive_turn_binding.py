from __future__ import annotations

import v2.core.runtime as runtime_mod


def test_phase40_multiple_choice_flow_binds_next_turn_and_resolves_a():
    runtime = runtime_mod.BillyRuntime(config={})

    quiz = runtime.run_turn("quiz me on vocabulary", {"trace_id": "trace-phase40-quiz"})
    assert quiz["status"] == "success"
    assert quiz["mode"] == "interactive_prompt"
    assert "A) brief" in quiz["final_output"]
    assert quiz["interactive_prompt_active"] is True

    answer = runtime.run_turn("A", {"trace_id": "trace-phase40-quiz-answer"})
    assert answer["status"] == "success"
    assert answer["mode"] == "interactive_response"
    assert "Correct: option A" in answer["final_output"]
    assert answer["interactive_prompt_active"] is False


def test_phase40_same_input_a_outside_interaction_is_treated_normally():
    runtime = runtime_mod.BillyRuntime(config={})

    result = runtime.run_turn("A", {"trace_id": "trace-phase40-a-normal"})

    assert result["status"] == "success"
    assert result.get("mode") != "interactive_response"
    assert "Correct: option A" not in str(result["final_output"])


def test_phase40_interactive_state_clears_after_completion():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("quiz me on vocabulary", {"trace_id": "trace-phase40-clear-1"})
    runtime.run_turn("A", {"trace_id": "trace-phase40-clear-2"})
    follow_up = runtime.run_turn("A", {"trace_id": "trace-phase40-clear-3"})

    assert follow_up["status"] == "success"
    assert follow_up.get("mode") != "interactive_response"
    assert "Correct: option A" not in str(follow_up["final_output"])


def test_phase40_yes_no_binding_from_advisory_prompt():
    runtime = runtime_mod.BillyRuntime(config={})

    advisory = runtime.run_turn(
        "I want to make an html file",
        {"trace_id": "trace-phase40-yesno-advisory"},
    )
    assert advisory["status"] == "success"
    assert advisory["mode"] == "advisory"

    yes_reply = runtime.run_turn("yes", {"trace_id": "trace-phase40-yesno-reply"})
    assert yes_reply["status"] == "success"
    assert yes_reply["mode"] == "interactive_response"
    assert "Tell me exactly what to change in the HTML" in yes_reply["final_output"]
    assert yes_reply["interactive_prompt_active"] is False


def test_phase40_safety_and_governance_behavior_unchanged():
    runtime = runtime_mod.BillyRuntime(config={})

    execution_attempt = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase40-exec"},
    )
    governed_action = runtime.run_turn("create a file", {"trace_id": "trace-phase40-governed"})

    assert execution_attempt["status"] == "error"
    assert execution_attempt["mode"] == "aci_intent_gatekeeper"
    assert execution_attempt["final_output"]["type"] == "refusal"

    assert governed_action["status"] == "success"
    assert governed_action["mode"] == "aci_intent_gatekeeper"
    assert governed_action["final_output"]["type"] in {"proposal", "clarification"}
