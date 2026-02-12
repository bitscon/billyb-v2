import v2.core.runtime as runtime_mod


def test_plan_validation_uses_planning_validator_signature(monkeypatch):
    result = runtime_mod.run_turn("/plan validate me", {"trace_id": "trace-plan-validator"})

    assert result["status"] == "error"
    assert "legacy interaction '/plan'" in result["final_output"]
