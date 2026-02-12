import v2.core.runtime as runtime_mod


def test_ask_identity_question_bypasses_llm(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})

    def _should_not_call_llm(_prompt: str) -> str:
        raise AssertionError("LLM should not be called for deterministic identity questions.")

    monkeypatch.setattr(runtime, "_llm_answer", _should_not_call_llm)

    response = runtime.ask("Who are you?")
    assert response == "I am Billy, the Farm Hand and Foreman operating inside workshop.home."


def test_run_turn_identity_question_bypasses_task_graph(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})

    def _should_not_run_loop(_user_input: str, _trace_id: str):
        raise AssertionError("Deterministic loop should not run for identity questions.")

    monkeypatch.setattr(runtime_mod, "_run_deterministic_loop", _should_not_run_loop)

    result = runtime.run_turn("what is my name?", {})
    assert result["status"] == "success"
    assert result["final_output"] == (
        "You are Chad McCormack, the owner/operator of workshop.home."
    )


def test_ask_non_identity_question_routes_through_runtime_dispatch(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})
    observed = {}

    def _should_not_call_llm(_prompt: str) -> str:
        raise AssertionError("ask() should route through run_turn, not direct LLM fallback.")

    def _fake_run_turn(user_input: str, session_context: dict):
        observed["user_input"] = user_input
        observed["trace_id"] = session_context.get("trace_id")
        return {
            "final_output": "runtime-response",
            "tool_calls": [],
            "status": "success",
            "trace_id": "trace-dispatch",
        }

    monkeypatch.setattr(runtime, "_llm_answer", _should_not_call_llm)
    monkeypatch.setattr(runtime, "run_turn", _fake_run_turn)

    response = runtime.ask("Give me a short summary of the logs.")
    assert response == "runtime-response"
    assert observed["user_input"] == "Give me a short summary of the logs."
    assert observed["trace_id"]
