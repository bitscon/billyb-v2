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


def test_ask_non_identity_question_still_routes_to_llm(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})
    calls = []

    def _fake_llm(prompt: str) -> str:
        calls.append(prompt)
        return "llm-response"

    monkeypatch.setattr(runtime, "_llm_answer", _fake_llm)

    response = runtime.ask("Give me a short summary of the logs.")
    assert response == "llm-response"
    assert calls == ["Give me a short summary of the logs."]
