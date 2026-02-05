import v2.core.runtime as runtime_mod


def _seed_inspection(units: list[str]) -> None:
    runtime_mod._last_inspection.clear()
    runtime_mod._last_inspection.update(
        {
            "timestamp": "2026-02-04T00:00:00Z",
            "systemd_units": units,
            "systemd_lines": {unit: f"{unit} loaded active running" for unit in units},
        }
    )


def test_high_risk_requires_ops():
    response = runtime_mod.run_turn("/exec systemctl restart nginx", {})
    assert "high-risk operation requires /ops" in response["final_output"]


def test_ops_plan_requires_observed_target():
    _seed_inspection(["nginx.service"])
    response = runtime_mod.run_turn("/ops restart nginx", {})
    assert "Atomic action plan:" in response["final_output"]
    assert "Command: sudo systemctl restart nginx.service" in response["final_output"]
    assert "Command: systemctl status nginx.service" in response["final_output"]
    assert "Approve? (yes/no)" in response["final_output"]


def test_ops_rejects_unobserved_target():
    _seed_inspection(["ssh.service"])
    response = runtime_mod.run_turn("/ops restart nginx", {})
    assert "Cannot proceed: target was not observed during inspection." in response["final_output"]


def test_ops_rejects_non_atomic():
    _seed_inspection(["nginx.service"])
    response = runtime_mod.run_turn("/ops restart nginx now", {})
    assert "Atomic action required" in response["final_output"]
