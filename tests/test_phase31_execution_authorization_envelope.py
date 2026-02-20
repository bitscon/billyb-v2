from __future__ import annotations

from v2.core.approval_authority import (
    get_approval_ledger,
    issue_approval,
    reset_approval_ledger,
)
from v2.core.execution_attempt_admissibility import evaluate_execution_attempt_admissibility
from v2.core.execution_authorization_envelope import (
    get_execution_authorization,
    get_execution_authorization_ledger,
    issue_execution_authorization,
    reset_execution_authorization_ledger,
    validate_execution_authorization,
)
from v2.core.proposal_governance import (
    create_proposal,
    get_proposal_ledger,
    reset_proposal_ledger,
    submit_proposal,
)


def _governance_context(*, max_age_seconds: int = 600) -> dict:
    return {
        "domain": "phase31",
        "approval_authority": {
            "authorized_approvers": ["governor.alpha", "governor.beta"],
            "allowed_scopes": ["proposal_review"],
        },
        "approval_validity": {
            "max_age_seconds": max_age_seconds,
            "required_scope": "proposal_review",
        },
        "system_phase_constraints": {
            "allowed_phases": [30, 31],
            "min_phase": 30,
            "max_phase": 31,
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
    reset_execution_authorization_ledger()


def teardown_function() -> None:
    reset_execution_authorization_ledger()
    reset_approval_ledger()
    reset_proposal_ledger()


def test_phase31_issues_time_bound_context_bound_authorization_from_phase30_admissibility():
    context = _governance_context(max_age_seconds=600)
    proposal_id, approval_id = _create_approved_proposal_chain(
        context=context,
        originating_turn_id="turn-phase31-001",
        approved_at="2026-02-18T00:00:00Z",
    )
    admissibility = evaluate_execution_attempt_admissibility(
        proposal_id=proposal_id,
        approval_id=approval_id,
        governance_context=context,
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-001"},
        system_phase=30,
        evaluated_at="2026-02-18T00:01:00Z",
    )
    assert admissibility["admissible"] is True

    result = issue_execution_authorization(
        proposal_id=proposal_id,
        approval_id=approval_id,
        governance_context=context,
        admissibility_fingerprint=admissibility["decision_fingerprint"],
        issued_at="2026-02-18T00:01:00Z",
        expires_at="2026-02-18T00:06:00Z",
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-001"},
        system_phase=30,
    )

    assert result.ok is True
    assert result.reason_code == "AUTHORIZATION_ISSUED"
    assert result.envelope is not None
    envelope = result.envelope
    assert envelope["authorization_id"].startswith("authorization-")
    assert envelope["proposal_id"] == proposal_id
    assert envelope["approval_id"] == approval_id
    assert envelope["issued_at"] == "2026-02-18T00:01:00Z"
    assert envelope["expires_at"] == "2026-02-18T00:06:00Z"
    assert envelope["governance_context"] == context
    assert envelope["admissibility_fingerprint"] == admissibility["decision_fingerprint"]
    assert envelope["authorized"] is True
    assert envelope["execution_enabled"] is False

    stored = get_execution_authorization(envelope["authorization_id"])
    assert stored == envelope
    stored["authorized"] = False
    assert get_execution_authorization(envelope["authorization_id"])["authorized"] is True


def test_phase31_refuses_issuance_when_phase30_is_not_admissible():
    context = _governance_context(max_age_seconds=600)
    proposal_id, approval_id = _create_approved_proposal_chain(
        context=context,
        originating_turn_id="turn-phase31-002",
        approved_at="2026-02-18T00:00:00Z",
    )
    inadmissible = evaluate_execution_attempt_admissibility(
        proposal_id=proposal_id,
        approval_id=approval_id,
        governance_context=context,
        execution_arming_status={"explicit": True, "armed": False, "arming_id": "arming-002"},
        system_phase=30,
        evaluated_at="2026-02-18T00:01:00Z",
    )
    assert inadmissible["admissible"] is False

    result = issue_execution_authorization(
        proposal_id=proposal_id,
        approval_id=approval_id,
        governance_context=context,
        admissibility_fingerprint=inadmissible["decision_fingerprint"],
        issued_at="2026-02-18T00:01:00Z",
        expires_at="2026-02-18T00:06:00Z",
        execution_arming_status={"explicit": True, "armed": False, "arming_id": "arming-002"},
        system_phase=30,
    )

    assert result.ok is False
    assert result.reason_code.startswith("AUTHORIZATION_ADMISSIBILITY_REFUSED:")


def test_phase31_refuses_issuance_on_admissibility_fingerprint_mismatch_and_replay():
    context = _governance_context(max_age_seconds=600)
    proposal_id, approval_id = _create_approved_proposal_chain(
        context=context,
        originating_turn_id="turn-phase31-003",
        approved_at="2026-02-18T00:00:00Z",
    )
    admissibility = evaluate_execution_attempt_admissibility(
        proposal_id=proposal_id,
        approval_id=approval_id,
        governance_context=context,
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-003"},
        system_phase=30,
        evaluated_at="2026-02-18T00:01:00Z",
    )
    assert admissibility["admissible"] is True

    mismatch = issue_execution_authorization(
        proposal_id=proposal_id,
        approval_id=approval_id,
        governance_context=context,
        admissibility_fingerprint="deadbeef",
        issued_at="2026-02-18T00:01:00Z",
        expires_at="2026-02-18T00:06:00Z",
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-003"},
        system_phase=30,
    )
    assert mismatch.ok is False
    assert mismatch.reason_code == "AUTHORIZATION_ADMISSIBILITY_FINGERPRINT_MISMATCH"

    first = issue_execution_authorization(
        proposal_id=proposal_id,
        approval_id=approval_id,
        governance_context=context,
        admissibility_fingerprint=admissibility["decision_fingerprint"],
        issued_at="2026-02-18T00:01:00Z",
        expires_at="2026-02-18T00:06:00Z",
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-003"},
        system_phase=30,
    )
    assert first.ok is True

    replay = issue_execution_authorization(
        proposal_id=proposal_id,
        approval_id=approval_id,
        governance_context=context,
        admissibility_fingerprint=admissibility["decision_fingerprint"],
        issued_at="2026-02-18T00:01:00Z",
        expires_at="2026-02-18T00:06:00Z",
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-003"},
        system_phase=30,
    )
    assert replay.ok is False
    assert replay.reason_code == "AUTHORIZATION_REPLAY_DETECTED"


def test_phase31_refuses_issuance_if_referenced_artifact_is_effectively_expired():
    context = _governance_context(max_age_seconds=30)
    proposal_id, approval_id = _create_approved_proposal_chain(
        context=context,
        originating_turn_id="turn-phase31-004",
        approved_at="2026-02-18T00:00:00Z",
    )
    inadmissible = evaluate_execution_attempt_admissibility(
        proposal_id=proposal_id,
        approval_id=approval_id,
        governance_context=context,
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-004"},
        system_phase=30,
        evaluated_at="2026-02-18T00:02:00Z",
    )
    assert inadmissible["admissible"] is False
    assert inadmissible["reason"] == "APPROVAL_STALE"

    result = issue_execution_authorization(
        proposal_id=proposal_id,
        approval_id=approval_id,
        governance_context=context,
        admissibility_fingerprint=inadmissible["decision_fingerprint"],
        issued_at="2026-02-18T00:02:00Z",
        expires_at="2026-02-18T00:06:00Z",
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-004"},
        system_phase=30,
    )

    assert result.ok is False
    assert result.reason_code.startswith("AUTHORIZATION_ADMISSIBILITY_REFUSED:APPROVAL_STALE")


def test_phase31_validation_is_deterministic_and_refuses_expired_or_mismatched_context():
    context = _governance_context(max_age_seconds=600)
    proposal_id, approval_id = _create_approved_proposal_chain(
        context=context,
        originating_turn_id="turn-phase31-005",
        approved_at="2026-02-18T00:00:00Z",
    )
    admissibility = evaluate_execution_attempt_admissibility(
        proposal_id=proposal_id,
        approval_id=approval_id,
        governance_context=context,
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-005"},
        system_phase=30,
        evaluated_at="2026-02-18T00:01:00Z",
    )
    issued = issue_execution_authorization(
        proposal_id=proposal_id,
        approval_id=approval_id,
        governance_context=context,
        admissibility_fingerprint=admissibility["decision_fingerprint"],
        issued_at="2026-02-18T00:01:00Z",
        expires_at="2026-02-18T00:06:00Z",
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-005"},
        system_phase=30,
    )
    assert issued.ok is True
    assert issued.envelope is not None
    authorization_id = issued.envelope["authorization_id"]

    first = validate_execution_authorization(
        authorization_id=authorization_id,
        governance_context=context,
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-005"},
        system_phase=30,
        evaluated_at="2026-02-18T00:02:00Z",
    )
    second = validate_execution_authorization(
        authorization_id=authorization_id,
        governance_context=context,
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-005"},
        system_phase=30,
        evaluated_at="2026-02-18T00:02:00Z",
    )
    assert first["valid"] is True
    assert first["reason"] == "AUTHORIZATION_VALID"
    assert first == second

    expired = validate_execution_authorization(
        authorization_id=authorization_id,
        governance_context=context,
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-005"},
        system_phase=30,
        evaluated_at="2026-02-18T00:07:00Z",
    )
    assert expired["valid"] is False
    assert expired["reason"] == "AUTHORIZATION_EXPIRED"

    mismatched_context = _governance_context(max_age_seconds=600)
    mismatched_context["domain"] = "phase31-other"
    mismatch = validate_execution_authorization(
        authorization_id=authorization_id,
        governance_context=mismatched_context,
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-005"},
        system_phase=30,
        evaluated_at="2026-02-18T00:02:00Z",
    )
    assert mismatch["valid"] is False
    assert mismatch["reason"] == "AUTHORIZATION_GOVERNANCE_CONTEXT_MISMATCH"


def test_phase31_ledger_is_append_only_and_validation_is_read_only():
    context = _governance_context(max_age_seconds=600)
    proposal_id, approval_id = _create_approved_proposal_chain(
        context=context,
        originating_turn_id="turn-phase31-006",
        approved_at="2026-02-18T00:00:00Z",
    )
    admissibility = evaluate_execution_attempt_admissibility(
        proposal_id=proposal_id,
        approval_id=approval_id,
        governance_context=context,
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-006"},
        system_phase=30,
        evaluated_at="2026-02-18T00:01:00Z",
    )

    proposal_ledger_before_issue = get_proposal_ledger()
    approval_ledger_before_issue = get_approval_ledger()

    issued = issue_execution_authorization(
        proposal_id=proposal_id,
        approval_id=approval_id,
        governance_context=context,
        admissibility_fingerprint=admissibility["decision_fingerprint"],
        issued_at="2026-02-18T00:01:00Z",
        expires_at="2026-02-18T00:06:00Z",
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-006"},
        system_phase=30,
    )
    assert issued.ok is True
    assert get_proposal_ledger() == proposal_ledger_before_issue
    assert get_approval_ledger() == approval_ledger_before_issue

    authorization_ledger = get_execution_authorization_ledger()
    assert len(authorization_ledger) == 1
    assert authorization_ledger[0]["event_type"] == "authorization_issued"
    assert authorization_ledger[0]["record_id"] == "execution-authorization-ledger-00000001"
    assert authorization_ledger[0]["record_hash"]

    ledger_before_validation = get_execution_authorization_ledger()
    validation = validate_execution_authorization(
        authorization_id=issued.envelope["authorization_id"],
        governance_context=context,
        execution_arming_status={"explicit": True, "armed": True, "arming_id": "arming-006"},
        system_phase=30,
        evaluated_at="2026-02-18T00:02:00Z",
    )
    assert validation["valid"] is True
    assert get_execution_authorization_ledger() == ledger_before_validation

