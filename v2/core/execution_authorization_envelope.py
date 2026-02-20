"""Phase 31 execution authorization envelope (non-executing)."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping

from v2.core.execution_attempt_admissibility import evaluate_execution_attempt_admissibility


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


def _normalize_iso8601(value: str) -> str | None:
    parsed = _parse_iso8601(value)
    if parsed is None:
        return None
    return parsed.isoformat().replace("+00:00", "Z")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class AuthorizationOperationResult:
    ok: bool
    reason_code: str
    envelope: Dict[str, Any] | None
    ledger_entry: Dict[str, Any] | None


class ExecutionAuthorizationLedger:
    """Append-only authorization envelope ledger.

    Scope is strictly limited to authorization representation and validation.
    No execution behavior is provided by this class.
    """

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
        payload["record_id"] = f"execution-authorization-ledger-{len(self._records) + 1:08d}"
        payload["recorded_at"] = payload.get("recorded_at", _utc_now_iso())
        payload["previous_record_hash"] = previous_hash
        payload["record_hash"] = _digest(
            {
                "record_id": payload["record_id"],
                "event_type": payload.get("event_type", ""),
                "authorization_id": payload.get("authorization_id", ""),
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
        approval_id: str,
        reason_code: str,
        details: Mapping[str, Any] | None = None,
    ) -> Dict[str, Any]:
        return self._append_record(
            {
                "event_type": "authorization_refused",
                "authorization_id": "",
                "payload": {
                    "proposal_id": str(proposal_id),
                    "approval_id": str(approval_id),
                    "reason_code": str(reason_code),
                    "details": dict(details or {}),
                },
            }
        )

    def _issued_records(self) -> List[Dict[str, Any]]:
        return [
            copy.deepcopy(item)
            for item in self._records
            if str(item.get("event_type", "")) == "authorization_issued"
        ]

    def _find_by_authorization_id(self, authorization_id: str) -> Dict[str, Any] | None:
        target = str(authorization_id).strip()
        if not target:
            return None
        for item in self._issued_records():
            if str(item.get("authorization_id", "")) == target:
                return copy.deepcopy(item)
        return None

    def _find_by_key(self, authorization_key: str) -> Dict[str, Any] | None:
        target = str(authorization_key).strip()
        if not target:
            return None
        for item in self._issued_records():
            payload = item.get("payload", {})
            payload = payload if isinstance(payload, dict) else {}
            if str(payload.get("authorization_key", "")) == target:
                return copy.deepcopy(item)
        return None

    def _build_authorization_envelope(
        self,
        *,
        authorization_id: str,
        proposal_id: str,
        approval_id: str,
        issued_at: str,
        expires_at: str,
        governance_context: Mapping[str, Any],
        admissibility_fingerprint: str,
        authorized: bool = False,
    ) -> Dict[str, Any]:
        return {
            "authorization_id": str(authorization_id),
            "proposal_id": str(proposal_id),
            "approval_id": str(approval_id),
            "issued_at": str(issued_at),
            "expires_at": str(expires_at),
            "governance_context": copy.deepcopy(dict(governance_context)),
            "admissibility_fingerprint": str(admissibility_fingerprint),
            "authorized": bool(authorized),
            "execution_enabled": False,
        }

    def get_authorization(self, authorization_id: str) -> Dict[str, Any] | None:
        record = self._find_by_authorization_id(authorization_id)
        if record is None:
            return None
        payload = record.get("payload", {})
        payload = payload if isinstance(payload, dict) else {}
        envelope = payload.get("envelope", {})
        envelope = envelope if isinstance(envelope, dict) else {}
        return copy.deepcopy(envelope)

    def issue_authorization(
        self,
        *,
        proposal_id: str,
        approval_id: str,
        governance_context: Mapping[str, Any],
        admissibility_fingerprint: str,
        issued_at: str,
        expires_at: str,
        execution_arming_status: Mapping[str, Any],
        system_phase: int | str,
    ) -> AuthorizationOperationResult:
        proposal_id_value = str(proposal_id).strip()
        approval_id_value = str(approval_id).strip()
        admissibility_fingerprint_value = str(admissibility_fingerprint).strip()
        issued_at_value = str(issued_at).strip()
        expires_at_value = str(expires_at).strip()
        context_value = dict(governance_context or {})
        arming_value = dict(execution_arming_status or {})

        if not proposal_id_value:
            refusal = self._append_refusal(
                proposal_id="",
                approval_id=approval_id_value,
                reason_code="AUTHORIZATION_PROPOSAL_ID_REQUIRED",
                details={},
            )
            return AuthorizationOperationResult(
                ok=False,
                reason_code="AUTHORIZATION_PROPOSAL_ID_REQUIRED",
                envelope=None,
                ledger_entry=refusal,
            )
        if not approval_id_value:
            refusal = self._append_refusal(
                proposal_id=proposal_id_value,
                approval_id="",
                reason_code="AUTHORIZATION_APPROVAL_ID_REQUIRED",
                details={},
            )
            return AuthorizationOperationResult(
                ok=False,
                reason_code="AUTHORIZATION_APPROVAL_ID_REQUIRED",
                envelope=None,
                ledger_entry=refusal,
            )
        if not isinstance(context_value, dict) or not context_value:
            refusal = self._append_refusal(
                proposal_id=proposal_id_value,
                approval_id=approval_id_value,
                reason_code="AUTHORIZATION_GOVERNANCE_CONTEXT_REQUIRED",
                details={},
            )
            return AuthorizationOperationResult(
                ok=False,
                reason_code="AUTHORIZATION_GOVERNANCE_CONTEXT_REQUIRED",
                envelope=None,
                ledger_entry=refusal,
            )
        if not admissibility_fingerprint_value:
            refusal = self._append_refusal(
                proposal_id=proposal_id_value,
                approval_id=approval_id_value,
                reason_code="AUTHORIZATION_ADMISSIBILITY_FINGERPRINT_REQUIRED",
                details={},
            )
            return AuthorizationOperationResult(
                ok=False,
                reason_code="AUTHORIZATION_ADMISSIBILITY_FINGERPRINT_REQUIRED",
                envelope=None,
                ledger_entry=refusal,
            )

        normalized_issued_at = _normalize_iso8601(issued_at_value)
        normalized_expires_at = _normalize_iso8601(expires_at_value)
        if normalized_issued_at is None:
            refusal = self._append_refusal(
                proposal_id=proposal_id_value,
                approval_id=approval_id_value,
                reason_code="AUTHORIZATION_ISSUED_AT_INVALID",
                details={},
            )
            return AuthorizationOperationResult(
                ok=False,
                reason_code="AUTHORIZATION_ISSUED_AT_INVALID",
                envelope=None,
                ledger_entry=refusal,
            )
        if normalized_expires_at is None:
            refusal = self._append_refusal(
                proposal_id=proposal_id_value,
                approval_id=approval_id_value,
                reason_code="AUTHORIZATION_EXPIRES_AT_INVALID",
                details={},
            )
            return AuthorizationOperationResult(
                ok=False,
                reason_code="AUTHORIZATION_EXPIRES_AT_INVALID",
                envelope=None,
                ledger_entry=refusal,
            )
        issued_dt = _parse_iso8601(normalized_issued_at)
        expires_dt = _parse_iso8601(normalized_expires_at)
        if issued_dt is None or expires_dt is None or issued_dt >= expires_dt:
            refusal = self._append_refusal(
                proposal_id=proposal_id_value,
                approval_id=approval_id_value,
                reason_code="AUTHORIZATION_TIME_WINDOW_INVALID",
                details={},
            )
            return AuthorizationOperationResult(
                ok=False,
                reason_code="AUTHORIZATION_TIME_WINDOW_INVALID",
                envelope=None,
                ledger_entry=refusal,
            )

        admissibility_result = evaluate_execution_attempt_admissibility(
            proposal_id=proposal_id_value,
            approval_id=approval_id_value,
            governance_context=context_value,
            execution_arming_status=arming_value,
            system_phase=system_phase,
            evaluated_at=normalized_issued_at,
        )
        if bool(admissibility_result.get("admissible", False)) is not True:
            reason = str(admissibility_result.get("reason", "UNKNOWN")).strip() or "UNKNOWN"
            refusal = self._append_refusal(
                proposal_id=proposal_id_value,
                approval_id=approval_id_value,
                reason_code=f"AUTHORIZATION_ADMISSIBILITY_REFUSED:{reason}",
                details={"admissibility": copy.deepcopy(admissibility_result)},
            )
            return AuthorizationOperationResult(
                ok=False,
                reason_code=f"AUTHORIZATION_ADMISSIBILITY_REFUSED:{reason}",
                envelope=None,
                ledger_entry=refusal,
            )
        evaluated_fingerprint = str(admissibility_result.get("decision_fingerprint", "")).strip()
        if evaluated_fingerprint != admissibility_fingerprint_value:
            refusal = self._append_refusal(
                proposal_id=proposal_id_value,
                approval_id=approval_id_value,
                reason_code="AUTHORIZATION_ADMISSIBILITY_FINGERPRINT_MISMATCH",
                details={},
            )
            return AuthorizationOperationResult(
                ok=False,
                reason_code="AUTHORIZATION_ADMISSIBILITY_FINGERPRINT_MISMATCH",
                envelope=None,
                ledger_entry=refusal,
            )

        authorization_key = _digest(
            {
                "proposal_id": proposal_id_value,
                "approval_id": approval_id_value,
                "issued_at": normalized_issued_at,
                "expires_at": normalized_expires_at,
                "governance_context": context_value,
                "admissibility_fingerprint": admissibility_fingerprint_value,
            }
        )
        if self._find_by_key(authorization_key) is not None:
            refusal = self._append_refusal(
                proposal_id=proposal_id_value,
                approval_id=approval_id_value,
                reason_code="AUTHORIZATION_REPLAY_DETECTED",
                details={},
            )
            return AuthorizationOperationResult(
                ok=False,
                reason_code="AUTHORIZATION_REPLAY_DETECTED",
                envelope=None,
                ledger_entry=refusal,
            )

        authorization_id = f"authorization-{authorization_key[:16]}"
        envelope = self._build_authorization_envelope(
            authorization_id=authorization_id,
            proposal_id=proposal_id_value,
            approval_id=approval_id_value,
            issued_at=normalized_issued_at,
            expires_at=normalized_expires_at,
            governance_context=context_value,
            admissibility_fingerprint=admissibility_fingerprint_value,
            authorized=True,
        )

        if envelope.get("execution_enabled") is not False:
            refusal = self._append_refusal(
                proposal_id=proposal_id_value,
                approval_id=approval_id_value,
                reason_code="AUTHORIZATION_EXECUTION_ENABLED_VIOLATION",
                details={},
            )
            return AuthorizationOperationResult(
                ok=False,
                reason_code="AUTHORIZATION_EXECUTION_ENABLED_VIOLATION",
                envelope=None,
                ledger_entry=refusal,
            )

        issued_record = self._append_record(
            {
                "event_type": "authorization_issued",
                "authorization_id": authorization_id,
                "payload": {
                    "proposal_id": proposal_id_value,
                    "approval_id": approval_id_value,
                    "authorization_key": authorization_key,
                    "envelope": envelope,
                    "envelope_digest": _digest(envelope),
                    "admissibility_fingerprint": admissibility_fingerprint_value,
                },
            }
        )
        return AuthorizationOperationResult(
            ok=True,
            reason_code="AUTHORIZATION_ISSUED",
            envelope=copy.deepcopy(envelope),
            ledger_entry=issued_record,
        )

    def validate_authorization(
        self,
        *,
        authorization_id: str,
        governance_context: Mapping[str, Any],
        execution_arming_status: Mapping[str, Any],
        system_phase: int | str,
        evaluated_at: str,
    ) -> Dict[str, Any]:
        authorization_id_value = str(authorization_id).strip()
        evaluated_at_value = str(evaluated_at).strip()
        context_value = dict(governance_context or {})
        arming_value = dict(execution_arming_status or {})

        normalized_evaluated_at = _normalize_iso8601(evaluated_at_value)
        if not authorization_id_value:
            return {
                "valid": False,
                "reason": "AUTHORIZATION_ID_REQUIRED",
                "authorization": None,
                "evaluated_at": evaluated_at_value,
                "decision_fingerprint": _digest(
                    {
                        "authorization_id": authorization_id_value,
                        "reason": "AUTHORIZATION_ID_REQUIRED",
                        "evaluated_at": evaluated_at_value,
                    }
                ),
            }
        if normalized_evaluated_at is None:
            return {
                "valid": False,
                "reason": "EVALUATED_AT_INVALID",
                "authorization": None,
                "evaluated_at": evaluated_at_value,
                "decision_fingerprint": _digest(
                    {
                        "authorization_id": authorization_id_value,
                        "reason": "EVALUATED_AT_INVALID",
                        "evaluated_at": evaluated_at_value,
                    }
                ),
            }

        issued = self._find_by_authorization_id(authorization_id_value)
        if issued is None:
            return {
                "valid": False,
                "reason": "AUTHORIZATION_NOT_FOUND",
                "authorization": None,
                "evaluated_at": normalized_evaluated_at,
                "decision_fingerprint": _digest(
                    {
                        "authorization_id": authorization_id_value,
                        "reason": "AUTHORIZATION_NOT_FOUND",
                        "evaluated_at": normalized_evaluated_at,
                    }
                ),
            }

        payload = issued.get("payload", {})
        payload = payload if isinstance(payload, dict) else {}
        envelope = payload.get("envelope", {})
        envelope = envelope if isinstance(envelope, dict) else {}
        expected_envelope_digest = str(payload.get("envelope_digest", "")).strip()
        actual_envelope_digest = _digest(envelope)
        if not expected_envelope_digest or expected_envelope_digest != actual_envelope_digest:
            return {
                "valid": False,
                "reason": "AUTHORIZATION_INTEGRITY_VIOLATION",
                "authorization": copy.deepcopy(envelope),
                "evaluated_at": normalized_evaluated_at,
                "decision_fingerprint": _digest(
                    {
                        "authorization_id": authorization_id_value,
                        "reason": "AUTHORIZATION_INTEGRITY_VIOLATION",
                        "evaluated_at": normalized_evaluated_at,
                    }
                ),
            }

        if not isinstance(context_value, dict) or not context_value:
            return {
                "valid": False,
                "reason": "AUTHORIZATION_GOVERNANCE_CONTEXT_REQUIRED",
                "authorization": copy.deepcopy(envelope),
                "evaluated_at": normalized_evaluated_at,
                "decision_fingerprint": _digest(
                    {
                        "authorization_id": authorization_id_value,
                        "reason": "AUTHORIZATION_GOVERNANCE_CONTEXT_REQUIRED",
                        "evaluated_at": normalized_evaluated_at,
                    }
                ),
            }

        if envelope.get("execution_enabled") is not False:
            return {
                "valid": False,
                "reason": "AUTHORIZATION_EXECUTION_ENABLED_VIOLATION",
                "authorization": copy.deepcopy(envelope),
                "evaluated_at": normalized_evaluated_at,
                "decision_fingerprint": _digest(
                    {
                        "authorization_id": authorization_id_value,
                        "reason": "AUTHORIZATION_EXECUTION_ENABLED_VIOLATION",
                        "evaluated_at": normalized_evaluated_at,
                    }
                ),
            }
        if bool(envelope.get("authorized", False)) is not True:
            return {
                "valid": False,
                "reason": "AUTHORIZATION_NOT_GRANTED",
                "authorization": copy.deepcopy(envelope),
                "evaluated_at": normalized_evaluated_at,
                "decision_fingerprint": _digest(
                    {
                        "authorization_id": authorization_id_value,
                        "reason": "AUTHORIZATION_NOT_GRANTED",
                        "evaluated_at": normalized_evaluated_at,
                    }
                ),
            }

        envelope_context = envelope.get("governance_context", {})
        envelope_context = envelope_context if isinstance(envelope_context, dict) else {}
        if _digest(envelope_context) != _digest(context_value):
            return {
                "valid": False,
                "reason": "AUTHORIZATION_GOVERNANCE_CONTEXT_MISMATCH",
                "authorization": copy.deepcopy(envelope),
                "evaluated_at": normalized_evaluated_at,
                "decision_fingerprint": _digest(
                    {
                        "authorization_id": authorization_id_value,
                        "reason": "AUTHORIZATION_GOVERNANCE_CONTEXT_MISMATCH",
                        "evaluated_at": normalized_evaluated_at,
                    }
                ),
            }

        issued_dt = _parse_iso8601(str(envelope.get("issued_at", "")).strip())
        expires_dt = _parse_iso8601(str(envelope.get("expires_at", "")).strip())
        evaluated_dt = _parse_iso8601(normalized_evaluated_at)
        if issued_dt is None or expires_dt is None or evaluated_dt is None:
            return {
                "valid": False,
                "reason": "AUTHORIZATION_TIME_WINDOW_INVALID",
                "authorization": copy.deepcopy(envelope),
                "evaluated_at": normalized_evaluated_at,
                "decision_fingerprint": _digest(
                    {
                        "authorization_id": authorization_id_value,
                        "reason": "AUTHORIZATION_TIME_WINDOW_INVALID",
                        "evaluated_at": normalized_evaluated_at,
                    }
                ),
            }
        if issued_dt >= expires_dt:
            return {
                "valid": False,
                "reason": "AUTHORIZATION_TIME_WINDOW_INVALID",
                "authorization": copy.deepcopy(envelope),
                "evaluated_at": normalized_evaluated_at,
                "decision_fingerprint": _digest(
                    {
                        "authorization_id": authorization_id_value,
                        "reason": "AUTHORIZATION_TIME_WINDOW_INVALID",
                        "evaluated_at": normalized_evaluated_at,
                    }
                ),
            }
        if evaluated_dt < issued_dt:
            return {
                "valid": False,
                "reason": "AUTHORIZATION_NOT_YET_ACTIVE",
                "authorization": copy.deepcopy(envelope),
                "evaluated_at": normalized_evaluated_at,
                "decision_fingerprint": _digest(
                    {
                        "authorization_id": authorization_id_value,
                        "reason": "AUTHORIZATION_NOT_YET_ACTIVE",
                        "evaluated_at": normalized_evaluated_at,
                    }
                ),
            }
        if evaluated_dt >= expires_dt:
            return {
                "valid": False,
                "reason": "AUTHORIZATION_EXPIRED",
                "authorization": copy.deepcopy(envelope),
                "evaluated_at": normalized_evaluated_at,
                "decision_fingerprint": _digest(
                    {
                        "authorization_id": authorization_id_value,
                        "reason": "AUTHORIZATION_EXPIRED",
                        "evaluated_at": normalized_evaluated_at,
                    }
                ),
            }

        issuance_admissibility = evaluate_execution_attempt_admissibility(
            proposal_id=str(envelope.get("proposal_id", "")),
            approval_id=str(envelope.get("approval_id", "")),
            governance_context=context_value,
            execution_arming_status=arming_value,
            system_phase=system_phase,
            evaluated_at=str(envelope.get("issued_at", "")),
        )
        if str(issuance_admissibility.get("decision_fingerprint", "")).strip() != str(
            envelope.get("admissibility_fingerprint", "")
        ).strip():
            return {
                "valid": False,
                "reason": "AUTHORIZATION_ADMISSIBILITY_FINGERPRINT_MISMATCH",
                "authorization": copy.deepcopy(envelope),
                "evaluated_at": normalized_evaluated_at,
                "decision_fingerprint": _digest(
                    {
                        "authorization_id": authorization_id_value,
                        "reason": "AUTHORIZATION_ADMISSIBILITY_FINGERPRINT_MISMATCH",
                        "evaluated_at": normalized_evaluated_at,
                    }
                ),
            }

        current_admissibility = evaluate_execution_attempt_admissibility(
            proposal_id=str(envelope.get("proposal_id", "")),
            approval_id=str(envelope.get("approval_id", "")),
            governance_context=context_value,
            execution_arming_status=arming_value,
            system_phase=system_phase,
            evaluated_at=normalized_evaluated_at,
        )
        if bool(current_admissibility.get("admissible", False)) is not True:
            reason = str(current_admissibility.get("reason", "UNKNOWN")).strip() or "UNKNOWN"
            return {
                "valid": False,
                "reason": f"AUTHORIZATION_ADMISSIBILITY_INVALID:{reason}",
                "authorization": copy.deepcopy(envelope),
                "evaluated_at": normalized_evaluated_at,
                "decision_fingerprint": _digest(
                    {
                        "authorization_id": authorization_id_value,
                        "reason": f"AUTHORIZATION_ADMISSIBILITY_INVALID:{reason}",
                        "evaluated_at": normalized_evaluated_at,
                    }
                ),
            }
        return {
            "valid": True,
            "reason": "AUTHORIZATION_VALID",
            "authorization": copy.deepcopy(envelope),
            "evaluated_at": normalized_evaluated_at,
            "decision_fingerprint": _digest(
                {
                    "authorization_id": authorization_id_value,
                    "reason": "AUTHORIZATION_VALID",
                    "evaluated_at": normalized_evaluated_at,
                    "admissibility_fingerprint": str(envelope.get("admissibility_fingerprint", "")),
                }
            ),
        }


_AUTHORIZATION_LEDGER = ExecutionAuthorizationLedger()


def issue_execution_authorization(
    *,
    proposal_id: str,
    approval_id: str,
    governance_context: Mapping[str, Any],
    admissibility_fingerprint: str,
    issued_at: str,
    expires_at: str,
    execution_arming_status: Mapping[str, Any],
    system_phase: int | str,
) -> AuthorizationOperationResult:
    return _AUTHORIZATION_LEDGER.issue_authorization(
        proposal_id=proposal_id,
        approval_id=approval_id,
        governance_context=governance_context,
        admissibility_fingerprint=admissibility_fingerprint,
        issued_at=issued_at,
        expires_at=expires_at,
        execution_arming_status=execution_arming_status,
        system_phase=system_phase,
    )


def validate_execution_authorization(
    *,
    authorization_id: str,
    governance_context: Mapping[str, Any],
    execution_arming_status: Mapping[str, Any],
    system_phase: int | str,
    evaluated_at: str,
) -> Dict[str, Any]:
    return _AUTHORIZATION_LEDGER.validate_authorization(
        authorization_id=authorization_id,
        governance_context=governance_context,
        execution_arming_status=execution_arming_status,
        system_phase=system_phase,
        evaluated_at=evaluated_at,
    )


def get_execution_authorization(authorization_id: str) -> Dict[str, Any] | None:
    return _AUTHORIZATION_LEDGER.get_authorization(authorization_id)


def get_execution_authorization_ledger() -> List[Dict[str, Any]]:
    return _AUTHORIZATION_LEDGER.get_ledger()


def reset_execution_authorization_ledger() -> None:
    _AUTHORIZATION_LEDGER.reset()
