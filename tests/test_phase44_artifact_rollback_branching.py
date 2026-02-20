from __future__ import annotations

import v2.core.runtime as runtime_mod


def test_phase44_rollback_creates_new_revision():
    runtime = runtime_mod.BillyRuntime(config={})

    initial = runtime.run_turn("I want to make an html file", {"trace_id": "trace-phase44-rb-1"})
    updated = runtime.run_turn(
        'add a paragraph "rollback-marker" to the html we made earlier',
        {"trace_id": "trace-phase44-rb-2"},
    )
    rolled_back = runtime.run_turn("undo the last change", {"trace_id": "trace-phase44-rb-3"})

    assert initial["status"] == "success"
    assert updated["status"] == "success"
    assert rolled_back["status"] == "success"
    assert rolled_back["mode"] == "advisory"
    assert rolled_back["final_output"]["task_artifact"]["name"] == "html_page"
    assert (
        rolled_back["final_output"]["task_artifact"]["revision"]
        == updated["final_output"]["task_artifact"]["revision"] + 1
    )
    assert "rollback-marker" not in rolled_back["final_output"]["example_html"]


def test_phase44_rollback_renders_diff_visibility():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("I want to make an html file", {"trace_id": "trace-phase44-rbdiff-1"})
    runtime.run_turn(
        'add a paragraph "rollback-diff-marker" to the html we made earlier',
        {"trace_id": "trace-phase44-rbdiff-2"},
    )
    rolled_back = runtime.run_turn("revert to the previous version", {"trace_id": "trace-phase44-rbdiff-3"})

    assert rolled_back["status"] == "success"
    assert rolled_back["mode"] == "advisory"
    assert "artifact_diff" in rolled_back["final_output"]
    assert "Artifact Diff:" in rolled_back["final_output"]["rendered_advisory"]
    assert "rollback-diff-marker" in rolled_back["final_output"]["artifact_diff"]["diff_text"]


def test_phase44_can_roll_back_to_specific_revision_number():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("I want to make an html file", {"trace_id": "trace-phase44-rnum-1"})
    runtime.run_turn(
        'add a paragraph "rnum-marker" to the html we made earlier',
        {"trace_id": "trace-phase44-rnum-2"},
    )
    rolled_back = runtime.run_turn("roll back to revision r1 for html_page", {"trace_id": "trace-phase44-rnum-3"})

    assert rolled_back["status"] == "success"
    assert rolled_back["mode"] == "advisory"
    assert "rnum-marker" not in rolled_back["final_output"]["example_html"]


def test_phase44_branch_creates_independent_artifact():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("I want to make an html file", {"trace_id": "trace-phase44-branch-1"})
    branch = runtime.run_turn("branch this into an alternate version", {"trace_id": "trace-phase44-branch-2"})

    assert branch["status"] == "success"
    assert branch["mode"] == "advisory"
    branch_name = str(branch["final_output"]["task_artifact"]["name"])
    assert branch_name.startswith("html_page_alt")

    branch_updated = runtime.run_turn(
        f'add a paragraph "branch-only-marker" to {branch_name}',
        {"trace_id": "trace-phase44-branch-3"},
    )
    original_view = runtime.run_turn("edit html_page", {"trace_id": "trace-phase44-branch-4"})

    assert branch_updated["status"] == "success"
    assert branch_updated["final_output"]["task_artifact"]["name"] == branch_name
    assert "branch-only-marker" in branch_updated["final_output"]["example_html"]

    assert original_view["status"] == "success"
    assert original_view["final_output"]["task_artifact"]["name"] == "html_page"
    assert "branch-only-marker" not in original_view["final_output"]["example_html"]


def test_phase44_branch_history_isolation():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("I want to make an html file", {"trace_id": "trace-phase44-biso-1"})
    branch = runtime.run_turn("create a variant", {"trace_id": "trace-phase44-biso-2"})
    branch_name = str(branch["final_output"]["task_artifact"]["name"])
    branch_revision = int(branch["final_output"]["task_artifact"]["revision"])

    runtime.run_turn(
        'add a paragraph "original-only-marker" to html_page',
        {"trace_id": "trace-phase44-biso-3"},
    )
    branch_view = runtime.run_turn(f"edit {branch_name}", {"trace_id": "trace-phase44-biso-4"})

    assert branch_view["status"] == "success"
    assert branch_view["final_output"]["task_artifact"]["name"] == branch_name
    assert branch_view["final_output"]["task_artifact"]["revision"] == branch_revision
    assert "original-only-marker" not in branch_view["final_output"]["example_html"]


def test_phase44_governance_and_safety_unchanged():
    runtime = runtime_mod.BillyRuntime(config={})

    execution_attempt = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase44-exec"},
    )
    governed_action = runtime.run_turn("create a file", {"trace_id": "trace-phase44-governed"})

    assert execution_attempt["status"] == "error"
    assert execution_attempt["mode"] == "aci_intent_gatekeeper"
    assert execution_attempt["final_output"]["type"] == "refusal"

    assert governed_action["status"] == "success"
    assert governed_action["mode"] == "aci_intent_gatekeeper"
    assert governed_action["final_output"]["type"] in {"proposal", "clarification"}
