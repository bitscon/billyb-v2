"""Phase 29 approval authority boundary (non-executing)."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping

from v2.core.proposal_governance import get_proposal, approve_proposal


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalize_identity(value: str) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class ApprovalOperationResult:
    ok: bool
    reason_code: str
    approval: Dict[str, Any] | None
    proposal: Dict[str, Any] | None
    ledger_entry: Dict[str, Any] | None


class ApprovalAuthorityLedger:
    """Append-only approval authority ledger."""

    def __init__(self) -> None:
        self._records: List[Dict[str, Any]] = []

    def reset(self) -> None:
        self._records.clear()

    def _append_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        previous_hash = str(self._records[-1].get("record_hash", "")) if self._records else ""
        payload = dict(record)
        payload["record_id"] = f"approval-ledger-{len(self._records) + 1:08d}"
        payload["recorded_at"] = payload.get("recorded_at", _utc_now_iso())
        payload["previous_record_hash"] = previous_hash
        payload["record_hash"] = _digest(
            {
                "record_id": payload["record_id"],
                "event_type": payload.get("event_type", ""),
                "approval_id": payload.get("approval_id", ""),
                "proposal_id": payload.get("proposal_id", ""),
                "payload": payload.get("payload", {}),
                "recorded_at": payload["recorded_at"],
                "previous_record_hash": previous_hash,
            }
        )
        self._records.append(copy.deepcopy(payload))
        return copy.deepcopy(payload)

    def _append_refusal(
        self,
        *,
        proposal_id: str,
        reason_code: str,
        details: Mapping[str, Any] | None = None,
    ) -> Dict[str, Any]:
        return self._append_record(
            {
                "event_type": "approval_refused",
                "approval_id": "",
                "proposal_id": str(proposal_id),
                "payload": {
                    "reason_code": str(reason_code),
                    "details": dict(details or {}),
                },
            }
        )

    def _issued_records(self) -> List[Dict[str, Any]]:
        return [copy.deepcopy(item) for item in self._records if str(item.get("event_type", "")) == "approval_issued"]

    def _find_by_approval_id(self, approval_id: str) -> Dict[str, Any] | None:
        target = str(approval_id).strip()
        if not target:
            return None
        for item in self._issued_records():
            if str(item.get("approval_id", "")) == target:
                return item
        return None

    def _find_by_key(self, approval_key: str) -> Dict[str, Any] | None:
        target = str(approval_key)
        for item in self._issued_records():
            payload = item.get("payload", {})
            payload = payload if isinstance(payload, dict) else {}
            if str(payload.get("approval_key", "")) == target:
                return item
        return None

    def _find_by_reference(self, approval_reference: str) -> Dict[str, Any] | None:
        target = str(approval_reference).strip()
        if not target:
            return None
        for item in self._issued_records():
            payload = item.get("payload", {})
            payload = payload if isinstance(payload, dict) else {}
            if str(payload.get("approval_reference", "")).strip() == target:
                return item
        return None

    def get_ledger(self) -> List[Dict[str, Any]]:
        return copy.deepcopy(self._records)

    def get_approval(self, approval_id: str) -> Dict[str, Any] | None:
        record = self._find_by_approval_id(approval_id)
        if record is None:
            return None
        payload = record.get("payload", {})
        payload = payload if isinstance(payload, dict) else {}
        artifact = payload.get("artifact", {})
        artifact = artifact if isinstance(artifact, dict) else {}
        return copy.deepcopy(artifact)

    def _validate_authority(
        self,
        *,
        governance_context: Mapping[str, Any],
        approver_identity: str,
        approval_scope: str,
    ) -> tuple[bool, str]:
        policy = governance_context.get("approval_authority")
        if not isinstance(policy, dict):
            return False, "APPROVAL_AUTHORITY_POLICY_MISSING"

        allowed_approvers = policy.get("authorized_approvers")
        if not isinstance(allowed_approvers, list) or not allowed_approvers:
            return False, "APPROVAL_AUTHORITY_POLICY_INVALID"
        allowed_approvers_normalized = {_normalize_identity(str(item)) for item in allowed_approvers if str(item).strip()}
        if not allowed_approvers_normalized:
            return False, "APPROVAL_AUTHORITY_POLICY_INVALID"
        if approver_identity not in allowed_approvers_normalized:
            return False, "APPROVAL_AUTHORITY_DENIED"

        allowed_scopes = policy.get("allowed_scopes")
        if allowed_scopes is not None:
            if not isinstance(allowed_scopes, list) or not allowed_scopes:
                return False, "APPROVAL_SCOPE_POLICY_INVALID"
            allowed_scope_values = {str(item).strip() for item in allowed_scopes if str(item).strip()}
            if approval_scope not in allowed_scope_values:
                return False, "APPROVAL_SCOPE_DENIED"
        return True, "OK"

    def issue_approval(
        self,
        *,
        proposal_id: str,
        approver_identity: str,
        approval_scope: str,
        approval_reference: str,
        governance_context: Mapping[str, Any],
        approved_at: str | None = None,
    ) -> ApprovalOperationResult:
        proposal_id_value = str(proposal_id).strip()
        approver_value = _normalize_identity(approver_identity)
        scope_value = str(approval_scope).strip()
        reference_value = str(approval_reference).strip()
        context = dict(governance_context or {})
        approved_at_value = str(approved_at).strip() if approved_at is not None else _utc_now_iso()
        if not proposal_id_value:
            refusal = self._append_refusal(
                proposal_id="",
                reason_code="APPROVAL_PROPOSAL_ID_REQUIRED",
                details={},
            )
            return ApprovalOperationResult(
                ok=False,
                reason_code="APPROVAL_PROPOSAL_ID_REQUIRED",
                approval=None,
                proposal=None,
                ledger_entry=refusal,
            )
        if not approver_value:
            refusal = self._append_refusal(
                proposal_id=proposal_id_value,
                reason_code="APPROVAL_APPROVER_IDENTITY_REQUIRED",
                details={},
            )
            return ApprovalOperationResult(
                ok=False,
                reason_code="APPROVAL_APPROVER_IDENTITY_REQUIRED",
                approval=None,
                proposal=None,
                ledger_entry=refusal,
            )
        if not scope_value:
            refusal = self._append_refusal(
                proposal_id=proposal_id_value,
                reason_code="APPROVAL_SCOPE_REQUIRED",
                details={},
            )
            return ApprovalOperationResult(
                ok=False,
                reason_code="APPROVAL_SCOPE_REQUIRED",
                approval=None,
                proposal=None,
                ledger_entry=refusal,
            )
        if not reference_value:
            refusal = self._append_refusal(
                proposal_id=proposal_id_value,
                reason_code="APPROVAL_REFERENCE_REQUIRED",
                details={},
            )
            return ApprovalOperationResult(
                ok=False,
                reason_code="APPROVAL_REFERENCE_REQUIRED",
                approval=None,
                proposal=None,
                ledger_entry=refusal,
            )

        proposal = get_proposal(proposal_id_value)
        if proposal is None:
            refusal = self._append_refusal(
                proposal_id=proposal_id_value,
                reason_code="APPROVAL_PROPOSAL_NOT_FOUND",
                details={},
            )
            return ApprovalOperationResult(
                ok=False,
                reason_code="APPROVAL_PROPOSAL_NOT_FOUND",
                approval=None,
                proposal=None,
                ledger_entry=refusal,
            )

        proposal_state = str(proposal.get("state", "")).strip()
        if proposal_state != "submitted":
            refusal = self._append_refusal(
                proposal_id=proposal_id_value,
                reason_code="APPROVAL_PROPOSAL_STATE_INVALID",
                details={"proposal_state": proposal_state},
            )
            return ApprovalOperationResult(
                ok=False,
                reason_code="APPROVAL_PROPOSAL_STATE_INVALID",
                approval=None,
                proposal=proposal,
                ledger_entry=refusal,
            )

        proposal_context = proposal.get("governance_context", {})
        proposal_context = proposal_context if isinstance(proposal_context, dict) else {}
        if _digest(proposal_context) != _digest(context):
            refusal = self._append_refusal(
                proposal_id=proposal_id_value,
                reason_code="APPROVAL_GOVERNANCE_CONTEXT_MISMATCH",
                details={},
            )
            return ApprovalOperationResult(
                ok=False,
                reason_code="APPROVAL_GOVERNANCE_CONTEXT_MISMATCH",
                approval=None,
                proposal=proposal,
                ledger_entry=refusal,
            )

        authority_ok, authority_code = self._validate_authority(
            governance_context=context,
            approver_identity=approver_value,
            approval_scope=scope_value,
        )
        if not authority_ok:
            refusal = self._append_refusal(
                proposal_id=proposal_id_value,
                reason_code=authority_code,
                details={},
            )
            return ApprovalOperationResult(
                ok=False,
                reason_code=authority_code,
                approval=None,
                proposal=proposal,
                ledger_entry=refusal,
            )

        existing_reference = self._find_by_reference(reference_value)
        if existing_reference is not None:
            existing_proposal = str(existing_reference.get("proposal_id", "")).strip()
            reason = "APPROVAL_REFERENCE_REUSED" if existing_proposal != proposal_id_value else "APPROVAL_DUPLICATE_REFERENCE"
            refusal = self._append_refusal(
                proposal_id=proposal_id_value,
                reason_code=reason,
                details={"existing_proposal_id": existing_proposal},
            )
            return ApprovalOperationResult(
                ok=False,
                reason_code=reason,
                approval=None,
                proposal=proposal,
                ledger_entry=refusal,
            )

        approval_key = _digest(
            {
                "proposal_id": proposal_id_value,
                "approver_identity": approver_value,
                "approval_scope": scope_value,
                "approval_reference": reference_value,
                "governance_context": context,
            }
        )
        if self._find_by_key(approval_key) is not None:
            refusal = self._append_refusal(
                proposal_id=proposal_id_value,
                reason_code="APPROVAL_REPLAY_DETECTED",
                details={},
            )
            return ApprovalOperationResult(
                ok=False,
                reason_code="APPROVAL_REPLAY_DETECTED",
                approval=None,
                proposal=proposal,
                ledger_entry=refusal,
            )

        approval_id = f"approval-{approval_key[:16]}"

        transition = approve_proposal(proposal_id_value, approval_reference=reference_value)
        if not transition.ok or transition.proposal is None:
            refusal = self._append_refusal(
                proposal_id=proposal_id_value,
                reason_code=f"APPROVAL_TRANSITION_REFUSED:{transition.reason_code}",
                details={},
            )
            return ApprovalOperationResult(
                ok=False,
                reason_code=f"APPROVAL_TRANSITION_REFUSED:{transition.reason_code}",
                approval=None,
                proposal=proposal,
                ledger_entry=refusal,
            )

        approval_artifact = {
            "approval_id": approval_id,
            "proposal_id": proposal_id_value,
            "approved_at": approved_at_value or _utc_now_iso(),
            "approver_identity": approver_value,
            "approval_scope": scope_value,
            "approval_reference": reference_value,
            "governance_context": context,
        }

        issued_record = self._append_record(
            {
                "event_type": "approval_issued",
                "approval_id": approval_id,
                "proposal_id": proposal_id_value,
                "payload": {
                    "artifact": approval_artifact,
                    "artifact_digest": _digest(approval_artifact),
                    "approval_key": approval_key,
                    "approval_reference": reference_value,
                },
            }
        )
        return ApprovalOperationResult(
            ok=True,
            reason_code="APPROVAL_ISSUED",
            approval=copy.deepcopy(approval_artifact),
            proposal=copy.deepcopy(transition.proposal),
            ledger_entry=issued_record,
        )


_APPROVAL_LEDGER = ApprovalAuthorityLedger()


def issue_approval(
    *,
    proposal_id: str,
    approver_identity: str,
    approval_scope: str,
    approval_reference: str,
    governance_context: Mapping[str, Any],
    approved_at: str | None = None,
) -> ApprovalOperationResult:
    return _APPROVAL_LEDGER.issue_approval(
        proposal_id=proposal_id,
        approver_identity=approver_identity,
        approval_scope=approval_scope,
        approval_reference=approval_reference,
        governance_context=governance_context,
        approved_at=approved_at,
    )


def get_approval(approval_id: str) -> Dict[str, Any] | None:
    return _APPROVAL_LEDGER.get_approval(approval_id)


def get_approval_ledger() -> List[Dict[str, Any]]:
    return _APPROVAL_LEDGER.get_ledger()


def reset_approval_ledger() -> None:
    _APPROVAL_LEDGER.reset()

