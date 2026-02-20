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
        ("create a file", "aci_intent_gatekeeper"),
        ("service_foo_bar_12345", "conversation_layer"),
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
        "read ONBOARDING.md",
        "show me /etc/passwd",
    ],
)
def test_read_like_prompts_stay_non_authoritative_without_governed_or_inspection(monkeypatch, user_input: str):
    runtime = runtime_mod.BillyRuntime(config={})

    def _fail_governed(_intent_envelope):
        raise AssertionError("Read-like non-authoritative prompts must not enter governed interpreter execution.")

    def _fail_loop(_user_input: str, _trace_id: str):
        raise AssertionError("Read-like non-authoritative prompts must not trigger deterministic loop.")

    def _fail_inspect(_query: str):
        raise AssertionError("Read-like non-authoritative prompts must not trigger inspection.")

    monkeypatch.setattr(runtime_mod, "run_governed_interpreter", _fail_governed)
    monkeypatch.setattr(runtime_mod, "_run_deterministic_loop", _fail_loop)
    monkeypatch.setattr(runtime_mod, "_inspect_barn", _fail_inspect)

    result = runtime.run_turn(user_input, {"trace_id": f"trace-read-non-authority-{abs(hash(user_input))}"})

    assert result["status"] == "success"
    assert result["mode"] == "conversation_layer"
    assert result["tool_calls"] == []
    assert "governance cannot be assumed implicitly" not in result["final_output"].lower()


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
    assert result["mode"] == "aci_intent_gatekeeper"
    assert isinstance(result["final_output"], dict)
    assert result["final_output"]["type"] in {"proposal", "clarification", "refusal"}


def test_action_request_escalates_to_aci_gatekeeper(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})

    def _fail_llm(_prompt: str) -> str:
        raise AssertionError("Action rejection path must not route to conversational generation.")

    monkeypatch.setattr(runtime, "_llm_answer", _fail_llm)

    result = runtime.run_turn("create a file", {"trace_id": "trace-action-reject-stable"})

    assert result["status"] == "success"
    assert result["mode"] == "aci_intent_gatekeeper"


def test_phase34_hello_routes_to_conversational_response(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})

    monkeypatch.setattr(runtime, "_llm_answer", lambda _prompt: "hello-response")

    result = runtime.run_turn("hello", {"trace_id": "trace-phase34-hello"})

    assert result["status"] == "success"
    assert result.get("mode") != "aci_intent_gatekeeper"
    assert result["final_output"] == "hello-response"


def test_phase34_informational_query_routes_to_chat_without_aci(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})

    monkeypatch.setattr(runtime, "_llm_answer", lambda _prompt: "fact-response")

    result = runtime.run_turn("tell me a fun fact about octopuses", {"trace_id": "trace-phase34-info"})

    assert result["status"] == "success"
    assert result["mode"] == "read_only_conversation"
    assert result["final_output"] == "fact-response"


@pytest.mark.parametrize(
    "user_input",
    [
        "plan a safe rollout for nginx service updates",
        "what should I check before restarting nginx?",
    ],
)
def test_phase34_advisory_and_planning_requests_return_advisory_output(monkeypatch, user_input: str):
    runtime = runtime_mod.BillyRuntime(config={})

    def _fail_llm(_prompt: str) -> str:
        raise AssertionError("Advisory/planning dispatch must not call direct chat generation.")

    monkeypatch.setattr(runtime, "_llm_answer", _fail_llm)

    result = runtime.run_turn(user_input, {"trace_id": f"trace-phase34-advisory-{abs(hash(user_input))}"})

    assert result["status"] == "success"
    assert result["mode"] == "advisory"
    assert result["execution_enabled"] is False
    assert result["advisory_only"] is True
    assert isinstance(result["final_output"], dict)
    assert result["final_output"]["mode"] == "advisory"
    assert result["final_output"]["execution_enabled"] is False
    assert result["final_output"]["advisory_only"] is True


def test_phase34_execution_attempt_still_refused_by_aci():
    runtime = runtime_mod.BillyRuntime(config={})

    result = runtime.run_turn("run this now and execute immediately", {"trace_id": "trace-phase34-exec"})

    assert result["mode"] == "aci_intent_gatekeeper"
    assert result["status"] == "error"
    assert isinstance(result["final_output"], dict)
    assert result["final_output"]["type"] == "refusal"


