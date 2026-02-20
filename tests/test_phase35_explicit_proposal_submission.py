from __future__ import annotations

from v2.core.advisory_planning import build_advisory_plan
from v2.core.explicit_proposal_submission import (
    build_phase33_proposal_draft,
    get_proposal_submission_ledger,
    reset_proposal_submission_ledger,
    submit_draft_proposal,
)
from v2.core.proposal_governance import get_proposal, get_proposal_ledger, reset_proposal_ledger


def _phase35_draft() -> dict:
    return build_phase33_proposal_draft(
        originating_turn_id="turn-phase35-001",
        governance_context={"domain": "phase35", "intent": "write_file"},
        advisory_fingerprint="advisory-fingerprint-001",
        created_at="2026-02-18T00:00:00Z",
    )


def setup_function() -> None:
    reset_proposal_ledger()
    reset_proposal_submission_ledger()


def teardown_function() -> None:
    reset_proposal_submission_ledger()
    reset_proposal_ledger()


def test_phase35_submission_requires_explicit_confirmation():
    draft = _phase35_draft()
    proposal_ledger_before = get_proposal_ledger()
    submission_ledger_before = get_proposal_submission_ledger()

    result = submit_draft_proposal(
        draft_artifact=draft,
        confirmation_text="yes",
        request_draft_fingerprint=draft["draft_fingerprint"],
    )

    assert result.ok is False
    assert result.reason_code == "SUBMISSION_CONFIRMATION_REQUIRED"
    assert result.receipt is None
    assert get_proposal_ledger() == proposal_ledger_before
    assert get_proposal_submission_ledger() == submission_ledger_before


def test_phase35_submits_only_after_explicit_confirmation_and_records_fingerprints():
    draft = _phase35_draft()

    result = submit_draft_proposal(
        draft_artifact=draft,
        confirmation_text="yes, submit this proposal",
        request_draft_fingerprint=draft["draft_fingerprint"],
        submitted_at="2026-02-18T00:01:00Z",
    )

    assert result.ok is True
    assert result.reason_code == "PROPOSAL_DRAFT_SUBMITTED"
    assert result.receipt is not None

    receipt = result.receipt
    assert receipt["type"] == "proposal_submission_receipt"
    assert receipt["proposal_id"].startswith("proposal-")
    assert receipt["proposal_state"] == "drafted"
    assert receipt["submitted_at"] == "2026-02-18T00:01:00Z"
    assert receipt["draft_id"] == draft["draft_id"]
    assert receipt["draft_fingerprint"] == draft["draft_fingerprint"]
    assert receipt["advisory_fingerprint"] == draft["advisory_fingerprint"]
    assert receipt["execution_enabled"] is False
    assert receipt["approved"] is False
    assert receipt["executed"] is False

    proposal = get_proposal(receipt["proposal_id"])
    assert proposal is not None
    assert proposal["state"] == "drafted"
    assert proposal["executed"] is False
    submission_context = proposal["governance_context"]["phase35_submission"]
    assert submission_context["draft_id"] == draft["draft_id"]
    assert submission_context["draft_fingerprint"] == draft["draft_fingerprint"]
    assert submission_context["advisory_fingerprint"] == draft["advisory_fingerprint"]

    proposal_ledger = get_proposal_ledger()
    assert len(proposal_ledger) == 1
    assert proposal_ledger[0]["event_type"] == "proposal_created"
    assert proposal_ledger[0]["proposal_id"] == receipt["proposal_id"]

    submission_ledger = get_proposal_submission_ledger()
    assert len(submission_ledger) == 1
    assert submission_ledger[0]["event_type"] == "proposal_submitted"
    assert submission_ledger[0]["payload"]["receipt"]["proposal_id"] == receipt["proposal_id"]


def test_phase35_confirmation_replay_is_refused_without_additional_side_effects():
    draft = _phase35_draft()

    first = submit_draft_proposal(
        draft_artifact=draft,
        confirmation_text="submit proposal",
        request_draft_fingerprint=draft["draft_fingerprint"],
    )
    assert first.ok is True

    proposal_ledger_before_replay = get_proposal_ledger()
    submission_ledger_before_replay = get_proposal_submission_ledger()

    replay = submit_draft_proposal(
        draft_artifact=draft,
        confirmation_text="submit proposal",
        request_draft_fingerprint=draft["draft_fingerprint"],
    )

    assert replay.ok is False
    assert replay.reason_code == "SUBMISSION_CONFIRMATION_REPLAYED"
    assert replay.receipt is None
    assert get_proposal_ledger() == proposal_ledger_before_replay
    assert get_proposal_submission_ledger() == submission_ledger_before_replay


def test_phase35_draft_fingerprint_mismatch_is_refused_without_submission():
    draft = _phase35_draft()
    proposal_ledger_before = get_proposal_ledger()
    submission_ledger_before = get_proposal_submission_ledger()

    mismatch = submit_draft_proposal(
        draft_artifact=draft,
        confirmation_text="yes, submit this proposal",
        request_draft_fingerprint="deadbeef",
    )

    assert mismatch.ok is False
    assert mismatch.reason_code == "SUBMISSION_DRAFT_FINGERPRINT_MISMATCH"
    assert mismatch.receipt is None
    assert get_proposal_ledger() == proposal_ledger_before
    assert get_proposal_submission_ledger() == submission_ledger_before


def test_phase35_advisory_only_output_never_creates_submission():
    advisory_only = build_advisory_plan(
        utterance="plan a safe rollout for nginx service updates",
        intent_class="planning_request",
    )
    proposal_ledger_before = get_proposal_ledger()
    submission_ledger_before = get_proposal_submission_ledger()

    result = submit_draft_proposal(
        draft_artifact=advisory_only,
        confirmation_text="submit proposal",
        request_draft_fingerprint="advisory-only",
    )

    assert result.ok is False
    assert result.reason_code == "SUBMISSION_DRAFT_INVALID"
    assert result.receipt is None
    assert get_proposal_ledger() == proposal_ledger_before
    assert get_proposal_submission_ledger() == submission_ledger_before

