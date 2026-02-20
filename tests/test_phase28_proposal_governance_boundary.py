from __future__ import annotations

from v2.core.conversation_layer import (
    IntentClass,
    process_conversational_turn,
    reset_intent_routing_audit_log,
    run_governed_interpreter,
)
from v2.core.proposal_governance import (
    PROPOSAL_STATE_APPROVED,
    PROPOSAL_STATE_DRAFTED,
    PROPOSAL_STATE_EXPIRED,
    PROPOSAL_STATE_REJECTED,
    PROPOSAL_STATE_SUBMITTED,
    PROPOSAL_STATES,
    REQUIRED_INTENT_CLASS,
    approve_proposal,
    create_proposal,
    enforce_proposal_expiration,
    get_proposal,
    get_proposal_ledger,
    reject_proposal,
    reset_proposal_ledger,
    submit_proposal,
)


def _draft_from_phase27(utterance: str = "save this idea to a file") -> dict:
    routed = process_conversational_turn(utterance)
    assert routed["intent_class"] == IntentClass.GOVERNED_ACTION_PROPOSAL.value
    assert routed["escalate"] is True
    governed = run_governed_interpreter(routed["intent_envelope"])
    assert governed["governed_result"]["type"] == "proposal"
    return governed["governed_result"]["proposal_artifact"]


def setup_function() -> None:
    reset_intent_routing_audit_log()
    reset_proposal_ledger()


def teardown_function() -> None:
    reset_proposal_ledger()
    reset_intent_routing_audit_log()


def test_phase28_lifecycle_states_match_exact_contract():
    assert set(PROPOSAL_STATES) == {
        PROPOSAL_STATE_DRAFTED,
        PROPOSAL_STATE_SUBMITTED,
        PROPOSAL_STATE_APPROVED,
        PROPOSAL_STATE_REJECTED,
        PROPOSAL_STATE_EXPIRED,
    }


def test_proposal_creation_via_phase27_is_drafted_immutable_and_logged():
    proposal = _draft_from_phase27()
    assert proposal["intent_class"] == REQUIRED_INTENT_CLASS
    assert proposal["state"] == PROPOSAL_STATE_DRAFTED
    assert proposal["approved"] is False
    assert proposal["executed"] is False
    assert proposal["approval_reference"] is None
    assert isinstance(proposal["governance_context"], dict)
    assert proposal["originating_turn_id"]
    assert proposal["proposal_id"].startswith("proposal-")
    assert proposal["created_at"]
    assert proposal["expiration_time"] is None

    ledger = get_proposal_ledger()
    assert len(ledger) == 1
    assert ledger[0]["event_type"] == "proposal_created"
    assert ledger[0]["proposal_id"] == proposal["proposal_id"]


def test_submission_is_explicit_transition_and_preserves_non_execution():
    proposal = _draft_from_phase27()
    submitted = submit_proposal(proposal["proposal_id"])
    assert submitted.ok is True
    assert submitted.proposal is not None
    assert submitted.proposal["state"] == PROPOSAL_STATE_SUBMITTED
    assert submitted.proposal["executed"] is False
    assert submitted.proposal["approved"] is False

    ledger = get_proposal_ledger()
    assert len(ledger) == 2
    assert ledger[1]["event_type"] == "proposal_transition"
    payload = ledger[1]["payload"]
    assert payload["from_state"] == PROPOSAL_STATE_DRAFTED
    assert payload["to_state"] == PROPOSAL_STATE_SUBMITTED


def test_approval_requires_external_reference_and_never_executes():
    proposal = _draft_from_phase27()
    submit_ok = submit_proposal(proposal["proposal_id"])
    assert submit_ok.ok is True

    missing = approve_proposal(proposal["proposal_id"], approval_reference="")
    assert missing.ok is False
    assert missing.reason_code == "PROPOSAL_APPROVAL_REFERENCE_REQUIRED"

    approved = approve_proposal(proposal["proposal_id"], approval_reference="approval-artifact-001")
    assert approved.ok is True
    assert approved.proposal is not None
    assert approved.proposal["state"] == PROPOSAL_STATE_APPROVED
    assert approved.proposal["approved"] is True
    assert approved.proposal["approval_reference"] == "approval-artifact-001"
    assert approved.proposal["executed"] is False


