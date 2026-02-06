from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Literal, Optional
import hashlib
import json
import uuid

from core.contracts.loader import ContractViolation
from core.guardrails.invariants import assert_trace_id


EvidenceSourceType = Literal["command", "file", "test", "observation", "introspection"]
EvidenceScope = Literal["host", "service", "container", "file", "network"]


@dataclass
class Evidence:
    evidence_id: str
    claim: str
    source_type: EvidenceSourceType
    source_ref: str
    content_hash: str
    timestamp: datetime
    ttl_seconds: Optional[int] = None
    expires_at: Optional[datetime] = None
    scope: Optional[EvidenceScope] = None
    confidence: Optional[float] = None

    def to_dict(self) -> dict:
        payload = {
            "evidence_id": self.evidence_id,
            "claim": self.claim,
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "content_hash": self.content_hash,
            "timestamp": _dt_to_iso(self.timestamp),
        }
        if self.ttl_seconds is not None:
            payload["ttl_seconds"] = self.ttl_seconds
        if self.expires_at is not None:
            payload["expires_at"] = _dt_to_iso(self.expires_at)
        if self.scope is not None:
            payload["scope"] = self.scope
        if self.confidence is not None:
            payload["confidence"] = self.confidence
        return payload

    @classmethod
    def from_dict(cls, data: dict) -> "Evidence":
        return cls(
            evidence_id=str(data["evidence_id"]),
            claim=str(data["claim"]),
            source_type=_coerce_source_type(data["source_type"]),
            source_ref=str(data["source_ref"]),
            content_hash=str(data["content_hash"]),
            timestamp=_dt_from_iso(data["timestamp"]),
            ttl_seconds=int(data["ttl_seconds"]) if data.get("ttl_seconds") is not None else None,
            expires_at=_dt_from_iso(data["expires_at"]) if data.get("expires_at") else None,
            scope=_coerce_scope(data["scope"]) if data.get("scope") else None,
            confidence=float(data["confidence"]) if data.get("confidence") is not None else None,
        )


EVIDENCE_DIR = Path("v2/state/evidence")
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

_CURRENT_TRACE_ID: Optional[str] = None


ALLOWED_SOURCE_TYPES: set[str] = {"command", "file", "test", "observation", "introspection"}
ALLOWED_SCOPES: set[str] = {"host", "service", "container", "file", "network"}

DEFAULT_TTL_BY_SOURCE: dict[str, int] = {
    "introspection": 300,
    "command": 300,
    "file": 3600,
    "test": 3600,
    "observation": 60,
}

CONFIDENCE_SINGLE = 0.5
CONFIDENCE_MULTI = 0.8


