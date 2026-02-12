from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List
import shlex

from v2.core.contracts.loader import ContractViolation
from v2.core.task_graph import TaskNode
from v2.core.evidence import load_evidence, _evaluate_claim_records


@dataclass(frozen=True)
class RuntimeContext:
    trace_id: str
    user_input: str
    via_ops: bool
    evidence_ttl_seconds: int = 3600


@dataclass(frozen=True)
class FailureResult:
    status: str
    failure_code: Optional[str]
    reason: Optional[str]


FAILURE_CODES = {
    "EVIDENCE_MISSING",
    "EVIDENCE_CONFLICT",
    "EVIDENCE_STALE",
    "EVIDENCE_SCOPE",
    "CAPABILITY_MISSING",
    "CAPABILITY_AMBIGUOUS",
    "CAPABILITY_INVALID",
    "CAPABILITY_GUARANTEES",
    "SCOPE_WILDCARD",
    "SCOPE_RECURSIVE",
    "SCOPE_AMBIGUOUS",
    "IRREVERSIBLE_NO_ACK",
    "AUTHORITY_BOUNDARY",
}


def evaluate_failure_modes(task: TaskNode, context: RuntimeContext) -> FailureResult:
    load_evidence(context.trace_id)

    capability, action_text, via_ops = _extract_capability(task.description)
    contract = None
    if capability:
        contract_result = _load_contract_for_failure(capability)
        if contract_result[0] == "refuse":
            return FailureResult(status="refuse", failure_code=contract_result[1], reason=contract_result[2])
        contract = contract_result[3]

        if contract and not contract.get("guarantees"):
            return FailureResult(
                status="refuse",
                failure_code="CAPABILITY_GUARANTEES",
                reason="Refusing to act: capability guarantees are underspecified.",
            )

    required_evidence = _extract_required_evidence(task.description)
    if contract:
        required_evidence.extend(contract.get("requires", {}).get("evidence", []))

    if required_evidence:
        evidence_result = _evaluate_evidence(required_evidence, context.evidence_ttl_seconds)
        if evidence_result:
            return evidence_result

    scope_result = _evaluate_scope_uncertainty(task.description)
    if scope_result:
        return scope_result

    if _is_destructive(task.description) and not _has_acknowledgment(context.user_input):
        return FailureResult(
            status="refuse",
            failure_code="IRREVERSIBLE_NO_ACK",
            reason="Refusing to act: destructive action without explicit acknowledgment.",
        )

    authority_result = _evaluate_authority_boundary(task.description)
    if authority_result:
        return authority_result

    return FailureResult(status="pass", failure_code=None, reason=None)


def _extract_required_evidence(description: str) -> List[str]:
    normalized = description.strip()
    evidence = []
    if normalized.lower().startswith("claim:"):
        claim = normalized.split(":", 1)[1].strip()
        if claim:
            evidence.append(claim)
    if "evidence:" in normalized.lower():
        _, tail = normalized.split("evidence:", 1)
        for item in tail.split(","):
            claim = item.strip()
            if claim:
                evidence.append(claim)
    return evidence


def _extract_capability(description: str) -> tuple[str, str, bool]:
    normalized = description.strip()
    if normalized.startswith("/ops "):
        rest = normalized[len("/ops "):].strip()
        parts = shlex.split(rest)
        if len(parts) == 2:
            verb, target = parts
            capability = {
                "restart": "restart_service",
                "start": "start_service",
                "stop": "stop_service",
                "enable": "enable_service",
                "disable": "disable_service",
            }.get(verb, "")
            return capability, f"{verb} {target}", True
    if normalized.startswith("/exec "):
        command = normalized[len("/exec "):].strip()
        parts = shlex.split(command)
        if parts:
            if parts[0] in ("touch", "mkdir"):
                return "filesystem.write", command, False
            if parts[0] == "rm":
                return "filesystem.delete", command, False
            if parts[0] in ("cat", "ls"):
                return "filesystem.read", command, False
            if parts[0] == "git" and len(parts) == 2 and parts[1] == "push":
                return "git.push", command, False
    return "", "", False


