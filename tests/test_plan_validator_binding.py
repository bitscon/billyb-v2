import v2.core.runtime as runtime_mod


def test_plan_validation_uses_planning_validator_signature(monkeypatch):
    monkeypatch.setattr(runtime_mod, "_should_use_legacy_routing", lambda _text: True)
    monkeypatch.setattr(
        runtime_mod._llm_planner,
        "propose_many",
        lambda intent, tool_specs: [{"intent": intent, "steps": []}],
    )

    result = runtime_mod.run_turn("/plan validate me", {"trace_id": "trace-plan-validator"})

    assert result["status"] == "success"
    assert "candidates" in result["final_output"]
