from __future__ import annotations

from v2.core.approval_authority import (
    get_approval_ledger,
    issue_approval,
    reset_approval_ledger,
)
from v2.core.execution_attempt_admissibility import evaluate_execution_attempt_admissibility
from v2.core.proposal_governance import (
    create_proposal,
    get_proposal_ledger,
    reset_proposal_ledger,
    submit_proposal,
)


def _governance_context(*, max_age_seconds: int = 600) -> dict:
    return {
        "domain": "phase30",
        "approval_authority": {
            "authorized_approvers": ["governor.alpha", "governor.beta"],
            "allowed_scopes": ["proposal_review"],
        },
        "approval_validity": {
            "max_age_seconds": max_age_seconds,
            "required_scope": "proposal_review",
        },
        "system_phase_constraints": {
            "allowed_phases": [30],
            "min_phase": 30,
            "max_phase": 30,
        },
    }


def _create_approved_proposal_chain(
    *,
    context: dict,
    originating_turn_id: str,
    approved_at: str,
) -> tuple[str, str]:
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

    approval_result = issue_approval(
        proposal_id=proposal_id,
        approver_identity="governor.alpha",
        approval_scope="proposal_review",
        approval_reference=f"approval-ref-{originating_turn_id}",
        governance_context=context,
        approved_at=approved_at,
    )
    assert approval_result.ok is True
    assert approval_result.approval is not None
    return proposal_id, approval_result.approval["approval_id"]


def setup_function() -> None:
    reset_proposal_ledger()
    reset_approval_ledger()


def teardown_function() -> None:
    reset_approval_ledger()
    reset_proposal_ledger()


def test_phase30_admissibility_allows_only_valid_explicitly_armed_chain():
    context = _governance_context(max_age_seconds=600)
    proposal_id, approval_id = _create_approved_proposal_chain(
        context=context,
        originating_turn_id="turn-phase30-001",
        approved_at="2026-02-18T00:00:00Z",
    )

    first = evaluate_execution_attempt_admissibility(
        proposal_id=proposal_id,
        approval_id=approval_id,
        governance_context=context,
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-001"},
        system_phase=30,
        evaluated_at="2026-02-18T00:01:00Z",
    )
    second = evaluate_execution_attempt_admissibility(
        proposal_id=proposal_id,
        approval_id=approval_id,
        governance_context=context,
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-001"},
        system_phase=30,
        evaluated_at="2026-02-18T00:01:00Z",
    )

    assert first["admissible"] is True
    assert first["reason"] == "EXECUTION_ATTEMPT_ADMISSIBLE"
    assert first["evaluated_at"] == "2026-02-18T00:01:00Z"
    assert set(first.keys()) == {
        "admissible",
        "reason",
        "governance_citations",
        "evaluated_at",
        "decision_fingerprint",
    }
    assert isinstance(first["governance_citations"], list)
    assert all(isinstance(item, str) and item for item in first["governance_citations"])
    assert first["decision_fingerprint"]
    assert first == second


def test_phase30_missing_approval_fails_closed():
    context = _governance_context()
    proposal_id, _ = _create_approved_proposal_chain(
        context=context,
        originating_turn_id="turn-phase30-002",
        approved_at="2026-02-18T00:00:00Z",
    )

    result = evaluate_execution_attempt_admissibility(
        proposal_id=proposal_id,
        approval_id="approval-missing",
        governance_context=context,
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-002"},
        system_phase=30,
        evaluated_at="2026-02-18T00:01:00Z",
    )

    assert result["admissible"] is False
    assert result["reason"] == "APPROVAL_NOT_FOUND"


def test_phase30_stale_approval_fails_closed():
    context = _governance_context(max_age_seconds=30)
    proposal_id, approval_id = _create_approved_proposal_chain(
        context=context,
        originating_turn_id="turn-phase30-003",
        approved_at="2026-02-18T00:00:00Z",
    )

    result = evaluate_execution_attempt_admissibility(
        proposal_id=proposal_id,
        approval_id=approval_id,
        governance_context=context,
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-003"},
        system_phase=30,
        evaluated_at="2026-02-18T00:02:00Z",
    )

    assert result["admissible"] is False
    assert result["reason"] == "APPROVAL_STALE"


