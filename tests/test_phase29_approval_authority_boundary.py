from __future__ import annotations

from v2.core.approval_authority import (
    get_approval,
    get_approval_ledger,
    issue_approval,
    reset_approval_ledger,
)
from v2.core.proposal_governance import (
    create_proposal,
    get_proposal,
    reset_proposal_ledger,
    submit_proposal,
)


def _governance_context() -> dict:
    return {
        "domain": "phase29",
        "approval_authority": {
            "authorized_approvers": ["governor.alpha", "governor.beta"],
            "allowed_scopes": ["proposal_review"],
        },
    }


def _create_submitted_proposal(
    *,
    originating_turn_id: str = "turn-001",
    governance_context: dict | None = None,
):
    context = governance_context if governance_context is not None else _governance_context()
    drafted = create_proposal(
        intent_class="governed_action_proposal",
        originating_turn_id=originating_turn_id,
        governance_context=context,
        expiration_time=None,
    )
    assert drafted.ok is True
    assert drafted.proposal is not None
    proposal_id = drafted.proposal["proposal_id"]
    submitted = submit_proposal(proposal_id)
    assert submitted.ok is True
    assert submitted.proposal is not None
    assert submitted.proposal["state"] == "submitted"
    return proposal_id, context


def setup_function() -> None:
    reset_proposal_ledger()
    reset_approval_ledger()


def teardown_function() -> None:
    reset_approval_ledger()
    reset_proposal_ledger()


def test_issue_approval_creates_immutable_auditable_artifact_and_keeps_execution_disabled():
    proposal_id, context = _create_submitted_proposal(originating_turn_id="turn-phase29-001")

    result = issue_approval(
        proposal_id=proposal_id,
        approver_identity="governor.alpha",
        approval_scope="proposal_review",
        approval_reference="approval-ref-001",
        governance_context=context,
        approved_at="2026-02-18T00:00:00Z",
    )

    assert result.ok is True
    assert result.reason_code == "APPROVAL_ISSUED"
    assert result.approval is not None
    assert result.proposal is not None
    assert result.proposal["state"] == "approved"
    assert result.proposal["executed"] is False

    approval = result.approval
    assert approval["approval_id"].startswith("approval-")
    assert approval["proposal_id"] == proposal_id
    assert approval["approved_at"] == "2026-02-18T00:00:00Z"
    assert approval["approver_identity"] == "governor.alpha"
    assert approval["approval_scope"] == "proposal_review"
    assert approval["approval_reference"] == "approval-ref-001"
    assert approval["governance_context"] == context

    stored = get_approval(approval["approval_id"])
    assert stored == approval
    stored["approval_scope"] = "tampered"
    stored_again = get_approval(approval["approval_id"])
    assert stored_again["approval_scope"] == "proposal_review"

    ledger = get_approval_ledger()
    assert len(ledger) == 1
    assert ledger[0]["event_type"] == "approval_issued"
    assert ledger[0]["approval_id"] == approval["approval_id"]


def test_reject_approval_for_non_submitted_proposal():
    drafted = create_proposal(
        intent_class="governed_action_proposal",
        originating_turn_id="turn-phase29-002",
        governance_context=_governance_context(),
        expiration_time=None,
    )
    assert drafted.ok is True
    assert drafted.proposal is not None

    result = issue_approval(
        proposal_id=drafted.proposal["proposal_id"],
        approver_identity="governor.alpha",
        approval_scope="proposal_review",
        approval_reference="approval-ref-002",
        governance_context=_governance_context(),
    )

    assert result.ok is False
    assert result.reason_code == "APPROVAL_PROPOSAL_STATE_INVALID"


def test_reject_approval_for_missing_proposal():
    result = issue_approval(
        proposal_id="proposal-missing",
        approver_identity="governor.alpha",
        approval_scope="proposal_review",
        approval_reference="approval-ref-missing",
        governance_context=_governance_context(),
    )
    assert result.ok is False
    assert result.reason_code == "APPROVAL_PROPOSAL_NOT_FOUND"