def test_phase34_governed_action_request_routes_to_aci_gatekeeper():
    runtime = runtime_mod.BillyRuntime(config={})

    result = runtime.run_turn("create a file", {"trace_id": "trace-phase34-governed"})

    assert result["mode"] == "aci_intent_gatekeeper"
    assert result["status"] == "success"
    assert isinstance(result["final_output"], dict)
    assert result["final_output"]["type"] in {"proposal", "clarification"}


def test_phase36_follow_up_how_resolves_against_previous_request(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})

    def _fail_llm(_prompt: str) -> str:
        raise AssertionError("Website advisory and follow-up should not require direct LLM chat generation.")

    monkeypatch.setattr(runtime, "_llm_answer", _fail_llm)

    first_request = "Can we build a website page called test.html with a heading and intro copy?"
    first = runtime.run_turn(first_request, {"trace_id": "trace-phase36-followup-1"})
    assert first["status"] == "success"
    assert first["mode"] == "advisory"

    follow_up = runtime.run_turn("how?", {"trace_id": "trace-phase36-followup-2"})
    assert follow_up["status"] == "success"
    assert follow_up["mode"] == "advisory"
    assert follow_up["execution_enabled"] is False
    assert follow_up["advisory_only"] is True
    assert follow_up["final_output"]["follow_up"]["question"] == "how"
    assert follow_up["final_output"]["follow_up"]["resolved_from"] == first_request
    assert "NOT EXECUTED" in follow_up["final_output"]["message"]

    repeated = runtime.run_turn("how?", {"trace_id": "trace-phase36-followup-3"})
    assert repeated["final_output"] == follow_up["final_output"]


def test_phase36_website_build_request_returns_advisory_plan_and_html(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})

    def _fail_llm(_prompt: str) -> str:
        raise AssertionError("Website build advisory path should not call direct LLM chat generation.")

    monkeypatch.setattr(runtime, "_llm_answer", _fail_llm)

    result = runtime.run_turn(
        "can we build a website page called landing.html for spring launch",
        {"trace_id": "trace-phase36-website"},
    )

    assert result["status"] == "success"
    assert result["mode"] == "advisory"
    assert result["execution_enabled"] is False
    assert result["advisory_only"] is True
    assert result["final_output"]["mode"] == "advisory"
    assert result["final_output"]["execution_enabled"] is False
    assert result["final_output"]["advisory_only"] is True
    assert "plan_steps" in result["final_output"]
    assert result["final_output"]["plan_steps"]
    assert "<!doctype html>" in result["final_output"]["example_html"].lower()
    assert "<title>landing.html</title>" in result["final_output"]["example_html"].lower()
    assert all(cmd.startswith("NOT EXECUTED:") for cmd in result["final_output"]["suggested_commands"])


def test_phase36_terminal_filler_is_suppressed_on_repeated_turns(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})

    monkeypatch.setattr(runtime, "_llm_answer", lambda _prompt: "I can help with that.")

    first = runtime.run_turn("tell me something useful", {"trace_id": "trace-phase36-filler-1"})
    second = runtime.run_turn("tell me something useful", {"trace_id": "trace-phase36-filler-2"})

    assert first["status"] == "success"
    assert second["status"] == "success"
    assert first["final_output"].strip().lower() != "i can help with that."
    assert second["final_output"].strip().lower() != "i can help with that."
    assert "what outcome do you want" in first["final_output"].lower()
    assert "what outcome do you want" in second["final_output"].lower()


def test_phase36_execution_attempt_still_refused_after_conversational_context():
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn(
        "can we build a website page called test.html",
        {"trace_id": "trace-phase36-exec-setup"},
    )
    execution_attempt = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-phase36-exec"},
    )

    assert execution_attempt["mode"] == "aci_intent_gatekeeper"
    assert execution_attempt["status"] == "error"
    assert isinstance(execution_attempt["final_output"], dict)
    assert execution_attempt["final_output"]["type"] == "refusal"


def test_phase36_identity_response_remains_unchanged():
    runtime = runtime_mod.BillyRuntime(config={})

    result = runtime.run_turn("who are you?", {"trace_id": "trace-phase36-identity"})

    assert result["status"] == "success"
    assert result["final_output"] == "I am Billy, the Farm Hand and Foreman operating inside workshop.home."


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
