from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import shlex

from v2.core import evidence as evidence_store
from v2.core.capability_contracts import load_contract
from v2.core.contracts.loader import ContractViolation
from v2.core.failure_modes import evaluate_failure_modes, RuntimeContext
from v2.core.plans_hamp import get_plan, Plan
from v2.core.task_graph import TaskNode
from v2.core.causal_trace import explain_causal_chain

_V2_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class SimulationResult:
    status: str  # allowed | blocked | unknown
    reasons: List[str] = field(default_factory=list)
    required_evidence: List[str] = field(default_factory=list)
    required_capabilities: List[str] = field(default_factory=list)
    triggered_failure_modes: List[str] = field(default_factory=list)
    hypothetical_outcomes: List[str] = field(default_factory=list)


def simulate_action(
    task_id: Optional[str],
    plan_id: Optional[str],
    step_id: Optional[str],
    proposed_action: str,
    now: datetime,
) -> SimulationResult:
    reasons: List[str] = []
    required_evidence: List[str] = []
    required_capabilities: List[str] = []
    triggered_failure_modes: List[str] = []
    hypothetical_outcomes: List[str] = []

    action_text = proposed_action.strip()

    plan_error: Optional[str] = None
    step_action = None
    if plan_id:
        try:
            plan = get_plan(plan_id)
        except ContractViolation as exc:
            plan_error = f"plan not found: {exc}"
            plan = None
        if plan:
            if not plan.approved:
                plan_error = "plan not approved"
            if step_id:
                step_matches = [step for step in plan.steps if step.step_id == step_id]
                if not step_matches:
                    plan_error = "step not found"
                else:
                    step_action = step_matches[0]
                    if plan.steps and plan.steps[0].step_id != step_id:
                        plan_error = "step order violation"
            else:
                if not plan.steps:
                    plan_error = "plan has no steps"
                else:
                    step_action = plan.steps[0]

        if step_action:
            action_text = step_action.description
            required_evidence.extend(step_action.required_evidence)
            if step_action.required_capability:
                required_capabilities.append(step_action.required_capability)

    if not required_evidence:
        required_evidence.extend(_extract_required_evidence(action_text))

    if not required_capabilities:
        capability = _extract_capability(action_text)
        if capability:
            required_capabilities.append(capability)

    contract_errors: List[str] = []
    for capability in required_capabilities:
        try:
            contract = load_contract(capability)
            required_evidence.extend(contract.requires.get("evidence", []))
        except ContractViolation:
            contract_errors.append(f"missing capability contract: {capability}")

    # Evidence validity (M26)
    if evidence_store._CURRENT_TRACE_ID is None:
        return SimulationResult(
            status="unknown",
            reasons=["evidence store not loaded"],
            required_evidence=required_evidence,
            required_capabilities=required_capabilities,
        )
    path = evidence_store._require_path(allow_missing=True)
    if not path or not path.exists():
        return SimulationResult(
            status="unknown",
            reasons=["evidence store missing"],
            required_evidence=required_evidence,
            required_capabilities=required_capabilities,
        )

    for claim in required_evidence:
        status, _ = evidence_store._evaluate_claim_records(claim, now)
        if status == "missing":
            reasons.append(f"missing evidence: {claim}")
        elif status == "stale":
            reasons.append(f"stale evidence: {claim}")
        elif status == "conflict":
            reasons.append(f"conflicting evidence: {claim}")
        elif status == "scope":
            reasons.append(f"invalid evidence scope: {claim}")

    if reasons:
        return SimulationResult(
            status="blocked",
            reasons=reasons,
            required_evidence=required_evidence,
            required_capabilities=required_capabilities,
        )

    # Failure modes (M23)
    task = _simulation_task(task_id, action_text, now)
    failure = evaluate_failure_modes(task, RuntimeContext(trace_id=evidence_store._CURRENT_TRACE_ID, user_input=action_text, via_ops=action_text.startswith("/ops ")))
    if failure.status == "refuse":
        triggered_failure_modes.append(failure.failure_code or "UNKNOWN_FAILURE")
        return SimulationResult(
            status="blocked",
            reasons=[failure.reason or "failure mode refusal"],
            required_evidence=required_evidence,
            required_capabilities=required_capabilities,
            triggered_failure_modes=triggered_failure_modes,
        )

    # Capability contracts (M20)
    if contract_errors:
        return SimulationResult(
            status="blocked",
            reasons=contract_errors,
            required_evidence=required_evidence,
            required_capabilities=required_capabilities,
        )
    for capability in required_capabilities:
        contract = load_contract(capability)
        if contract.requires.get("ops_required") and not action_text.startswith("/ops "):
            return SimulationResult(
                status="blocked",
                reasons=[f"ops required for capability: {capability}"],
                required_evidence=required_evidence,
                required_capabilities=required_capabilities,
            )

    # Plan constraints (M24)
    if plan_error:
        return SimulationResult(
            status="blocked" if "not found" not in plan_error else "unknown",
            reasons=[plan_error],
            required_evidence=required_evidence,
            required_capabilities=required_capabilities,
            triggered_failure_modes=triggered_failure_modes,
            hypothetical_outcomes=hypothetical_outcomes,
        )

    # Causal expectations (M27) read-only
    if task_id:
        if not _causal_trace_exists(evidence_store._CURRENT_TRACE_ID):
            return SimulationResult(
                status="unknown",
                reasons=["causal trace missing"],
                required_evidence=required_evidence,
                required_capabilities=required_capabilities,
            )
        chain = explain_causal_chain(task_id)
        if chain is None:
            return SimulationResult(
                status="unknown",
                reasons=["causal chain incomplete"],
                required_evidence=required_evidence,
                required_capabilities=required_capabilities,
            )
        hypothetical_outcomes.append("causal chain present")

    hypothetical_outcomes.append("action could proceed if executed")
    return SimulationResult(
        status="allowed",
        reasons=reasons,
        required_evidence=required_evidence,
        required_capabilities=required_capabilities,
        triggered_failure_modes=triggered_failure_modes,
        hypothetical_outcomes=hypothetical_outcomes,
    )


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


def _extract_capability(description: str) -> str:
    normalized = description.strip()
    if normalized.startswith("/ops "):
        rest = normalized[len("/ops "):].strip()
        parts = shlex.split(rest)
        if len(parts) == 2:
            verb, _ = parts
            return {
                "restart": "restart_service",
                "start": "start_service",
                "stop": "stop_service",
                "enable": "enable_service",
                "disable": "disable_service",
            }.get(verb, "")
    if normalized.startswith("/exec "):
        command = normalized[len("/exec "):].strip()
        parts = shlex.split(command)
        if parts:
            if parts[0] in ("touch", "mkdir"):
                return "filesystem.write"
            if parts[0] == "rm":
                return "filesystem.delete"
            if parts[0] in ("cat", "ls"):
                return "filesystem.read"
            if parts[0] == "git" and len(parts) == 2 and parts[1] == "push":
                return "git.push"
    return ""


def _simulation_task(task_id: Optional[str], description: str, now: datetime) -> TaskNode:
    return TaskNode(
        task_id=task_id or "simulation",
        parent_id=None,
        description=description,
        status="ready",
        depends_on=[],
        created_at=now,
        updated_at=now,
        block_reason=None,
    )


def _causal_trace_exists(trace_id: Optional[str]) -> bool:
    if not trace_id:
        return False
    path = _V2_ROOT / "state" / "causal_traces" / f"{trace_id}.jsonl"
    return path.exists()