def test_replay_attempt_is_refused_and_recorded_append_only():
    routed = process_conversational_turn("save this idea to a file")
    first = run_governed_interpreter(routed["intent_envelope"])
    second = run_governed_interpreter(routed["intent_envelope"])

    assert first["governed_result"]["type"] == "proposal"
    assert second["governed_result"]["type"] == "proposal_rejected"
    assert second["governed_result"]["reason_code"] == "PROPOSAL_REPLAY_DETECTED"

    ledger = get_proposal_ledger()
    assert len(ledger) == 2
    assert ledger[0]["event_type"] == "proposal_created"
    assert ledger[1]["event_type"] == "proposal_refusal"
    assert ledger[1]["payload"]["reason_code"] == "PROPOSAL_REPLAY_DETECTED"


def test_state_regression_and_terminal_reuse_are_forbidden():
    proposal = _draft_from_phase27()
    proposal_id = proposal["proposal_id"]

    submit_first = submit_proposal(proposal_id)
    assert submit_first.ok is True

    submit_again = submit_proposal(proposal_id)
    assert submit_again.ok is False
    assert submit_again.reason_code == "PROPOSAL_STATE_REGRESSION_FORBIDDEN"

    rejected = reject_proposal(proposal_id, rejection_reason="manual policy rejection")
    assert rejected.ok is True
    assert rejected.proposal is not None
    assert rejected.proposal["state"] == PROPOSAL_STATE_REJECTED

    approve_after_reject = approve_proposal(proposal_id, approval_reference="approval-artifact-002")
    assert approve_after_reject.ok is False
    assert approve_after_reject.reason_code == "PROPOSAL_TERMINAL_STATE"


def test_expiration_is_terminal_and_enforced_deterministically():
    created = create_proposal(
        intent_class=REQUIRED_INTENT_CLASS,
        originating_turn_id="turn-expire-001",
        governance_context={"source": "phase28-test"},
        expiration_time="2000-01-01T00:00:00Z",
    )
    assert created.ok is True
    assert created.proposal is not None
    proposal_id = created.proposal["proposal_id"]

    expired = enforce_proposal_expiration(proposal_id, now_iso="2026-02-18T00:00:00Z")
    assert expired.ok is True
    assert expired.proposal is not None
    assert expired.proposal["state"] == PROPOSAL_STATE_EXPIRED
    assert expired.proposal["executed"] is False

    submit_after_expiry = submit_proposal(proposal_id)
    assert submit_after_expiry.ok is False
    assert submit_after_expiry.reason_code == "PROPOSAL_TERMINAL_STATE"

    current = get_proposal(proposal_id)
    assert current is not None
    assert current["state"] == PROPOSAL_STATE_EXPIRED


def test_ledger_is_append_only_and_traceable():
    proposal = _draft_from_phase27()
    proposal_id = proposal["proposal_id"]
    submit_proposal(proposal_id)
    reject_proposal(proposal_id, rejection_reason="declined")

    ledger = get_proposal_ledger()
    assert [item["event_type"] for item in ledger] == [
        "proposal_created",
        "proposal_transition",
        "proposal_transition",
    ]
    assert ledger[0]["record_id"] == "proposal-ledger-00000001"
    assert ledger[1]["record_id"] == "proposal-ledger-00000002"
    assert ledger[2]["record_id"] == "proposal-ledger-00000003"
    assert ledger[0]["record_hash"]
    assert ledger[1]["previous_record_hash"] == ledger[0]["record_hash"]
    assert ledger[2]["previous_record_hash"] == ledger[1]["record_hash"]

