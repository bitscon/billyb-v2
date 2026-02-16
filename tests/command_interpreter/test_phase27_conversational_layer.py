from __future__ import annotations

import pytest

import v2.core.command_interpreter as interpreter
from v2.core.conversation_layer import process_conversational_turn, run_governed_interpreter


def _set_flags(*, phase3: bool, phase4: bool, phase4_explain: bool, phase5: bool, phase8: bool) -> None:
    interpreter.set_phase3_enabled(phase3)
    interpreter.set_phase4_enabled(phase4)
    interpreter.set_phase4_explanation_enabled(phase4_explain)
    interpreter.set_phase5_enabled(phase5)
    interpreter.set_phase8_enabled(phase8)
    interpreter.set_phase8_approval_mode("step")
    interpreter.set_phase19_enabled(True)
    interpreter.set_phase20_enabled(True)
    interpreter.set_phase21_enabled(True)
    interpreter.set_phase22_enabled(True)
    interpreter.set_phase23_enabled(True)
    interpreter.set_phase24_enabled(True)
    interpreter.set_phase25_enabled(True)
    interpreter.set_phase26_enabled(True)


@pytest.fixture(autouse=True)
def _phase27_state():
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.set_tool_invoker(interpreter.StubToolInvoker())
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        yield
    finally:
        interpreter.reset_phase5_state()
        _set_flags(phase3=False, phase4=False, phase4_explain=False, phase5=False, phase8=False)
        interpreter.set_tool_invoker(interpreter.StubToolInvoker())
        interpreter.configure_memory_store("in_memory")
        interpreter.configure_capture_store("in_memory")


def test_simple_chat():
    result = process_conversational_turn("tell me a joke")
    assert result["escalate"] is False
    assert "joke" in result["chat_response"].lower()


def test_thanks_response():
    result = process_conversational_turn("thanks for the help!")
    assert result["escalate"] is False


def test_simple_escalation():
    result = process_conversational_turn("save this idea to a file")
    assert result["escalate"] is True
    assert "intent_envelope" in result
    assert result["intent_envelope"]["intent"] in {
        "write_file",
        "persist_note",
        "plan.user_action_request",
        "clarify.request_context",
    }


def test_mixed_chat_then_action():
    result = process_conversational_turn("that looks good; now save it")
    assert result["escalate"] is True


def test_ambiguous_then_clarify():
    result = process_conversational_turn("I want something done")
    assert result["escalate"] is True
    assert result["intent_envelope"]["intent"] in {"clarify.request_context", "plan.user_action_request"}


def test_chat_no_governed_invocation():
    convo = process_conversational_turn("what is billy's policy?")
    assert "governed_result" not in convo
    assert convo["escalate"] is False


@pytest.mark.parametrize(
    "utterance",
    [
        "read ONBOARDING.md",
        "show me /etc/passwd",
        "read this file",
    ],
)
def test_read_like_language_stays_chat_only_without_escalation(utterance: str):
    result = process_conversational_turn(utterance)
    assert result["escalate"] is False
    assert "chat_response" in result
    assert "intent_envelope" not in result


def test_explicit_structured_read_file_request_escalates():
    result = process_conversational_turn("read file notes.txt from my workspace")
    assert result["escalate"] is True
    assert result["intent_envelope"]["intent"] == "read_file"


def test_escalation_routes_to_billy():
    conv = process_conversational_turn("write text hello to file hello.html in my workspace")
    assert conv["escalate"] is True

    governed = run_governed_interpreter(conv["intent_envelope"])
    assert governed["intent"] == "write_file"
