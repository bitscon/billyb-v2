import v2.core.runtime as runtime_mod


def test_cdm_run_turn_is_read_only_and_structured(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})

    def _fail(*_args, **_kwargs):
        raise AssertionError("CDM should short-circuit before execution paths.")

    monkeypatch.setattr(runtime, "_llm_answer", _fail)
    monkeypatch.setattr(runtime_mod, "_run_deterministic_loop", _fail)
    monkeypatch.setattr(runtime_mod, "_requires_barn_inspection", _fail)
    monkeypatch.setattr(runtime_mod._memory_store, "write", _fail)
    monkeypatch.setattr(runtime_mod._memory_store, "query", _fail)
    monkeypatch.setattr(runtime_mod._docker_runner, "run", _fail)

    result = runtime.run_turn("draft: add validation to parser", {})

    assert result["status"] == "success"
    assert result["tool_calls"] == []
    output = result["final_output"]
    sections = [
        "1. Intent Summary",
        "2. Scope Outline",
        "3. Rationale",
        "4. Code Proposal (diff/snippet/file)",
        "5. Optional Tests",
        "6. Review Notes",
        "7. Approval Request",
    ]
    positions = [output.index(section) for section in sections]
    assert positions == sorted(positions)
    assert "```diff" in output


def test_ask_routes_explicit_cdm_prefix_to_runtime(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})
    observed = {}

    def _fail_llm(_prompt: str) -> str:
        raise AssertionError("Explicit CDM input should not route to _llm_answer.")

    def _fake_run_turn(user_input: str, session_context: dict):
        observed["user_input"] = user_input
        observed["trace_id"] = session_context.get("trace_id")
        return {
            "final_output": "cdm-output",
            "tool_calls": [],
            "status": "success",
            "trace_id": "trace-cdm",
        }

    monkeypatch.setattr(runtime, "_llm_answer", _fail_llm)
    monkeypatch.setattr(runtime, "run_turn", _fake_run_turn)

    response = runtime.ask("fix: tighten null handling in resolver")

    assert response == "cdm-output"
    assert observed["user_input"] == "fix: tighten null handling in resolver"
    assert observed["trace_id"]


def test_ask_requires_explicit_cdm_prefix(monkeypatch):
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

    response = runtime.ask("can you suggest a safer patch for this?")

    assert response == "runtime-output"
    assert observed["user_input"] == "can you suggest a safer patch for this?"
    assert observed["trace_id"]