def _load_contract_for_failure(capability: str):
    from v2.core.capability_contracts import CAPABILITY_DIR

    matches = []
    invalid = False
    for path in CAPABILITY_DIR.glob("*.yaml"):
        try:
            data = path.read_text(encoding="utf-8")
        except Exception:
            invalid = True
            continue
        try:
            import yaml

            parsed = yaml.safe_load(data)
        except Exception:
            invalid = True
            continue
        if not isinstance(parsed, dict):
            invalid = True
            continue
        if parsed.get("capability") == capability:
            matches.append(parsed)

    if len(matches) == 0:
        return ("refuse", "CAPABILITY_MISSING", "Refusing to act: capability contract missing.", None)
    if len(matches) > 1:
        return ("refuse", "CAPABILITY_AMBIGUOUS", "Refusing to act: capability contract is ambiguous.", None)

    contract = matches[0]
    if not _valid_contract_schema(contract):
        return ("refuse", "CAPABILITY_INVALID", "Refusing to act: capability contract invalid.", None)

    return ("pass", None, None, contract)


def _valid_contract_schema(contract: dict) -> bool:
    if contract.get("risk_level") not in ("low", "medium", "high"):
        return False
    requires = contract.get("requires")
    if not isinstance(requires, dict):
        return False
    if "ops_required" not in requires or "evidence" not in requires:
        return False
    if not isinstance(requires.get("evidence"), list):
        return False
    guarantees = contract.get("guarantees")
    if guarantees is None or not isinstance(guarantees, list):
        return False
    return True


def _evaluate_evidence(required_claims: List[str], ttl_seconds: int) -> Optional[FailureResult]:
    now = datetime.now(timezone.utc)
    for claim in required_claims:
        status, _ = _evaluate_claim_records(claim, now)
        if status == "missing":
            return FailureResult(
                status="refuse",
                failure_code="EVIDENCE_MISSING",
                reason=f"Refusing to act: evidence for claim {claim} is missing or inconsistent.",
            )
        if status == "conflict":
            return FailureResult(
                status="refuse",
                failure_code="EVIDENCE_CONFLICT",
                reason=f"Refusing to act: evidence for claim {claim} is missing or inconsistent.",
            )
        if status == "stale":
            return FailureResult(
                status="refuse",
                failure_code="EVIDENCE_STALE",
                reason=f"Refusing to act: evidence for claim {claim} is stale.",
            )
        if status == "scope":
            return FailureResult(
                status="refuse",
                failure_code="EVIDENCE_SCOPE",
                reason=f"Refusing to act: evidence for claim {claim} has invalid scope.",
            )
    return None


def _evaluate_scope_uncertainty(description: str) -> Optional[FailureResult]:
    normalized = description.strip()
    if not normalized.startswith("/exec "):
        return None
    command = normalized[len("/exec "):].strip()
    parts = shlex.split(command)
    if not parts:
        return None
    for token in parts[1:]:
        if any(ch in token for ch in ("*", "?", "[", "]")):
            return FailureResult(
                status="refuse",
                failure_code="SCOPE_WILDCARD",
                reason="Refusing to act: wildcard path is not allowed.",
            )
    if parts[0] == "rm" and any(flag in parts[1:] for flag in ("-r", "-rf", "--recursive")):
        return FailureResult(
            status="refuse",
            failure_code="SCOPE_RECURSIVE",
            reason="Refusing to act: recursive delete is not allowed.",
        )
    return None


def _is_destructive(description: str) -> bool:
    normalized = description.strip()
    if normalized.startswith("/exec "):
        command = normalized[len("/exec "):].strip()
        parts = shlex.split(command)
        if not parts:
            return False
        return parts[0] in ("rm", "shred", "mkfs", "dd")
    return False


def _has_acknowledgment(user_input: str) -> bool:
    lowered = user_input.lower()
    return "acknowledge" in lowered or lowered.startswith("ack:")


def _evaluate_authority_boundary(description: str) -> Optional[FailureResult]:
    normalized = description.strip()
    if normalized.startswith("/exec "):
        command = normalized[len("/exec "):].strip()
        parts = shlex.split(command)
        for token in parts[1:]:
            if token.startswith("/"):
                if token.startswith(("/etc", "/var", "/usr", "/bin", "/sbin", "/root")):
                    return FailureResult(
                        status="refuse",
                        failure_code="AUTHORITY_BOUNDARY",
                        reason="Refusing to act: protected resource targeted.",
                    )
    if normalized.startswith("/ops "):
        rest = normalized[len("/ops "):].strip()
        if any(ch in rest for ch in ("@", ":")):
            return FailureResult(
                status="refuse",
                failure_code="AUTHORITY_BOUNDARY",
                reason="Refusing to act: ambiguous or remote target.",
            )
    return None
