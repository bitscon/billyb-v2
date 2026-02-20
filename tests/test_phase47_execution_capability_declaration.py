from __future__ import annotations

import v2.core.runtime as runtime_mod


def test_phase47_capability_declaration_present_and_disabled():
    runtime = runtime_mod.BillyRuntime(config={})

    result = runtime.run_turn("what can you execute?", {"trace_id": "trace-phase47-declaration"})

    assert result["status"] == "success"
    assert result["mode"] == "advisory"
    assert result["execution_enabled"] is False
    assert result["advisory_only"] is True
    assert result["tool_calls"] == []

    final_output = result["final_output"]
    assert final_output["type"] == "execution_capability_declaration"
    assert final_output["can_execute"] is False
    assert final_output["executable_actions"] == "none"
    assert final_output["capability_declaration_read_only"] is True
    assert final_output["execution_capabilities"]["enabled"] is False
    assert final_output["execution_capabilities"]["available_modes"] == []
    declared_absences = final_output["execution_capabilities"]["declared_absences"]
    assert "file_write" in declared_absences
    assert "command_execution" in declared_absences
    assert "network_calls" in declared_absences
    assert "service_control" in declared_absences
    assert "none" in final_output["message"].lower()


def test_phase47_queries_return_explicit_absence_for_execution():
    runtime = runtime_mod.BillyRuntime(config={})

    can_you_run = runtime.run_turn("can you run this?", {"trace_id": "trace-phase47-run-query"})
    what_execute = runtime.run_turn("what can you execute?", {"trace_id": "trace-phase47-what-query"})

    assert can_you_run["status"] == "success"
    assert what_execute["status"] == "success"
    assert can_you_run["mode"] == "advisory"
    assert what_execute["mode"] == "advisory"
    assert can_you_run["final_output"]["can_execute"] is False
    assert what_execute["final_output"]["can_execute"] is False
    assert can_you_run["final_output"]["execution_capabilities"]["available_modes"] == []
    assert what_execute["final_output"]["execution_capabilities"]["available_modes"] == []
    assert (
        can_you_run["final_output"]["manifest_fingerprint"]
        == what_execute["final_output"]["manifest_fingerprint"]
    )


def test_phase47_capability_declaration_is_deterministic_and_side_effect_free():
    runtime = runtime_mod.BillyRuntime(config={})

    before_artifacts = dict(runtime._task_artifacts)
    first = runtime.run_turn("what can you execute?", {"trace_id": "trace-phase47-deterministic-1"})
    second = runtime.run_turn("what can you execute?", {"trace_id": "trace-phase47-deterministic-2"})
    after_artifacts = dict(runtime._task_artifacts)

    assert first["status"] == "success"
    assert second["status"] == "success"
    assert first["final_output"] == second["final_output"]
    assert before_artifacts == after_artifacts
    assert "Billy will not execute commands or tools now." in first["final_output"]["execution_boundary_notice"]


def test_phase47_governance_and_execution_behavior_unchanged():
    runtime = runtime_mod.BillyRuntime(config={})

    execution_attempt = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase47-exec"},
    )
    governed_action = runtime.run_turn("create a file", {"trace_id": "trace-phase47-governed"})

    assert execution_attempt["status"] == "error"
    assert execution_attempt["mode"] == "aci_intent_gatekeeper"
    assert execution_attempt["final_output"]["type"] == "refusal"

    assert governed_action["status"] == "success"
    assert governed_action["mode"] == "aci_intent_gatekeeper"
    assert governed_action["final_output"]["type"] in {"proposal", "clarification"}
