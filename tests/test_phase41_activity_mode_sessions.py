from __future__ import annotations

import v2.core.runtime as runtime_mod


def test_phase41_mode_entry_confirms_study_mode_once():
    runtime = runtime_mod.BillyRuntime(config={})

    entered = runtime.run_turn("let's study vocabulary", {"trace_id": "trace-phase41-enter"})

    assert entered["status"] == "success"
    assert entered["mode"] == "activity_mode"
    assert entered["activity_mode"] == "study_mode"
    assert entered["activity_mode_active"] is True
    assert entered["interactive_prompt_active"] is True
    assert "Entered study_mode" in entered["final_output"]
    assert "Question 1" in entered["final_output"]


def test_phase41_multi_turn_study_mode_keeps_context_and_advances_question():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("let's study vocabulary", {"trace_id": "trace-phase41-study-1"})
    answer = runtime.run_turn("A", {"trace_id": "trace-phase41-study-2"})

    assert answer["status"] == "success"
    assert answer["mode"] == "activity_mode"
    assert answer["activity_mode"] == "study_mode"
    assert answer["activity_mode_active"] is True
    assert answer["interactive_prompt_active"] is True
    assert "Correct: option A" in answer["final_output"]
    assert "Question 2" in answer["final_output"]


def test_phase41_explicit_mode_exit_clears_activity_state():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("let's study vocabulary", {"trace_id": "trace-phase41-exit-seed"})
    exited = runtime.run_turn("exit study mode", {"trace_id": "trace-phase41-exit"})

    assert exited["status"] == "success"
    assert exited["mode"] == "activity_mode"
    assert exited["activity_mode"] == "study_mode"
    assert exited["activity_mode_active"] is False
    assert exited["interactive_prompt_active"] is False
    assert "Exited study_mode" in exited["final_output"]


def test_phase41_implicit_mode_exit_on_topic_change_resumes_normal_routing():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("let's study vocabulary", {"trace_id": "trace-phase41-implicit-seed"})
    website_request = runtime.run_turn(
        "I want to make an html file",
        {"trace_id": "trace-phase41-implicit-exit"},
    )

    assert website_request["status"] == "success"
    assert website_request["mode"] == "advisory"
    assert website_request["execution_enabled"] is False
    assert website_request["advisory_only"] is True


def test_phase41_normal_routing_resumes_after_explicit_exit():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("let's study vocabulary", {"trace_id": "trace-phase41-resume-seed"})
    runtime.run_turn("exit study mode", {"trace_id": "trace-phase41-resume-exit"})
    post_exit = runtime.run_turn("what do bees eat?", {"trace_id": "trace-phase41-resume-chat"})

    assert post_exit["status"] == "success"
    assert post_exit["mode"] == "conversation_layer"


def test_phase41_safety_and_governance_paths_unchanged_under_activity_mode():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("let's study vocabulary", {"trace_id": "trace-phase41-safety-seed"})
    execution_attempt = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase41-exec"},
    )
    governed_action = runtime.run_turn("create a file", {"trace_id": "trace-phase41-governed"})

    assert execution_attempt["status"] == "error"
    assert execution_attempt["mode"] == "aci_intent_gatekeeper"
    assert execution_attempt["final_output"]["type"] == "refusal"

    assert governed_action["status"] == "success"
    assert governed_action["mode"] == "aci_intent_gatekeeper"
    assert governed_action["final_output"]["type"] in {"proposal", "clarification"}
