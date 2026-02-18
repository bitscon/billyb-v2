from __future__ import annotations

import v2.core.runtime as runtime_mod


def _last_non_empty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return ""


def test_phase37_html_advisory_renders_visible_content_and_single_next_step_question():
    runtime = runtime_mod.BillyRuntime(config={})

    rendered = runtime.ask("I want to make an html file called test.html")

    assert "<!doctype html>" in rendered.lower()
    assert "plan steps:" in rendered.lower()
    assert "suggested commands:" in rendered.lower()
    assert "NOT EXECUTED:" in rendered
    assert "risk notes:" in rendered.lower()

    final_line = _last_non_empty_line(rendered)
    assert final_line.endswith("?")
    assert rendered.count("?") == 1


def test_phase37_html_advisory_rendering_is_deterministic_across_runs():
    runtime = runtime_mod.BillyRuntime(config={})

    first = runtime.ask("I want to make an html file called test.html")
    second = runtime.ask("I want to make an html file called test.html")

    assert first == second


def test_phase37_advisory_payload_includes_rendered_content_and_question():
    runtime = runtime_mod.BillyRuntime(config={})

    result = runtime.run_turn(
        "I want to make an html file called test.html",
        {"trace_id": "trace-phase37-advisory"},
    )

    assert result["status"] == "success"
    assert result["mode"] == "advisory"
    assert result["execution_enabled"] is False
    assert result["advisory_only"] is True
    assert isinstance(result["final_output"], dict)
    assert "<!doctype html>" in result["final_output"]["rendered_advisory"].lower()
    assert result["final_output"]["continuation_question"].endswith("?")
    assert result["final_output"]["rendered_advisory"].rstrip().endswith(result["final_output"]["continuation_question"])


def test_phase37_execution_attempts_still_refused():
    runtime = runtime_mod.BillyRuntime(config={})

    result = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase37-exec-refusal"},
    )

    assert result["status"] == "error"
    assert result["mode"] == "aci_intent_gatekeeper"
    assert isinstance(result["final_output"], dict)
    assert result["final_output"]["type"] == "refusal"


def test_phase37_governance_routing_for_governed_action_unchanged():
    runtime = runtime_mod.BillyRuntime(config={})

    result = runtime.run_turn("create a file", {"trace_id": "trace-phase37-governed"})

    assert result["status"] == "success"
    assert result["mode"] == "aci_intent_gatekeeper"
    assert isinstance(result["final_output"], dict)
    assert result["final_output"]["type"] in {"proposal", "clarification"}
