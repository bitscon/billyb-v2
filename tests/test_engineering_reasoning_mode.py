import v2.core.runtime as runtime_mod


def test_erm_run_turn_is_read_only_and_structured(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})

    def _fail(*_args, **_kwargs):
        raise AssertionError("ERM should short-circuit before execution paths.")

    monkeypatch.setattr(runtime, "_llm_answer", _fail)
    monkeypatch.setattr(runtime_mod, "_run_deterministic_loop", _fail)
    monkeypatch.setattr(runtime_mod, "_requires_barn_inspection", _fail)
    monkeypatch.setattr(runtime_mod._memory_store, "write", _fail)
    monkeypatch.setattr(runtime_mod._memory_store, "query", _fail)
    monkeypatch.setattr(runtime_mod._docker_runner, "run", _fail)

    result = runtime.run_turn("analyze: map restart-service behavior", {})

    assert result["status"] == "success"
    assert result["tool_calls"] == []

    output = result["final_output"]
    sections = [
        "Understanding of the request",
        "Current system behavior",
        "Options",
        "Tradeoffs / risks",
        "Recommendation",
        "Explicit next-step approval request",
    ]
    positions = [output.index(section) for section in sections]
    assert positions == sorted(positions)
    assert "approve erm option" in output.lower()


def test_ask_routes_explicit_erm_prefix_to_runtime(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})
    observed = {}

    def _fail_llm(_prompt: str) -> str:
        raise AssertionError("Explicit ERM input should not route to _llm_answer.")

    def _fake_run_turn(user_input: str, session_context: dict):
        observed["user_input"] = user_input
        observed["trace_id"] = session_context.get("trace_id")
        return {
            "final_output": "erm-output",
            "tool_calls": [],
            "status": "success",
            "trace_id": "trace-erm",
        }

    monkeypatch.setattr(runtime, "_llm_answer", _fail_llm)
    monkeypatch.setattr(runtime, "run_turn", _fake_run_turn)

    response = runtime.ask("review: inspect runtime guards")

    assert response == "erm-output"
    assert observed["user_input"] == "review: inspect runtime guards"
    assert observed["trace_id"]


def test_ask_requires_explicit_erm_prefix(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})
    observed = {}

    def _fail_llm(_prompt: str) -> str:
        raise AssertionError("ask() should not use direct LLM fallback for non-prefixed text.")

    def _fake_run_turn(user_input: str, session_context: dict):
        observed["user_input"] = user_input
        observed["trace_id"] = session_context.get("trace_id")
        return {
            "final_output": "runtime-output",
            "tool_calls": [],
            "status": "success",
            "trace_id": "trace-runtime",
        }

    monkeypatch.setattr(runtime, "_llm_answer", _fail_llm)
    monkeypatch.setattr(runtime, "run_turn", _fake_run_turn)

    response = runtime.ask("please review this module")

    assert response == "runtime-output"
    assert observed["user_input"] == "please review this module"
    assert observed["trace_id"]