def load_evidence(trace_id: str) -> Path:
    assert_trace_id(trace_id)
    global _CURRENT_TRACE_ID
    _CURRENT_TRACE_ID = trace_id
    path = _evidence_path(trace_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()
    try:
        from core.causal_trace import load_trace

        load_trace(trace_id)
    except Exception:
        pass
    return path


def record_evidence(
    claim: str,
    source_type: str,
    source_ref: str,
    raw_content: str,
    ttl_seconds: Optional[int] = None,
    scope: Optional[str] = None,
) -> Evidence:
    if not claim:
        raise ValueError("Claim is required.")
    if not source_ref:
        raise ValueError("source_ref is required.")
    if raw_content is None:
        raise ValueError("raw_content is required.")

    path = _require_path()
    evidence = Evidence(
        evidence_id=str(uuid.uuid4()),
        claim=claim,
        source_type=_coerce_source_type(source_type),
        source_ref=source_ref,
        content_hash=_hash_content(raw_content),
        timestamp=_now(),
        ttl_seconds=_default_ttl(source_type, ttl_seconds),
        expires_at=None,
        scope=_coerce_scope(scope) if scope else _scope_from_claim(claim),
        confidence=CONFIDENCE_SINGLE,
    )
    evidence = _apply_expiry(evidence)
    _append_line(path, evidence.to_dict())
    try:
        from core.causal_trace import create_node

        create_node(
            node_type="EVIDENCE",
            description=claim,
            related_task_id=None,
            related_plan_id=None,
            related_step_id=None,
        )
    except Exception:
        pass
    return evidence


def has_evidence(claim: str) -> bool:
    if not claim:
        raise ValueError("Claim is required.")
    now = _now()
    return get_best_evidence_for_claim(claim, now) is not None


def list_evidence(claim: str) -> List[Evidence]:
    if not claim:
        raise ValueError("Claim is required.")
    path = _require_path(allow_missing=True)
    if not path or not path.exists():
        return []
    return [record for record in _iter_records(path) if record.claim == claim]


def assert_claim_known(claim: str) -> None:
    if not has_evidence(claim):
        raise ContractViolation("blocked(reason=\"no evidence\")")


def is_evidence_valid(evidence: Evidence, now: datetime) -> bool:
    ttl = evidence.ttl_seconds if evidence.ttl_seconds is not None else _default_ttl(evidence.source_type, None)
    expires_at = evidence.expires_at or (evidence.timestamp + timedelta(seconds=ttl))
    return now <= expires_at


def get_best_evidence_for_claim(claim: str, now: datetime) -> Optional[Evidence]:
    status, records = _evaluate_claim_records(claim, now)
    if status != "ok" or not records:
        return None
    latest = max(records, key=lambda rec: rec.timestamp)
    confidence = CONFIDENCE_MULTI if len(records) > 1 else CONFIDENCE_SINGLE
    return Evidence(
        evidence_id=latest.evidence_id,
        claim=latest.claim,
        source_type=latest.source_type,
        source_ref=latest.source_ref,
        content_hash=latest.content_hash,
        timestamp=latest.timestamp,
        ttl_seconds=latest.ttl_seconds,
        expires_at=latest.expires_at,
        scope=latest.scope,
        confidence=confidence,
    )


def needs_revalidation(claim: str, now: datetime) -> bool:
    return get_best_evidence_for_claim(claim, now) is None


def confidence_for_claim(claim: str, now: datetime) -> float:
    status, records = _evaluate_claim_records(claim, now)
    if status != "ok" or not records:
        return 0.0
    return CONFIDENCE_MULTI if len(records) > 1 else CONFIDENCE_SINGLE


def _evidence_path(trace_id: str) -> Path:
    return EVIDENCE_DIR / f"{trace_id}.jsonl"


def _require_path(allow_missing: bool = False) -> Optional[Path]:
    if not _CURRENT_TRACE_ID:
        raise RuntimeError("Evidence trace not loaded.")
    path = _evidence_path(_CURRENT_TRACE_ID)
    if allow_missing:
        return path
    if not path.exists():
        raise RuntimeError("Evidence store not initialized.")
    return path


def _append_line(path: Path, payload: dict) -> None:
    line = json.dumps(payload, sort_keys=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _iter_records(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_num, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid evidence record at line {line_num}.") from exc
            if not isinstance(data, dict):
                raise ValueError(f"Invalid evidence record at line {line_num}.")
            yield Evidence.from_dict(data)


def _hash_content(raw_content: str) -> str:
    return hashlib.sha256(raw_content.encode("utf-8")).hexdigest()


def _coerce_source_type(source_type: str) -> EvidenceSourceType:
    if source_type not in ALLOWED_SOURCE_TYPES:
        raise ValueError(f"Invalid source_type: {source_type}")
    return source_type  # type: ignore[return-value]


def _coerce_scope(scope: str) -> EvidenceScope:
    if scope not in ALLOWED_SCOPES:
        raise ValueError(f"Invalid scope: {scope}")
    return scope  # type: ignore[return-value]


def _scope_from_claim(claim: str) -> EvidenceScope:
    lowered = claim.lower().strip()
    if lowered.startswith("host."):
        return "host"
    if lowered.startswith("services."):
        return "service"
    if lowered.startswith("containers."):
        return "container"
    if lowered.startswith("filesystem."):
        return "file"
    if lowered.startswith("network."):
        return "network"
    return "host"


def _default_ttl(source_type: str, ttl_seconds: Optional[int]) -> int:
    if ttl_seconds is not None:
        return int(ttl_seconds)
    return DEFAULT_TTL_BY_SOURCE.get(source_type, 300)


def _apply_expiry(evidence: Evidence) -> Evidence:
    ttl = evidence.ttl_seconds if evidence.ttl_seconds is not None else _default_ttl(evidence.source_type, None)
    expires_at = evidence.timestamp + timedelta(seconds=ttl)
    return Evidence(
        evidence_id=evidence.evidence_id,
        claim=evidence.claim,
        source_type=evidence.source_type,
        source_ref=evidence.source_ref,
        content_hash=evidence.content_hash,
        timestamp=evidence.timestamp,
        ttl_seconds=ttl,
        expires_at=expires_at,
        scope=evidence.scope,
        confidence=evidence.confidence,
    )


def _evaluate_claim_records(claim: str, now: datetime) -> tuple[str, List[Evidence]]:
    records = list_evidence(claim)
    if not records:
        return "missing", []
    expected_scope = _scope_from_claim(claim)
    valid_records: List[Evidence] = []
    for record in records:
        scope = record.scope or _scope_from_claim(record.claim)
        if scope != expected_scope:
            return "scope", []
        record_with_expiry = _apply_expiry(record) if record.expires_at is None else record
        if not is_evidence_valid(record_with_expiry, now):
            continue
        valid_records.append(record_with_expiry)
    if not valid_records:
        return "stale", []
    hashes = {record.content_hash for record in valid_records}
    if len(hashes) > 1:
        return "conflict", []
    return "ok", valid_records


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dt_to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _dt_from_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
