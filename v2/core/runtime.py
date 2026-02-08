"""
Updated runtime module for Billy v2.

This version adjusts the BillyRuntime constructor to accept an optional
configuration dictionary and default to an empty dictionary when none is
provided. It also adds the ask() method required by the API layer to
correctly invoke the configured LLM.
"""

import hashlib
import json
import os
import shlex
import socket
import subprocess
import time
import yaml
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

from . import llm_api
from .charter import load_charter
from core.contracts.loader import load_schema, ContractViolation
from core.tool_runner.docker_runner import DockerRunner
from core.trace.file_trace_sink import FileTraceSink
from core.tool_registry.registry import ToolRegistry
from core.tool_registry.loader import ToolLoader
from core.agent.tool_router import ToolRouter
from core.agent.memory_router import MemoryRouter
from core.agent.memory_reader import MemoryReader
from core.agent.plan_router import PlanRouter
from core.agent.approval_router import ApprovalRouter
from core.agent.step_executor import StepExecutor
from core.agent.plan_state import PlanState
from core.memory.file_memory_store import FileMemoryStore
from core.planning.plan import Plan
from core.agent.evaluation_router import EvaluationRouter
from core.evaluation.evaluation import Evaluation
from core.evaluation.synthesizer import EvaluationSynthesizer
from core.agent.promotion_router import PromotionRouter
from core.planning.llm_planner import LLMPlanner
from core.planning.plan_scorer import PlanScorer
from core.planning.plan_validator import PlanValidator
from core.plans.plan_fingerprint import fingerprint
from core.plans.plan_diff import diff_plans
from core.plans.promotion_lock import PromotionLock
from core.plans.plan_history import PlanHistory
from core.plans.rollback import RollbackEngine
from core.tools.capability_registry import CapabilityRegistry
from core.tools.tool_guard import ToolGuard
from core.execution.execution_journal import ExecutionJournal
from core.approval.approval_store import ApprovalStore
from core.approval.approval_flow import ApprovalFlow
from core.autonomy.autonomy_registry import AutonomyRegistry
from core.guardrails.invariants import (
    assert_trace_id,
    assert_no_tool_execution_without_registry,
    assert_explicit_memory_write,
)
from core.validation.plan_validator import PlanValidator
from core.guardrails.output_guard import OutputGuard
from core.resolution.outcomes import M27_CONTRACT_VERSION
try:
    from v2.billy_engineering import detect_engineering_intent, enforce_engineering
    from v2.billy_engineering.enforcement import EngineeringError
except ImportError:
    from billy_engineering import detect_engineering_intent, enforce_engineering
    from billy_engineering.enforcement import EngineeringError

# --- HARD GUARDRAILS (fast stability) ---
FORBIDDEN_IDENTITY_PHRASES = (
    "i'm an ai",
    "i am an ai",
    "i’m an ai",
    "artificial intelligence",
    "chatbot",
    "language model",
    "llm",
    "assistant",
    "conversational ai",
)

# Deterministic fallback identity/purpose (authoritative, no LLM needed)
IDENTITY_FALLBACK = (
    "I am Billy — a digital Farm Hand and Foreman operating inside the Farm."
)


_trace_sink = FileTraceSink()
_docker_runner = DockerRunner(trace_sink=_trace_sink)
_tool_registry = ToolRegistry()
_memory_store = FileMemoryStore(trace_sink=_trace_sink)

_loader = ToolLoader("tools")
for spec in _loader.load_all():
    _tool_registry.register(spec)
_tool_router = ToolRouter(_tool_registry)
_memory_router = MemoryRouter()
_memory_reader = MemoryReader()
_plan_router = PlanRouter()
_approval_router = ApprovalRouter()
_last_plan = None  # TEMP: single-plan memory (no persistence yet)
_step_executor = StepExecutor()
_plan_state = None
_evaluation_router = EvaluationRouter()
_evaluation_synthesizer = EvaluationSynthesizer()
_promotion_router = PromotionRouter()
_last_evaluation = None
_llm_planner = LLMPlanner()
_plan_scorer = PlanScorer()
_plan_validator = PlanValidator()
_output_guard = OutputGuard()
_promotion_lock = PromotionLock()
_previous_plan = None
_previous_fingerprint = None
_plan_history = PlanHistory()
_rollback_engine = RollbackEngine()
_capability_registry = CapabilityRegistry()
_tool_guard = ToolGuard()
_execution_journal = ExecutionJournal()
_approval_store = ApprovalStore()
_approval_flow = ApprovalFlow()
_autonomy_registry = AutonomyRegistry()

_exec_contract_dir = Path("v2/var/execution_contract")
_exec_contract_dir.mkdir(parents=True, exist_ok=True)
_exec_contract_state_path = _exec_contract_dir / "state.json"
_exec_contract_journal_path = _exec_contract_dir / "journal.jsonl"
_pending_exec_proposals: Dict[str, Dict[str, str]] = {}

_ops_contract_dir = Path("v2/var/ops")
_ops_contract_dir.mkdir(parents=True, exist_ok=True)
_ops_state_path = _ops_contract_dir / "state.json"
_ops_journal_path = _ops_contract_dir / "journal.jsonl"
_pending_ops_plans: Dict[str, Dict[str, str]] = {}
_last_inspection: dict = {}
_last_introspection_snapshot: Dict[str, Any] = {}
_last_resolution: Dict[str, Any] = {}

_default_capability_grants = {
    "filesystem.write": {
        "scope": {
            "allowed_paths": ["/home/billyb/"],
            "deny_patterns": [".ssh", ".git"],
        },
        "limits": {
            "max_actions_per_session": 10,
            "max_actions_per_minute": 3,
        },
        "risk_level": "low",
        "require_grant": False,
    },
    "filesystem.read": {
        "scope": {
            "allowed_paths": ["/home/billyb/"],
            "deny_patterns": [".ssh", ".git"],
        },
        "limits": {
            "max_actions_per_session": 20,
            "max_actions_per_minute": 6,
        },
        "risk_level": "low",
        "require_grant": False,
    },
    "filesystem.delete": {
        "scope": {
            "allowed_paths": ["/home/billyb/"],
            "deny_patterns": [".ssh", ".git"],
        },
        "limits": {
            "max_actions_per_session": 5,
            "max_actions_per_minute": 2,
        },
        "risk_level": "medium",
        "require_grant": True,
    },
    "git.push": {
        "scope": {},
        "limits": {
            "max_actions_per_session": 5,
            "max_actions_per_minute": 2,
        },
        "risk_level": "medium",
        "require_grant": True,
    },
}


