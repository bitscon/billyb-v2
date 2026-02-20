from __future__ import annotations

import v2.core.runtime as runtime_mod


def test_phase46_execution_plan_is_deterministic_and_read_only():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn(
        "I want to make an html file called phase46.html",
        {"trace_id": "trace-phase46-seed"},
    )
    first = runtime.run_turn(
        "give me the execution plan",
        {"trace_id": "trace-phase46-plan-1"},
    )
    second = runtime.run_turn(
        "give me the execution plan",
        {"trace_id": "trace-phase46-plan-2"},
    )

    assert first["status"] == "success"
    assert first["mode"] == "advisory"
    assert first["execution_enabled"] is False
    assert first["advisory_only"] is True
    assert first["final_output"]["execution_plan_read_only"] is True
    assert first["final_output"]["ready"] is True
    assert first["final_output"]["blocking_issues"] == []

    assert second["status"] == "success"
    assert second["mode"] == "advisory"
    assert first["final_output"]["execution_plan_fingerprint"] == second["final_output"]["execution_plan_fingerprint"]
    assert first["final_output"] == second["final_output"]


def test_phase46_execution_plan_reflects_readiness_blockers():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime._upsert_task_artifact(
        name="html_page",
        artifact_type="html_page",
        content={
            "filename": "broken_phase46.html",
            "html": "<html><body><p>broken",
            "include_style": False,
        },
        summary="Broken html for execution-plan readiness check.",
        source_mode="advisory",
    )
    plan = runtime.run_turn(
        "how do I run this manually?",
        {"trace_id": "trace-phase46-blockers"},
    )

    assert plan["status"] == "success"
    assert plan["mode"] == "advisory"
    assert plan["final_output"]["ready"] is False
    assert plan["final_output"]["blocking_issues"]
    assert any("head" in issue.lower() for issue in plan["final_output"]["blocking_issues"])
    assert any(
        "missing opening `<head>` section.".lower() in item.lower()
        for item in plan["final_output"]["preconditions_to_confirm"]
    )
    assert any("pause manual execution" in step.lower() for step in plan["final_output"]["manual_execution_steps"])


def test_phase46_execution_plan_has_required_sections_and_boundary_notice():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn(
        "I want to make an html file called deploy46.html",
        {"trace_id": "trace-phase46-deploy-seed"},
    )
    plan = runtime.run_turn(
        "what are the steps to deploy this?",
        {"trace_id": "trace-phase46-deploy"},
    )

    assert plan["status"] == "success"
    assert plan["mode"] == "advisory"
    final_output = plan["final_output"]
    assert isinstance(final_output.get("summary"), str) and final_output["summary"].strip()
    assert isinstance(final_output.get("preconditions_to_confirm"), list)
    assert isinstance(final_output.get("manual_preparation_steps"), list)
    assert isinstance(final_output.get("manual_execution_steps"), list)
    assert isinstance(final_output.get("verification_checklist"), list)
    assert isinstance(final_output.get("rollback_recovery_guidance"), list)
    assert isinstance(final_output.get("execution_boundary_notice"), str)
    assert "billy will not execute these steps" in final_output["execution_boundary_notice"].lower()
    assert all(str(step).startswith("YOU will") for step in final_output["manual_execution_steps"])

    rendered = str(final_output.get("rendered_advisory", ""))
    assert "Summary" in rendered
    assert "Preconditions to Confirm" in rendered
    assert "Manual Preparation Steps" in rendered
    assert "Manual Execution Steps" in rendered
    assert "Verification Checklist" in rendered
    assert "Rollback / Recovery Guidance" in rendered
    assert "Execution Boundary Notice" in rendered


def test_phase46_governance_and_execution_behavior_unchanged():
    runtime = runtime_mod.BillyRuntime(config={})

    execution_attempt = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase46-exec"},
    )
    governed_action = runtime.run_turn(
        "create a file",
        {"trace_id": "trace-phase46-governed"},
    )

    assert execution_attempt["status"] == "error"
    assert execution_attempt["mode"] == "aci_intent_gatekeeper"
    assert execution_attempt["final_output"]["type"] == "refusal"

    assert governed_action["status"] == "success"
    assert governed_action["mode"] == "aci_intent_gatekeeper"
    assert governed_action["final_output"]["type"] in {"proposal", "clarification"}
