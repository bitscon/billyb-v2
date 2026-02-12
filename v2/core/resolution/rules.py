from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import re

from v2.core.resolution.outcomes import ResolutionOutcome


@dataclass(frozen=True)
class ResolutionTask:
    task_id: str
    description: str
    scope: str


@dataclass(frozen=True)
class EvidenceBundle:
    services_units: List[str]
    services_processes: List[str]
    services_listening_ports: List[str]
    containers: List[Dict[str, str]]
    network_listening_sockets: List[str]


@dataclass(frozen=True)
class InspectionMeta:
    completed: bool
    source: str
    inspected_at: Optional[str]
    scope: List[str]


@dataclass(frozen=True)
class RuleContext:
    task: ResolutionTask
    evidence: EvidenceBundle
    inspection: InspectionMeta


@dataclass(frozen=True)
class EvidenceSignals:
    service_name: str
    running_service_lines: List[str]
    inactive_service_lines: List[str]
    container_matches: List[str]
    process_matches: List[str]
    port_matches: List[int]

    @property
    def has_positive(self) -> bool:
        return bool(self.running_service_lines or self.container_matches or self.port_matches)

    @property
    def has_partial(self) -> bool:
        return bool(self.inactive_service_lines or self.process_matches)

    @property
    def has_conflict(self) -> bool:
        return bool(self.running_service_lines) and bool(self.inactive_service_lines)


_STOP_WORDS = {
    "locate",
    "inspect",
    "find",
    "where",
    "is",
    "where's",
    "check",
    "show",
    "status",
    "running",
    "installed",
    "service",
    "container",
    "on",
    "the",
    "a",
    "an",
    "of",
    "for",
    "to",
    "in",
    "at",
    "barn",
    "host",
    "server",
}

_SERVICE_PORTS: Dict[str, List[int]] = {
    "n8n": [5678],
    "nginx": [80, 443],
    "postgres": [5432],
    "postgresql": [5432],
    "redis": [6379],
    "mysql": [3306],
    "mariadb": [3306],
    "rabbitmq": [5672],
    "grafana": [3000],
    "prometheus": [9090],
    "mongodb": [27017],
    "elasticsearch": [9200],
    "kibana": [5601],
}

_PORT_RE = re.compile(r":(\d{2,5})")


def extract_task_scope(description: str) -> str:
    if "scope:" not in description:
        return "unknown"
    tail = description.split("scope:", 1)[1]
    value = tail.split("]", 1)[0].strip()
    return value or "unknown"


def extract_original_request(description: str) -> str:
    cleaned = description.strip()
    if "[" in cleaned:
        cleaned = cleaned.split("[", 1)[0].strip()
    lowered = cleaned.lower()
    if lowered.startswith("locate/inspect:"):
        return cleaned.split(":", 1)[1].strip()
    if lowered.startswith("action requested:"):
        return cleaned.split(":", 1)[1].strip()
    if lowered.startswith("analyze"):
        return cleaned.split(":", 1)[1].strip()
    return cleaned


def extract_service_query(description: str) -> str:
    base = extract_original_request(description)
    tokens = re.split(r"[^A-Za-z0-9_.-]+", base)
    for token in tokens:
        if not token:
            continue
        lowered = token.lower()
        if lowered in _STOP_WORDS:
            continue
        return token
    return ""


def _normalize_service(name: str) -> str:
    return name.strip().lower()


def _service_variants(name: str) -> List[str]:
    normalized = _normalize_service(name)
    if not normalized:
        return []
    if normalized.endswith(".service"):
        return [normalized, normalized.replace(".service", "")]
    return [normalized, f"{normalized}.service"]


def _match_systemd_units(units: List[str], service: str) -> tuple[List[str], List[str]]:
    running: List[str] = []
    inactive: List[str] = []
    variants = _service_variants(service)
    if not variants:
        return running, inactive
    for line in units:
        lowered = line.lower()
        if not any(variant in lowered for variant in variants):
            continue
        if "inactive" in lowered or "failed" in lowered or "dead" in lowered:
            inactive.append(line)
        elif "running" in lowered or "active" in lowered:
            running.append(line)
        else:
            inactive.append(line)
    return running, inactive


def _match_processes(processes: List[str], service: str) -> List[str]:
    normalized = _normalize_service(service)
    if not normalized:
        return []
    matches = []
    for line in processes:
        if normalized in line.lower():
            matches.append(line)
    return matches


def _match_containers(containers: List[Dict[str, str]], service: str) -> List[str]:
    normalized = _normalize_service(service)
    if not normalized:
        return []
    matches = []
    for container in containers:
        name = (container.get("name") or "").lower()
        if normalized and normalized in name:
            matches.append(container.get("name") or name)
    return matches