def _load_exec_contract_state() -> dict:
    if not _exec_contract_state_path.exists():
        return {}
    try:
        with _exec_contract_state_path.open("r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_exec_contract_state(state: dict) -> None:
    with _exec_contract_state_path.open("w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def _next_exec_contract_id() -> str:
    today = datetime.utcnow().strftime("%Y%m%d")
    state = _load_exec_contract_state()
    counters = state.get("counters", {})
    next_num = counters.get(today, 0) + 1
    counters[today] = next_num
    state["counters"] = counters
    _save_exec_contract_state(state)
    return f"exec-{today}-{next_num:03d}"


def _load_ops_state() -> dict:
    if not _ops_state_path.exists():
        return {}
    try:
        with _ops_state_path.open("r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_ops_state(state: dict) -> None:
    with _ops_state_path.open("w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def _next_ops_id() -> str:
    today = datetime.utcnow().strftime("%Y%m%d")
    state = _load_ops_state()
    counters = state.get("counters", {})
    next_num = counters.get(today, 0) + 1
    counters[today] = next_num
    state["counters"] = counters
    _save_ops_state(state)
    return f"ops-{today}-{next_num:03d}"


def _journal_exec_contract(event: str, payload: dict) -> None:
    record = {
        "event": event,
        "payload": payload,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    with _exec_contract_journal_path.open("a") as f:
        f.write(json.dumps(record))
        f.write("\n")


def _journal_ops(event: str, payload: dict) -> None:
    record = {
        "event": event,
        "payload": payload,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    with _ops_journal_path.open("a") as f:
        f.write(json.dumps(record))
        f.write("\n")


def _validate_exec_command(command: str) -> tuple[bool, str]:
    if not command or command.strip() != command:
        return False, "Command must be non-empty and fully explicit"
    if "\n" in command or "\r" in command:
        return False, "Command must be a single line"
    if any(token in command for token in ("&&", "||", ";", "|", "&")):
        return False, "Command chaining is not allowed"
    if any(token in command for token in ("$", "`", "~")):
        return False, "Variables are not allowed"
    try:
        parts = shlex.split(command)
    except ValueError:
        return False, "Command parsing failed"
    if not parts:
        return False, "Command must include an executable"
    if parts[0] in ("sudo", "su"):
        return False, "Privilege escalation is not allowed"
    return True, ""


def _expected_result_for_command(command: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError:
        return "command executed"
    if not parts:
        return "command executed"
    if parts[0] == "touch" and len(parts) >= 2:
        return "empty file created"
    if parts[0] == "rm" and len(parts) >= 2:
        return "file removed"
    if parts[0] == "mkdir":
        return "directory created"
    return "command executed"


def _verify_command_result(command: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError:
        return "no verification rule for command"
    if not parts:
        return "no verification rule for command"
    if parts[0] == "touch" and len(parts) >= 2:
        target = parts[-1]
        if os.path.exists(target):
            return f"file exists at {target}"
        return f"file missing at {target}"
    if parts[0] == "rm" and len(parts) >= 2:
        target = parts[-1]
        if not os.path.exists(target):
            return f"file removed at {target}"
        return f"file still exists at {target}"
    if parts[0] == "mkdir" and len(parts) >= 2:
        target = parts[-1]
        if os.path.isdir(target):
            return f"directory exists at {target}"
        return f"directory missing at {target}"
    return "no verification rule for command"


def _execute_shell_command(command: str, working_dir: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        shlex.split(command),
        cwd=working_dir,
        capture_output=True,
        text=True,
        check=False,
    )


def _get_repo_root() -> Path:
    env_root = os.environ.get("BILLY_REPO_ROOT")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[3]


def _parse_duration_seconds(value: str) -> int | None:
    if not value:
        return None
    try:
        if value.endswith("s"):
            return int(value[:-1])
        if value.endswith("m"):
            return int(value[:-1]) * 60
        if value.endswith("h"):
            return int(value[:-1]) * 3600
        return int(value)
    except ValueError:
        return None


def _requires_barn_inspection(text: str) -> bool:
    lowered = text.lower()
    if lowered.startswith("/"):
        return False
    triggers = [
        "service",
        "daemon",
        "url",
        "installed",
        "running",
        "where is",
        "where's",
        "cmdb",
        "port",
        "listening",
        "systemctl",
        "docker",
        "restart",
        "start",
        "stop",
        "reload",
    ]
    return any(trigger in lowered for trigger in triggers)


def _select_active_task(tasks: dict) -> str | None:
    if not tasks:
        return None
    ordered = sorted(
        tasks.values(),
        key=lambda node: (node.created_at, node.task_id),
    )
    for node in ordered:
        if node.status not in ("done", "failed"):
            return node.task_id
    return ordered[0].task_id


def _extract_required_evidence(description: str) -> list[str]:
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
            capability = _ops_capability_for(verb)
            return capability, f"{verb} {target}", True
    if normalized.startswith("/exec "):
        command = normalized[len("/exec "):].strip()
        action = _classify_shell_action(command, "/")
        if action and action.get("capability"):
            return action.get("capability", ""), command, False
    return "", "", False


def _format_blocker_list(items: list[str]) -> str:
    return ", ".join(items) if items else "none"


def _format_del_response(
    selection: dict,
    active_task: dict,
    next_step: str,
    trace_id: str,
    task_origination: str | None = None,
) -> dict:
    lines = []
    if task_origination:
        lines.append(task_origination.strip())
        lines.append("")
    lines.extend(
        [
            "TASK SELECTION:",
            f"- selected: {selection.get('selected', 'none')}",
            f"- reason: {selection.get('reason', '')}",
            "",
            "ACTIVE TASK:",
            f"- id: {active_task.get('id', 'none')}",
            f"- description: {active_task.get('description', 'none')}",
            f"- status: {active_task.get('status', 'none')}",
            "",
            "NEXT STEP:",
            next_step,
        ]
    )
    response = "\n".join(lines)
    return {
        "final_output": response,
        "tool_calls": [],
        "status": "success",
        "trace_id": trace_id,
    }


def _is_mode_command(text: str) -> bool:
    stripped = text.strip().lower()
    return stripped in ("/plan", "/engineer", "/ops", "/simulate")


def _classify_dto_type(text: str) -> str:
    lowered = text.lower()
    inspection_keywords = (
        "locate",
        "find",
        "where is",
        "where's",
        "check",
        "list",
        "show",
        "status",
        "running",
        "installed",
        "port",
        "logs",
    )
    action_keywords = (
        "restart",
        "start",
        "stop",
        "enable",
        "disable",
        "install",
        "deploy",
        "update",
        "delete",
        "remove",
        "configure",
    )
    analysis_keywords = (
        "why",
        "explain",
        "analyze",
        "what caused",
        "root cause",
    )
    has_action = any(keyword in lowered for keyword in action_keywords)
    has_inspection = any(keyword in lowered for keyword in inspection_keywords)
    has_analysis = any(keyword in lowered for keyword in analysis_keywords)
    if has_action and has_inspection:
        return "action"
    if has_action:
        return "action"
    if has_analysis and not has_action:
        return "analysis"
    return "inspection"


def _dto_description(task_type: str, request: str) -> tuple[str, str]:
    trimmed = request.strip()
    if task_type == "action":
        scope = "mutating"
        prefix = "Action Requested"
    elif task_type == "analysis":
        scope = "read_only"
        prefix = "Analyze"
    else:
        scope = "read_only"
        prefix = "Locate/Inspect"
    description = f"{prefix}: {trimmed} [origin:dto scope:{scope}]"
    return description, scope


def _task_is_inspection(description: str) -> bool:
    normalized = description.strip().lower()
    return normalized.startswith("locate/inspect:")


def _introspection_claim(task_id: str) -> str:
    return f"task:{task_id}:introspection"


def _has_introspection_evidence(task_id: str) -> bool:
    try:
        from core import evidence as evidence_store

        claim = _introspection_claim(task_id)
        result = evidence_store.get_best_evidence_for_claim(claim, datetime.now(timezone.utc))
        return result is not None
    except Exception:
        return False


def _render_introspection_snapshot(snapshot, task_id: str) -> str:
    services = snapshot.services or {}
    containers = snapshot.containers or {}
    network = snapshot.network or {}
    filesystem = snapshot.filesystem or {}
    lines = [
        "INTROSPECTION:",
        f"- services checked: {len(services.get('systemd_units', []))}",
        f"- containers checked: {len(containers.get('containers', []))}",
        f"- listening sockets: {len(network.get('listening_sockets', []))}",
        f"- paths checked: {len(filesystem.get('paths', []))}",
        "",
        "EVIDENCE RECORDED:",
        f"- {_introspection_claim(task_id)}",
    ]
    return "\n".join(lines)


def _render_resolution(outcome) -> str:
    lines = [
        "RESOLUTION:",
        f"- outcome: {outcome.outcome_type}",
        f"- message: {outcome.message}",
    ]
    if outcome.next_step:
        lines.append(f"- next_step: {outcome.next_step}")
    return "\n".join(lines)


def _format_resolution_response(
    selection: dict,
    active_task: dict,
    outcome,
    trace_id: str,
    task_origination: str | None = None,
    snapshot_block: str | None = None,
) -> dict:
    resolution_type = outcome.outcome_type
    if outcome.contract_version != M27_CONTRACT_VERSION:
        raise RuntimeError("Resolution contract version mismatch.")
    next_step = outcome.next_step
    if resolution_type == "RESOLVED":
        next_step = None
    elif resolution_type in ("BLOCKED", "ESCALATE", "FOLLOW_UP_INSPECTION"):
        if not next_step:
            raise RuntimeError("Resolution next_step required.")
    payload = {
        "task_id": active_task.get("id", ""),
        "resolution_type": resolution_type,
        "message": outcome.message,
        "next_step": next_step,
    }
    return {
        "final_output": payload,
        "tool_calls": [],
        "status": "success",
        "trace_id": trace_id,
    }


def _validate_resolution_outcome(outcome) -> None:
    if outcome is None:
        raise RuntimeError("Resolution outcome missing.")
    if isinstance(outcome, (list, tuple)):
        raise RuntimeError("Resolution outcome must be singular.")
    if not hasattr(outcome, "outcome_type"):
        raise RuntimeError("Resolution outcome missing type.")
    outcome_type = getattr(outcome, "outcome_type")
    if outcome_type not in ("RESOLVED", "BLOCKED", "ESCALATE", "FOLLOW_UP_INSPECTION"):
        raise RuntimeError("Resolution outcome invalid type.")
    if not hasattr(outcome, "contract_version"):
        raise RuntimeError("Resolution outcome missing contract version.")
    if outcome.contract_version != M27_CONTRACT_VERSION:
        raise RuntimeError("Resolution contract version mismatch.")


def _canonicalize_value(value):
    if isinstance(value, dict):
        return {key: _canonicalize_value(value[key]) for key in sorted(value.keys())}
    if isinstance(value, list):
        normalized = [_canonicalize_value(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
        )
    return value


def _canonical_fingerprint(payload: dict) -> str:
    canonical = _canonicalize_value(payload)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _evidence_payload_from_bundle(bundle) -> dict:
    return {
        "services_units": list(bundle.services_units),
        "services_processes": list(bundle.services_processes),
        "services_listening_ports": list(bundle.services_listening_ports),
        "containers": list(bundle.containers),
        "network_listening_sockets": list(bundle.network_listening_sockets),
    }


def _resolution_fingerprints(bundle, outcome) -> tuple[str, str]:
    evidence_payload = _evidence_payload_from_bundle(bundle)
    evidence_fp = _canonical_fingerprint(evidence_payload)
    if outcome.outcome_type == "FOLLOW_UP_INSPECTION":
        resolution_fp = _canonical_fingerprint(
            {
                "prior": evidence_fp,
                "delta": outcome.next_step or "",
            }
        )
    else:
        resolution_fp = evidence_fp
    return evidence_fp, resolution_fp


def _find_resolution_record(task_id: str, fingerprint: str | None = None) -> dict | None:
    path = _execution_journal.records_path
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except Exception:
            continue
        payload = record.get("resolution")
        if not payload:
            continue
        if payload.get("task_id") != task_id:
            continue
        if payload.get("terminal") is not True:
            continue
        if payload.get("contract_version") != M27_CONTRACT_VERSION:
            raise RuntimeError("Resolution contract version mismatch in journal.")
        if fingerprint is None or payload.get("evidence_fingerprint") == fingerprint:
            return payload
    return None


def _resolution_record_to_outcome(record: dict):
    from core.resolution.outcomes import ResolutionOutcome

    return ResolutionOutcome(
        outcome_type=record.get("resolution_type"),
        message=record.get("resolution_message", ""),
        next_step=record.get("next_step"),
        contract_version=record.get("contract_version", ""),
    )


def _journal_resolution(
    trace_id: str,
    task_id: str,
    outcome,
    evidence_fingerprint: str,
    linked_task_id: str | None = None,
) -> None:
    if _find_resolution_record(task_id) is not None:
        raise RuntimeError("Resolution already journaled for task.")
    record = _execution_journal.build_resolution_record(
        trace_id=trace_id,
        task_id=task_id,
        resolution_type=outcome.outcome_type,
        resolution_message=outcome.message,
        next_step=outcome.next_step,
        evidence_fingerprint=evidence_fingerprint,
        contract_version=outcome.contract_version,
        terminal=True,
        linked_task_id=linked_task_id,
    )
    _execution_journal.append(record)


def _journal_follow_up_inspection(
    trace_id: str,
    origin_task_id: str,
    new_task_id: str,
    description: str,
) -> None:
    record = _execution_journal.build_inspection_origination_record(
        trace_id=trace_id,
        origin_task_id=origin_task_id,
        new_task_id=new_task_id,
        description=description,
    )
    _execution_journal.append(record)


def _run_deterministic_loop(user_input: str, trace_id: str) -> dict:
    from core.task_graph import load_graph, save_graph, block_task, create_task, update_status
    from core.evidence import has_evidence, load_evidence, record_evidence
    from core.introspection import collect_environment_snapshot, IntrospectionError
    from core.capability_contracts import load_contract, validate_preconditions
    from core.task_selector import select_next_task, SelectionContext
    from core.failure_modes import evaluate_failure_modes, RuntimeContext
    from core.causal_trace import create_node, create_edge, find_latest_node_id, load_trace
    from core.plans_hamp import (
        create_plan,
        approve_plan,
        get_plan,
        find_plans_for_task,
        PlanStep,
    )
    from core.failure_modes import FAILURE_CODES
    from core.resolution.resolver import build_evidence_bundle_from_snapshot, resolve_task, build_task, empty_evidence_bundle
    from core.resolution.rules import InspectionMeta

    load_evidence(trace_id)
    load_trace(trace_id)
    graph = load_graph(trace_id)
    def _link_evidence_to(node_id: str, claims: list[str]) -> None:
        for claim in claims:
            evidence_node_id = find_latest_node_id("EVIDENCE", claim)
            if evidence_node_id:
                create_edge(evidence_node_id, node_id, "caused_by")

    selection = select_next_task(
        list(graph.tasks.values()),
        SelectionContext(
            user_input=user_input,
            trace_id=trace_id,
            via_ops=user_input.strip().startswith("/ops ")
            or user_input.strip().lower().startswith("plan")
            or user_input.strip().upper().startswith("APPROVE PLAN "),
        ),
    )

    task_origination_block = None
    if selection.status == "blocked" and "no tasks" in (selection.reason or "").lower():
        if user_input.strip() and not _is_mode_command(user_input):
            task_type = _classify_dto_type(user_input)
            description, _scope = _dto_description(task_type, user_input)
            created_id = create_task(description)
            update_status(created_id, "ready")
            save_graph(trace_id)
            task_origination_block = "\n".join([
                "TASK ORIGINATION:",
                f"- created: {created_id}",
                f"- type: {task_type}",
                f"- description: {description}",
            ])
            selection = select_next_task(
                list(graph.tasks.values()),
                SelectionContext(
                    user_input=user_input,
                    trace_id=trace_id,
                    via_ops=user_input.strip().startswith("/ops ")
                    or user_input.strip().lower().startswith("plan")
                    or user_input.strip().upper().startswith("APPROVE PLAN "),
                ),
            )
    decision = create_node(
        "DECISION",
        f"task selection: {selection.status}",
        related_task_id=selection.task_id,
    )

    if selection.status == "selected":
        task = graph.tasks[selection.task_id]
        if _task_is_inspection(task.description):
            if not _has_introspection_evidence(task.task_id):
                try:
                    snapshot = collect_environment_snapshot(
                        scope=["services", "containers", "network", "filesystem"]
                    )
                except IntrospectionError as exc:
                    return _format_del_response(
                        {"selected": task.task_id, "reason": selection.reason or ""},
                        {"id": task.task_id, "description": task.description, "status": task.status},
                        "NEXT STEP: none (introspection blocked)",
                        trace_id,
                        task_origination=task_origination_block,
                    )
                record_evidence(
                    claim=_introspection_claim(task.task_id),
                    source_type="introspection",
                    source_ref="m25:task",
                    raw_content=getattr(snapshot, "snapshot_id", "snapshot"),
                )
                evidence_bundle, inspection_meta = build_evidence_bundle_from_snapshot(snapshot)
                task_context = build_task(task.task_id, task.description)
                outcome = resolve_task(task_context, evidence_bundle, inspection_meta).outcome
                _validate_resolution_outcome(outcome)
                _last_introspection_snapshot[task.task_id] = snapshot
                _last_resolution[task.task_id] = outcome
                evidence_fp, resolution_fp = _resolution_fingerprints(evidence_bundle, outcome)
                existing_record = _find_resolution_record(task.task_id, resolution_fp)
                if existing_record is None:
                    other_record = _find_resolution_record(task.task_id)
                    if other_record is not None:
                        raise RuntimeError("Resolution already journaled for task.")
                else:
                    outcome = _resolution_record_to_outcome(existing_record)
                    _validate_resolution_outcome(outcome)
                    return _format_resolution_response(
                        {"selected": task.task_id, "reason": selection.reason or ""},
                        {"id": task.task_id, "description": task.description, "status": task.status},
                        outcome,
                        trace_id,
                        task_origination=task_origination_block,
                        snapshot_block=_render_introspection_snapshot(snapshot, task.task_id),
                    )
                outcome_node = create_node(
                    "OUTCOME",
                    f"{outcome.outcome_type}: {outcome.message}",
                    related_task_id=task.task_id,
                )
                create_edge(decision.node_id, outcome_node.node_id, "caused_by")
                _link_evidence_to(outcome_node.node_id, [_introspection_claim(task.task_id)])
                follow_up_task_id = None
                if outcome.outcome_type == "FOLLOW_UP_INSPECTION" and outcome.next_step:
                    follow_up_description = (
                        f"Locate/Inspect: {outcome.next_step} [origin:resolution scope:read_only]"
                    )
                    follow_up_task_id = create_task(follow_up_description, parent_id=task.task_id)
                    update_status(follow_up_task_id, "ready")
                    save_graph(trace_id)
                _journal_resolution(
                    trace_id,
                    task.task_id,
                    outcome,
                    resolution_fp if outcome.outcome_type == "FOLLOW_UP_INSPECTION" else evidence_fp,
                    linked_task_id=follow_up_task_id,
                )
                if follow_up_task_id is not None and outcome.next_step:
                    _journal_follow_up_inspection(
                        trace_id=trace_id,
                        origin_task_id=task.task_id,
                        new_task_id=follow_up_task_id,
                        description=follow_up_description,
                    )
                return _format_resolution_response(
                    {"selected": task.task_id, "reason": selection.reason or ""},
                    {"id": task.task_id, "description": task.description, "status": task.status},
                    outcome,
                    trace_id,
                    task_origination=task_origination_block,
                    snapshot_block=_render_introspection_snapshot(snapshot, task.task_id),
                )
            outcome = _last_resolution.get(task.task_id)
            snapshot = _last_introspection_snapshot.get(task.task_id)
            if outcome is None and snapshot is not None:
                evidence_bundle, inspection_meta = build_evidence_bundle_from_snapshot(snapshot)
                task_context = build_task(task.task_id, task.description)
                outcome = resolve_task(task_context, evidence_bundle, inspection_meta).outcome
                _validate_resolution_outcome(outcome)
                _last_resolution[task.task_id] = outcome
            if outcome is None:
                task_context = build_task(task.task_id, task.description)
                inspection_meta = InspectionMeta(
                    completed=False,
                    source="introspection",
                    inspected_at=None,
                    scope=[],
                )
                outcome = resolve_task(task_context, empty_evidence_bundle(), inspection_meta).outcome
                _validate_resolution_outcome(outcome)
                _last_resolution[task.task_id] = outcome
            else:
                _validate_resolution_outcome(outcome)
            evidence_bundle = empty_evidence_bundle()
            if snapshot is not None:
                evidence_bundle, _inspection_meta = build_evidence_bundle_from_snapshot(snapshot)
            evidence_fp, resolution_fp = _resolution_fingerprints(evidence_bundle, outcome)
            existing_record = _find_resolution_record(task.task_id, resolution_fp)
            if existing_record is None:
                other_record = _find_resolution_record(task.task_id)
                if other_record is not None:
                    raise RuntimeError("Resolution already journaled for task.")
            else:
                outcome = _resolution_record_to_outcome(existing_record)
                _validate_resolution_outcome(outcome)
                return _format_resolution_response(
                    {"selected": task.task_id, "reason": selection.reason or ""},
                    {"id": task.task_id, "description": task.description, "status": task.status},
                    outcome,
                    trace_id,
                    task_origination=task_origination_block,
                    snapshot_block=_render_introspection_snapshot(snapshot, task.task_id) if snapshot is not None else None,
                )
            outcome_node = create_node(
                "OUTCOME",
                f"{outcome.outcome_type}: {outcome.message}",
                related_task_id=task.task_id,
            )
            create_edge(decision.node_id, outcome_node.node_id, "caused_by")
            _link_evidence_to(outcome_node.node_id, [_introspection_claim(task.task_id)])
            follow_up_task_id = None
            if outcome.outcome_type == "FOLLOW_UP_INSPECTION" and outcome.next_step:
                follow_up_description = (
                    f"Locate/Inspect: {outcome.next_step} [origin:resolution scope:read_only]"
                )
                follow_up_task_id = create_task(follow_up_description, parent_id=task.task_id)
                update_status(follow_up_task_id, "ready")
                save_graph(trace_id)
            _journal_resolution(
                trace_id,
                task.task_id,
                outcome,
                resolution_fp if outcome.outcome_type == "FOLLOW_UP_INSPECTION" else evidence_fp,
                linked_task_id=follow_up_task_id,
            )
            if follow_up_task_id is not None and outcome.next_step:
                _journal_follow_up_inspection(
                    trace_id=trace_id,
                    origin_task_id=task.task_id,
                    new_task_id=follow_up_task_id,
                    description=follow_up_description,
                )
            return _format_resolution_response(
                {"selected": task.task_id, "reason": selection.reason or ""},
                {"id": task.task_id, "description": task.description, "status": task.status},
                outcome,
                trace_id,
                task_origination=task_origination_block,
                snapshot_block=_render_introspection_snapshot(snapshot, task.task_id) if snapshot is not None else None,
            )

    if selection.status == "blocked":
        reason = selection.reason or "No eligible tasks."
        blocker = create_node("BLOCKER", reason, related_task_id=None)
        create_edge(blocker.node_id, decision.node_id, "blocked_by")
        reason_lines = reason.splitlines()
        first_blocker = ""
        for line in reason_lines:
            if line.strip().startswith("- "):
                first_blocker = line.strip()[2:]
                break
        if "missing evidence:" in first_blocker:
            claim = first_blocker.split("missing evidence:", 1)[1].strip()
            _link_evidence_to(blocker.node_id, [claim])
            response = "\n".join(
                [
                    "REFUSAL:",
                    "- code: EVIDENCE_MISSING",
                    f"- reason: Refusing to act: evidence for claim {claim} is missing or inconsistent.",
                    "",
                    "NEXT STEP:",
                    "none (refused by safety rule)",
                ]
            )
            return {
                "final_output": response,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }
        if "conflicting evidence:" in first_blocker:
            claim = first_blocker.split("conflicting evidence:", 1)[1].strip()
            _link_evidence_to(blocker.node_id, [claim])
            response = "\n".join(
                [
                    "REFUSAL:",
                    "- code: EVIDENCE_CONFLICT",
                    f"- reason: Refusing to act: evidence for claim {claim} is missing or inconsistent.",
                    "",
                    "NEXT STEP:",
                    "none (refused by safety rule)",
                ]
            )
            return {
                "final_output": response,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }
        if "missing capability contract" in first_blocker:
            response = "\n".join(
                [
                    "REFUSAL:",
                    "- code: CAPABILITY_MISSING",
                    "- reason: Refusing to act: capability contract missing.",
                    "",
                    "NEXT STEP:",
                    "none (refused by safety rule)",
                ]
            )
            return {
                "final_output": response,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }
        if "capability contract is ambiguous" in first_blocker:
            response = "\n".join(
                [
                    "REFUSAL:",
                    "- code: CAPABILITY_AMBIGUOUS",
                    "- reason: Refusing to act: capability contract is ambiguous.",
                    "",
                    "NEXT STEP:",
                    "none (refused by safety rule)",
                ]
            )
            return {
                "final_output": response,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }
        if "requires /ops:" in first_blocker:
            response = "\n".join(
                [
                    "REFUSAL:",
                    "- code: CAPABILITY_AMBIGUOUS",
                    "- reason: Refusing to act: capability requires /ops context.",
                    "",
                    "NEXT STEP:",
                    "none (refused by safety rule)",
                ]
            )
            return {
                "final_output": response,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }
        next_step = "NEXT STEP: none (no eligible tasks)"
        if "missing evidence:" in first_blocker:
            claim = first_blocker.split("missing evidence:", 1)[1].strip()
            next_step = f"NEXT STEP: provide evidence {claim}"
        elif "conflicting evidence:" in first_blocker:
            claim = first_blocker.split("conflicting evidence:", 1)[1].strip()
            next_step = f"NEXT STEP: provide evidence {claim}"
        elif "requires /ops:" in first_blocker:
            action = first_blocker.split("requires /ops:", 1)[1].strip()
            next_step = f"NEXT STEP: /ops {action}"
        elif "missing capability contract:" in first_blocker:
            cap = first_blocker.split("missing capability contract:", 1)[1].strip()
            next_step = f"NEXT STEP: resolve dependency missing capability contract: {cap}"
        elif "dependencies not done" in first_blocker:
            parts = first_blocker.split()
            task_ref = parts[1] if len(parts) > 1 else "unknown"
            next_step = f"NEXT STEP: resolve dependency {task_ref}"

        return _format_del_response(
            {"selected": "none", "reason": reason},
            {"id": "none", "description": "none", "status": "none"},
            next_step,
            trace_id,
            task_origination=task_origination_block,
        )

    task = graph.tasks[selection.task_id]
    _link_evidence_to(decision.node_id, _extract_required_evidence(task.description))

    failure = evaluate_failure_modes(
        task,
        RuntimeContext(
            trace_id=trace_id,
            user_input=user_input,
            via_ops=user_input.strip().startswith("/ops "),
        ),
    )
    if failure.status == "refuse":
        blocker = create_node("BLOCKER", failure.reason or "failure mode refusal", related_task_id=task.task_id)
        create_edge(blocker.node_id, decision.node_id, "blocked_by")
        outcome = create_node("OUTCOME", "refusal prevents progress", related_task_id=task.task_id)
        create_edge(decision.node_id, outcome.node_id, "caused_by")
        response = "\n".join(
            [
                "REFUSAL:",
                f"- code: {failure.failure_code}",
                f"- reason: {failure.reason}",
                "",
                "NEXT STEP:",
                "none (refused by safety rule)",
            ]
        )
        return {
            "final_output": response,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
        }

    normalized_input = user_input.strip()
    if normalized_input.upper().startswith("APPROVE PLAN "):
        plan_id = normalized_input.split("APPROVE PLAN ", 1)[1].strip()
        if not plan_id:
            response = "\n".join(
                [
                    "REFUSAL:",
                    "- code: PLAN_REFUSED",
                    "- reason: Refusing to approve plan: plan_id missing.",
                    "",
                    "NEXT STEP:",
                    "none (refused by safety rule)",
                ]
            )
            return {
                "final_output": response,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }
        try:
            approve_plan(plan_id)
        except Exception as exc:
            response = "\n".join(
                [
                    "REFUSAL:",
                    "- code: PLAN_REFUSED",
                    f"- reason: Refusing to approve plan: {exc}",
                    "",
                    "NEXT STEP:",
                    "none (refused by safety rule)",
                ]
            )
            return {
                "final_output": response,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }
        plan = get_plan(plan_id)
        step = plan.steps[0]
        decision = create_node("DECISION", "plan approved", related_task_id=plan.task_id, related_plan_id=plan.plan_id)
        action = create_node("ACTION", step.description, related_task_id=plan.task_id, related_plan_id=plan.plan_id, related_step_id=step.step_id)
        create_edge(decision.node_id, action.node_id, "requires")
        response = "\n".join(
            [
                "ACTIVE PLAN:",
                f"- plan_id: {plan.plan_id}",
                f"- step_id: {step.step_id}",
                f"- description: {step.description}",
                "",
                "NEXT STEP:",
                f"{'NEXT STEP: /ops ' + step.description.split('/ops ',1)[1] if step.ops_required and step.description.startswith('/ops ') else 'NEXT STEP: ' + step.description}",
            ]
        )
        return {
            "final_output": response,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
        }

    missing_deps = []
    for dep_id in task.depends_on:
        dep = graph.tasks.get(dep_id)
        if not dep or dep.status != "done":
            missing_deps.append(dep_id)

    if missing_deps:
        blocker = create_node("BLOCKER", f"missing dependency: {missing_deps[0]}", related_task_id=task.task_id)
        create_edge(blocker.node_id, decision.node_id, "blocked_by")
        block_task(task.task_id, f"missing dependency: {missing_deps[0]}")
        save_graph(trace_id)
        return _format_del_response(
            {"selected": task.task_id, "reason": selection.reason or ""},
            {"id": task.task_id, "description": task.description, "status": "blocked"},
            f"NEXT STEP: resolve dependency {missing_deps[0]}",
            trace_id,
            task_origination=task_origination_block,
        )

    plans_for_task = find_plans_for_task(task.task_id)
    approved_plan = next((plan for plan in plans_for_task if plan.approved), None)
    if approved_plan:
        step = approved_plan.steps[0]
        decision = create_node("DECISION", "plan step ready", related_task_id=approved_plan.task_id, related_plan_id=approved_plan.plan_id)
        action = create_node("ACTION", step.description, related_task_id=approved_plan.task_id, related_plan_id=approved_plan.plan_id, related_step_id=step.step_id)
        create_edge(decision.node_id, action.node_id, "requires")
        response = "\n".join(
            [
                "ACTIVE PLAN:",
                f"- plan_id: {approved_plan.plan_id}",
                f"- step_id: {step.step_id}",
                f"- description: {step.description}",
                "",
                "NEXT STEP:",
                f"{'NEXT STEP: /ops ' + step.description.split('/ops ',1)[1] if step.ops_required and step.description.startswith('/ops ') else 'NEXT STEP: ' + step.description}",
            ]
        )
        return {
            "final_output": response,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
        }

    if normalized_input.lower().startswith("plan"):
        if task.status != "ready":
            blocker = create_node("BLOCKER", "plan refused: task not ready", related_task_id=task.task_id)
            create_edge(blocker.node_id, decision.node_id, "blocked_by")
            outcome = create_node("OUTCOME", "refusal prevents progress", related_task_id=task.task_id)
            create_edge(decision.node_id, outcome.node_id, "caused_by")
            response = "\n".join(
                [
                    "REFUSAL:",
                    "- code: PLAN_REFUSED",
                    "- reason: Refusing to plan: task is not ready.",
                    "",
                    "NEXT STEP:",
                    "none (refused by safety rule)",
                ]
            )
            return {
                "final_output": response,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }
        if plans_for_task:
            blocker = create_node("BLOCKER", "plan refused: plan already exists", related_task_id=task.task_id)
            create_edge(blocker.node_id, decision.node_id, "blocked_by")
            outcome = create_node("OUTCOME", "refusal prevents progress", related_task_id=task.task_id)
            create_edge(decision.node_id, outcome.node_id, "caused_by")
            response = "\n".join(
                [
                    "REFUSAL:",
                    "- code: PLAN_REFUSED",
                    "- reason: Refusing to plan: plan already exists for task.",
                    "",
                    "NEXT STEP:",
                    "none (refused by safety rule)",
                ]
            )
            return {
                "final_output": response,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }
        capability, _, via_ops = _extract_capability(task.description)
        contract = None
        if capability:
            try:
                contract = load_contract(capability)
            except Exception:
                blocker = create_node("BLOCKER", "plan refused: capability contract missing", related_task_id=task.task_id)
                create_edge(blocker.node_id, decision.node_id, "blocked_by")
                outcome = create_node("OUTCOME", "refusal prevents progress", related_task_id=task.task_id)
                create_edge(decision.node_id, outcome.node_id, "caused_by")
                response = "\n".join(
                    [
                        "REFUSAL:",
                        "- code: PLAN_REFUSED",
                        "- reason: Refusing to plan: capability contract missing.",
                        "",
                        "NEXT STEP:",
                        "none (refused by safety rule)",
                    ]
                )
                return {
                    "final_output": response,
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                }
        required_evidence = _extract_required_evidence(task.description)
        ops_required = False
        if contract:
            required_evidence.extend(contract.requires.get("evidence", []))
            ops_required = bool(contract.requires.get("ops_required"))
        step = PlanStep(
            step_id=str(uuid.uuid4()),
            description=task.description,
            required_evidence=required_evidence,
            required_capability=capability,
            ops_required=ops_required,
            failure_modes=sorted(FAILURE_CODES),
        )
        plan = create_plan(task.task_id, [step])
        plan_decision = create_node("DECISION", "plan proposed", related_task_id=task.task_id, related_plan_id=plan.plan_id)
        _link_evidence_to(plan_decision.node_id, required_evidence)
        response = "\n".join(
            [
                "PLAN PROPOSAL:",
                f"- plan_id: {plan.plan_id}",
                f"- task_id: {plan.task_id}",
                "",
                "STEPS:",
                "1. " + step.description,
                f"   - capability: {step.required_capability}",
                f"   - ops_required: {str(step.ops_required).lower()}",
                f"   - required_evidence: {step.required_evidence}",
                f"   - failure_modes: {step.failure_modes}",
                "",
                "APPROVAL REQUIRED:",
                f"APPROVE PLAN {plan.plan_id}",
            ]
        )
        return {
            "final_output": response,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
        }

    capability, action_text, via_ops = _extract_capability(task.description)
    contract = None
    if capability:
        try:
            contract = load_contract(capability)
        except ContractViolation:
            blocker = create_node("BLOCKER", f"missing capability contract: {capability}", related_task_id=task.task_id)
            create_edge(blocker.node_id, decision.node_id, "blocked_by")
            block_task(task.task_id, "missing capability contract")
            save_graph(trace_id)
            return _format_del_response(
                {"selected": task.task_id, "reason": selection.reason or ""},
                {"id": task.task_id, "description": task.description, "status": "blocked"},
                f"NEXT STEP: resolve dependency missing capability contract: {capability}",
                trace_id,
                task_origination=task_origination_block,
            )

    required_evidence = _extract_required_evidence(task.description)
    if contract:
        required_evidence.extend(contract.requires.get("evidence", []))
    missing_evidence = [claim for claim in required_evidence if not has_evidence(claim)]
    if missing_evidence:
        blocker = create_node("BLOCKER", f"no evidence: {missing_evidence[0]}", related_task_id=task.task_id)
        create_edge(blocker.node_id, decision.node_id, "blocked_by")
        _link_evidence_to(blocker.node_id, [missing_evidence[0]])
        block_task(task.task_id, f"no evidence: {missing_evidence[0]}")
        save_graph(trace_id)
        return _format_del_response(
            {"selected": task.task_id, "reason": selection.reason or ""},
            {"id": task.task_id, "description": task.description, "status": "blocked"},
            f"NEXT STEP: provide evidence {missing_evidence[0]}",
            trace_id,
            task_origination=task_origination_block,
        )

    if contract:
        ok, reason = validate_preconditions(contract, {"trace_id": trace_id, "via_ops": via_ops})
        if not ok:
            blocker = create_node("BLOCKER", f"preconditions failed: {reason}", related_task_id=task.task_id)
            create_edge(blocker.node_id, decision.node_id, "blocked_by")
            block_task(task.task_id, reason)
            save_graph(trace_id)
            if reason == "ops_required":
                action = create_node("ACTION", f"/ops {action_text}", related_task_id=task.task_id)
                create_edge(decision.node_id, action.node_id, "requires")
                return _format_del_response(
                    {"selected": task.task_id, "reason": selection.reason or ""},
                    {"id": task.task_id, "description": task.description, "status": "blocked"},
                    f"NEXT STEP: /ops {action_text}",
                    trace_id,
                    task_origination=task_origination_block,
                )
            return _format_del_response(
                {"selected": task.task_id, "reason": selection.reason or ""},
                {"id": task.task_id, "description": task.description, "status": "blocked"},
                "NEXT STEP: none (task complete)",
                trace_id,
                task_origination=task_origination_block,
            )

    if task.status in ("done", "failed"):
        outcome = create_node("OUTCOME", f"task {task.status}", related_task_id=task.task_id)
        create_edge(decision.node_id, outcome.node_id, "caused_by")
        save_graph(trace_id)
        return _format_del_response(
            {"selected": task.task_id, "reason": selection.reason or ""},
            {"id": task.task_id, "description": task.description, "status": task.status},
            "NEXT STEP: none (task complete)",
            trace_id,
            task_origination=task_origination_block,
        )

    if contract and contract.requires.get("ops_required"):
        action = create_node("ACTION", f"/ops {action_text}", related_task_id=task.task_id)
        create_edge(decision.node_id, action.node_id, "requires")
        return _format_del_response(
            {"selected": task.task_id, "reason": selection.reason or ""},
            {"id": task.task_id, "description": task.description, "status": task.status},
            f"NEXT STEP: /ops {action_text}",
            trace_id,
            task_origination=task_origination_block,
        )

    return _format_del_response(
        {"selected": task.task_id, "reason": selection.reason or ""},
        {"id": task.task_id, "description": task.description, "status": task.status},
        "NEXT STEP: none (task complete)",
        trace_id,
        task_origination=task_origination_block,
    )


def _is_action_request(text: str) -> bool:
    lowered = text.lower()
    action_triggers = [
        "restart",
        "stop",
        "reload",
        "start",
        "install",
        "upgrade",
        "update",
        "remove",
        "delete",
        "uninstall",
        "push",
        "deploy",
        "enable",
        "disable",
    ]
    return any(trigger in lowered for trigger in action_triggers)


def _should_use_legacy_routing(normalized_input: str) -> bool:
    if normalized_input.upper().startswith("APPROVE PLAN "):
        return False
    if normalized_input.lower().startswith("claim:"):
        return False
    if normalized_input.lower().startswith("plan"):
        return False
    legacy_prefixes = (
        "/exec ",
        "/ops ",
        "GRANT_CAPABILITY",
        "/revoke_autonomy",
        "APPROVE ",
    )
    if normalized_input.startswith(legacy_prefixes):
        return True
    if _requires_barn_inspection(normalized_input):
        return True
    return False


def _normalize_service_name(name: str) -> str:
    if name.endswith(".service"):
        return name
    return f"{name}.service"


def _build_atomic_ops_plan(verb: str, target: str) -> str | None:
    if not _last_inspection:
        return None

    systemd_units = set(_last_inspection.get("systemd_units", []))
    systemd_lines = _last_inspection.get("systemd_lines", {})
    docker_names = set(_last_inspection.get("docker_names", []))
    docker_lines = _last_inspection.get("docker_lines", {})

    normalized = _normalize_service_name(target)
    unit_name = normalized if normalized in systemd_units else target
    use_systemd = unit_name in systemd_units
    use_docker = False
    if not use_systemd:
        use_docker = target in docker_names

    if verb in ("enable", "disable") and not use_systemd:
        return None

    if not use_systemd and not use_docker:
        return None

    timestamp = _last_inspection.get("timestamp", "unknown")

    if use_systemd:
        observed_line = systemd_lines.get(unit_name, f"{unit_name} (observed in systemd)")
        action_command = f"sudo systemctl {verb} {unit_name}"
        verify_command = f"systemctl status {unit_name}"
        observed_label = "systemd"
    else:
        observed_line = docker_lines.get(target, f"{target} (observed in docker)")
        action_command = f"sudo docker {verb} {target}"
        verify_command = (
            f"sudo docker ps --filter name=^/{target}$ --format \"{{{{.Names}}}}\t{{{{.Status}}}}\""
        )
        observed_label = "docker"

    return "\n".join(
        [
            "Atomic action plan:",
            "",
            "Observed:",
            f"- {observed_label}: {observed_line}",
            f"- inspection time: {timestamp}",
            "",
            "Action:",
            f"- Command: {action_command}",
            "",
            "Verification:",
            f"- Command: {verify_command}",
            "",
            "This action requires sudo.",
            "Approve? (yes/no)",
        ]
    )


def _ops_capability_for(verb: str) -> str:
    mapping = {
        "restart": "restart_service",
        "start": "start_service",
        "stop": "stop_service",
        "enable": "enable_service",
        "disable": "disable_service",
    }
    return mapping.get(verb, "")


def _run_inspection_command(command: list[str], timeout: int = 3) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError:
        return False, "command not found"
    except subprocess.TimeoutExpired:
        return False, "command timed out"
    except Exception as exc:
        return False, f"command failed: {exc}"
    output = (result.stdout or "").strip()
    if not output:
        output = (result.stderr or "").strip()
    return True, output or "no output"


def _summarize_output(output: str, max_lines: int = 20) -> str:
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[:max_lines] + ["... (truncated)"])


def _parse_systemd_units(output: str) -> tuple[set[str], dict[str, str]]:
    units = set()
    unit_lines = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if not parts:
            continue
        unit = parts[0]
        if "." in unit:
            units.add(unit)
            unit_lines[unit] = line.strip()
    return units, unit_lines


def _parse_docker_lines(output: str) -> tuple[set[str], dict[str, str]]:
    names = set()
    lines = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        name = line.split("\t", 1)[0].strip()
        if name:
            names.add(name)
            lines[name] = line.strip()
    return names, lines


def _record_inspection(data: dict) -> None:
    _last_inspection.clear()
    _last_inspection.update(data)


def _inspect_barn(query: str) -> str:
    terms = [word for word in shlex.split(query) if word.isalnum() and len(word) >= 3]
    search_term = terms[0] if terms else "cmdb"

    systemd_ok, systemd_out = _run_inspection_command(
        ["systemctl", "list-units", "--type=service", "--all"]
    )
    docker_ok, docker_out = _run_inspection_command(
        ["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"]
    )
    ports_ok, ports_out = _run_inspection_command(["ss", "-ltnp"])
    rg_ok, rg_out = _run_inspection_command(
        [
            "rg",
            "-n",
            search_term,
            "/etc",
            "/home/billyb",
            "-g",
            "*.yml",
            "-g",
            "*.yaml",
            "-g",
            "*.conf",
            "-g",
            "*.env",
            "-g",
            "*.service",
        ],
        timeout=5,
    )

    systemd_units, systemd_lines = _parse_systemd_units(systemd_out if systemd_ok else "")
    docker_names, docker_lines = _parse_docker_lines(docker_out if docker_ok else "")

    _record_inspection(
        {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "systemd_units": sorted(systemd_units),
            "systemd_lines": systemd_lines,
            "docker_names": sorted(docker_names),
            "docker_lines": docker_lines,
            "ports_output": ports_out if ports_ok else "",
            "config_hits": rg_out if rg_ok else "",
            "search_term": search_term,
        }
    )

    response_lines = [
        "Inspecting the Barn (read-only).",
        "I checked:",
        "- systemd services",
        "- Docker containers",
        "- listening ports",
        "- config files",
        "",
        "SYSTEMD:",
        _summarize_output(systemd_out if systemd_ok else systemd_out),
        "",
        "DOCKER:",
        _summarize_output(docker_out if docker_ok else docker_out),
        "",
        "PORTS:",
        _summarize_output(ports_out if ports_ok else ports_out),
        "",
        f"CONFIG SEARCH (term: {search_term}):",
        _summarize_output(rg_out if rg_ok else rg_out),
        "",
        "Let me know which entry looks like the target, or if you want me to refine the search.",
    ]
    return "\n".join(response_lines)


def _is_high_risk_command(command: str) -> tuple[bool, str]:
    try:
        parts = shlex.split(command)
    except ValueError:
        return False, ""
    if not parts:
        return False, ""
    executable = parts[0]
    args = parts[1:]

    if executable in ("apt", "apt-get", "dnf", "pacman", "apk"):
        return True, "system_package"
    if executable == "systemctl" and args:
        if args[0] in ("restart", "stop", "reload"):
            return True, "service_control"
    if executable == "docker" and args:
        if args[0] in ("restart", "stop", "kill", "rm"):
            return True, "service_control"
    if executable in ("iptables", "ufw", "firewall-cmd", "ip", "route", "ifconfig", "nmcli"):
        return True, "network_change"
    return False, ""


def _build_ops_plan(command: str, category: str) -> dict:
    host = socket.gethostname()
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = []

    target = {}
    if parts:
        if parts[0] == "systemctl" and len(parts) >= 2:
            if len(parts) >= 3:
                target = {"service": parts[2], "host": host}
            else:
                target = {"service": "unknown", "host": host}
        elif parts[0] in ("apt", "apt-get", "dnf", "pacman", "apk"):
            target = {"package": " ".join(parts[1:]) or "unknown", "host": host}
        elif parts[0] == "docker" and len(parts) >= 2:
            target = {"service": parts[1], "host": host}
        else:
            target = {"host": host}
    else:
        target = {"host": host}

    pre_checks = [
        "operator intent confirmed",
        "no pending approvals",
    ]
    impact = ["potential service disruption", "manual verification required"]
    rollback = ["manual rollback required"]
    verification = ["manual verification required"]

    return {
        "category": category,
        "risk_level": "HIGH",
        "target": target,
        "pre_checks": pre_checks,
        "impact": impact,
        "rollback": rollback,
        "verification": verification,
    }


def _git_status_clean(repo_root: Path) -> tuple[bool, list[str]]:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return False, []
    lines = [line for line in (result.stdout or "").splitlines() if line.strip()]
    return len(lines) == 0, lines


def _git_current_branch(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return ""
    return (result.stdout or "").strip()


def _validate_delete_command(parts: list[str]) -> tuple[bool, str]:
    if not parts or parts[0] != "rm":
        return False, "Invalid delete command"
    args = parts[1:]
    if not args or len(args) != 1:
        return False, "Delete requires exactly one target"
    if any(flag in args[0] for flag in ("*", "?", "[")):
        return False, "Wildcards are not allowed"
    if any(arg.startswith("-") for arg in args):
        return False, "Flags are not allowed"
    return True, ""


def _classify_shell_action(command: str, working_dir: str) -> dict | None:
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    if not parts:
        return None

    executable = parts[0]
    args = parts[1:]

    if executable in ("touch", "mkdir") and args:
        target = args[-1]
        if not target.startswith("/"):
            target = str(Path(working_dir) / target)
        return {
            "capability": "filesystem.write",
            "operation": executable,
            "path": target,
            "working_dir": working_dir,
        }

    if executable == "rm":
        ok, reason = _validate_delete_command(parts)
        target = args[-1] if args else ""
        if target and not target.startswith("/"):
            target = str(Path(working_dir) / target)
        return {
            "capability": "filesystem.delete",
            "operation": executable,
            "path": target,
            "valid": ok,
            "reason": reason if not ok else "",
            "working_dir": working_dir,
        }

    if executable in ("cat", "ls") and args:
        target = args[-1]
        if not target.startswith("/"):
            target = str(Path(working_dir) / target)
        return {
            "capability": "filesystem.read",
            "operation": executable,
            "path": target,
            "working_dir": working_dir,
        }

    if executable == "git" and args:
        if args[0] != "push":
            return None
        if len(args) != 1:
            return {
                "capability": "git.push",
                "operation": "git push",
                "valid": False,
                "reason": "Git push arguments are not allowed",
                "working_dir": str(_get_repo_root()),
            }
        return {
            "capability": "git.push",
            "operation": "git push",
            "valid": True,
            "working_dir": str(_get_repo_root()),
        }

    return None


def mark_claim_known(claim: str, trace_id: str) -> None:
    from core.evidence import load_evidence, assert_claim_known

    load_evidence(trace_id)
    assert_claim_known(claim)

_capability_registry.register({
    "capability": "write_file",
    "tool": {
        "name": "demo.hello",
        "version": "1.0.0",
        "description": "Writes hello output to workspace",
        "inputs": [],
        "outputs": [
            {"name": "output.txt", "type": "string"},
        ],
        "side_effects": ["writes /workspace/output.txt"],
        "safety": {
            "reversible": True,
            "destructive": False,
            "requires_approval": False,
        },
    }
})


def _run_demo_tool(trace_id: str):
    return _docker_runner.run(
        tool_id="demo.hello",
        image="billy-hello",
        args=[],
        trace_id=trace_id,
    )


class BillyRuntime:
    def __init__(self, config: Dict[str, Any] | None = None, root_path: str | None = None) -> None:
        """
        Initialize the runtime.

        Args:
            config: Optional configuration dictionary. If not provided,
            config will be loaded automatically from v2/config.yaml.
            root_path: Optional root path, reserved for compatibility.
        """
        # Enforce presence of canonical contracts at boot
        try:
            load_schema("tool-spec.schema.yaml")
            load_schema("trace-event.schema.yaml")
        except ContractViolation as e:
            raise SystemExit(f"[FATAL] Contract enforcement failed at startup: {e}")
        self.config = config or {}

    def _identity_guard(self, user_input: str, answer: str) -> str:
        """
        Identity guardrails (currently permissive).

        This hook exists to enforce identity rules later.
        """
        return answer

    def _load_config_from_yaml(self) -> Dict[str, Any]:
        """
        Load model configuration from v2/config.yaml if present.
        """
        try:
            v2_root = Path(__file__).resolve().parents[1]
            config_path = v2_root / "config.yaml"

            if not config_path.exists():
                return {}

            data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {}

            # Expect config under top-level "model"
            return data.get("model", {})
        except Exception:
            return {}

    def ask(self, prompt: str) -> str:
        """
        Route every request through the deterministic pipeline.

        This is the method called by:
        - /ask
        - /v1/chat/completions

        Special routing for Agent Zero commands starting with "a0 ".
        """
        
        # Route Agent Zero commands
        if prompt.strip().startswith("a0 "):
            try:
                from v2.agent_zero.commands import handle_command
                result = handle_command(prompt)
                if result:
                    return json.dumps(result, indent=2)
            except ImportError as e:
                return json.dumps({"error": f"Agent Zero module not available: {str(e)}"}, indent=2)
            except Exception as e:
                return json.dumps({"error": f"Error handling Agent Zero command: {str(e)}"}, indent=2)

        trace_id = f"trace-{int(time.time() * 1000)}"
        assert_trace_id(trace_id)
        assert_explicit_memory_write(prompt)
        result = _run_deterministic_loop(prompt, trace_id)
        return result.get("final_output", "")

    def run_turn(self, user_input: str, session_context: Dict[str, Any]):
        trace_id = session_context.get("trace_id") if isinstance(session_context, dict) else None
        if not trace_id:
            trace_id = f"trace-{int(time.time() * 1000)}"
        assert_trace_id(trace_id)
        assert_explicit_memory_write(user_input)
        normalized_input = user_input.strip()
        if normalized_input.lower().startswith("/simulate "):
            from core.counterfactual import simulate_action

            proposed = normalized_input[len("/simulate "):].strip()
            result = simulate_action(
                task_id=None,
                plan_id=None,
                step_id=None,
                proposed_action=proposed,
                now=datetime.now(timezone.utc),
            )
            response = "\n".join(
                [
                    "SIMULATION:",
                    f"- status: {result.status}",
                    f"- reasons: {result.reasons}",
                    f"- required_evidence: {result.required_evidence}",
                    f"- required_capabilities: {result.required_capabilities}",
                    f"- triggered_failure_modes: {result.triggered_failure_modes}",
                    f"- hypothetical_outcomes: {result.hypothetical_outcomes}",
                ]
            )
            return {
                "final_output": response,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }
        if not _should_use_legacy_routing(normalized_input):
            return _run_deterministic_loop(user_input, trace_id)

        if normalized_input.startswith("/ops "):
            rest = normalized_input[len("/ops "):].strip()
            parts = shlex.split(rest)
            if len(parts) != 2:
                return {
                    "final_output": "Atomic action required: use /ops <verb> <target>.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            verb, target = parts
            allowed_verbs = {"restart", "start", "stop", "enable", "disable"}
            if verb not in allowed_verbs:
                return {
                    "final_output": "Atomic action required: unsupported verb.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            from core.capability_contracts import load_contract, validate_preconditions

            capability = _ops_capability_for(verb)
            try:
                contract = load_contract(capability)
            except ContractViolation:
                return {
                    "final_output": "Execution denied: missing capability contract.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            if not contract.requires.get("ops_required"):
                return {
                    "final_output": "Execution denied: ops not required for this capability.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            ok, reason = validate_preconditions(contract, {"trace_id": trace_id, "via_ops": True})
            if not ok:
                return {
                    "final_output": f"Execution denied: {reason}",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            plan = _build_atomic_ops_plan(verb, target)
            if not plan:
                return {
                    "final_output": "Cannot proceed: target was not observed during inspection.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            return {
                "final_output": plan,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        if _requires_barn_inspection(normalized_input):
            inspection = _inspect_barn(normalized_input)
            if _is_action_request(normalized_input):
                next_step = "\n\nNEXT STEP:\n- If you want me to act, reply with: /ops " + normalized_input
                inspection = inspection + next_step
            return {
                "final_output": inspection,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        if normalized_input.startswith("GRANT_CAPABILITY"):
            lines = [line.strip() for line in normalized_input.splitlines() if line.strip()]
            name_line = next((line for line in lines if line.startswith("name:")), "")
            scope_line = next((line for line in lines if line.startswith("scope:")), "")
            mode_line = next((line for line in lines if line.startswith("mode:")), "")
            expires_line = next((line for line in lines if line.startswith("expires_in:")), "")
            max_actions_line = next((line for line in lines if line.startswith("max_actions:")), "")

            capability_name = name_line.replace("name:", "", 1).strip()
            scope_name = scope_line.replace("scope:", "", 1).strip()
            mode = mode_line.replace("mode:", "", 1).strip()
            expires_in = expires_line.replace("expires_in:", "", 1).strip()
            max_actions = max_actions_line.replace("max_actions:", "", 1).strip()

            if not capability_name:
                return {
                    "final_output": "Capability grant rejected: name is required.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            if scope_name not in ("", "default"):
                return {
                    "final_output": "Capability grant rejected: only scope: default is supported.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            expires_seconds = _parse_duration_seconds(expires_in) if expires_in else None
            if expires_in and expires_seconds is None:
                return {
                    "final_output": "Capability grant rejected: expires_in must be like 10m, 30s, or 1h.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            max_actions_value = int(max_actions) if max_actions else None

            preset = _default_capability_grants.get(capability_name)
            if not preset:
                return {
                    "final_output": "Capability grant rejected: unknown capability.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            default_mode = "auto" if not preset.get("require_grant") else "approval"
            mode = mode or default_mode
            if mode not in ("approval", "auto"):
                return {
                    "final_output": "Capability grant rejected: mode must be approval or auto.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            limits = dict(preset["limits"])
            if max_actions_value:
                limits["max_actions_per_session"] = max_actions_value

            record = _autonomy_registry.grant_capability(
                capability=capability_name,
                scope=preset["scope"],
                limits=limits,
                risk_level=preset["risk_level"],
                grantor="human",
                mode=mode,
                expires_at=(time.time() + expires_seconds) if expires_seconds else None,
            )
            _journal_exec_contract("capability_grant", record)
            return {
                "final_output": f"Capability granted: {capability_name}",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        if normalized_input.startswith("grant_autonomy "):
            capability_name = normalized_input[len("grant_autonomy "):].strip()
            preset = _default_capability_grants.get(capability_name)
            if not preset:
                return {
                    "final_output": "Capability grant rejected: unknown capability.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            record = _autonomy_registry.grant_capability(
                capability=capability_name,
                scope=preset["scope"],
                limits=preset["limits"],
                risk_level=preset["risk_level"],
                grantor="human",
                mode="auto" if not preset.get("require_grant") else "approval",
            )
            _journal_exec_contract("capability_grant", record)
            return {
                "final_output": f"Capability granted: {capability_name}",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        approve_parts = normalized_input.split()
        if len(approve_parts) == 2 and approve_parts[0] == "APPROVE":
            approval_id = approve_parts[1]
            proposal = _pending_exec_proposals.get(approval_id)
            if not proposal:
                return {
                    "final_output": "Approval rejected: unknown or expired proposal id.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            command = proposal.get("command", "")
            working_dir = proposal.get("working_dir", "/")
            capability = proposal.get("capability")
            valid, reason = _validate_exec_command(command)
            if not valid:
                _journal_exec_contract(
                    "approval",
                    {"id": approval_id, "status": "rejected", "reason": reason},
                )
                return {
                    "final_output": f"Approval rejected: {reason}",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            _journal_exec_contract(
                "approval",
                {"id": approval_id, "status": "approved"},
            )
            _journal_exec_contract(
                "execution",
                {"id": approval_id, "command": command, "working_dir": working_dir, "capability": capability},
            )

            try:
                result = _execute_shell_command(command, working_dir)
            except Exception as exc:
                _journal_exec_contract(
                    "result",
                    {"id": approval_id, "status": "error", "error": str(exc)},
                )
                return {
                    "final_output": f"Execution failed: {exc}",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            verification = _verify_command_result(command)
            stdout_repr = json.dumps(result.stdout or "")
            stderr_repr = json.dumps(result.stderr or "")
            limits_remaining = None
            if capability and _autonomy_registry.get_grant(capability):
                limits_remaining = _autonomy_registry.consume_grant(capability)
            _journal_exec_contract(
                "result",
                {
                    "id": approval_id,
                    "exit_code": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "verification": verification,
                    "limits_remaining": limits_remaining,
                },
            )
            _pending_exec_proposals.pop(approval_id, None)

            response = "\n".join(
                [
                    "EXECUTION_RESULT",
                    f"id: {approval_id}",
                    f"exit_code: {result.returncode}",
                    f"stdout: {stdout_repr}",
                    f"stderr: {stderr_repr}",
                    f"verification: {verification}",
                ]
            )
            return {
                "final_output": response,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        if normalized_input.startswith("/exec "):
            command = normalized_input[len("/exec "):].strip()
            valid, reason = _validate_exec_command(command)
            if not valid:
                return {
                    "final_output": f"Execution request rejected: {reason}",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            is_high_risk, _ = _is_high_risk_command(command)
            if is_high_risk:
                return {
                    "final_output": "Execution denied: high-risk operation requires /ops.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            working_dir = "/"
            action = _classify_shell_action(command, working_dir)
            if action:
                capability = action.get("capability", "")
                action_working_dir = action.get("working_dir", working_dir)
                grant = _autonomy_registry.get_grant(capability)
            else:
                capability = ""

            if not capability:
                _journal_exec_contract(
                    "capability_denied",
                    {"capability": capability or "unknown", "command": command, "reason": "Missing capability"},
                )
                return {
                    "final_output": "Execution denied: missing capability contract.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            from core.capability_contracts import load_contract, validate_preconditions

            try:
                contract = load_contract(capability)
            except ContractViolation:
                _journal_exec_contract(
                    "capability_denied",
                    {"capability": capability, "command": command, "reason": "Missing capability contract"},
                )
                return {
                    "final_output": "Execution denied: missing capability contract.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            ok, reason = validate_preconditions(contract, {"trace_id": trace_id, "via_ops": False})
            if not ok:
                _journal_exec_contract(
                    "capability_denied",
                    {"capability": capability, "command": command, "reason": reason},
                )
                if reason == "ops_required":
                    return {
                        "final_output": "Execution denied: capability requires /ops.",
                        "tool_calls": [],
                        "status": "error",
                        "trace_id": trace_id,
                    }
                return {
                    "final_output": f"Execution denied: {reason}",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            if not action.get("valid", True):
                reason = action.get("reason", "Capability scope violation")
                _journal_exec_contract(
                    "capability_denied",
                    {"capability": capability, "command": command, "reason": reason},
                )
                return {
                    "final_output": f"Execution denied: {reason}",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            allowed, reason, remaining = _autonomy_registry.is_grant_allowed(
                capability,
                action,
            )

            preset = _default_capability_grants.get(capability, {})
            require_grant = preset.get("require_grant", False)

            if not grant and require_grant:
                _journal_exec_contract(
                    "capability_denied",
                    {"capability": capability, "command": command, "reason": "Capability not granted"},
                )
                return {
                    "final_output": "Execution denied: capability not granted.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            if capability == "git.push":
                repo_root = Path(action_working_dir)
                clean, lines = _git_status_clean(repo_root)
                if not clean:
                    _journal_exec_contract(
                        "capability_denied",
                        {
                            "capability": capability,
                            "command": command,
                            "reason": "Working tree not clean",
                            "details": lines,
                        },
                    )
                    return {
                        "final_output": "Execution denied: working tree not clean.",
                        "tool_calls": [],
                        "status": "error",
                        "trace_id": trace_id,
                    }

            if allowed and grant and grant.get("mode") == "auto":
                _journal_exec_contract(
                    "auto_execution",
                    {
                        "capability": capability,
                        "command": command,
                        "working_dir": action_working_dir,
                        "limits_remaining": remaining,
                    },
                )
                try:
                    result = _execute_shell_command(command, action_working_dir)
                except Exception as exc:
                    _journal_exec_contract(
                        "result",
                        {"status": "error", "error": str(exc)},
                    )
                    return {
                        "final_output": f"Execution failed: {exc}",
                        "tool_calls": [],
                        "status": "error",
                        "trace_id": trace_id,
                    }

                remaining = _autonomy_registry.consume_grant(capability)
                verification = _verify_command_result(command)
                stdout_repr = json.dumps(result.stdout or "")
                stderr_repr = json.dumps(result.stderr or "")
                _journal_exec_contract(
                    "result",
                    {
                        "capability": capability,
                        "exit_code": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "verification": verification,
                        "limits_remaining": remaining,
                    },
                )

                response = "\n".join(
                    [
                        "EXECUTION_RESULT",
                        "id: auto-exec",
                        f"exit_code: {result.returncode}",
                        f"stdout: {stdout_repr}",
                        f"stderr: {stderr_repr}",
                        f"verification: {verification}",
                    ]
                )
                return {
                    "final_output": response,
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                }

            if not allowed and reason in (
                "Capability scope violation",
                "Capability limits exceeded",
                "Capability expired",
                "Capability revoked",
            ):
                if preset.get("require_grant"):
                    _journal_exec_contract(
                        "capability_denied",
                        {"capability": capability, "command": command, "reason": reason},
                    )
                    return {
                        "final_output": f"Execution denied: {reason}",
                        "tool_calls": [],
                        "status": "error",
                        "trace_id": trace_id,
                    }

            if capability == "git.push":
                repo_root = Path(action_working_dir)
                branch = _git_current_branch(repo_root)
                proposal_id = _next_exec_contract_id()
                proposal = {
                    "id": proposal_id,
                    "type": "git.push",
                    "command": command,
                    "working_dir": action_working_dir,
                    "capability": capability,
                    "risk": "medium",
                    "expected_result": "git push executed",
                    "preconditions": [
                        "clean working tree",
                        "no untracked files",
                    ],
                    "branch": branch,
                }
                _pending_exec_proposals[proposal_id] = proposal
                _journal_exec_contract("proposal", proposal)

                response = "\n".join(
                    [
                        "PROPOSED_ACTION",
                        f"id: {proposal_id}",
                        "type: git.push",
                        "preconditions:",
                        "  - clean working tree",
                        "  - no untracked files",
                        f"branch: {branch}",
                    ]
                )
                return {
                    "final_output": response,
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                }

            proposal_id = _next_exec_contract_id()
            expected_result = _expected_result_for_command(command)
            proposal = {
                "id": proposal_id,
                "type": "shell",
                "command": command,
                "working_dir": action.get("working_dir", working_dir) if action else working_dir,
                "capability": capability if action else None,
                "risk": preset.get("risk_level", "low") if action else "low",
                "expected_result": expected_result,
            }
            _pending_exec_proposals[proposal_id] = proposal
            _journal_exec_contract("proposal", proposal)

            response = "\n".join(
                [
                    "PROPOSED_ACTION",
                    f"id: {proposal_id}",
                    "type: shell",
                    f"command: {command}",
                    f"working_dir: {proposal['working_dir']}",
                    f"risk: {proposal['risk']}",
                    f"expected_result: {expected_result}",
                ]
            )
            return {
                "final_output": response,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        if user_input.strip().lower().startswith("/approve"):
            parts = user_input.strip().split()
            if len(parts) != 3:
                return {
                    "final_output": "Usage: /approve <plan_fingerprint> <step_id>",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            plan_fp = parts[1]
            step_id = parts[2]
            record = _plan_history.get(plan_fp)
            if not record or not record.get("plan"):
                return {
                    "final_output": {
                        "tool_execution": {
                            "status": "blocked",
                            "reason": "Execution denied by human",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            step = next((s for s in record["plan"].get("steps", []) if s.get("step_id") == step_id), None)
            capability = step.get("capability") if step else ""
            try:
                record = _approval_store.approve(plan_fp, step_id, capability)
            except Exception:
                return {
                    "final_output": {
                        "tool_execution": {
                            "status": "blocked",
                            "reason": "Execution denied by human",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            return {
                "final_output": record,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        if user_input.strip().lower().startswith("/deny"):
            parts = user_input.strip().split()
            if len(parts) != 3:
                return {
                    "final_output": "Usage: /deny <plan_fingerprint> <step_id>",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            plan_fp = parts[1]
            step_id = parts[2]
            record = _plan_history.get(plan_fp)
            if not record or not record.get("plan"):
                return {
                    "final_output": {
                        "tool_execution": {
                            "status": "blocked",
                            "reason": "Execution denied by human",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            step = next((s for s in record["plan"].get("steps", []) if s.get("step_id") == step_id), None)
            capability = step.get("capability") if step else ""
            try:
                record = _approval_store.deny(plan_fp, step_id, capability)
            except Exception:
                return {
                    "final_output": {
                        "tool_execution": {
                            "status": "blocked",
                            "reason": "Execution denied by human",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            return {
                "final_output": record,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        def _fallback_invalid_plan():
            return {
                "plan": {
                    "id": "fallback-invalid-plan",
                    "version": "0.0.0",
                    "objective": "Plan rejected due to validation failure",
                    "assumptions": [
                        "LLM output was incomplete or invalid"
                    ],
                    "steps": [],
                    "artifacts": [],
                    "risks": [
                        {
                            "risk": "Unsafe execution",
                            "mitigation": "Execution blocked"
                        }
                    ],
                }
            }

        plan_intent = _plan_router.route(user_input)
        if plan_intent is not None:
            tool_specs = _tool_registry._tools

            proposals = _llm_planner.propose_many(
                intent=plan_intent,
                tool_specs=tool_specs,
            )

            comparisons = []
            for p in proposals:
                validation = _plan_validator.validate(p, tool_specs)

                if not validation["valid"]:
                    comparisons.append({
                        "intent": p.get("intent"),
                        "valid": False,
                        "errors": validation["errors"],
                    })
                    continue

                plan = Plan(
                    intent=p["intent"],
                    steps=p.get("steps", []),
                    assumptions=p.get("assumptions"),
                    risks=p.get("risks"),
                )

                score = _plan_scorer.score(plan.to_dict())
                plan_dict = plan.to_dict()
                plan_dict["score"] = score
                plan_dict["valid"] = True

                comparisons.append(plan_dict)

            return {
                "final_output": {
                    "intent": plan_intent,
                    "candidates": comparisons,
                },
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        approved_plan_id = _approval_router.route(user_input)
        if approved_plan_id:
            if not _last_plan:
                return {
                    "final_output": _fallback_invalid_plan(),
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            guard = _output_guard.guard(_last_plan.to_dict() if _last_plan else {}, plan_mode=False)
            if not guard["valid"]:
                return {
                    "final_output": _fallback_invalid_plan(),
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            validation = _plan_validator.validate(guard["parsed"] or {})
            if not validation["valid"]:
                return {
                    "final_output": _fallback_invalid_plan(),
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            if not _last_plan or _last_plan.to_dict()["plan_id"] != approved_plan_id:
                return {
                    "final_output": "No matching plan to approve.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            current_plan = guard["parsed"] or _last_plan.to_dict()
            current_fp = fingerprint(current_plan)
            diff = diff_plans(_previous_plan or {}, current_plan) if _previous_plan else {}
            lock = _promotion_lock.check(current_fp, _previous_fingerprint, diff)
            if not lock["allowed"]:
                return {
                    "final_output": {
                        "promotion": {
                            "status": "blocked",
                            "reason": "No meaningful diff or promotion not approved",
                            "current_fingerprint": current_fp,
                            "previous_fingerprint": _previous_fingerprint,
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            _plan_history.append(current_plan, current_fp)
            _plan_history.set_active(current_fp)

            _previous_plan = current_plan
            _previous_fingerprint = current_fp

            _plan_state = PlanState(_last_plan.to_dict())
            return {
                "final_output": "Plan approved. Execution not yet implemented.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        cmd = user_input.strip().lower()

        if cmd.startswith("/rollback"):
            parts = user_input.strip().split()
            if len(parts) != 2:
                return {
                    "final_output": {
                        "rollback": {
                            "status": "blocked",
                            "reason": "Target plan fingerprint not found or invalid",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            target_fp = parts[1]
            try:
                result = _rollback_engine.rollback(target_fp, _plan_history)
            except Exception:
                return {
                    "final_output": {
                        "rollback": {
                            "status": "blocked",
                            "reason": "Target plan fingerprint not found or invalid",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            record = _plan_history.get(target_fp)
            if record and record.get("plan"):
                _last_plan = Plan(intent=record["plan"].get("intent", ""), steps=record["plan"].get("steps", []))

            return {
                "final_output": result,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        eval_req = _evaluation_router.route(user_input)
        if eval_req:
            evaluation = Evaluation(
                subject_type=eval_req["subject_type"],
                subject_id=eval_req["subject_id"],
                outcome="success",
                observations=[
                    "Execution completed without contract violations",
                    "All required artifacts were produced",
                ],
                risks=[],
            )
            _last_evaluation = evaluation.to_dict()

            summary = _evaluation_synthesizer.summarize(evaluation.to_dict())

            return {
                "final_output": summary,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        if _promotion_router.route(user_input):
            if not _last_evaluation:
                return {
                    "final_output": "No evaluation available to promote.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            memory_entry = {
                "content": _last_evaluation,
                "scope": {
                    "user_id": "default",
                    "persona_id": None,
                    "session_id": None,
                },
                "metadata": {
                    "category": "evaluation",
                    "confidence": 0.8,
                    "importance": "medium",
                    "source": "system",
                },
            }

            _memory_store.write(memory_entry, trace_id=trace_id)

            return {
                "final_output": "Evaluation promoted to memory.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        if cmd == "/pause" and _plan_state:
            _plan_state.pause()
            return {
                "final_output": "Plan paused.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        if cmd == "/abort" and _plan_state:
            _plan_state.abort()
            return {
                "final_output": "Plan aborted.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        if user_input.strip().lower().startswith("/step"):
            parts = user_input.strip().split()
            if len(parts) != 2:
                return {
                    "final_output": "Usage: /step <step_id>",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            step_id = parts[1]

            if not _last_plan:
                return {
                    "final_output": "No active plan.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            active_fp = _plan_history.get_active()
            if not active_fp:
                return {
                    "final_output": "No active plan.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            current_fp = fingerprint(_last_plan.to_dict())
            if current_fp != active_fp:
                return {
                    "final_output": "No active plan.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            guard = _output_guard.guard(_last_plan.to_dict(), plan_mode=False)
            if not guard["valid"]:
                return {
                    "final_output": _fallback_invalid_plan(),
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            validation = _plan_validator.validate(guard["parsed"] or {})
            if not validation["valid"]:
                return {
                    "final_output": _fallback_invalid_plan(),
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            _plan_state.can_execute(step_id)
            _plan_state.mark_running(step_id)

            step = next((s for s in _last_plan.to_dict().get("steps", []) if s.get("step_id") == step_id), None)
            if not step:
                record = _execution_journal.build_record(
                    trace_id=trace_id,
                    plan_fingerprint=current_fp,
                    step_id=step_id,
                    capability="",
                    tool_name="",
                    tool_version="",
                    inputs={},
                    status="blocked",
                    reason="Capability not registered or contract violation",
                    outputs=None,
                )
                _execution_journal.append(record)
                return {
                    "final_output": {
                        "tool_execution": {
                            "status": "blocked",
                            "reason": "Capability not registered or contract violation",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            capability = step.get("capability")
            if not capability:
                record = _execution_journal.build_record(
                    trace_id=trace_id,
                    plan_fingerprint=current_fp,
                    step_id=step_id,
                    capability="",
                    tool_name="",
                    tool_version="",
                    inputs={},
                    status="blocked",
                    reason="Capability not registered or contract violation",
                    outputs=None,
                )
                _execution_journal.append(record)
                return {
                    "final_output": {
                        "tool_execution": {
                            "status": "blocked",
                            "reason": "Capability not registered or contract violation",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            try:
                tool_name, tool_version, contract = _capability_registry.resolve(capability)
            except Exception:
                record = _execution_journal.build_record(
                    trace_id=trace_id,
                    plan_fingerprint=current_fp,
                    step_id=step_id,
                    capability=capability,
                    tool_name="",
                    tool_version="",
                    inputs={},
                    status="blocked",
                    reason="Capability not registered or contract violation",
                    outputs=None,
                )
                _execution_journal.append(record)
                return {
                    "final_output": {
                        "tool_execution": {
                            "status": "blocked",
                            "reason": "Capability not registered or contract violation",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            safety = contract.get("tool", {}).get("safety", {})
            if safety.get("requires_approval"):
                state = _approval_store.get_state(current_fp, step_id, capability)
                if state == "approved":
                    pass
                elif state == "denied":
                    record = _execution_journal.build_record(
                        trace_id=trace_id,
                        plan_fingerprint=current_fp,
                        step_id=step_id,
                        capability=capability,
                        tool_name=contract.get("tool", {}).get("name", ""),
                        tool_version=contract.get("tool", {}).get("version", ""),
                        inputs=inputs,
                        status="blocked",
                        reason="Execution denied by human",
                        outputs=None,
                    )
                    _execution_journal.append(record)
                    return {
                        "final_output": {
                            "tool_execution": {
                                "status": "blocked",
                                "reason": "Execution denied by human",
                            }
                        },
                        "tool_calls": [],
                        "status": "error",
                        "trace_id": trace_id,
                    }
                else:
                    try:
                        _approval_store.request(current_fp, step_id, capability)
                    except Exception:
                        pass

                    approval_payload = _approval_flow.build_request(
                        plan_fingerprint=current_fp,
                        step_id=step_id,
                        capability=capability,
                        tool=contract.get("tool", {}),
                        safety=safety,
                    )

                    record = _execution_journal.build_record(
                        trace_id=trace_id,
                        plan_fingerprint=current_fp,
                        step_id=step_id,
                        capability=capability,
                        tool_name=contract.get("tool", {}).get("name", ""),
                        tool_version=contract.get("tool", {}).get("version", ""),
                        inputs=inputs,
                        status="blocked",
                        reason="Human approval required",
                        outputs=None,
                    )
                    _execution_journal.append(record)

                    return {
                        "final_output": {
                            "tool_execution": {
                                "status": "blocked",
                                "reason": "Human approval required",
                                "approval_state": "pending",
                            },
                            **approval_payload,
                        },
                        "tool_calls": [],
                        "status": "error",
                        "trace_id": trace_id,
                    }

            allowed, reason = _autonomy_registry.is_autonomy_allowed(
                capability,
                {"step_id": step_id, "plan_fingerprint": current_fp},
            )
            if not allowed:
                record = _execution_journal.build_record(
                    trace_id=trace_id,
                    plan_fingerprint=current_fp,
                    step_id=step_id,
                    capability=capability,
                    tool_name=contract.get("tool", {}).get("name", ""),
                    tool_version=contract.get("tool", {}).get("version", ""),
                    inputs=inputs,
                    status="blocked",
                    reason="Autonomy policy violation or exhausted",
                    outputs=None,
                )
                _execution_journal.append(record)
                return {
                    "final_output": {
                        "tool_execution": {
                            "status": "blocked",
                            "reason": "Autonomy policy violation or exhausted",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            _autonomy_registry.consume_autonomy(
                capability,
                {"step_id": step_id, "plan_fingerprint": current_fp},
            )

            spec = _tool_registry.get(tool_name)
            if spec.get("version") != tool_version:
                record = _execution_journal.build_record(
                    trace_id=trace_id,
                    plan_fingerprint=current_fp,
                    step_id=step_id,
                    capability=capability,
                    tool_name=tool_name,
                    tool_version=tool_version,
                    inputs={},
                    status="blocked",
                    reason="Capability not registered or contract violation",
                    outputs=None,
                )
                _execution_journal.append(record)
                return {
                    "final_output": {
                        "tool_execution": {
                            "status": "blocked",
                            "reason": "Capability not registered or contract violation",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            inputs = step.get("args", {})
            inputs = inputs if isinstance(inputs, dict) else {}
            guard = _tool_guard.validate(contract, inputs)
            if not guard["valid"]:
                record = _execution_journal.build_record(
                    trace_id=trace_id,
                    plan_fingerprint=current_fp,
                    step_id=step_id,
                    capability=capability,
                    tool_name=tool_name,
                    tool_version=tool_version,
                    inputs=inputs,
                    status="blocked",
                    reason="Capability not registered or contract violation",
                    outputs=None,
                )
                _execution_journal.append(record)
                return {
                    "final_output": {
                        "tool_execution": {
                            "status": "blocked",
                            "reason": "Capability not registered or contract violation",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            intent_record = _execution_journal.build_record(
                trace_id=trace_id,
                plan_fingerprint=current_fp,
                step_id=step_id,
                capability=capability,
                tool_name=tool_name,
                tool_version=tool_version,
                inputs=inputs,
                status="success",
                reason="intent logged",
                outputs=None,
            )
            _execution_journal.append(intent_record)

            try:
                result = _step_executor.execute_step(
                    plan=_last_plan.to_dict(),
                    step_id=step_id,
                    tool_registry=_tool_registry,
                    docker_runner=_docker_runner,
                    trace_id=trace_id,
                )
                _plan_state.mark_done(step_id)
                outcome_record = _execution_journal.build_record(
                    trace_id=trace_id,
                    plan_fingerprint=current_fp,
                    step_id=step_id,
                    capability=capability,
                    tool_name=tool_name,
                    tool_version=tool_version,
                    inputs=inputs,
                    status="success",
                    reason="execution complete",
                    outputs={
                        "stdout": result.get("stdout"),
                        "stderr": result.get("stderr"),
                        "artifact": result.get("artifact"),
                    },
                )
                _execution_journal.append(outcome_record)
            except Exception as exc:
                _plan_state.mark_failed(step_id)
                outcome_record = _execution_journal.build_record(
                    trace_id=trace_id,
                    plan_fingerprint=current_fp,
                    step_id=step_id,
                    capability=capability,
                    tool_name=tool_name,
                    tool_version=tool_version,
                    inputs=inputs,
                    status="error",
                    reason=str(exc),
                    outputs=None,
                )
                _execution_journal.append(outcome_record)
                raise

            return {
                "final_output": f"Step executed: {step_id}",
                "tool_calls": [result],
                "status": "success",
                "trace_id": trace_id,
            }

        if user_input.strip().lower().startswith("/revoke_autonomy"):
            parts = user_input.strip().split()
            if len(parts) != 2:
                return {
                    "final_output": "Usage: /revoke_autonomy <capability>",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            capability = parts[1]
            try:
                _autonomy_registry.revoke_autonomy(capability)
            except Exception:
                pass

            _journal_exec_contract(
                "capability_revoked",
                {"capability": capability},
            )

            record = _execution_journal.build_record(
                trace_id=trace_id,
                plan_fingerprint="",
                step_id="",
                capability=capability,
                tool_name="",
                tool_version="",
                inputs={},
                status="blocked",
                reason="Autonomy revoked",
                outputs=None,
            )
            _execution_journal.append(record)

            return {
                "final_output": {
                    "autonomy": {
                        "status": "revoked",
                        "capability": capability,
                    }
                },
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        memory_entry = _memory_router.route_write(user_input)
        if memory_entry:
            _memory_store.write(memory_entry, trace_id=trace_id)
            return {
                "final_output": "Memory saved.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        read_scope = _memory_reader.route_read(user_input)
        if read_scope:
            memories = _memory_store.query(scope=read_scope, trace_id=trace_id)
            formatted = "\n".join([m["content"] for m in memories]) or "No memories found."
            return {
                "final_output": formatted,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        tool_id = _tool_router.route(user_input)

        if tool_id:
            assert_no_tool_execution_without_registry(tool_id, _tool_registry)
            spec = _tool_registry.get(tool_id)
            result = _docker_runner.run(
                tool_spec=spec,
                image="billy-hello",
                args=[],
                trace_id=trace_id,
            )
            return {
                "final_output": f"Tool executed: {tool_id}",
                "tool_calls": [result],
                "status": "success",
                "trace_id": trace_id,
            }

        return {
            "final_output": self.ask(user_input),
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
        }


runtime = BillyRuntime(config=None)


def run_turn(user_input: str, session_context: dict):
    return runtime.run_turn(user_input=user_input, session_context=session_context)
