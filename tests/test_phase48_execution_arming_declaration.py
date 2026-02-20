from __future__ import annotations

import v2.core.runtime as runtime_mod


def test_phase48_arming_artifact_exists_and_is_disarmed():
    runtime = runtime_mod.BillyRuntime(config={})

    result = runtime.run_turn("is execution armed?", {"trace_id": "trace-phase48-armed-query"})

    assert result["status"] == "success"
    assert result["mode"] == "advisory"
    assert result["execution_enabled"] is False
    assert result["advisory_only"] is True
    assert result["tool_calls"] == []

    final_output = result["final_output"]
    assert final_output["type"] == "execution_arming_declaration"
    assert final_output["execution_arming_read_only"] is True
    arming = final_output["execution_arming"]
    assert arming["armed"] is False
    assert arming["arming_required_for_execution"] is True
    assert arming["arming_supported"] is False
    assert "not enabled" in str(arming["reason"]).lower()


def test_phase48_conceptual_enable_query_returns_explanation_without_steps():
    runtime = runtime_mod.BillyRuntime(config={})

    result = runtime.run_turn(
        "how would execution be enabled?",
        {"trace_id": "trace-phase48-enable-concept"},
    )

    assert result["status"] == "success"
    assert result["mode"] == "advisory"
    final_output = result["final_output"]
    assert final_output["execution_arming"]["armed"] is False
    explanation = str(final_output.get("conceptual_explanation", ""))
    assert "conceptually" in explanation.lower()
    assert "no enablement steps are provided" in explanation.lower()
    assert "1." not in explanation


def test_phase48_arming_declaration_is_deterministic_and_side_effect_free():
    runtime = runtime_mod.BillyRuntime(config={})

    before_artifacts = dict(runtime._task_artifacts)
    first = runtime.run_turn("is execution armed?", {"trace_id": "trace-phase48-deterministic-1"})
    second = runtime.run_turn("is execution armed?", {"trace_id": "trace-phase48-deterministic-2"})
    after_artifacts = dict(runtime._task_artifacts)

    assert first["status"] == "success"
    assert second["status"] == "success"
    assert first["final_output"] == second["final_output"]
    assert first["final_output"]["manifest_fingerprint"] == second["final_output"]["manifest_fingerprint"]
    assert before_artifacts == after_artifacts


def test_phase48_execution_attempt_behavior_unchanged():
    runtime = runtime_mod.BillyRuntime(config={})

    execution_attempt = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase48-exec"},
    )
    governed_action = runtime.run_turn("create a file", {"trace_id": "trace-phase48-governed"})

    assert execution_attempt["status"] == "error"
    assert execution_attempt["mode"] == "aci_intent_gatekeeper"
    assert execution_attempt["final_output"]["type"] == "refusal"

    assert governed_action["status"] == "success"
    assert governed_action["mode"] == "aci_intent_gatekeeper"
    assert governed_action["final_output"]["type"] in {"proposal", "clarification"}