def test_phase30_requires_proposal_to_be_approved():
    context = _governance_context()
    drafted = create_proposal(
        intent_class="governed_action_proposal",
        originating_turn_id="turn-phase30-003b",
        governance_context=context,
        expiration_time=None,
    )
    assert drafted.ok is True
    assert drafted.proposal is not None
    proposal_id = drafted.proposal["proposal_id"]

    submitted = submit_proposal(proposal_id)
    assert submitted.ok is True

    result = evaluate_execution_attempt_admissibility(
        proposal_id=proposal_id,
        approval_id="approval-any",
        governance_context=context,
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-003b"},
        system_phase=30,
        evaluated_at="2026-02-18T00:01:00Z",
    )

    assert result["admissible"] is False
    assert result["reason"] == "PROPOSAL_NOT_APPROVED"


def test_phase30_governance_context_mismatch_fails_closed():
    context = _governance_context()
    proposal_id, approval_id = _create_approved_proposal_chain(
        context=context,
        originating_turn_id="turn-phase30-003c",
        approved_at="2026-02-18T00:00:00Z",
    )
    mismatched_context = _governance_context()
    mismatched_context["domain"] = "phase30-mismatch"

    result = evaluate_execution_attempt_admissibility(
        proposal_id=proposal_id,
        approval_id=approval_id,
        governance_context=mismatched_context,
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-003c"},
        system_phase=30,
        evaluated_at="2026-02-18T00:01:00Z",
    )

    assert result["admissible"] is False
    assert result["reason"] == "GOVERNANCE_CONTEXT_MISMATCH_PROPOSAL"


def test_phase30_arming_must_be_explicit_and_armed():
    context = _governance_context()
    proposal_id, approval_id = _create_approved_proposal_chain(
        context=context,
        originating_turn_id="turn-phase30-004",
        approved_at="2026-02-18T00:00:00Z",
    )

    missing_explicit = evaluate_execution_attempt_admissibility(
        proposal_id=proposal_id,
        approval_id=approval_id,
        governance_context=context,
        execution_arming_status={"armed": True, "arming_id": "arming-004"},
        system_phase=30,
        evaluated_at="2026-02-18T00:01:00Z",
    )
    not_armed = evaluate_execution_attempt_admissibility(
        proposal_id=proposal_id,
        approval_id=approval_id,
        governance_context=context,
        execution_arming_status={"explicit": True, "armed": False, "arming_id": "arming-004"},
        system_phase=30,
        evaluated_at="2026-02-18T00:01:00Z",
    )

    assert missing_explicit["admissible"] is False
    assert missing_explicit["reason"] == "EXECUTION_ARMING_EXPLICIT_REQUIRED"
    assert not_armed["admissible"] is False
    assert not_armed["reason"] == "EXECUTION_ARMING_NOT_ARMED"


def test_phase30_system_phase_constraints_are_enforced():
    context = _governance_context()
    proposal_id, approval_id = _create_approved_proposal_chain(
        context=context,
        originating_turn_id="turn-phase30-005",
        approved_at="2026-02-18T00:00:00Z",
    )

    result = evaluate_execution_attempt_admissibility(
        proposal_id=proposal_id,
        approval_id=approval_id,
        governance_context=context,
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-005"},
        system_phase=29,
        evaluated_at="2026-02-18T00:01:00Z",
    )

    assert result["admissible"] is False
    assert result["reason"] == "SYSTEM_PHASE_CONSTRAINT_VIOLATION"


def test_phase30_evaluation_is_read_only_and_non_mutating():
    context = _governance_context()
    proposal_id, approval_id = _create_approved_proposal_chain(
        context=context,
        originating_turn_id="turn-phase30-006",
        approved_at="2026-02-18T00:00:00Z",
    )

    proposal_ledger_before = get_proposal_ledger()
    approval_ledger_before = get_approval_ledger()

    result = evaluate_execution_attempt_admissibility(
        proposal_id=proposal_id,
        approval_id=approval_id,
        governance_context=context,
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-006"},
        system_phase=30,
        evaluated_at="2026-02-18T00:01:00Z",
    )

    assert result["admissible"] is True
    assert get_proposal_ledger() == proposal_ledger_before
    assert get_approval_ledger() == approval_ledger_before
