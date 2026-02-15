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


def test_explicit_inspection_input_routes_to_deterministic_loop(monkeypatch):
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


@pytest.mark.parametrize(
    "user_input, expected_mode",
    [
        ("create a file", "governed_interpreter"),
        ("service_foo_bar_12345", "governed_interpreter"),
    ],
)
def test_invalid_ambiguous_input_routes_through_conversational_layer(
    monkeypatch,
    user_input: str,
    expected_mode: str,
):
    runtime = runtime_mod.BillyRuntime(config={})

    def _fail_loop(_user_input: str, _trace_id: str):
        raise AssertionError("Invalid/ambiguous input should not route to deterministic loop.")

    def _fail_inspect(_query: str):
        raise AssertionError("Invalid/ambiguous input should not trigger inspection.")

    monkeypatch.setattr(runtime_mod, "_run_deterministic_loop", _fail_loop)
    monkeypatch.setattr(runtime_mod, "_inspect_barn", _fail_inspect)

    result = runtime.run_turn(user_input, {"trace_id": "trace-invalid"})

    assert result["status"] == "success"
    assert result["mode"] == expected_mode


def test_identity_location_question_routes_to_read_only_without_filesystem_access(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})

    def _fail_llm(_prompt: str) -> str:
        raise AssertionError("Identity-location route must be deterministic and not call LLM.")

    def _fail_loop(_user_input: str, _trace_id: str):
        raise AssertionError("Identity-location route must not trigger deterministic loop.")

    def _fail_inspect(_query: str):
        raise AssertionError("Identity-location route must not trigger inspection.")

    monkeypatch.setattr(runtime, "_llm_answer", _fail_llm)
    monkeypatch.setattr(runtime_mod, "_run_deterministic_loop", _fail_loop)
    monkeypatch.setattr(runtime_mod, "_inspect_barn", _fail_inspect)

    result = runtime.run_turn("where are you?", {"trace_id": "trace-identity-location"})

    assert result["status"] == "success"
    assert result["mode"] == "read_only_conversation"
    assert "runtime host" in result["final_output"].lower()
    assert "path" in result["final_output"].lower()
    assert "port" in result["final_output"].lower()
    assert result["tool_calls"] == []


def test_read_only_informational_question_routes_to_llm(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})
    observed = {}

    def _fake_llm(prompt: str) -> str:
        observed["prompt"] = prompt
        return "informational-response"

    def _fail_loop(_user_input: str, _trace_id: str):
        raise AssertionError("Read-only informational prompt should not route to deterministic loop.")

    def _fail_inspect(_query: str):
        raise AssertionError("Read-only informational prompt should not trigger inspection.")

    monkeypatch.setattr(runtime, "_llm_answer", _fake_llm)
    monkeypatch.setattr(runtime_mod, "_run_deterministic_loop", _fail_loop)
    monkeypatch.setattr(runtime_mod, "_inspect_barn", _fail_inspect)

    result = runtime.run_turn("tell me a fun fact about octopuses", {"trace_id": "trace-read-only"})

    assert result["status"] == "success"
    assert result["final_output"] == "informational-response"
    assert result["tool_calls"] == []
    assert result["mode"] == "read_only_conversation"
    assert observed["prompt"] == "tell me a fun fact about octopuses"


@pytest.mark.parametrize(
    "user_input",
    [
        "what do bees eat?",
        "what services are running on this server?",
    ],
)
def test_read_only_informational_prompts_use_conversational_layer(monkeypatch, user_input: str):
    runtime = runtime_mod.BillyRuntime(config={})

    def _fail_llm(_prompt: str) -> str:
        raise AssertionError("Blocked prompts must not route to LLM conversation path.")

    monkeypatch.setattr(runtime, "_llm_answer", _fail_llm)

    result = runtime.run_turn(user_input, {"trace_id": "trace-read-only-reject"})

    assert result["status"] == "success"
    assert result["mode"] == "conversation_layer"
    assert "invalid/ambiguous" not in result["final_output"].lower()


@pytest.mark.parametrize(
    "user_input",
    [
        "assume governance",
        "use operating model",
        "read onboarding",
    ],
)
def test_governance_handoff_returns_deterministic_instruction_without_filesystem_access(monkeypatch, user_input: str):
    runtime = runtime_mod.BillyRuntime(config={})

    def _fail_llm(_prompt: str) -> str:
        raise AssertionError("Governance handoff must not call LLM.")

    def _fail_loop(_user_input: str, _trace_id: str):
        raise AssertionError("Governance handoff must not trigger deterministic loop.")

    def _fail_inspect(_query: str):
        raise AssertionError("Governance handoff must not trigger inspection.")

    monkeypatch.setattr(runtime, "_llm_answer", _fail_llm)
    monkeypatch.setattr(runtime_mod, "_run_deterministic_loop", _fail_loop)
    monkeypatch.setattr(runtime_mod, "_inspect_barn", _fail_inspect)

    result = runtime.run_turn(user_input, {"trace_id": "trace-governance-handoff"})

    assert result["status"] == "success"
    assert "governance cannot be assumed implicitly" in result["final_output"].lower()
    assert "use: /governance load <path>" in result["final_output"].lower()
    assert "invalid/ambiguous" not in result["final_output"].lower()
    assert result["tool_calls"] == []


