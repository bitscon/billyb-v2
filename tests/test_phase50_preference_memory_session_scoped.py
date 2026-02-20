from __future__ import annotations

import v2.core.runtime as runtime_mod


def _set_styled_preference(runtime: runtime_mod.BillyRuntime, seed: str) -> None:
    capture = runtime.run_turn(
        "use styled html for this session",
        {"trace_id": f"{seed}-capture"},
    )
    assert capture["status"] == "success"
    assert capture["mode"] == "interactive_prompt"
    assert capture["interactive_prompt_type"] == "preference_capture"
    confirm = runtime.run_turn("yes", {"trace_id": f"{seed}-confirm"})
    assert confirm["status"] == "success"
    assert runtime._session_preferences.get("website_style") == "styled"


def test_phase50_preference_capture_requires_confirmation_before_store():
    runtime = runtime_mod.BillyRuntime(config={})

    capture = runtime.run_turn(
        "use styled html for this session",
        {"trace_id": "trace-phase50-capture-1"},
    )

    assert capture["status"] == "success"
    assert capture["mode"] == "interactive_prompt"
    assert capture["interactive_prompt_active"] is True
    assert capture["interactive_prompt_type"] == "preference_capture"
    assert runtime._session_preferences == {}

    decline = runtime.run_turn("no", {"trace_id": "trace-phase50-capture-2"})
    assert decline["status"] == "success"
    assert decline["mode"] == "interactive_response"
    assert runtime._session_preferences == {}


def test_phase50_preference_reused_in_subsequent_advisory_output():
    runtime = runtime_mod.BillyRuntime(config={})
    _set_styled_preference(runtime, "trace-phase50-reuse")

    advisory = runtime.run_turn(
        "I want to make a website and generate HTML now.",
        {"trace_id": "trace-phase50-reuse-advisory"},
    )

    assert advisory["status"] == "success"
    assert advisory["mode"] == "advisory"
    assert advisory["execution_enabled"] is False
    example_html = str(advisory["final_output"].get("example_html", ""))
    assert "<style>" in example_html
    assumptions = advisory["final_output"].get("assumptions", [])
    assert any("Session preference applied: styled HTML with CSS." in str(item) for item in assumptions)


def test_phase50_preference_reset_clears_session_memory():
    runtime = runtime_mod.BillyRuntime(config={})
    _set_styled_preference(runtime, "trace-phase50-reset")

    reset = runtime.run_turn("forget preferences", {"trace_id": "trace-phase50-reset-clear"})
    assert reset["status"] == "success"
    assert runtime._session_preferences == {}

    advisory = runtime.run_turn(
        "I want to make a website and generate HTML now.",
        {"trace_id": "trace-phase50-reset-advisory"},
    )
    assert advisory["status"] == "success"
    assert advisory["mode"] == "advisory"
    example_html = str(advisory["final_output"].get("example_html", ""))
    assert "<style>" not in example_html


def test_phase50_safety_and_governance_behavior_unchanged():
    runtime = runtime_mod.BillyRuntime(config={})

    execution_attempt = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase50-exec"},
    )
    governed_action = runtime.run_turn("create a file", {"trace_id": "trace-phase50-governed"})

    assert execution_attempt["status"] == "error"
    assert execution_attempt["mode"] == "aci_intent_gatekeeper"
    assert execution_attempt["final_output"]["type"] == "refusal"

    assert governed_action["status"] == "success"
    assert governed_action["mode"] == "aci_intent_gatekeeper"
    assert governed_action["final_output"]["type"] in {"proposal", "clarification"}
