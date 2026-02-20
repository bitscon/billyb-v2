from __future__ import annotations

import v2.core.runtime as runtime_mod


def test_phase45_readiness_evaluates_deterministically_for_html_artifact():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("I want to make an html file called test.html", {"trace_id": "trace-phase45-ready-seed"})
    first = runtime.run_turn("is this ready to run?", {"trace_id": "trace-phase45-ready-1"})
    second = runtime.run_turn("is this ready to run?", {"trace_id": "trace-phase45-ready-2"})

    assert first["status"] == "success"
    assert first["mode"] == "advisory"
    assert first["final_output"]["ready"] is True
    assert first["final_output"]["blocking_issues"] == []
    assert first["final_output"]["readiness_read_only"] is True
    assert first["final_output"]["execution_enabled"] is False

    assert second["status"] == "success"
    assert second["mode"] == "advisory"
    assert first["final_output"]["readiness_fingerprint"] == second["final_output"]["readiness_fingerprint"]
    assert first["final_output"] == second["final_output"]


def test_phase45_missing_prerequisites_are_reported_with_ready_false():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime._upsert_task_artifact(
        name="html_page",
        artifact_type="html_page",
        content={
            "filename": "broken.html",
            "html": "<html><body><p>broken",
            "include_style": False,
        },
        summary="Broken html for readiness check.",
        source_mode="advisory",
    )
    readiness = runtime.run_turn(
        "what's missing before I can run this?",
        {"trace_id": "trace-phase45-missing-1"},
    )

    assert readiness["status"] == "success"
    assert readiness["mode"] == "advisory"
    assert readiness["final_output"]["ready"] is False
    assert readiness["final_output"]["blocking_issues"]
    assert any("head" in issue.lower() for issue in readiness["final_output"]["blocking_issues"])


def test_phase45_blockers_query_phrase_is_supported():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime._upsert_task_artifact(
        name="html_page",
        artifact_type="html_page",
        content={
            "filename": "broken.html",
            "html": "<body><p>missing wrappers</p>",
            "include_style": False,
        },
        summary="Broken html for blockers query.",
        source_mode="advisory",
    )
    blockers = runtime.run_turn("are there any blockers?", {"trace_id": "trace-phase45-blockers"})

    assert blockers["status"] == "success"
    assert blockers["mode"] == "advisory"
    assert blockers["final_output"]["ready"] is False
    assert blockers["final_output"]["blocking_issues"]


def test_phase45_governance_and_execution_behavior_unchanged():
    runtime = runtime_mod.BillyRuntime(config={})

    execution_attempt = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase45-exec"},
    )
    governed_action = runtime.run_turn("create a file", {"trace_id": "trace-phase45-governed"})

    assert execution_attempt["status"] == "error"
    assert execution_attempt["mode"] == "aci_intent_gatekeeper"
    assert execution_attempt["final_output"]["type"] == "refusal"

    assert governed_action["status"] == "success"
    assert governed_action["mode"] == "aci_intent_gatekeeper"
    assert governed_action["final_output"]["type"] in {"proposal", "clarification"}