def _extract_ports(lines: List[str]) -> List[int]:
    ports: List[int] = []
    for line in lines:
        for match in _PORT_RE.findall(line):
            try:
                ports.append(int(match))
            except ValueError:
                continue
    return ports


def _match_ports(ports: List[int], service: str) -> List[int]:
    normalized = _normalize_service(service)
    if not normalized:
        return []
    known = _SERVICE_PORTS.get(normalized, [])
    return [port for port in ports if port in known]


def build_evidence_signals(context: RuleContext) -> EvidenceSignals:
    service = extract_service_query(context.task.description)
    running, inactive = _match_systemd_units(context.evidence.services_units, service)
    processes = _match_processes(context.evidence.services_processes, service)
    containers = _match_containers(context.evidence.containers, service)
    ports = _extract_ports(context.evidence.services_listening_ports) + _extract_ports(
        context.evidence.network_listening_sockets
    )
    port_matches = _match_ports(ports, service)
    return EvidenceSignals(
        service_name=service,
        running_service_lines=running,
        inactive_service_lines=inactive,
        container_matches=containers,
        process_matches=processes,
        port_matches=port_matches,
    )


def _follow_up_next_step(service: str) -> str:
    normalized = _normalize_service(service)
    if not normalized:
        return "FOLLOW_UP_INSPECTION: provide the exact service or container name to inspect."
    unit = normalized if normalized.endswith(".service") else f"{normalized}.service"
    port_hint = ""
    ports = _SERVICE_PORTS.get(normalized, [])
    if ports:
        port_hint = f"; ss -ltnp | rg ':{ports[0]}'"
    return (
        "FOLLOW_UP_INSPECTION: "
        f"systemctl status {unit}; "
        f"docker ps --filter name={normalized} --format '{{{{.Names}}}}\t{{{{.Ports}}}}'; "
        f"ps -eo pid,comm | rg '{normalized}'"
        f"{port_hint}"
    )


def rule_service_located(context: RuleContext) -> Optional[ResolutionOutcome]:
    signals = build_evidence_signals(context)
    if not signals.has_positive:
        return None

    evidence_bits: List[str] = []
    if signals.running_service_lines:
        evidence_bits.append("running service")
    if signals.container_matches:
        evidence_bits.append("running container")
    if signals.port_matches:
        evidence_bits.append("listening port")

    detail = {
        "service": signals.service_name,
        "evidence": evidence_bits,
        "ports": signals.port_matches,
    }
    message = (
        f"Service '{signals.service_name}' located via "
        + ", ".join(evidence_bits)
        + "."
    )
    return ResolutionOutcome(
        outcome_type="RESOLVED",
        message=message,
        next_step=None,
        rule_id="service_located",
        details=detail,
    )


def rule_service_not_found(context: RuleContext) -> Optional[ResolutionOutcome]:
    signals = build_evidence_signals(context)
    if not context.inspection.completed:
        return None
    if signals.has_positive or signals.has_partial:
        return None
    original_request = extract_original_request(context.task.description)
    message = (
        f"Inspection completed; no evidence of '{signals.service_name}' "
        "in services, containers, or listening ports."
    )
    next_step = f"/ops {original_request}".strip()
    return ResolutionOutcome(
        outcome_type="BLOCKED",
        message=message,
        next_step=next_step,
        rule_id="service_not_found",
        details={"service": signals.service_name},
    )


def rule_ambiguous_evidence(context: RuleContext) -> Optional[ResolutionOutcome]:
    signals = build_evidence_signals(context)
    if not signals.has_partial and not signals.has_conflict:
        return None
    message = (
        f"Evidence for '{signals.service_name}' is ambiguous; "
        "partial indicators detected without a confirmed running service."
    )
    next_step = _follow_up_next_step(signals.service_name)
    return ResolutionOutcome(
        outcome_type="FOLLOW_UP_INSPECTION",
        message=message,
        next_step=next_step,
        rule_id="ambiguous_evidence",
        details={
            "service": signals.service_name,
            "process_matches": signals.process_matches,
            "inactive_service_lines": signals.inactive_service_lines,
        },
    )


def apply_rules(context: RuleContext) -> ResolutionOutcome:
    for rule in (rule_service_located, rule_ambiguous_evidence, rule_service_not_found):
        outcome = rule(context)
        if outcome is not None:
            return outcome
    service = extract_service_query(context.task.description)
    message = "No trusted inspection evidence available to resolve the request."
    return ResolutionOutcome(
        outcome_type="FOLLOW_UP_INSPECTION",
        message=message,
        next_step=_follow_up_next_step(service),
        rule_id="no_evidence",
        details={"service": service},
    )