def test_content_generation_routes_to_review_only_conversation_without_execution(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})
    observed = {}

    def _fake_llm(prompt: str) -> str:
        observed["prompt"] = prompt
        return "drafted-content"

    def _fail_loop(_user_input: str, _trace_id: str):
        raise AssertionError("Content generation must not route to deterministic loop.")

    def _fail_inspect(_query: str):
        raise AssertionError("Content generation must not trigger inspection.")

    monkeypatch.setattr(runtime, "_llm_answer", _fake_llm)
    monkeypatch.setattr(runtime_mod, "_run_deterministic_loop", _fail_loop)
    monkeypatch.setattr(runtime_mod, "_inspect_barn", _fail_inspect)

    result = runtime.run_turn("Propose a simple HTML homepage template.", {"trace_id": "trace-content-generation"})

    assert result["status"] == "success"
    assert result["mode"] == "content_generation"
    assert result["final_output"] == "drafted-content"
    assert result["tool_calls"] == []
    assert observed["prompt"] == "Propose a simple HTML homepage template."
    assert "approval" not in result["final_output"].lower()


def test_generation_with_execution_terms_does_not_route_to_content_generation(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})

    def _fail_llm(_prompt: str) -> str:
        raise AssertionError("Execution-oriented generation prompts must not route to LLM content generation.")

    monkeypatch.setattr(runtime, "_llm_answer", _fail_llm)

    result = runtime.run_turn(
        "Propose a template and write file index.html",
        {"trace_id": "trace-content-generation-exec-mix"},
    )

    assert result["status"] == "success"
    assert result["mode"] == "governed_interpreter"
    assert "invalid/ambiguous" not in result["final_output"].lower()


def test_action_request_escalates_to_governed_interpreter(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})

    def _fail_llm(_prompt: str) -> str:
        raise AssertionError("Action rejection path must not route to conversational generation.")

    monkeypatch.setattr(runtime, "_llm_answer", _fail_llm)

    result = runtime.run_turn("create a file", {"trace_id": "trace-action-reject-stable"})

    assert result["status"] == "success"
    assert result["mode"] == "governed_interpreter"


def test_content_capture_works_immediately_after_content_generation(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})
    observed = {"calls": 0}

    def _fake_llm(prompt: str) -> str:
        observed["calls"] += 1
        if "propose" in prompt.lower():
            return "<html><body><h1>Homepage</h1></body></html>"
        return "unused"

    monkeypatch.setattr(runtime, "_llm_answer", _fake_llm)

    generated = runtime.run_turn(
        "Propose a simple homepage template.",
        {"trace_id": "trace-capture-source"},
    )
    assert generated["status"] == "success"
    assert generated["mode"] == "content_generation"

    captured = runtime.run_turn(
        "capture this as homepage_template",
        {"trace_id": "trace-capture-explicit"},
    )
    assert captured["status"] == "success"
    assert captured["mode"] == "content_capture"
    assert captured["tool_calls"] == []
    assert captured["next_state"] == "ready_for_input"
    assert captured["captured_content"]["label"] == "homepage_template"
    assert captured["captured_content"]["text"] == "<html><body><h1>Homepage</h1></body></html>"
    assert observed["calls"] == 1


def test_content_capture_rejects_ambiguous_reference(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})

    monkeypatch.setattr(runtime, "_llm_answer", lambda _prompt: "draft-output")

    runtime.run_turn("draft an email welcome message", {"trace_id": "trace-capture-ambiguous-source"})
    rejected = runtime.run_turn("capture it as welcome_email", {"trace_id": "trace-capture-ambiguous"})

    assert rejected["status"] == "error"
    assert rejected["mode"] == "content_capture"
    assert "ambiguous reference" in rejected["final_output"].lower()
    assert rejected["tool_calls"] == []
    assert runtime.get_captured_content_last(10) == []


def test_content_capture_does_not_occur_without_explicit_command(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})
    observed = {"calls": 0}

    def _fake_llm(prompt: str) -> str:
        observed["calls"] += 1
        if "draft" in prompt.lower():
            return "Generated body text."
        return "You are welcome."

    monkeypatch.setattr(runtime, "_llm_answer", _fake_llm)

    runtime.run_turn("draft a short onboarding email", {"trace_id": "trace-capture-none-source"})
    follow_up = runtime.run_turn("thanks", {"trace_id": "trace-capture-none-follow-up"})

    assert follow_up["status"] == "success"
    assert follow_up["tool_calls"] == []
    assert runtime.get_captured_content_last(10) == []
    assert observed["calls"] == 2
