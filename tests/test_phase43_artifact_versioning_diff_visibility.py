from __future__ import annotations

import v2.core.runtime as runtime_mod


def test_phase43_revision_created_on_artifact_update():
    runtime = runtime_mod.BillyRuntime(config={})

    initial = runtime.run_turn("I want to make an html file", {"trace_id": "trace-phase43-rev-1"})
    updated = runtime.run_turn(
        'add a paragraph "Versioning check paragraph" to the html we made earlier',
        {"trace_id": "trace-phase43-rev-2"},
    )

    first_artifact = initial["final_output"]["task_artifact"]
    second_artifact = updated["final_output"]["task_artifact"]
    assert second_artifact["revision"] == first_artifact["revision"] + 1
    assert second_artifact["revision_id"] != first_artifact["revision_id"]


def test_phase43_no_revision_created_on_noop_artifact_update():
    runtime = runtime_mod.BillyRuntime(config={})

    first = runtime.run_turn("I want to make an html file", {"trace_id": "trace-phase43-noop-1"})
    second = runtime.run_turn("I want to make an html file", {"trace_id": "trace-phase43-noop-2"})

    first_artifact = first["final_output"]["task_artifact"]
    second_artifact = second["final_output"]["task_artifact"]
    assert first_artifact["revision"] == second_artifact["revision"]
    assert first_artifact["revision_id"] == second_artifact["revision_id"]


def test_phase43_diff_is_rendered_when_artifact_changes():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("I want to make an html file", {"trace_id": "trace-phase43-diff-1"})
    updated = runtime.run_turn(
        'add a paragraph "Diff visibility paragraph" to the html we made earlier',
        {"trace_id": "trace-phase43-diff-2"},
    )

    assert updated["status"] == "success"
    assert updated["mode"] == "advisory"
    assert "artifact_diff" in updated["final_output"]
    diff_payload = updated["final_output"]["artifact_diff"]
    assert diff_payload["artifact_name"] == "html_page"
    assert "Diff visibility paragraph" in diff_payload["diff_text"]
    assert "Artifact Diff:" in updated["final_output"]["rendered_advisory"]


def test_phase43_what_changed_resolves_to_last_diff():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("I want to make an html file", {"trace_id": "trace-phase43-query-1"})
    runtime.run_turn(
        'add a paragraph "Query the diff paragraph" to the html we made earlier',
        {"trace_id": "trace-phase43-query-2"},
    )
    changed = runtime.run_turn("what changed?", {"trace_id": "trace-phase43-query-3"})

    assert changed["status"] == "success"
    assert changed["mode"] == "conversation_layer"
    assert "Diff" in changed["final_output"]
    assert "Query the diff paragraph" in changed["final_output"]


def test_phase43_governance_and_safety_unchanged():
    runtime = runtime_mod.BillyRuntime(config={})

    execution_attempt = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase43-exec"},
    )
    governed_action = runtime.run_turn("create a file", {"trace_id": "trace-phase43-governed"})

    assert execution_attempt["status"] == "error"
    assert execution_attempt["mode"] == "aci_intent_gatekeeper"
    assert execution_attempt["final_output"]["type"] == "refusal"

    assert governed_action["status"] == "success"
    assert governed_action["mode"] == "aci_intent_gatekeeper"
    assert governed_action["final_output"]["type"] in {"proposal", "clarification"}
