"""Phase 30 execution-attempt admissibility gate (non-executing)."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Mapping

from v2.core.approval_authority import get_approval
from v2.core.proposal_governance import get_proposal

_GOVERNANCE_CITATIONS = (
    "v2/docs/charter/08_TOOLS_WORKERS_EXECUTION.md",
    "v2/core/proposal_governance.py",
    "v2/core/approval_authority.py",
    "docs/PHASE30_PROMOTION_CHECKLIST.md",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _parse_iso8601(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_iso8601(value: str) -> str | None:
    parsed = _parse_iso8601(value)
    if parsed is None:
        return None
    return parsed.isoformat().replace("+00:00", "Z")


def _parse_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _build_result(
    *,
    admissible: bool,
    reason: str,
    evaluated_at: str,
    input_fingerprint: str,
) -> Dict[str, Any]:
    citations = list(_GOVERNANCE_CITATIONS)
    decision_fingerprint = _digest(
        {
            "input_fingerprint": str(input_fingerprint),
            "admissible": bool(admissible),
            "reason": str(reason),
            "governance_citations": citations,
        }
    )
    return {
        "admissible": bool(admissible),
        "reason": str(reason),
        "governance_citations": citations,
        "evaluated_at": str(evaluated_at),
        "decision_fingerprint": decision_fingerprint,
    }


def evaluate_execution_attempt_admissibility(
    *,
    proposal_id: str,
    approval_id: str,
    governance_context: Mapping[str, Any],
    execution_arming_status: Mapping[str, Any],
    system_phase: int | str,
    evaluated_at: str,
) -> Dict[str, Any]:
    """Pure admissibility evaluation for execution-attempt intent.

    This function is side-effect free:
    - no execution
    - no tool invocation
    - no state mutation
    """

    proposal_id_value = str(proposal_id or "").strip()
    approval_id_value = str(approval_id or "").strip()
    governance_context_value = (
        copy.deepcopy(dict(governance_context)) if isinstance(governance_context, Mapping) else governance_context
    )
    execution_arming_status_value = (
        copy.deepcopy(dict(execution_arming_status))
        if isinstance(execution_arming_status, Mapping)
        else execution_arming_status
    )
    evaluated_at_value = str(evaluated_at or "").strip()

    input_fingerprint = _digest(
        {
            "proposal_id": proposal_id_value,
            "approval_id": approval_id_value,
            "governance_context": governance_context_value,
            "execution_arming_status": execution_arming_status_value,
            "system_phase": system_phase,
            "evaluated_at": evaluated_at_value,
        }
    )

    normalized_evaluated_at = _normalize_iso8601(evaluated_at_value)
    if not evaluated_at_value:
        return _build_result(
            admissible=False,
            reason="EVALUATED_AT_REQUIRED",
            evaluated_at=evaluated_at_value,
            input_fingerprint=input_fingerprint,
        )
    if normalized_evaluated_at is None:
        return _build_result(
            admissible=False,
            reason="EVALUATED_AT_INVALID",
            evaluated_at=evaluated_at_value,
            input_fingerprint=input_fingerprint,
        )
    evaluated_at_dt = _parse_iso8601(normalized_evaluated_at)
    if evaluated_at_dt is None:
        return _build_result(
            admissible=False,
            reason="EVALUATED_AT_INVALID",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )

    if not proposal_id_value:
        return _build_result(
            admissible=False,
            reason="PROPOSAL_ID_REQUIRED",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    proposal = get_proposal(proposal_id_value)
    if proposal is None:
        return _build_result(
            admissible=False,
            reason="PROPOSAL_NOT_FOUND",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    proposal_state = str(proposal.get("state", "")).strip()
    if proposal_state != "approved" or not bool(proposal.get("approved", False)):
        return _build_result(
            admissible=False,
            reason="PROPOSAL_NOT_APPROVED",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )

    proposal_expiration = str(proposal.get("expiration_time", "") or "").strip()
    if proposal_expiration:
        expiration_dt = _parse_iso8601(proposal_expiration)
        if expiration_dt is None:
            return _build_result(
                admissible=False,
                reason="PROPOSAL_EXPIRATION_INVALID",
                evaluated_at=normalized_evaluated_at,
                input_fingerprint=input_fingerprint,
            )
        if evaluated_at_dt >= expiration_dt:
            return _build_result(
                admissible=False,
                reason="PROPOSAL_EXPIRED",
                evaluated_at=normalized_evaluated_at,
                input_fingerprint=input_fingerprint,
            )

    if not approval_id_value:
        return _build_result(
            admissible=False,
            reason="APPROVAL_ID_REQUIRED",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    approval = get_approval(approval_id_value)
    if approval is None:
        return _build_result(
            admissible=False,
            reason="APPROVAL_NOT_FOUND",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    if str(approval.get("proposal_id", "")).strip() != proposal_id_value:
        return _build_result(
            admissible=False,
            reason="APPROVAL_PROPOSAL_MISMATCH",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )

    proposal_reference = str(proposal.get("approval_reference", "") or "").strip()
    approval_reference = str(approval.get("approval_reference", "") or "").strip()
    if not proposal_reference or not approval_reference:
        return _build_result(
            admissible=False,
            reason="APPROVAL_REFERENCE_REQUIRED",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    if proposal_reference != approval_reference:
        return _build_result(
            admissible=False,
            reason="APPROVAL_REFERENCE_MISMATCH",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )

    if not isinstance(governance_context_value, dict) or not governance_context_value:
        return _build_result(
            admissible=False,
            reason="GOVERNANCE_CONTEXT_REQUIRED",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )

    proposal_context = proposal.get("governance_context", {})
    proposal_context = proposal_context if isinstance(proposal_context, dict) else {}
    if _digest(proposal_context) != _digest(governance_context_value):
        return _build_result(
            admissible=False,
            reason="GOVERNANCE_CONTEXT_MISMATCH_PROPOSAL",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    approval_context = approval.get("governance_context", {})
    approval_context = approval_context if isinstance(approval_context, dict) else {}
    if _digest(approval_context) != _digest(governance_context_value):
        return _build_result(
            admissible=False,
            reason="GOVERNANCE_CONTEXT_MISMATCH_APPROVAL",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )

    authority_policy = governance_context_value.get("approval_authority")
    if not isinstance(authority_policy, dict):
        return _build_result(
            admissible=False,
            reason="APPROVAL_AUTHORITY_POLICY_MISSING",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    allowed_approvers = authority_policy.get("authorized_approvers")
    if not isinstance(allowed_approvers, list) or not allowed_approvers:
        return _build_result(
            admissible=False,
            reason="APPROVAL_AUTHORITY_POLICY_INVALID",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    allowed_approvers_set = {str(item).strip() for item in allowed_approvers if str(item).strip()}
    if not allowed_approvers_set:
        return _build_result(
            admissible=False,
            reason="APPROVAL_AUTHORITY_POLICY_INVALID",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    approver_identity = str(approval.get("approver_identity", "")).strip()
    if approver_identity not in allowed_approvers_set:
        return _build_result(
            admissible=False,
            reason="APPROVAL_AUTHORITY_DENIED",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )

    approval_scope = str(approval.get("approval_scope", "")).strip()
    allowed_scopes = authority_policy.get("allowed_scopes")
    if allowed_scopes is not None:
        if not isinstance(allowed_scopes, list) or not allowed_scopes:
            return _build_result(
                admissible=False,
                reason="APPROVAL_SCOPE_POLICY_INVALID",
                evaluated_at=normalized_evaluated_at,
                input_fingerprint=input_fingerprint,
            )
        allowed_scope_set = {str(item).strip() for item in allowed_scopes if str(item).strip()}
        if approval_scope not in allowed_scope_set:
            return _build_result(
                admissible=False,
                reason="APPROVAL_SCOPE_DENIED",
                evaluated_at=normalized_evaluated_at,
                input_fingerprint=input_fingerprint,
            )

    validity_policy = governance_context_value.get("approval_validity")
    if not isinstance(validity_policy, dict):
        return _build_result(
            admissible=False,
            reason="APPROVAL_VALIDITY_POLICY_MISSING",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    max_age_seconds = _parse_int(validity_policy.get("max_age_seconds"))
    if max_age_seconds is None or max_age_seconds <= 0:
        return _build_result(
            admissible=False,
            reason="APPROVAL_VALIDITY_POLICY_INVALID",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    required_scope = str(validity_policy.get("required_scope", "") or "").strip()
    if required_scope and approval_scope != required_scope:
        return _build_result(
            admissible=False,
            reason="APPROVAL_SCOPE_REQUIRED_MISMATCH",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )

    approved_at_dt = _parse_iso8601(str(approval.get("approved_at", "")).strip())
    if approved_at_dt is None:
        return _build_result(
            admissible=False,
            reason="APPROVAL_TIMESTAMP_INVALID",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    if approved_at_dt > evaluated_at_dt:
        return _build_result(
            admissible=False,
            reason="APPROVAL_TIMESTAMP_IN_FUTURE",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    age_seconds = int((evaluated_at_dt - approved_at_dt).total_seconds())
    if age_seconds > max_age_seconds:
        return _build_result(
            admissible=False,
            reason="APPROVAL_STALE",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )

    if not isinstance(execution_arming_status_value, dict):
        return _build_result(
            admissible=False,
            reason="EXECUTION_ARMING_STATUS_REQUIRED",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    if execution_arming_status_value.get("explicit") is not True:
        return _build_result(
            admissible=False,
            reason="EXECUTION_ARMING_EXPLICIT_REQUIRED",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    arming_id = str(execution_arming_status_value.get("arming_id", "")).strip()
    if not arming_id:
        return _build_result(
            admissible=False,
            reason="EXECUTION_ARMING_REFERENCE_REQUIRED",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    armed_state = execution_arming_status_value.get("armed")
    if not isinstance(armed_state, bool):
        return _build_result(
            admissible=False,
            reason="EXECUTION_ARMING_STATE_AMBIGUOUS",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    if not armed_state:
        return _build_result(
            admissible=False,
            reason="EXECUTION_ARMING_NOT_ARMED",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )

    constraints = governance_context_value.get("system_phase_constraints")
    if not isinstance(constraints, dict):
        return _build_result(
            admissible=False,
            reason="SYSTEM_PHASE_CONSTRAINTS_MISSING",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    phase_value = _parse_int(system_phase)
    if phase_value is None:
        return _build_result(
            admissible=False,
            reason="SYSTEM_PHASE_INVALID",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )

    allowed_phases_raw = constraints.get("allowed_phases")
    has_allowed_phases = allowed_phases_raw is not None
    allowed_phases: list[int] = []
    if has_allowed_phases:
        if not isinstance(allowed_phases_raw, list) or not allowed_phases_raw:
            return _build_result(
                admissible=False,
                reason="SYSTEM_PHASE_CONSTRAINTS_INVALID",
                evaluated_at=normalized_evaluated_at,
                input_fingerprint=input_fingerprint,
            )
        for item in allowed_phases_raw:
            parsed = _parse_int(item)
            if parsed is None:
                return _build_result(
                    admissible=False,
                    reason="SYSTEM_PHASE_CONSTRAINTS_INVALID",
                    evaluated_at=normalized_evaluated_at,
                    input_fingerprint=input_fingerprint,
                )
            allowed_phases.append(parsed)

    min_phase = _parse_int(constraints.get("min_phase"))
    max_phase = _parse_int(constraints.get("max_phase"))
    if min_phase is None and constraints.get("min_phase") is not None:
        return _build_result(
            admissible=False,
            reason="SYSTEM_PHASE_CONSTRAINTS_INVALID",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    if max_phase is None and constraints.get("max_phase") is not None:
        return _build_result(
            admissible=False,
            reason="SYSTEM_PHASE_CONSTRAINTS_INVALID",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    if not has_allowed_phases and min_phase is None and max_phase is None:
        return _build_result(
            admissible=False,
            reason="SYSTEM_PHASE_CONSTRAINTS_INVALID",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    if min_phase is not None and max_phase is not None and min_phase > max_phase:
        return _build_result(
            admissible=False,
            reason="SYSTEM_PHASE_CONSTRAINTS_INVALID",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    if allowed_phases and phase_value not in allowed_phases:
        return _build_result(
            admissible=False,
            reason="SYSTEM_PHASE_CONSTRAINT_VIOLATION",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    if min_phase is not None and phase_value < min_phase:
        return _build_result(
            admissible=False,
            reason="SYSTEM_PHASE_CONSTRAINT_VIOLATION",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )
    if max_phase is not None and phase_value > max_phase:
        return _build_result(
            admissible=False,
            reason="SYSTEM_PHASE_CONSTRAINT_VIOLATION",
            evaluated_at=normalized_evaluated_at,
            input_fingerprint=input_fingerprint,
        )

    return _build_result(
        admissible=True,
        reason="EXECUTION_ATTEMPT_ADMISSIBLE",
        evaluated_at=normalized_evaluated_at,
        input_fingerprint=input_fingerprint,
    )

