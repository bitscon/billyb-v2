from __future__ import annotations

import v2.core.runtime as runtime_mod


def test_phase42_creates_html_task_artifact_from_advisory_output():
    runtime = runtime_mod.BillyRuntime(config={})

    result = runtime.run_turn(
        "I want to make an html file called test.html",
        {"trace_id": "trace-phase42-create-html"},
    )

    assert result["status"] == "success"
    assert result["mode"] == "advisory"
    artifact = result["final_output"]["task_artifact"]
    assert artifact["name"] == "html_page"
    assert artifact["type"] == "html_page"
    assert artifact["session_scoped"] is True
    assert artifact["execution_enabled"] is False
    assert "Task Artifact:" in result["final_output"]["rendered_advisory"]


def test_phase42_multi_turn_html_artifact_update_accumulates_content():
    runtime = runtime_mod.BillyRuntime(config={})

    first = runtime.run_turn("I want to make an html file", {"trace_id": "trace-phase42-update-seed"})
    updated = runtime.run_turn(
        "add a paragraph \"Artifact paragraph\" to the html we made earlier",
        {"trace_id": "trace-phase42-update-1"},
    )

    assert first["status"] == "success"
    assert updated["status"] == "success"
    assert updated["mode"] == "advisory"
    assert "Artifact paragraph" in updated["final_output"]["example_html"]
    assert updated["final_output"]["task_artifact"]["name"] == "html_page"
    assert updated["final_output"]["task_artifact"]["revision"] >= first["final_output"]["task_artifact"]["revision"]


def test_phase42_resolves_html_artifact_reference_naturally():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("I want to make an html file", {"trace_id": "trace-phase42-ref-seed"})
    resolved = runtime.run_turn("edit the html we made earlier", {"trace_id": "trace-phase42-ref-1"})

    assert resolved["status"] == "success"
    assert resolved["mode"] == "advisory"
    assert "Resolved task artifact `html_page`" in resolved["final_output"]["message"]
    assert resolved["final_output"]["task_artifact"]["name"] == "html_page"


def test_phase42_explicit_artifact_reset_discards_html_artifact():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("I want to make an html file", {"trace_id": "trace-phase42-reset-seed"})
    discard = runtime.run_turn("discard the html", {"trace_id": "trace-phase42-reset-discard"})
    post_discard = runtime.run_turn(
        "edit the html we made earlier",
        {"trace_id": "trace-phase42-reset-post"},
    )

    assert discard["status"] == "success"
    assert "Discarded task artifact `html_page`" in discard["final_output"]
    assert post_discard["status"] == "success"
    assert post_discard.get("mode") != "advisory"


def test_phase42_study_session_artifact_can_resume_after_mode_exit():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("let's study vocabulary", {"trace_id": "trace-phase42-study-seed"})
    runtime.run_turn("exit study mode", {"trace_id": "trace-phase42-study-exit"})
    resumed = runtime.run_turn("continue the study set", {"trace_id": "trace-phase42-study-resume"})

    assert resumed["status"] == "success"
    assert resumed["mode"] == "activity_mode"
    assert resumed["activity_mode"] == "study_mode"
    assert resumed["activity_mode_active"] is True
    assert "Resuming task artifact `study_session`." in resumed["final_output"]


def test_phase42_safety_and_governance_behavior_unchanged():
    runtime = runtime_mod.BillyRuntime(config={})

    execution_attempt = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase42-exec"},
    )
    governed_action = runtime.run_turn("create a file", {"trace_id": "trace-phase42-governed"})

    assert execution_attempt["status"] == "error"
    assert execution_attempt["mode"] == "aci_intent_gatekeeper"
    assert execution_attempt["final_output"]["type"] == "refusal"

    assert governed_action["status"] == "success"
    assert governed_action["mode"] == "aci_intent_gatekeeper"
    assert governed_action["final_output"]["type"] in {"proposal", "clarification"}
