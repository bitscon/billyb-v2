"""ACI issuance ledger and artifact composition (non-executing)."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

REVOCATION_CONTRACT_NAME = "revocation_record.v1"
SUPERSESSION_CONTRACT_NAME = "supersession_record.v1"
_RECORD_TYPE_ISSUANCE = "issuance"
_RECORD_TYPE_REVOCATION = "revocation"
_RECORD_TYPE_SUPERSESSION = "supersession"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _compute_transition_key(
    *,
    phase_id: int,
    contract_name: str,
    environment_id: str,
    lineage_refs: Sequence[str],
) -> str:
    payload = {
        "phase_id": int(phase_id),
        "contract_name": str(contract_name),
        "environment_id": str(environment_id),
        "lineage_refs": sorted(str(item) for item in lineage_refs),
    }
    return _digest(payload)


def _phase_class(phase_id: int) -> str:
    if 27 <= phase_id <= 31:
        return "cognitive"
    if 32 <= phase_id <= 38:
        return "planning_governance"
    if 39 <= phase_id <= 46:
        return "execution_governance"
    if 47 <= phase_id <= 53:
        return "pre_execution_boundary"
    if 54 <= phase_id <= 62:
        return "replanning_governance"
    if 63 <= phase_id <= 67:
        return "readiness_eligibility"
    if 68 <= phase_id <= 69:
        return "handoff_boundary"
    return "unknown"


def compute_transition_key(
    *,
    phase_id: int,
    contract_name: str,
    environment_id: str,
    lineage_refs: Sequence[str],
) -> str:
    """Public deterministic transition-key helper for replay/duplication checks."""
    return _compute_transition_key(
        phase_id=phase_id,
        contract_name=contract_name,
        environment_id=environment_id,
        lineage_refs=lineage_refs,
    )


def _authority_guarantees() -> Dict[str, bool]:
    return {
        "can_execute": False,
        "can_invoke_tools": False,
        "can_mutate_state": False,
        "can_delegate": False,
        "can_background_process": False,
        "can_auto_apply": False,
        "can_auto_route": False,
        "can_escalate_authority": False,
    }


def compose_issued_artifact(
    *,
    phase_id: int,
    contract_name: str,
    issuer_identity_id: str,
    environment_id: str,
    lineage_refs: Sequence[str],
    request_context: Dict[str, Any],
) -> Dict[str, Any]:
    """Pure issuance artifact composition. No persistence, no side effects."""
    composed = {
        "phase_id": int(phase_id),
        "contract_name": str(contract_name),
        "issuer_identity_id": str(issuer_identity_id),
        "environment_id": str(environment_id),
        "lineage_refs": [str(item) for item in lineage_refs],
        "request_context": dict(request_context or {}),
        "execution_enabled": False,
        "authority_guarantees": _authority_guarantees(),
        "immutability_guarantees": {
            "append_only": True,
            "mutable_after_write": False,
            "overwrite_allowed": False,
            "delete_allowed": False,
        },
    }
    composed["input_digest"] = _digest(composed)
    return composed


@dataclass(frozen=True)
class LedgerAppendResult:
    ok: bool
    record: Dict[str, Any] | None
    reason_code: str


class ACIIssuanceLedger:
    """Append-only ledger for issued governance artifacts."""

    def __init__(self, ledger_path: str | Path):
        self.ledger_path = Path(ledger_path)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.ledger_path.exists():
            self.ledger_path.write_text("", encoding="utf-8")

    def _read_records(self) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        if not self.ledger_path.exists():
            return records
        for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
            payload = line.strip()
            if not payload:
                continue
            try:
                item = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)
        return records

    def _append_record(self, record: Dict[str, Any]) -> LedgerAppendResult:
        try:
            with self.ledger_path.open("a", encoding="utf-8") as handle:
                handle.write(_canonical_json(record))
                handle.write("\n")
        except OSError:
            return LedgerAppendResult(ok=False, record=None, reason_code="ISSUANCE_LEDGER_APPEND_FAILED")
        return LedgerAppendResult(ok=True, record=record, reason_code="ISSUED")

    def _next_artifact_id(self, phase_id: int, records: Sequence[Dict[str, Any]]) -> str:
        return f"artifact-p{int(phase_id):02d}-{len(records) + 1:08d}"

    def _next_revocation_id(self, records: Sequence[Dict[str, Any]]) -> str:
        count = sum(1 for item in records if str(item.get("record_type", "")) == _RECORD_TYPE_REVOCATION)
        return f"revocation-{count + 1:08d}"

    def _next_supersession_id(self, records: Sequence[Dict[str, Any]]) -> str:
        count = sum(1 for item in records if str(item.get("record_type", "")) == _RECORD_TYPE_SUPERSESSION)
        return f"supersession-{count + 1:08d}"

    def _is_issuance_record(self, record: Dict[str, Any]) -> bool:
        record_type = str(record.get("record_type", _RECORD_TYPE_ISSUANCE))
        return record_type == _RECORD_TYPE_ISSUANCE and bool(str(record.get("artifact_id", "")).strip())

    def lookup_by_artifact_id(self, artifact_id: str) -> Dict[str, Any] | None:
        target = str(artifact_id)
        for item in self._read_records():
            if not self._is_issuance_record(item):
                continue
            if str(item.get("artifact_id", "")) == target:
                return deepcopy(item)
        return None

    def lookup_by_revocation_id(self, revocation_id: str) -> Dict[str, Any] | None:
        target = str(revocation_id)
        for item in self._read_records():
            if str(item.get("record_type", "")) != _RECORD_TYPE_REVOCATION:
                continue
            if str(item.get("revocation_id", "")) == target:
                return deepcopy(item)
        return None

    def lookup_by_supersession_id(self, supersession_id: str) -> Dict[str, Any] | None:
        target = str(supersession_id)
        for item in self._read_records():
            if str(item.get("record_type", "")) != _RECORD_TYPE_SUPERSESSION:
                continue
            if str(item.get("supersession_id", "")) == target:
                return deepcopy(item)
        return None

    def lookup_by_phase_id(self, phase_id: int) -> List[Dict[str, Any]]:
        target = int(phase_id)
        return [
            deepcopy(item)
            for item in self._read_records()
            if self._is_issuance_record(item) and int(item.get("phase_id", -1)) == target
        ]

    def lookup_by_lineage_reference(self, artifact_id: str) -> List[Dict[str, Any]]:
        target = str(artifact_id)
        out: List[Dict[str, Any]] = []
        for item in self._read_records():
            if not self._is_issuance_record(item):
                continue
            refs = [str(x) for x in item.get("lineage_refs", []) if isinstance(x, str)]
            if target in refs:
                out.append(deepcopy(item))
        return out

    def get_artifact_status(self, artifact_id: str) -> Dict[str, Any]:
        target = str(artifact_id)
        revocation_ids: List[str] = []
        supersession_id = ""
        replacement_artifact_id = ""
        for item in self._read_records():
            record_type = str(item.get("record_type", ""))
            if record_type == _RECORD_TYPE_REVOCATION:
                if str(item.get("revoked_artifact_id", "")) == target:
                    revocation_ids.append(str(item.get("revocation_id", "")))
            elif record_type == _RECORD_TYPE_SUPERSESSION:
                if str(item.get("superseded_artifact_id", "")) == target and not supersession_id:
                    supersession_id = str(item.get("supersession_id", ""))
                    replacement_artifact_id = str(item.get("replacement_artifact_id", ""))
        return {
            "revoked": bool(revocation_ids) or bool(supersession_id),
            "revocation_ids": [item for item in revocation_ids if item],
            "superseded": bool(supersession_id),
            "supersession_id": supersession_id,
            "replacement_artifact_id": replacement_artifact_id,
        }

    def is_artifact_revoked(self, artifact_id: str) -> bool:
        return bool(self.get_artifact_status(artifact_id).get("revoked", False))

    def get_supersession_replacement(self, artifact_id: str) -> str | None:
        replacement = str(self.get_artifact_status(artifact_id).get("replacement_artifact_id", "")).strip()
        return replacement or None

    def has_transition_key(self, transition_key: str) -> bool:
        target = str(transition_key)
        return any(str(item.get("transition_key", "")) == target for item in self._read_records())

    def validate_lineage(
        self,
        *,
        lineage_refs: Sequence[str],
        environment_id: str,
        lineage_required: bool,
    ) -> Tuple[bool, str]:
        refs = [str(item) for item in lineage_refs if str(item).strip()]
        if lineage_required and not refs:
            return False, "ISSUANCE_LINEAGE_REQUIRED"

        env = str(environment_id)
        for artifact_id in refs:
            upstream = self.lookup_by_artifact_id(artifact_id)
            if upstream is None:
                return False, "ISSUANCE_UPSTREAM_NOT_FOUND"
            if self.is_artifact_revoked(artifact_id):
                return False, "ISSUANCE_UPSTREAM_REVOKED"
            if str(upstream.get("environment_id", "")) != env:
                return False, "ISSUANCE_ENVIRONMENT_MISMATCH"
        return True, "OK"

    def append_issued_artifact(
        self,
        *,
        phase_id: int,
        contract_name: str,
        issuer_identity_id: str,
        environment_id: str,
        lineage_refs: Sequence[str],
        request_context: Dict[str, Any],
        lineage_required: bool,
    ) -> LedgerAppendResult:
        valid_lineage, lineage_code = self.validate_lineage(
            lineage_refs=lineage_refs,
            environment_id=environment_id,
            lineage_required=lineage_required,
        )
        if not valid_lineage:
            return LedgerAppendResult(ok=False, record=None, reason_code=lineage_code)

        records = self._read_records()
        transition_key = _compute_transition_key(
            phase_id=phase_id,
            contract_name=contract_name,
            environment_id=environment_id,
            lineage_refs=lineage_refs,
        )
        for item in records:
            if str(item.get("transition_key", "")) == transition_key:
                return LedgerAppendResult(ok=False, record=None, reason_code="ISSUANCE_DUPLICATE_FOR_LINEAGE")

        composed = compose_issued_artifact(
            phase_id=phase_id,
            contract_name=contract_name,
            issuer_identity_id=issuer_identity_id,
            environment_id=environment_id,
            lineage_refs=lineage_refs,
            request_context=request_context,
        )

        record = {
            "record_type": _RECORD_TYPE_ISSUANCE,
            "artifact_id": self._next_artifact_id(phase_id, records),
            "phase_id": int(phase_id),
            "contract_name": str(contract_name),
            "issuer_identity_id": str(issuer_identity_id),
            "environment_id": str(environment_id),
            "issued_at": _utc_now_iso(),
            "input_digest": str(composed["input_digest"]),
            "lineage_refs": [str(item) for item in lineage_refs],
            "transition_key": transition_key,
            "revoked": False,
            "artifact": composed,
        }

        return self._append_record(record)

    def append_revocation_record(
        self,
        *,
        revoked_artifact_id: str,
        revocation_reason: str,
        issuer_identity_id: str,
        environment_id: str,
        request_context: Dict[str, Any],
    ) -> LedgerAppendResult:
        target_id = str(revoked_artifact_id).strip()
        reason = str(revocation_reason).strip()
        env = str(environment_id)
        if not target_id:
            return LedgerAppendResult(ok=False, record=None, reason_code="REVOCATION_TARGET_REQUIRED")
        if not reason:
            return LedgerAppendResult(ok=False, record=None, reason_code="REVOCATION_REASON_REQUIRED")

        target = self.lookup_by_artifact_id(target_id)
        if target is None:
            return LedgerAppendResult(ok=False, record=None, reason_code="REVOCATION_TARGET_NOT_FOUND")
        if str(target.get("environment_id", "")) != env:
            return LedgerAppendResult(ok=False, record=None, reason_code="REVOCATION_ENVIRONMENT_MISMATCH")
        if self.is_artifact_revoked(target_id):
            return LedgerAppendResult(ok=False, record=None, reason_code="REVOCATION_ALREADY_REVOKED")

        records = self._read_records()
        transition_key = _digest(
            {
                "record_type": _RECORD_TYPE_REVOCATION,
                "revoked_artifact_id": target_id,
                "environment_id": env,
            }
        )
        if self.has_transition_key(transition_key):
            return LedgerAppendResult(ok=False, record=None, reason_code="REVOCATION_DUPLICATE")

        payload = {
            "contract_name": REVOCATION_CONTRACT_NAME,
            "revoked_artifact_id": target_id,
            "revocation_reason": reason,
            "issuer_identity_id": str(issuer_identity_id),
            "environment_id": env,
            "request_context": dict(request_context or {}),
            "execution_enabled": False,
            "authority_guarantees": _authority_guarantees(),
            "immutability_guarantees": {
                "append_only": True,
                "mutable_after_write": False,
                "overwrite_allowed": False,
                "delete_allowed": False,
            },
        }
        payload["input_digest"] = _digest(payload)
        now = _utc_now_iso()
        record = {
            "record_type": _RECORD_TYPE_REVOCATION,
            "phase_id": int(target.get("phase_id", 0)),
            "contract_name": REVOCATION_CONTRACT_NAME,
            "revocation_id": self._next_revocation_id(records),
            "revoked_artifact_id": target_id,
            "revocation_reason": reason,
            "revoked_at": now,
            "issued_at": now,
            "issuer_identity_id": str(issuer_identity_id),
            "environment_id": env,
            "input_digest": str(payload["input_digest"]),
            "transition_key": transition_key,
            "artifact": payload,
        }
        result = self._append_record(record)
        if not result.ok:
            return result
        return LedgerAppendResult(ok=True, record=result.record, reason_code="REVOKED")

    def append_supersession_record(
        self,
        *,
        superseded_artifact_id: str,
        replacement_artifact_id: str,
        issuer_identity_id: str,
        environment_id: str,
        request_context: Dict[str, Any],
    ) -> LedgerAppendResult:
        old_id = str(superseded_artifact_id).strip()
        new_id = str(replacement_artifact_id).strip()
        env = str(environment_id)
        if not old_id or not new_id:
            return LedgerAppendResult(ok=False, record=None, reason_code="SUPERSESSION_ARTIFACT_IDS_REQUIRED")
        if old_id == new_id:
            return LedgerAppendResult(ok=False, record=None, reason_code="SUPERSESSION_SELF_REFERENCE")

        old_record = self.lookup_by_artifact_id(old_id)
        if old_record is None:
            return LedgerAppendResult(ok=False, record=None, reason_code="SUPERSESSION_OLD_NOT_FOUND")
        new_record = self.lookup_by_artifact_id(new_id)
        if new_record is None:
            return LedgerAppendResult(ok=False, record=None, reason_code="SUPERSESSION_REPLACEMENT_NOT_FOUND")
        if str(old_record.get("environment_id", "")) != env or str(new_record.get("environment_id", "")) != env:
            return LedgerAppendResult(ok=False, record=None, reason_code="SUPERSESSION_ENVIRONMENT_MISMATCH")
        if not self.is_artifact_revoked(old_id):
            return LedgerAppendResult(ok=False, record=None, reason_code="SUPERSESSION_OLD_NOT_REVOKED")
        if self.is_artifact_revoked(new_id):
            return LedgerAppendResult(ok=False, record=None, reason_code="SUPERSESSION_REPLACEMENT_REVOKED")
        old_phase = int(old_record.get("phase_id", 0))
        new_phase = int(new_record.get("phase_id", 0))
        if _phase_class(old_phase) != _phase_class(new_phase):
            return LedgerAppendResult(ok=False, record=None, reason_code="SUPERSESSION_PHASE_CLASS_MISMATCH")
        if self.get_supersession_replacement(old_id) is not None:
            return LedgerAppendResult(ok=False, record=None, reason_code="SUPERSESSION_ALREADY_EXISTS")

        records = self._read_records()
        transition_key = _digest(
            {
                "record_type": _RECORD_TYPE_SUPERSESSION,
                "superseded_artifact_id": old_id,
                "replacement_artifact_id": new_id,
                "environment_id": env,
            }
        )
        if self.has_transition_key(transition_key):
            return LedgerAppendResult(ok=False, record=None, reason_code="SUPERSESSION_DUPLICATE")

        payload = {
            "contract_name": SUPERSESSION_CONTRACT_NAME,
            "superseded_artifact_id": old_id,
            "replacement_artifact_id": new_id,
            "issuer_identity_id": str(issuer_identity_id),
            "environment_id": env,
            "request_context": dict(request_context or {}),
            "execution_enabled": False,
            "authority_guarantees": _authority_guarantees(),
            "immutability_guarantees": {
                "append_only": True,
                "mutable_after_write": False,
                "overwrite_allowed": False,
                "delete_allowed": False,
            },
        }
        payload["input_digest"] = _digest(payload)
        now = _utc_now_iso()
        record = {
            "record_type": _RECORD_TYPE_SUPERSESSION,
            "phase_id": old_phase,
            "contract_name": SUPERSESSION_CONTRACT_NAME,
            "supersession_id": self._next_supersession_id(records),
            "superseded_artifact_id": old_id,
            "replacement_artifact_id": new_id,
            "superseded_at": now,
            "issued_at": now,
            "issuer_identity_id": str(issuer_identity_id),
            "environment_id": env,
            "input_digest": str(payload["input_digest"]),
            "transition_key": transition_key,
            "artifact": payload,
        }
        result = self._append_record(record)
        if not result.ok:
            return result
        return LedgerAppendResult(ok=True, record=result.record, reason_code="SUPERSEDED")


def build_receipt_envelope(record: Dict[str, Any]) -> Dict[str, Any]:
    record_type = str(record.get("record_type", _RECORD_TYPE_ISSUANCE))
    refs: List[str] = []
    if record_type == _RECORD_TYPE_ISSUANCE:
        refs = [str(item) for item in record.get("lineage_refs", []) if isinstance(item, str)]
    elif record_type == _RECORD_TYPE_REVOCATION:
        target = str(record.get("revoked_artifact_id", "")).strip()
        if target:
            refs = [target]
    elif record_type == _RECORD_TYPE_SUPERSESSION:
        old_id = str(record.get("superseded_artifact_id", "")).strip()
        new_id = str(record.get("replacement_artifact_id", "")).strip()
        refs = [item for item in (old_id, new_id) if item]

    artifact_id = (
        str(record.get("artifact_id", "")).strip()
        or str(record.get("revocation_id", "")).strip()
        or str(record.get("supersession_id", "")).strip()
    )
    return {
        "type": "receipt",
        "artifact_id": artifact_id,
        "phase_id": int(record.get("phase_id", 0)),
        "contract_name": str(record.get("contract_name", "")),
        "issued_at": str(record.get("issued_at", "")),
        "lineage_summary": {
            "upstream_artifact_ids": refs,
            "lineage_count": len(refs),
            "environment_id": str(record.get("environment_id", "")),
        },
    }
