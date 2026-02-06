from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional
import hashlib
import json
import uuid

from core.contracts.loader import ContractViolation
from core.guardrails.invariants import assert_trace_id


EvidenceSourceType = Literal["command", "file", "test", "observation"]


@dataclass
class Evidence:
    evidence_id: str
    claim: str
    source_type: EvidenceSourceType
    source_ref: str
    content_hash: str
    timestamp: datetime

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "claim": self.claim,
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "content_hash": self.content_hash,
            "timestamp": _dt_to_iso(self.timestamp),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Evidence":
        return cls(
            evidence_id=str(data["evidence_id"]),
            claim=str(data["claim"]),
            source_type=_coerce_source_type(data["source_type"]),
            source_ref=str(data["source_ref"]),
            content_hash=str(data["content_hash"]),
            timestamp=_dt_from_iso(data["timestamp"]),
        )


EVIDENCE_DIR = Path("v2/state/evidence")
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

_CURRENT_TRACE_ID: Optional[str] = None


ALLOWED_SOURCE_TYPES: set[str] = {"command", "file", "test", "observation"}


def load_evidence(trace_id: str) -> Path:
    assert_trace_id(trace_id)
    global _CURRENT_TRACE_ID
    _CURRENT_TRACE_ID = trace_id
    path = _evidence_path(trace_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()
    return path


def record_evidence(
    claim: str,
    source_type: str,
    source_ref: str,
    raw_content: str,
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
    )
    _append_line(path, evidence.to_dict())
    return evidence


def has_evidence(claim: str) -> bool:
    if not claim:
        raise ValueError("Claim is required.")
    path = _require_path(allow_missing=True)
    if not path or not path.exists():
        return False
    for record in _iter_records(path):
        if record.claim == claim:
            return True
    return False


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
