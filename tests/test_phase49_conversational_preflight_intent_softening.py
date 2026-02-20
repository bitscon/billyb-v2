from __future__ import annotations

import v2.core.runtime as runtime_mod


def test_phase49_preflight_triggers_on_underspecified_website_request():
    runtime = runtime_mod.BillyRuntime(config={})

    first = runtime.run_turn(
        "I want to make a website",
        {"trace_id": "trace-phase49-preflight-1"},
    )

    assert first["status"] == "success"
    assert first["mode"] == "interactive_prompt"
    assert first["interactive_prompt_active"] is True
    assert first["interactive_prompt_type"] == "website_preflight"
    assert isinstance(first["final_output"], str)
    assert first["final_output"].endswith("?")
    assert runtime._get_task_artifact("html_page") is None


def test_phase49_preflight_defers_generation_until_clarification():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn(
        "I want to make a website",
        {"trace_id": "trace-phase49-preflight-2a"},
    )
    clarified = runtime.run_turn(
        "It's for my bakery customers and keep it minimal.",
        {"trace_id": "trace-phase49-preflight-2b"},
    )

    assert clarified["status"] == "success"
    assert clarified["mode"] == "advisory"
    assert clarified["execution_enabled"] is False
    assert clarified["advisory_only"] is True
    assert clarified["final_output"]["task_artifact"]["name"] == "html_page"
    assert "example_html" in clarified["final_output"]
    assert runtime._get_task_artifact("html_page") is not None


def test_phase49_explicit_generate_html_now_bypasses_preflight():
    runtime = runtime_mod.BillyRuntime(config={})

    direct = runtime.run_turn(
        "I want to make a website and generate HTML now.",
        {"trace_id": "trace-phase49-bypass-explicit"},
    )

    assert direct["status"] == "success"
    assert direct["mode"] == "advisory"
    assert direct.get("interactive_prompt_type") != "website_preflight"
    assert direct["final_output"]["task_artifact"]["name"] == "html_page"


def test_phase49_existing_artifact_modification_bypasses_preflight():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn(
        "I want to make a website and generate HTML now.",
        {"trace_id": "trace-phase49-bypass-existing-seed"},
    )
    updated = runtime.run_turn(
        'add a paragraph "phase49 paragraph" to the html we made earlier',
        {"trace_id": "trace-phase49-bypass-existing-update"},
    )

    assert updated["status"] == "success"
    assert updated["mode"] == "advisory"
    assert updated.get("interactive_prompt_type") != "website_preflight"
    assert "phase49 paragraph" in updated["final_output"]["example_html"]


def test_phase49_safety_and_governance_behavior_unchanged():
    runtime = runtime_mod.BillyRuntime(config={})

    execution_attempt = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase49-exec"},
    )
    governed_action = runtime.run_turn("create a file", {"trace_id": "trace-phase49-governed"})

    assert execution_attempt["status"] == "error"
    assert execution_attempt["mode"] == "aci_intent_gatekeeper"
    assert execution_attempt["final_output"]["type"] == "refusal"

    assert governed_action["status"] == "success"
    assert governed_action["mode"] == "aci_intent_gatekeeper"
    assert governed_action["final_output"]["type"] in {"proposal", "clarification"}
