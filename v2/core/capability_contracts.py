from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List
import yaml

from v2.core.contracts.loader import ContractViolation

_V2_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class CapabilityContract:
    capability: str
    risk_level: str
    requires: dict
    guarantees: List[str]


CAPABILITY_DIR = _V2_ROOT / "contracts" / "capabilities"

_ALLOWED_RISK_LEVELS = {"low", "medium", "high"}


def load_contract(capability: str) -> CapabilityContract:
    if not capability:
        raise ContractViolation("Missing capability name.")
    path = CAPABILITY_DIR / f"{capability}.yaml"
    if not path.exists():
        raise ContractViolation("Missing capability contract.")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ContractViolation("Invalid capability contract.")

    cap_name = raw.get("capability")
    risk_level = raw.get("risk_level")
    requires = raw.get("requires") or {}
    guarantees = raw.get("guarantees") or []

    if cap_name != capability:
        raise ContractViolation("Capability contract name mismatch.")
    if risk_level not in _ALLOWED_RISK_LEVELS:
        raise ContractViolation("Invalid risk level in contract.")
    if not isinstance(requires, dict):
        raise ContractViolation("Invalid requires in contract.")
    if not isinstance(guarantees, list):
        raise ContractViolation("Invalid guarantees in contract.")

    ops_required = requires.get("ops_required")
    evidence = requires.get("evidence")
    if ops_required is None:
        raise ContractViolation("Contract missing requires.ops_required.")
    if evidence is None:
        raise ContractViolation("Contract missing requires.evidence.")
    if not isinstance(evidence, list):
        raise ContractViolation("Contract requires.evidence must be a list.")

    return CapabilityContract(
        capability=capability,
        risk_level=risk_level,
        requires={"ops_required": bool(ops_required), "evidence": list(evidence)},
        guarantees=[str(item) for item in guarantees],
    )


def validate_preconditions(contract: CapabilityContract, context: dict) -> tuple[bool, str]:
    via_ops = bool(context.get("via_ops"))
    trace_id = context.get("trace_id")

    if contract.requires.get("ops_required") and not via_ops:
        return False, "ops_required"

    required_evidence = contract.requires.get("evidence") or []
    if required_evidence:
        if not trace_id:
            return False, "blocked(reason=\"no evidence\")"
        from v2.core.evidence import load_evidence, has_evidence

        load_evidence(trace_id)
        for claim in required_evidence:
            if not has_evidence(claim):
                return False, "blocked(reason=\"no evidence\")"

    return True, ""


def list_capabilities() -> List[str]:
    if not CAPABILITY_DIR.exists():
        return []
    return sorted(path.stem for path in CAPABILITY_DIR.glob("*.yaml"))
