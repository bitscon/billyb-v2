from __future__ import annotations

from v2.core.advisory_planning import build_advisory_plan
from v2.core.approval_authority import get_approval_ledger, reset_approval_ledger
from v2.core.execution_authorization_envelope import (
    get_execution_authorization_ledger,
    reset_execution_authorization_ledger,
)
from v2.core.proposal_governance import get_proposal_ledger, reset_proposal_ledger


def setup_function() -> None:
    reset_proposal_ledger()
    reset_approval_ledger()
    reset_execution_authorization_ledger()


def teardown_function() -> None:
    reset_execution_authorization_ledger()
    reset_approval_ledger()
    reset_proposal_ledger()


def test_phase32_advisory_output_contract_for_planning_request():
    response = build_advisory_plan(
        utterance="plan a safe rollout for nginx service updates",
        intent_class="planning_request",
    )

    assert response["mode"] == "advisory"
    assert response["execution_enabled"] is False
    assert response["advisory_only"] is True
    assert response["status"] == "advisory_ready"
    assert isinstance(response["plan_steps"], list) and response["plan_steps"]
    assert isinstance(response["suggested_commands"], list) and response["suggested_commands"]
    assert all(isinstance(item, str) for item in response["suggested_commands"])
    assert all(item.startswith("NOT EXECUTED: ") for item in response["suggested_commands"])
    assert isinstance(response["risk_notes"], list) and response["risk_notes"]
    assert isinstance(response["assumptions"], list) and response["assumptions"]
    assert isinstance(response["rollback_guidance"], list) and response["rollback_guidance"]
    assert isinstance(response["options"], list) and response["options"]
    assert all(isinstance(option, dict) for option in response["options"])
    for option in response["options"]:
        assert str(option.get("title", "")).strip()
        assert str(option.get("benefits", "")).strip()
        assert str(option.get("risks", "")).strip()
        assert str(option.get("effort", "")).strip()
        assert str(option.get("alignment", "")).strip()
    assert response["framing_fingerprint"]


def test_phase32_execution_attempt_is_refused_and_non_executing():
    proposal_ledger_before = get_proposal_ledger()
    approval_ledger_before = get_approval_ledger()
    authorization_ledger_before = get_execution_authorization_ledger()

    response = build_advisory_plan(
        utterance="run this now and execute immediately",
        intent_class="execution_attempt",
    )

    assert response["mode"] == "advisory"
    assert response["execution_enabled"] is False
    assert response["advisory_only"] is True
    assert response["status"] == "refused"
    assert response["suggested_commands"] == []
    assert response["plan_steps"] == []
    assert response["commands_not_executed"] is True

    assert get_proposal_ledger() == proposal_ledger_before
    assert get_approval_ledger() == approval_ledger_before
    assert get_execution_authorization_ledger() == authorization_ledger_before


def test_phase32_deterministic_output_framing_is_stable():
    first = build_advisory_plan(
        utterance="plan repository cleanup with minimal risk",
        intent_class="planning_request",
    )
    second = build_advisory_plan(
        utterance="plan repository cleanup with minimal risk",
        intent_class="planning_request",
    )

    assert first == second
    assert first["framing_fingerprint"] == second["framing_fingerprint"]


def test_phase32_escalation_is_prepared_only_when_explicitly_requested():
    without_explicit_escalation = build_advisory_plan(
        utterance="plan how to rotate logs safely",
        intent_class="planning_request",
    )
    with_explicit_escalation = build_advisory_plan(
        utterance="plan how to rotate logs safely and create proposal for approval",
        intent_class="planning_request",
    )

    assert without_explicit_escalation["escalation"]["explicitly_requested"] is False
    assert without_explicit_escalation["escalation"]["escalation_prepared"] is False
    assert without_explicit_escalation["escalation"]["next_step"] == "none"

    assert with_explicit_escalation["escalation"]["explicitly_requested"] is True
    assert with_explicit_escalation["escalation"]["escalation_prepared"] is True
    assert with_explicit_escalation["escalation"]["next_step"] == "request_governed_proposal"


def test_phase32_implicit_action_request_is_clarified_fail_closed():
    response = build_advisory_plan(
        utterance="restart nginx service",
        intent_class="ambiguous_intent",
    )

    assert response["mode"] == "advisory"
    assert response["execution_enabled"] is False
    assert response["advisory_only"] is True
    assert response["status"] == "clarification_required"
    assert "implies action" in response["message"].lower()
    assert response["plan_steps"] == []
    assert response["suggested_commands"] == []
