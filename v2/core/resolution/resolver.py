from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from core.resolution.outcomes import ResolutionOutcome
from core.resolution.rules import (
    EvidenceBundle,
    InspectionMeta,
    ResolutionTask,
    RuleContext,
    apply_rules,
    extract_task_scope,
)


@dataclass(frozen=True)
class ResolutionResult:
    outcome: ResolutionOutcome

    def to_dict(self) -> dict:
        return {"outcome": self.outcome.to_dict()}


def build_evidence_bundle_from_snapshot(snapshot) -> Tuple[EvidenceBundle, InspectionMeta]:
    services = getattr(snapshot, "services", None) or {}
    containers = getattr(snapshot, "containers", None) or {}
    network = getattr(snapshot, "network", None) or {}
    evidence = EvidenceBundle(
        services_units=list(services.get("systemd_units", []) or []),
        services_processes=list(services.get("process_list", []) or []),
        services_listening_ports=list(services.get("listening_ports", []) or []),
        containers=list(containers.get("containers", []) or []),
        network_listening_sockets=list(network.get("listening_sockets", []) or []),
    )
    inspected_at = None
    if getattr(snapshot, "collected_at", None) is not None:
        inspected_at = snapshot.collected_at.isoformat()
    meta = InspectionMeta(
        completed=True,
        source="introspection",
        inspected_at=inspected_at,
        scope=["services", "containers", "network", "filesystem"],
    )
    return evidence, meta


def empty_evidence_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        services_units=[],
        services_processes=[],
        services_listening_ports=[],
        containers=[],
        network_listening_sockets=[],
    )


def build_task(task_id: str, description: str) -> ResolutionTask:
    return ResolutionTask(task_id=task_id, description=description, scope=extract_task_scope(description))


def resolve_task(task: ResolutionTask, evidence: EvidenceBundle, inspection: InspectionMeta) -> ResolutionResult:
    context = RuleContext(task=task, evidence=evidence, inspection=inspection)
    outcome = apply_rules(context)
    if outcome is None:
        raise RuntimeError("Resolver returned no outcome.")
    if not isinstance(outcome, ResolutionOutcome):
        raise RuntimeError("Resolver returned invalid outcome type.")
    if outcome.outcome_type not in ("RESOLVED", "BLOCKED", "ESCALATE", "FOLLOW_UP_INSPECTION"):
        raise RuntimeError("Resolver returned invalid outcome value.")
    return ResolutionResult(outcome=outcome)
