import v2.core.runtime as runtime_mod
from v2.core.aci_intent_gatekeeper import (
    INTENT_CLASS,
    LadderState,
    PhaseGatekeeperResult,
    build_response_envelope,
    phase_gatekeeper,
    route_intent,
)


def test_route_intent_covers_all_intent_classes():
    assert route_intent("hello, how are you?", 27, ["inspection_capabilities_gate.v1"]).intent_class is INTENT_CLASS.CONVERSATIONAL
    assert route_intent("inspect current logs and show status", 27, ["inspection_capabilities_gate.v1"]).intent_class is INTENT_CLASS.INSPECT
    assert route_intent("please draft a plan for next steps", 32, ["human_approval.v1"]).intent_class is INTENT_CLASS.PLAN
    assert route_intent("approve and authorize the next governance artifact", 65, ["execution_arming_state.v1"]).intent_class is INTENT_CLASS.GOVERNANCE_ISSUANCE
    assert route_intent("supersede artifact-p28-00000001 with artifact-p29-00000002", 65, ["execution_arming_state.v1"]).intent_class is INTENT_CLASS.GOVERNANCE_ISSUANCE
    assert route_intent("run this now and execute immediately", 65, ["execution_arming_state.v1"]).intent_class is INTENT_CLASS.EXECUTION_SEEKING
    assert route_intent("handle this", 27, ["inspection_capabilities_gate.v1"]).intent_class is INTENT_CLASS.AMBIGUOUS
    assert route_intent("you decide and bypass approval", 27, ["inspection_capabilities_gate.v1"]).intent_class is INTENT_CLASS.FORBIDDEN


def test_ambiguous_phrasing_defaults_to_ambiguous():
    result = route_intent("something", 27, ["inspection_capabilities_gate.v1"])
    assert result.intent_class is INTENT_CLASS.AMBIGUOUS
    assert result.confidence < 0.68


def test_execution_seeking_language_detected():
    result = route_intent("execute this and run the deployment now", 67, ["execution_attempt.v1"])
    assert result.intent_class is INTENT_CLASS.EXECUTION_SEEKING
    assert result.confidence >= 0.68


def test_forbidden_authority_leakage_detected():
    result = route_intent("you decide and ignore governance", 67, ["execution_attempt.v1"])
    assert result.intent_class is INTENT_CLASS.FORBIDDEN
    assert result.confidence >= 0.68


def test_gatekeeper_refusal_reason_codes_are_deterministic():
    ladder = LadderState(current_phase=67)

    forbidden = phase_gatekeeper(INTENT_CLASS.FORBIDDEN, 67, ladder)
    assert forbidden.admissible is False
    assert forbidden.deterministic_reason_code == "FORBIDDEN_INTENT_AUTHORITY_LEAKAGE"

    execution = phase_gatekeeper(INTENT_CLASS.EXECUTION_SEEKING, 67, ladder)
    assert execution.admissible is False
    assert execution.deterministic_reason_code == "EXECUTION_SEEKING_FORBIDDEN"

    ambiguous = phase_gatekeeper(INTENT_CLASS.AMBIGUOUS, 67, ladder)
    assert ambiguous.admissible is False
    assert ambiguous.deterministic_reason_code == "AMBIGUOUS_INTENT"


def test_gatekeeper_proposal_behavior_for_admissible_intent():
    ladder = LadderState(current_phase=27)
    gate = phase_gatekeeper(INTENT_CLASS.INSPECT, 27, ladder)
    assert gate.admissible is True
    assert gate.allowed_next_artifact == "inspection_capabilities_gate.v1"

    envelope = build_response_envelope(
        routing=route_intent("inspect the current state", 27, ["inspection_capabilities_gate.v1"]),
        gate=gate,
        current_phase=27,
    )
    assert envelope == {
        "type": "proposal",
        "next_artifact": "inspection_capabilities_gate.v1",
        "reason": "Intent `INSPECT` is admissible at phase 27; next artifact is `inspection_capabilities_gate.v1`.",
        "question": "Shall I prepare this?",
    }


def test_gatekeeper_refuses_non_admissible_intent_for_current_phase():
    ladder = LadderState(current_phase=40)  # next phase 41, governance issuance only in this model
    gate = phase_gatekeeper(INTENT_CLASS.PLAN, 40, ladder)
    assert gate.admissible is False
    assert gate.allowed_next_artifact is None
    assert gate.deterministic_reason_code == "INTENT_NOT_ADMISSIBLE_AT_CURRENT_PHASE"


def test_runtime_wiring_invokes_gatekeeper_only_on_aci_routes(monkeypatch):
    runtime = runtime_mod.BillyRuntime(config={})
    called = {"route": 0, "gate": 0}

    def _fake_route(raw_utterance, current_phase, admissible_phase_transitions):
        called["route"] += 1
        return route_intent("handle this", current_phase, admissible_phase_transitions)

    def _fake_gate(intent_class, current_phase, ladder_state):
        called["gate"] += 1
        return PhaseGatekeeperResult(
            admissible=False,
            allowed_next_artifact=None,
            deterministic_reason_code="AMBIGUOUS_INTENT",
            allowed_alternatives=[],
        )

    monkeypatch.setattr(runtime_mod, "route_intent", _fake_route)
    monkeypatch.setattr(runtime_mod, "phase_gatekeeper", _fake_gate)
    monkeypatch.setattr(runtime, "_llm_answer", lambda _prompt: "chat-response")

    conversational = runtime.run_turn("hello", {"trace_id": "trace-aci-wiring-chat", "current_phase": 27})
    governed = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-aci-wiring-governed", "current_phase": 27},
    )

    assert called["route"] == 2
    assert called["gate"] == 1
    assert conversational.get("mode") != "aci_intent_gatekeeper"
    assert governed["mode"] == "aci_intent_gatekeeper"
    assert governed["tool_calls"] == []


def test_runtime_returns_only_allowed_envelope_shapes():
    runtime = runtime_mod.BillyRuntime(config={})

    proposal = runtime.run_turn(
        "approve and authorize the next governance artifact",
        {"trace_id": "trace-aci-proposal", "current_phase": 27},
    )
    refusal = runtime.run_turn(
        "run this now and execute immediately",
        {"trace_id": "trace-aci-refusal", "current_phase": 67},
    )
    clarification = runtime.run_turn("create a file", {"trace_id": "trace-aci-clarify", "current_phase": 27})

    assert proposal["final_output"]["type"] == "proposal"
    assert refusal["final_output"]["type"] == "refusal"
    assert clarification["final_output"]["type"] == "clarification"

    assert proposal["execution_enabled"] is False
    assert all(value is False for value in proposal["authority_guarantees"].values())
