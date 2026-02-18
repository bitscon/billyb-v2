from __future__ import annotations

import v2.core.runtime as runtime_mod


def test_phase39_html_advisory_proceeds_with_explicit_safe_defaults():
    runtime = runtime_mod.BillyRuntime(config={})

    result = runtime.run_turn("I want to make an html file", {"trace_id": "trace-phase39-default"})

    assert result["status"] == "success"
    assert result["mode"] == "advisory"
    assert result["execution_enabled"] is False
    assert result["advisory_only"] is True
    assert "<title>index.html</title>" in result["final_output"]["example_html"].lower()
    assert any("index.html" in cmd for cmd in result["final_output"]["suggested_commands"])
    assert "Assumptions:" in result["final_output"]["rendered_advisory"]
    assert any(str(item).startswith("Default:") for item in result["final_output"]["assumptions"])
    assert any("assuming `index.html`" in str(item) for item in result["final_output"]["assumptions"])


def test_phase39_user_override_replaces_default_and_is_deterministic():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("I want to make an html file", {"trace_id": "trace-phase39-seed"})
    updated = runtime.run_turn("use landing.html instead", {"trace_id": "trace-phase39-override-1"})
    repeated = runtime.run_turn("use landing.html instead", {"trace_id": "trace-phase39-override-2"})

    assert updated["status"] == "success"
    assert updated["mode"] == "advisory"
    assert "<title>landing.html</title>" in updated["final_output"]["example_html"].lower()
    assert any("landing.html" in cmd for cmd in updated["final_output"]["suggested_commands"])
    assert updated["final_output"] == repeated["final_output"]


def test_phase39_defaults_do_not_persist_beyond_runtime_session():
    first_runtime = runtime_mod.BillyRuntime(config={})
    first_runtime.run_turn("I want to make an html file", {"trace_id": "trace-phase39-session-1"})
    first_runtime.run_turn("use landing.html instead", {"trace_id": "trace-phase39-session-1-override"})

    second_runtime = runtime_mod.BillyRuntime(config={})
    fresh = second_runtime.run_turn("I want to make an html file", {"trace_id": "trace-phase39-session-2"})

    assert fresh["status"] == "success"
    assert fresh["mode"] == "advisory"
    assert "<title>index.html</title>" in fresh["final_output"]["example_html"].lower()


def test_phase39_governance_and_execution_behavior_unchanged():
    runtime = runtime_mod.BillyRuntime(config={})

    execution_attempt = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase39-exec"},
    )
    governed_action = runtime.run_turn("create a file", {"trace_id": "trace-phase39-governed"})

    assert execution_attempt["status"] == "error"
    assert execution_attempt["mode"] == "aci_intent_gatekeeper"
    assert execution_attempt["final_output"]["type"] == "refusal"

    assert governed_action["status"] == "success"
    assert governed_action["mode"] == "aci_intent_gatekeeper"
    assert governed_action["final_output"]["type"] in {"proposal", "clarification"}
