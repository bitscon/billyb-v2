"""Phase 28 proposal governance boundary (non-executing)."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping

PROPOSAL_STATE_DRAFTED = "drafted"
PROPOSAL_STATE_SUBMITTED = "submitted"
PROPOSAL_STATE_APPROVED = "approved"
PROPOSAL_STATE_REJECTED = "rejected"
PROPOSAL_STATE_EXPIRED = "expired"
PROPOSAL_STATES = (
    PROPOSAL_STATE_DRAFTED,
    PROPOSAL_STATE_SUBMITTED,
    PROPOSAL_STATE_APPROVED,
    PROPOSAL_STATE_REJECTED,
    PROPOSAL_STATE_EXPIRED,
)
REQUIRED_INTENT_CLASS = "governed_action_proposal"
_TERMINAL_STATES = {PROPOSAL_STATE_REJECTED, PROPOSAL_STATE_EXPIRED}
_ALLOWED_TRANSITIONS = {
    PROPOSAL_STATE_DRAFTED: {PROPOSAL_STATE_SUBMITTED, PROPOSAL_STATE_REJECTED, PROPOSAL_STATE_EXPIRED},
    PROPOSAL_STATE_SUBMITTED: {PROPOSAL_STATE_APPROVED, PROPOSAL_STATE_REJECTED, PROPOSAL_STATE_EXPIRED},
    PROPOSAL_STATE_APPROVED: {PROPOSAL_STATE_EXPIRED},
    PROPOSAL_STATE_REJECTED: set(),
    PROPOSAL_STATE_EXPIRED: set(),
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


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


@dataclass(frozen=True)
class ProposalOperationResult:
    ok: bool
    reason_code: str
    proposal: Dict[str, Any] | None
    ledger_entry: Dict[str, Any] | None


class ProposalGovernanceLedger:
    """Append-only in-memory proposal lifecycle ledger."""

    def __init__(self) -> None:
        self._records: List[Dict[str, Any]] = []

    def reset(self) -> None:
        self._records.clear()

    def get_ledger(self) -> List[Dict[str, Any]]:
        return copy.deepcopy(self._records)

    def _append_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        previous_hash = ""
        if self._records:
            previous_hash = str(self._records[-1].get("record_hash", ""))
        payload = dict(record)
        payload["record_id"] = f"proposal-ledger-{len(self._records) + 1:08d}"
        payload["recorded_at"] = payload.get("recorded_at", _utc_now_iso())
        payload["previous_record_hash"] = previous_hash
        payload["record_hash"] = _digest(
            {
                "record_id": payload["record_id"],
                "event_type": payload.get("event_type", ""),
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
        action: str,
        reason_code: str,
        details: Mapping[str, Any] | None = None,
    ) -> Dict[str, Any]:
        return self._append_record(
            {
                "event_type": "proposal_refusal",
                "proposal_id": str(proposal_id),
                "payload": {
                    "action": str(action),
                    "reason_code": str(reason_code),
                    "details": dict(details or {}),
                },
            }
        )

    def _created_records(self) -> List[Dict[str, Any]]:
        return [item for item in self._records if str(item.get("event_type", "")) == "proposal_created"]

    def _find_created_record(self, proposal_id: str) -> Dict[str, Any] | None:
        target = str(proposal_id)
        for item in self._created_records():
            if str(item.get("proposal_id", "")) == target:
                return copy.deepcopy(item)
        return None

    def _transition_records(self, proposal_id: str) -> List[Dict[str, Any]]:
        target = str(proposal_id)
        return [
            copy.deepcopy(item)
            for item in self._records
            if str(item.get("event_type", "")) == "proposal_transition"
            and str(item.get("proposal_id", "")) == target
        ]

    def _find_by_replay_key(self, replay_key: str) -> Dict[str, Any] | None:
        target = str(replay_key)
        for item in self._created_records():
            payload = item.get("payload", {})
            if not isinstance(payload, dict):
                continue
            if str(payload.get("replay_key", "")) == target:
                return copy.deepcopy(item)
        return None

    def _base_proposal_from_created(self, created_record: Dict[str, Any]) -> Dict[str, Any]:
        payload = created_record.get("payload", {})
        payload = payload if isinstance(payload, dict) else {}
        artifact = payload.get("artifact", {})
        artifact = artifact if isinstance(artifact, dict) else {}
        return copy.deepcopy(artifact)

    def _proposal_view(self, proposal_id: str) -> Dict[str, Any] | None:
        created = self._find_created_record(proposal_id)
        if created is None:
            return None
        proposal = self._base_proposal_from_created(created)
        transitions = self._transition_records(proposal_id)
        for entry in transitions:
            payload = entry.get("payload", {})
            payload = payload if isinstance(payload, dict) else {}
            to_state = str(payload.get("to_state", "")).strip()
            if to_state in PROPOSAL_STATES:
                proposal["state"] = to_state
            if to_state == PROPOSAL_STATE_APPROVED:
                proposal["approved"] = True
                proposal["approval_reference"] = str(payload.get("approval_reference", "")).strip() or None
            proposal["executed"] = False
        return proposal

    def _current_state(self, proposal_id: str) -> str | None:
        proposal = self._proposal_view(proposal_id)
        if proposal is None:
            return None
        return str(proposal.get("state", "")).strip() or None

    def _validate_integrity(self, proposal_id: str) -> tuple[bool, str]:
        created = self._find_created_record(proposal_id)
        if created is None:
            return False, "PROPOSAL_NOT_FOUND"
        payload = created.get("payload", {})
        payload = payload if isinstance(payload, dict) else {}
        artifact = payload.get("artifact", {})
        artifact = artifact if isinstance(artifact, dict) else {}
        expected = str(payload.get("artifact_digest", "")).strip()
        actual = _digest(artifact)
        if not expected or expected != actual:
            return False, "PROPOSAL_INTEGRITY_VIOLATION"
        return True, "OK"

    def _has_expired(self, proposal: Mapping[str, Any], *, now_iso: str | None = None) -> bool:
        expiration_time = str(proposal.get("expiration_time", "") or "").strip()
        if not expiration_time:
            return False
        deadline = _parse_iso8601(expiration_time)
        if deadline is None:
            return True
        now_dt = _parse_iso8601(now_iso or "") or _parse_iso8601(_utc_now_iso())
        if now_dt is None:
            return True
        return now_dt >= deadline

    def create_proposal(
        self,
        *,
        intent_class: str,
        originating_turn_id: str,
        governance_context: Mapping[str, Any],
        expiration_time: str | None = None,
        created_at: str | None = None,
    ) -> ProposalOperationResult:
        intent_value = str(intent_class).strip()
        turn_id = str(originating_turn_id).strip()
        if intent_value != REQUIRED_INTENT_CLASS:
            refusal = self._append_refusal(
                proposal_id="",
                action="create",
                reason_code="PROPOSAL_INTENT_CLASS_INVALID",
                details={"intent_class": intent_value},
            )
            return ProposalOperationResult(
                ok=False,
                reason_code="PROPOSAL_INTENT_CLASS_INVALID",
                proposal=None,
                ledger_entry=refusal,
            )
        if not turn_id:
            refusal = self._append_refusal(
                proposal_id="",
                action="create",
                reason_code="PROPOSAL_ORIGINATING_TURN_REQUIRED",
                details={},
            )
            return ProposalOperationResult(
                ok=False,
                reason_code="PROPOSAL_ORIGINATING_TURN_REQUIRED",
                proposal=None,
                ledger_entry=refusal,
            )

        context = dict(governance_context or {})
        expiry = str(expiration_time).strip() if expiration_time is not None else None
        if expiry == "":
            expiry = None
        created_at_value = str(created_at).strip() if created_at is not None else _utc_now_iso()
        if not created_at_value:
            created_at_value = _utc_now_iso()

        replay_basis = {
            "intent_class": intent_value,
            "originating_turn_id": turn_id,
            "governance_context": context,
            "expiration_time": expiry,
        }
        replay_key = _digest(replay_basis)
        existing = self._find_by_replay_key(replay_key)
        if existing is not None:
            existing_id = str(existing.get("proposal_id", ""))
            refusal = self._append_refusal(
                proposal_id=existing_id,
                action="create",
                reason_code="PROPOSAL_REPLAY_DETECTED",
                details={"replay_key": replay_key},
            )
            return ProposalOperationResult(
                ok=False,
                reason_code="PROPOSAL_REPLAY_DETECTED",
                proposal=self._proposal_view(existing_id),
                ledger_entry=refusal,
            )

        proposal_id = f"proposal-{replay_key[:16]}"
        artifact = {
            "proposal_id": proposal_id,
            "intent_class": REQUIRED_INTENT_CLASS,
            "originating_turn_id": turn_id,
            "created_at": created_at_value,
            "state": PROPOSAL_STATE_DRAFTED,
            "approved": False,
            "executed": False,
            "approval_reference": None,
            "expiration_time": expiry,
            "governance_context": context,
        }
        created_record = self._append_record(
            {
                "event_type": "proposal_created",
                "proposal_id": proposal_id,
                "payload": {
                    "artifact": artifact,
                    "artifact_digest": _digest(artifact),
                    "replay_key": replay_key,
                },
            }
        )
        return ProposalOperationResult(
            ok=True,
            reason_code="PROPOSAL_DRAFTED",
            proposal=self._proposal_view(proposal_id),
            ledger_entry=created_record,
        )

    def enforce_expiration(
        self,
        proposal_id: str,
        *,
        now_iso: str | None = None,
        trigger: str = "time-based",
    ) -> ProposalOperationResult:
        current = self._proposal_view(proposal_id)
        if current is None:
            refusal = self._append_refusal(
                proposal_id=proposal_id,
                action="enforce_expiration",
                reason_code="PROPOSAL_NOT_FOUND",
                details={},
            )
            return ProposalOperationResult(
                ok=False,
                reason_code="PROPOSAL_NOT_FOUND",
                proposal=None,
                ledger_entry=refusal,
            )
        state = str(current.get("state", ""))
        if state in _TERMINAL_STATES:
            return ProposalOperationResult(ok=True, reason_code="PROPOSAL_TERMINAL", proposal=current, ledger_entry=None)
        if not self._has_expired(current, now_iso=now_iso):
            return ProposalOperationResult(ok=True, reason_code="PROPOSAL_NOT_EXPIRED", proposal=current, ledger_entry=None)
        return self._transition(
            proposal_id=proposal_id,
            to_state=PROPOSAL_STATE_EXPIRED,
            action="expire",
            approval_reference=None,
            transition_reason=str(trigger or "time-based"),
            now_iso=now_iso,
            skip_expiration_check=True,
        )

    def _transition(
        self,
        *,
        proposal_id: str,
        to_state: str,
        action: str,
        approval_reference: str | None,
        transition_reason: str | None,
        now_iso: str | None = None,
        skip_expiration_check: bool = False,
    ) -> ProposalOperationResult:
        target_state = str(to_state).strip()
        proposal = self._proposal_view(proposal_id)
        if proposal is None:
            refusal = self._append_refusal(
                proposal_id=proposal_id,
                action=action,
                reason_code="PROPOSAL_NOT_FOUND",
                details={"to_state": target_state},
            )
            return ProposalOperationResult(
                ok=False,
                reason_code="PROPOSAL_NOT_FOUND",
                proposal=None,
                ledger_entry=refusal,
            )

        if target_state not in PROPOSAL_STATES:
            refusal = self._append_refusal(
                proposal_id=proposal_id,
                action=action,
                reason_code="PROPOSAL_STATE_INVALID",
                details={"to_state": target_state},
            )
            return ProposalOperationResult(
                ok=False,
                reason_code="PROPOSAL_STATE_INVALID",
                proposal=proposal,
                ledger_entry=refusal,
            )

        if not skip_expiration_check:
            expiration_result = self.enforce_expiration(proposal_id, now_iso=now_iso)
            if expiration_result.proposal is not None:
                proposal = expiration_result.proposal

        current_state = str(proposal.get("state", ""))
        if current_state in _TERMINAL_STATES:
            refusal = self._append_refusal(
                proposal_id=proposal_id,
                action=action,
                reason_code="PROPOSAL_TERMINAL_STATE",
                details={"current_state": current_state, "to_state": target_state},
            )
            return ProposalOperationResult(
                ok=False,
                reason_code="PROPOSAL_TERMINAL_STATE",
                proposal=proposal,
                ledger_entry=refusal,
            )

        allowed = _ALLOWED_TRANSITIONS.get(current_state, set())
        if target_state not in allowed:
            refusal = self._append_refusal(
                proposal_id=proposal_id,
                action=action,
                reason_code="PROPOSAL_STATE_REGRESSION_FORBIDDEN",
                details={"current_state": current_state, "to_state": target_state},
            )
            return ProposalOperationResult(
                ok=False,
                reason_code="PROPOSAL_STATE_REGRESSION_FORBIDDEN",
                proposal=proposal,
                ledger_entry=refusal,
            )

        if target_state == PROPOSAL_STATE_SUBMITTED:
            valid, reason = self._validate_integrity(proposal_id)
            if not valid:
                refusal = self._append_refusal(
                    proposal_id=proposal_id,
                    action=action,
                    reason_code=reason,
                    details={},
                )
                return ProposalOperationResult(
                    ok=False,
                    reason_code=reason,
                    proposal=proposal,
                    ledger_entry=refusal,
                )

        approval_ref = str(approval_reference).strip() if approval_reference is not None else ""
        if target_state == PROPOSAL_STATE_APPROVED and not approval_ref:
            refusal = self._append_refusal(
                proposal_id=proposal_id,
                action=action,
                reason_code="PROPOSAL_APPROVAL_REFERENCE_REQUIRED",
                details={},
            )
            return ProposalOperationResult(
                ok=False,
                reason_code="PROPOSAL_APPROVAL_REFERENCE_REQUIRED",
                proposal=proposal,
                ledger_entry=refusal,
            )

        transition_record = self._append_record(
            {
                "event_type": "proposal_transition",
                "proposal_id": str(proposal_id),
                "payload": {
                    "from_state": current_state,
                    "to_state": target_state,
                    "approval_reference": approval_ref or None,
                    "transition_reason": str(transition_reason or ""),
                    "approved": target_state == PROPOSAL_STATE_APPROVED or bool(proposal.get("approved", False)),
                    "executed": False,
                },
            }
        )
        updated = self._proposal_view(proposal_id)
        return ProposalOperationResult(
            ok=True,
            reason_code=f"PROPOSAL_{target_state.upper()}",
            proposal=updated,
            ledger_entry=transition_record,
        )

    def submit_proposal(self, proposal_id: str) -> ProposalOperationResult:
        return self._transition(
            proposal_id=proposal_id,
            to_state=PROPOSAL_STATE_SUBMITTED,
            action="submit",
            approval_reference=None,
            transition_reason="explicit_submission",
        )

    def approve_proposal(self, proposal_id: str, *, approval_reference: str) -> ProposalOperationResult:
        return self._transition(
            proposal_id=proposal_id,
            to_state=PROPOSAL_STATE_APPROVED,
            action="approve",
            approval_reference=approval_reference,
            transition_reason="external_approval_artifact",
        )

    def reject_proposal(self, proposal_id: str, *, rejection_reason: str | None = None) -> ProposalOperationResult:
        return self._transition(
            proposal_id=proposal_id,
            to_state=PROPOSAL_STATE_REJECTED,
            action="reject",
            approval_reference=None,
            transition_reason=str(rejection_reason or "explicit_rejection"),
        )

    def expire_proposal(self, proposal_id: str, *, trigger: str = "governance") -> ProposalOperationResult:
        return self._transition(
            proposal_id=proposal_id,
            to_state=PROPOSAL_STATE_EXPIRED,
            action="expire",
            approval_reference=None,
            transition_reason=trigger,
            skip_expiration_check=True,
        )

    def get_proposal(self, proposal_id: str) -> Dict[str, Any] | None:
        return copy.deepcopy(self._proposal_view(proposal_id))


_PROPOSAL_LEDGER = ProposalGovernanceLedger()


def create_proposal(
    *,
    intent_class: str,
    originating_turn_id: str,
    governance_context: Mapping[str, Any],
    expiration_time: str | None = None,
    created_at: str | None = None,
) -> ProposalOperationResult:
    return _PROPOSAL_LEDGER.create_proposal(
        intent_class=intent_class,
        originating_turn_id=originating_turn_id,
        governance_context=governance_context,
        expiration_time=expiration_time,
        created_at=created_at,
    )


def submit_proposal(proposal_id: str) -> ProposalOperationResult:
    return _PROPOSAL_LEDGER.submit_proposal(proposal_id)


def approve_proposal(proposal_id: str, *, approval_reference: str) -> ProposalOperationResult:
    return _PROPOSAL_LEDGER.approve_proposal(proposal_id, approval_reference=approval_reference)


def reject_proposal(proposal_id: str, *, rejection_reason: str | None = None) -> ProposalOperationResult:
    return _PROPOSAL_LEDGER.reject_proposal(proposal_id, rejection_reason=rejection_reason)


def expire_proposal(proposal_id: str, *, trigger: str = "governance") -> ProposalOperationResult:
    return _PROPOSAL_LEDGER.expire_proposal(proposal_id, trigger=trigger)


def enforce_proposal_expiration(proposal_id: str, *, now_iso: str | None = None) -> ProposalOperationResult:
    return _PROPOSAL_LEDGER.enforce_expiration(proposal_id, now_iso=now_iso)


def get_proposal(proposal_id: str) -> Dict[str, Any] | None:
    return _PROPOSAL_LEDGER.get_proposal(proposal_id)


def get_proposal_ledger() -> List[Dict[str, Any]]:
    return _PROPOSAL_LEDGER.get_ledger()


def reset_proposal_ledger() -> None:
    _PROPOSAL_LEDGER.reset()