def test_reject_duplicate_and_replay_approvals_deterministically():
    proposal_id, context = _create_submitted_proposal(originating_turn_id="turn-phase29-003")

    first = issue_approval(
        proposal_id=proposal_id,
        approver_identity="governor.alpha",
        approval_scope="proposal_review",
        approval_reference="approval-ref-003",
        governance_context=context,
    )
    second = issue_approval(
        proposal_id=proposal_id,
        approver_identity="governor.alpha",
        approval_scope="proposal_review",
        approval_reference="approval-ref-003",
        governance_context=context,
    )

    assert first.ok is True
    assert second.ok is False
    assert second.reason_code in {"APPROVAL_PROPOSAL_STATE_INVALID", "APPROVAL_DUPLICATE_REFERENCE", "APPROVAL_REPLAY_DETECTED"}


def test_reject_mismatched_governance_context():
    proposal_id, _ = _create_submitted_proposal(originating_turn_id="turn-phase29-004")
    mismatched = {
        "domain": "phase29",
        "approval_authority": {
            "authorized_approvers": ["governor.alpha"],
            "allowed_scopes": ["proposal_review"],
        },
        "mismatch": True,
    }

    result = issue_approval(
        proposal_id=proposal_id,
        approver_identity="governor.alpha",
        approval_scope="proposal_review",
        approval_reference="approval-ref-004",
        governance_context=mismatched,
    )

    assert result.ok is False
    assert result.reason_code == "APPROVAL_GOVERNANCE_CONTEXT_MISMATCH"


def test_reject_authority_forgery_and_scope_violation():
    proposal_id, context = _create_submitted_proposal(originating_turn_id="turn-phase29-005")

    denied_identity = issue_approval(
        proposal_id=proposal_id,
        approver_identity="intruder.gamma",
        approval_scope="proposal_review",
        approval_reference="approval-ref-005",
        governance_context=context,
    )
    assert denied_identity.ok is False
    assert denied_identity.reason_code == "APPROVAL_AUTHORITY_DENIED"

    denied_scope = issue_approval(
        proposal_id=proposal_id,
        approver_identity="governor.alpha",
        approval_scope="out_of_scope",
        approval_reference="approval-ref-006",
        governance_context=context,
    )
    assert denied_scope.ok is False
    assert denied_scope.reason_code == "APPROVAL_SCOPE_DENIED"


def test_reject_cross_proposal_approval_reference_reuse():
    first_proposal_id, context = _create_submitted_proposal(originating_turn_id="turn-phase29-006")
    second_proposal_id, _ = _create_submitted_proposal(originating_turn_id="turn-phase29-007")

    first = issue_approval(
        proposal_id=first_proposal_id,
        approver_identity="governor.alpha",
        approval_scope="proposal_review",
        approval_reference="approval-ref-reuse",
        governance_context=context,
    )
    second = issue_approval(
        proposal_id=second_proposal_id,
        approver_identity="governor.alpha",
        approval_scope="proposal_review",
        approval_reference="approval-ref-reuse",
        governance_context=context,
    )

    assert first.ok is True
    assert second.ok is False
    assert second.reason_code == "APPROVAL_REFERENCE_REUSED"


def test_approval_ledger_is_append_only_and_hash_chained():
    proposal_id, context = _create_submitted_proposal(originating_turn_id="turn-phase29-008")
    first = issue_approval(
        proposal_id=proposal_id,
        approver_identity="governor.alpha",
        approval_scope="proposal_review",
        approval_reference="approval-ref-008",
        governance_context=context,
    )
    assert first.ok is True

    second = issue_approval(
        proposal_id=proposal_id,
        approver_identity="governor.alpha",
        approval_scope="proposal_review",
        approval_reference="approval-ref-009",
        governance_context=context,
    )
    assert second.ok is False

    ledger = get_approval_ledger()
    assert len(ledger) == 2
    assert ledger[0]["record_id"] == "approval-ledger-00000001"
    assert ledger[1]["record_id"] == "approval-ledger-00000002"
    assert ledger[0]["record_hash"]
    assert ledger[1]["previous_record_hash"] == ledger[0]["record_hash"]

    proposal = get_proposal(proposal_id)
    assert proposal is not None
    assert proposal["executed"] is False
