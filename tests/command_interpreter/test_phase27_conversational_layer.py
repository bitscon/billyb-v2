from __future__ import annotations

import pytest

import v2.core.command_interpreter as interpreter
from v2.core.conversation_layer import (
    IntentClass,
    classify_turn_intent,
    get_intent_routing_audit_log,
    process_conversational_turn,
    reset_intent_routing_audit_log,
    run_governed_interpreter,
)
from v2.core.proposal_governance import reset_proposal_ledger


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
    reset_intent_routing_audit_log()
    reset_proposal_ledger()
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
        reset_proposal_ledger()
        reset_intent_routing_audit_log()


def test_canonical_intent_classes_are_exact_and_immutable():
    assert {entry.value for entry in IntentClass} == {
        "informational_query",
        "generative_content_request",
        "advisory_request",
        "planning_request",
        "governed_action_proposal",
        "execution_attempt",
        "policy_boundary_challenge",
        "meta_governance_inquiry",
        "ambiguous_intent",
    }


def test_simple_chat_is_informational_and_non_escalating():
    result = process_conversational_turn("tell me a joke")
    assert result["intent_class"] == IntentClass.INFORMATIONAL_QUERY.value
    assert result["escalate"] is False
    assert isinstance(result["reason"], str) and result["reason"]
    assert "joke" in result["chat_response"].lower()
    assert result["routing_contract"]["immutable"] is True


def test_thanks_response():
    result = process_conversational_turn("thanks for the help!")
    assert result["intent_class"] == IntentClass.INFORMATIONAL_QUERY.value
    assert result["escalate"] is False


def test_simple_escalation_is_governed_action_proposal():
    result = process_conversational_turn("save this idea to a file")
    assert result["intent_class"] == IntentClass.GOVERNED_ACTION_PROPOSAL.value
    assert result["escalate"] is True
    assert "intent_envelope" in result
    assert result["intent_envelope"]["intent_class"] == IntentClass.GOVERNED_ACTION_PROPOSAL.value


def test_mixed_chat_then_action():
    result = process_conversational_turn("that looks good; now save it")
    assert result["intent_class"] == IntentClass.GOVERNED_ACTION_PROPOSAL.value
    assert result["escalate"] is True


def test_ambiguous_routes_to_ambiguous_intent_without_escalation():
    result = process_conversational_turn("I want something done")
    assert result["intent_class"] == IntentClass.AMBIGUOUS_INTENT.value
    assert result["escalate"] is False
    assert "intent_envelope" not in result


def test_chat_no_governed_invocation():
    convo = process_conversational_turn("what is billy's policy?")
    assert convo["intent_class"] == IntentClass.META_GOVERNANCE_INQUIRY.value
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
    assert result["intent_class"] in {
        IntentClass.INFORMATIONAL_QUERY.value,
        IntentClass.AMBIGUOUS_INTENT.value,
    }
    assert result["escalate"] is False
    assert "chat_response" in result
    assert "intent_envelope" not in result


def test_explicit_structured_read_file_request_escalates():
    result = process_conversational_turn("read file notes.txt from my workspace")
    assert result["intent_class"] == IntentClass.GOVERNED_ACTION_PROPOSAL.value
    assert result["escalate"] is True
    assert result["intent_envelope"]["intent_class"] == IntentClass.GOVERNED_ACTION_PROPOSAL.value


def test_governed_action_proposal_routes_to_proposal_envelope():
    conv = process_conversational_turn("write text hello to file hello.html in my workspace")
    assert conv["intent_class"] == IntentClass.GOVERNED_ACTION_PROPOSAL.value
    assert conv["escalate"] is True

    governed = run_governed_interpreter(conv["intent_envelope"])
    assert governed["intent"] == "write_file"
    assert governed["governed_result"]["type"] == "proposal"
    assert governed["governed_result"]["executed"] is False
    proposal_envelope = governed["governed_result"]["proposal_envelope"]
    assert proposal_envelope["requires_approval"] is True
    assert proposal_envelope["approved"] is False
    assert proposal_envelope["executed"] is False


def test_execution_attempt_escalates_and_refuses_deterministically_with_citation():
    conv = process_conversational_turn("run this now and execute immediately")
    assert conv["intent_class"] == IntentClass.EXECUTION_ATTEMPT.value
    assert conv["escalate"] is True

    governed = run_governed_interpreter(conv["intent_envelope"])
    assert governed["intent"] == IntentClass.EXECUTION_ATTEMPT.value
    assert governed["governed_result"]["type"] == "execution_rejected"
    assert governed["governed_result"]["executed"] is False
    assert "governance citation" in governed["response"].lower()
    assert governed["governed_result"]["governance_citation"].endswith(
        "08_TOOLS_WORKERS_EXECUTION.md"
    )


def test_classification_output_contains_required_fields_and_is_single_label():
    classified = classify_turn_intent("plan next steps for a release")
    assert set(classified.keys()) >= {"intent_class", "escalate", "reason"}
    assert isinstance(classified["intent_class"], str)
    assert classified["intent_class"] in {entry.value for entry in IntentClass}


def test_repeated_identical_input_is_deterministic_and_stable():
    first = process_conversational_turn("save this idea to a file")
    second = process_conversational_turn("save this idea to a file")
    for key in ("intent_class", "escalate", "reason", "routing_contract"):
        assert first[key] == second[key]


def test_routing_contract_is_auditable_and_append_only():
    process_conversational_turn("tell me a joke")
    process_conversational_turn("save this idea to a file")
    audit_log = get_intent_routing_audit_log()
    assert len(audit_log) == 2
    assert all(entry["immutable"] is True for entry in audit_log)
    assert all(entry["decision_fingerprint"] for entry in audit_log)
