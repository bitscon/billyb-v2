import pytest

import v2.core.runtime as runtime_mod


@pytest.mark.parametrize(
    "user_input, token",
    [
        ("/plan", "/plan"),
        ("/engineer map runtime", "/engineer"),
        ("/exec touch /tmp/x", "/exec"),
        ("/ops restart nginx", "/ops"),
        ("/simulate restart nginx", "/simulate"),
        ("a0 status", "a0"),
        ("/unknown command", "/unknown"),
    ],
)
def test_run_turn_rejects_legacy_interactions(user_input: str, token: str):
    runtime = runtime_mod.BillyRuntime(config={})

    result = runtime.run_turn(user_input, {"trace_id": "trace-legacy"})

    assert result["status"] == "error"
    assert "Interaction rejected: legacy interaction" in result["final_output"]
    assert token in result["final_output"]


def test_non_legacy_input_routes_to_deterministic_loop(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})
    observed = {}

    def _fake_loop(user_input: str, trace_id: str):
        observed["user_input"] = user_input
        observed["trace_id"] = trace_id
        return {
            "final_output": "loop-output",
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
        }

    monkeypatch.setattr(runtime_mod, "_run_deterministic_loop", _fake_loop)

    result = runtime.run_turn("locate n8n on the barn", {"trace_id": "trace-loop"})

    assert result["status"] == "success"
    assert result["final_output"] == "loop-output"
    assert observed["user_input"] == "locate n8n on the barn"
    assert observed["trace_id"] == "trace-loop"
