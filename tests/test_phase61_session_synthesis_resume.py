from __future__ import annotations

import v2.core.runtime as runtime_mod


def _seed_planning_context(runtime: runtime_mod.BillyRuntime, trace_prefix: str) -> None:
    seeded = runtime.run_turn(
        "plan a safe rollout for nginx service updates",
        {"trace_id": f"{trace_prefix}-seed"},
    )
    assert seeded["status"] == "success"
    assert seeded["mode"] == "advisory"


def _capture_summary(runtime: runtime_mod.BillyRuntime, trace_prefix: str) -> dict:
    offered = runtime.run_turn(
        "let's stop here",
        {"trace_id": f"{trace_prefix}-offer"},
    )
    assert offered["status"] == "success"
    assert offered["mode"] == "interactive_prompt"
    assert offered["interactive_prompt_type"] == "session_summary_offer"

    captured = runtime.run_turn(
        "yes",
        {"trace_id": f"{trace_prefix}-confirm"},
    )
    assert captured["status"] == "success"
    assert captured["mode"] == "advisory"
    return captured


def test_phase61_summary_offer_triggers_once_per_session_pause_window():
    runtime = runtime_mod.BillyRuntime(config={})
    _seed_planning_context(runtime, "trace-phase61-once")

    offered = runtime.run_turn(
        "let's stop here",
        {"trace_id": "trace-phase61-once-offer"},
    )
    assert offered["status"] == "success"
    assert offered["mode"] == "interactive_prompt"
    assert offered["interactive_prompt_type"] == "session_summary_offer"

    declined = runtime.run_turn(
        "no",
        {"trace_id": "trace-phase61-once-decline"},
    )
    assert declined["status"] == "success"
    assert declined["mode"] == "interactive_response"

    repeated_pause = runtime.run_turn(
        "thanks",
        {"trace_id": "trace-phase61-once-repeat"},
    )
    assert not (
        repeated_pause.get("mode") == "interactive_prompt"
        and repeated_pause.get("interactive_prompt_type") == "session_summary_offer"
    )


def test_phase61_summary_is_created_only_after_confirmation_and_has_required_shape():
    runtime = runtime_mod.BillyRuntime(config={})
    _seed_planning_context(runtime, "trace-phase61-shape")

    offered = runtime.run_turn(
        "i'll think about it",
        {"trace_id": "trace-phase61-shape-offer"},
    )
    assert offered["status"] == "success"
    assert offered["interactive_prompt_type"] == "session_summary_offer"
    assert runtime._get_task_artifact("session_summary") is None

    captured = runtime.run_turn(
        "yes",
        {"trace_id": "trace-phase61-shape-confirm"},
    )
    assert captured["status"] == "success"
    assert captured["mode"] == "advisory"

    summary = captured["final_output"].get("session_summary", {})
    assert isinstance(summary, dict)
    assert set(summary.keys()) == {
        "primary_goal",
        "current_direction",
        "key_decisions",
        "open_questions",
        "next_suggested_thinking_step",
        "confidence_level",
    }
    assert summary["confidence_level"] in {"low", "medium", "high"}

    artifact = runtime._get_task_artifact("session_summary")
    assert isinstance(artifact, dict)
    assert artifact["name"] == "session_summary"
    assert artifact["artifact_type"] == "session_summary"


def test_phase61_resume_restates_summary_and_requests_explicit_next_action():
    runtime = runtime_mod.BillyRuntime(config={})
    _seed_planning_context(runtime, "trace-phase61-resume")
    _capture_summary(runtime, "trace-phase61-resume")

    resumed = runtime.run_turn(
        "where were we?",
        {"trace_id": "trace-phase61-resume-turn"},
    )
    assert resumed["status"] == "success"
    assert resumed["mode"] == "advisory"
    assert isinstance(resumed["final_output"].get("session_summary"), dict)
    assert resumed["final_output"]["continuation_question"] == "Do you want to proceed, revise the summary, or start fresh?"
    assert "Next thinking step:" in str(resumed["final_output"].get("message", ""))
    assert not (
        isinstance(resumed["final_output"].get("plan_progress"), dict)
        and resumed["final_output"]["plan_progress"].get("advanced") is True
    )

    proceed = runtime.run_turn(
        "proceed",
        {"trace_id": "trace-phase61-resume-proceed"},
    )
    assert proceed["status"] == "success"
    assert proceed["mode"] == "advisory"
    assert "Proceeding from the saved summary." in str(proceed["final_output"].get("message", ""))


def test_phase61_discard_commands_remove_only_session_summary():
    runtime = runtime_mod.BillyRuntime(config={})
    runtime.run_turn(
        "I want to make an html file called phase61.html",
        {"trace_id": "trace-phase61-discard-html"},
    )
    _seed_planning_context(runtime, "trace-phase61-discard")
    _capture_summary(runtime, "trace-phase61-discard")

    assert runtime._get_task_artifact("html_page") is not None
    assert runtime._get_task_artifact("session_summary") is not None

    discarded = runtime.run_turn(
        "start fresh",
        {"trace_id": "trace-phase61-discard-summary"},
    )
    assert discarded["status"] == "success"
    assert discarded["mode"] == "conversation_layer"
    assert "Discarded the session summary" in str(discarded["final_output"])
    assert runtime._get_task_artifact("session_summary") is None
    assert runtime._get_task_artifact("html_page") is not None

    no_summary = runtime.run_turn(
        "forget where we left off",
        {"trace_id": "trace-phase61-discard-none"},
    )
    assert no_summary["status"] == "success"
    assert "No session summary was recorded" in str(no_summary["final_output"])
    assert runtime._get_task_artifact("html_page") is not None


def test_phase61_execution_and_governance_boundaries_remain_unchanged():
    runtime = runtime_mod.BillyRuntime(config={})
    _seed_planning_context(runtime, "trace-phase61-boundary")
    _capture_summary(runtime, "trace-phase61-boundary")

    execution_attempt = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase61-exec"},
    )
    governed_action = runtime.run_turn(
        "create a file",
        {"trace_id": "trace-phase61-governed"},
    )

    assert execution_attempt["status"] == "error"
    assert execution_attempt["mode"] == "aci_intent_gatekeeper"
    assert execution_attempt["final_output"]["type"] == "refusal"

    assert governed_action["status"] == "success"
    assert governed_action["mode"] == "aci_intent_gatekeeper"
    assert governed_action["final_output"]["type"] in {"proposal", "clarification"}
