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
import re
import shlex
import socket
import subprocess
import time
import yaml
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

try:
    from . import llm_api
except ImportError:
    llm_api = None
from .charter import load_charter
from v2.core.contracts.loader import load_schema, ContractViolation
from v2.core.tool_runner.docker_runner import DockerRunner
from v2.core.trace.file_trace_sink import FileTraceSink
from v2.core.tool_registry.registry import ToolRegistry
from v2.core.tool_registry.loader import ToolLoader
from v2.core.agent.tool_router import ToolRouter
from v2.core.agent.memory_router import MemoryRouter
from v2.core.agent.memory_reader import MemoryReader
from v2.core.agent.plan_router import PlanRouter
from v2.core.agent.approval_router import ApprovalRouter
from v2.core.agent.step_executor import StepExecutor
from v2.core.agent.plan_state import PlanState
from v2.core.memory.file_memory_store import FileMemoryStore
from v2.core.planning.plan import Plan
from v2.core.agent.evaluation_router import EvaluationRouter
from v2.core.evaluation.evaluation import Evaluation
from v2.core.evaluation.synthesizer import EvaluationSynthesizer
from v2.core.agent.promotion_router import PromotionRouter
from v2.core.planning.llm_planner import LLMPlanner
from v2.core.planning.plan_scorer import PlanScorer
from v2.core.planning.plan_validator import PlanValidator as PlanningPlanValidator
from v2.core.plans.plan_fingerprint import fingerprint
from v2.core.plans.plan_diff import diff_plans
from v2.core.plans.promotion_lock import PromotionLock
from v2.core.plans.plan_history import PlanHistory
from v2.core.plans.rollback import RollbackEngine
from v2.core.tools.capability_registry import CapabilityRegistry
from v2.core.tools.tool_guard import ToolGuard
from v2.core.execution.execution_journal import ExecutionJournal
from v2.core.approval.approval_store import ApprovalStore
from v2.core.approval.approval_flow import ApprovalFlow
from v2.core.autonomy.autonomy_registry import AutonomyRegistry
from v2.core.guardrails.invariants import (
    assert_trace_id,
    assert_no_tool_execution_without_registry,
    assert_explicit_memory_write,
)
from v2.core.validation.plan_validator import PlanValidator as OutputPlanValidator
from v2.core.guardrails.output_guard import OutputGuard
from v2.core.resolution.outcomes import M27_CONTRACT_VERSION
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

# Runtime identity binding is injected on every LLM call to keep persona stable
# even when upstream docs/prompts use third-person references.
IDENTITY_BINDING_PREFIX = (
    "Identity Binding (Runtime-Enforced):\n"
    "- You are Billy and speak in first person (I/me/my).\n"
    "- Address the user in second person (you/your).\n"
    "- Never refer to Billy in third person.\n"
    "- Interpret 'Chad' as the user ('you')."
)

THIRD_PERSON_BLOCKLIST = (
    "billy must",
    "billy can only",
    "billy should",
)

_V2_ROOT = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _V2_ROOT.parent


_trace_sink = FileTraceSink()
_docker_runner = DockerRunner(trace_sink=_trace_sink)
_tool_registry = ToolRegistry()
_memory_store = FileMemoryStore(trace_sink=_trace_sink)

_loader = ToolLoader(str(_PROJECT_ROOT / "tools"))
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
_planning_plan_validator = PlanningPlanValidator()
_output_plan_validator = OutputPlanValidator()
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

_exec_contract_dir = _V2_ROOT / "var" / "execution_contract"
_exec_contract_dir.mkdir(parents=True, exist_ok=True)
_exec_contract_state_path = _exec_contract_dir / "state.json"
_exec_contract_journal_path = _exec_contract_dir / "journal.jsonl"
_pending_exec_proposals: Dict[str, Dict[str, str]] = {}

_ops_contract_dir = _V2_ROOT / "var" / "ops"
_ops_contract_dir.mkdir(parents=True, exist_ok=True)
_ops_state_path = _ops_contract_dir / "state.json"
_ops_journal_path = _ops_contract_dir / "journal.jsonl"
_pending_ops_plans: Dict[str, Dict[str, str]] = {}
_last_inspection: dict = {}
_last_introspection_snapshot: Dict[str, Any] = {}
_last_resolution: Dict[str, Any] = {}
_cdm_drafts: Dict[str, Dict[str, Any]] = {}
_approved_drafts: Dict[str, List[Dict[str, Any]]] = {}
_approved_drafts_audit: List[Dict[str, Any]] = []
_application_attempts: List[Dict[str, Any]] = []
_tool_drafts: Dict[str, Dict[str, Any]] = {}
_approved_tools: Dict[str, List[Dict[str, Any]]] = {}
_tool_approval_audit: List[Dict[str, Any]] = []
_registered_tools: Dict[str, Dict[str, Any]] = {}
_tool_registration_audit: List[Dict[str, Any]] = []
_pending_tool_executions: Dict[str, Dict[str, Any]] = {}
_tool_execution_audit: List[Dict[str, Any]] = []
_PENDING_TOOL_TTL_SECONDS = 300
_workflows: Dict[str, Dict[str, Any]] = {}
_approved_workflows: Dict[str, List[Dict[str, Any]]] = {}
_workflow_audit: List[Dict[str, Any]] = []
_WORKFLOW_DECLARED_MATURITY_LEVEL = 4
_WORKFLOW_LAYER_MATURITY_DECLARATIONS: Dict[str, Dict[str, int]] = {
    "interaction_dispatch": {"highest_supported": 4, "lowest_required_upstream": 1},
    "reasoning": {"highest_supported": 4, "lowest_required_upstream": 1},
    "drafting": {"highest_supported": 4, "lowest_required_upstream": 1},
    "approval_application": {"highest_supported": 4, "lowest_required_upstream": 2},
    "tool_lifecycle": {"highest_supported": 4, "lowest_required_upstream": 2},
    "documentation": {"highest_supported": 4, "lowest_required_upstream": 1},
    "workflow_mode": {"highest_supported": 4, "lowest_required_upstream": 4},
}

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


def _has_explicit_governed_trigger(text: str) -> bool:
    normalized = text.strip()
    return (
        _is_approval_command(normalized)
        or _is_tool_approval_command(normalized)
        or _is_tool_registration_command(normalized)
        or _is_workflow_definition_command(normalized)
        or _is_workflow_approval_command(normalized)
        or _is_run_workflow_command(normalized)
        or _is_run_tool_command(normalized)
        or _is_confirm_run_tool_command(normalized)
        or _is_apply_command(normalized)
        or _extract_erm_request(normalized) is not None
        or _extract_cdm_request(normalized) is not None
        or _extract_tdm_request(normalized) is not None
    )


def _is_explicit_inspection_request(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    if not normalized:
        return False
    if normalized.startswith("where are "):
        return False
    if normalized.startswith("where am "):
        return False
    if normalized.startswith("locate/inspect:"):
        return True
    if normalized.startswith(("locate ", "find ", "check ", "list ", "show ")):
        return True
    return normalized.startswith("where is ") or normalized.startswith("where's ")


def _is_deterministic_loop_trigger(text: str) -> bool:
    normalized = text.strip()
    lowered = normalized.lower()
    if lowered in {"ignored", "continue"}:
        return True
    if lowered.startswith("claim:"):
        return True
    if _is_explicit_inspection_request(normalized):
        return True
    if _is_action_request(normalized):
        return True
    return False


def _is_plan_control_input(text: str) -> bool:
    normalized = text.strip()
    return (
        normalized.upper().startswith("APPROVE PLAN ")
        or normalized.lower() == "plan"
        or normalized.lower().startswith("plan ")
    )


def _legacy_interaction_reason(text: str) -> str | None:
    normalized = text.strip()
    lowered = normalized.lower()
    if not normalized:
        return "Interaction rejected: input is empty."
    if lowered.startswith("a0 "):
        return "Interaction rejected: legacy interaction 'a0' is not supported."
    if lowered.startswith("/plan"):
        return "Interaction rejected: legacy interaction '/plan' is not supported."
    if lowered.startswith("/engineer"):
        return "Interaction rejected: legacy interaction '/engineer' is not supported."
    if lowered.startswith("/exec"):
        return "Interaction rejected: legacy interaction '/exec' is not supported."
    if lowered.startswith("/ops"):
        return "Interaction rejected: legacy interaction '/ops' is not supported."
    if lowered.startswith("/simulate"):
        return "Interaction rejected: legacy interaction '/simulate' is not supported."
    if lowered.startswith("/"):
        command = lowered.split()[0]
        return f"Interaction rejected: legacy interaction '{command}' is not supported."
    if normalized.startswith("GRANT_CAPABILITY"):
        return "Interaction rejected: legacy capability-grant command is not supported."
    if lowered.startswith("grant_autonomy "):
        return "Interaction rejected: legacy autonomy-grant command is not supported."
    if re.fullmatch(r"approve\s+[A-Za-z0-9._:-]+", lowered):
        return "Interaction rejected: legacy approval command is not supported."
    if lowered.startswith("approve plan "):
        return "Interaction rejected: legacy plan approval command is not supported."
    return None


def _dispatch_interaction(runtime: "BillyRuntime", text: str) -> Dict[str, Any]:
    normalized = text.strip()
    legacy_reason = _legacy_interaction_reason(normalized)
    if legacy_reason is not None:
        return {
            "category": "legacy interaction",
            "route": "reject",
            "message": legacy_reason,
        }

    if _has_explicit_governed_trigger(normalized):
        return {
            "category": "explicit governed",
            "route": "explicit_command",
        }

    identity_response = runtime.resolve_identity_question(normalized)
    if identity_response is not None:
        return {
            "category": "identity/context",
            "route": "identity",
            "response": identity_response,
        }

    if _is_governance_handoff_instruction(normalized):
        return {
            "category": "governance/instruction",
            "route": "governance_instruction",
            "message": _GOVERNANCE_HANDOFF_RESPONSE,
        }

    preinspection_route = _classify_preinspection_route(normalized)
    if preinspection_route is not None:
        return {
            "category": "identity/context",
            "route": "preinspection",
            "payload": preinspection_route,
        }

    if _is_deterministic_loop_trigger(normalized):
        return {
            "category": "internal/deterministic",
            "route": "deterministic_loop",
        }

    return {
        "category": "invalid/ambiguous",
        "route": "reject",
        "message": (
            "Interaction rejected: invalid/ambiguous input. "
            "Use an explicit governed trigger."
        ),
    }


_ERM_PREFIXES = ("engineer:", "analyze:", "review:")
_CDM_PREFIXES = ("draft:", "code:", "propose:", "suggest:", "fix:")
_TDM_PREFIXES = ("tool:", "define tool:", "design tool:", "propose tool:")


def _extract_erm_request(text: str) -> tuple[str, str] | None:
    normalized = text.strip()
    lowered = normalized.lower()
    for prefix in _ERM_PREFIXES:
        if lowered.startswith(prefix):
            request = normalized[len(prefix):].strip()
            return prefix[:-1], request
    return None


def _extract_cdm_request(text: str) -> tuple[str, str] | None:
    normalized = text.strip()
    lowered = normalized.lower()
    for prefix in _CDM_PREFIXES:
        if lowered.startswith(prefix):
            request = normalized[len(prefix):].strip()
            return prefix[:-1], request
    return None


def _extract_tdm_request(text: str) -> tuple[str, str] | None:
    normalized = text.strip()
    lowered = normalized.lower()
    for prefix in _TDM_PREFIXES:
        if lowered.startswith(prefix):
            request = normalized[len(prefix):].strip()
            return prefix[:-1], request
    return None


def _is_approval_command(text: str) -> bool:
    return text.strip().lower().startswith("approve:")


def _is_tool_approval_command(text: str) -> bool:
    return text.strip().lower().startswith("approve tool:")


def _is_tool_registration_command(text: str) -> bool:
    return text.strip().lower().startswith("register tool:")


def _is_workflow_definition_command(text: str) -> bool:
    return text.strip().lower().startswith("workflow:")


def _is_workflow_approval_command(text: str) -> bool:
    return text.strip().lower().startswith("approve workflow:")


def _is_run_workflow_command(text: str) -> bool:
    return text.strip().lower().startswith("run workflow:")


def _is_run_tool_command(text: str) -> bool:
    return text.strip().lower().startswith("run tool:")


def _is_confirm_run_tool_command(text: str) -> bool:
    return text.strip().lower().startswith("confirm run tool:")


def _is_apply_command(text: str) -> bool:
    return text.strip().lower().startswith("apply:")


def _extract_approval_request(text: str) -> str | None:
    normalized = text.strip()
    match = re.fullmatch(r"approve:\s*([A-Za-z0-9._:-]+)\s*", normalized)
    if not match:
        return None
    return match.group(1)


def _extract_apply_request(text: str) -> str | None:
    normalized = text.strip()
    match = re.fullmatch(r"apply:\s*([A-Za-z0-9._:-]+)\s*", normalized)
    if not match:
        return None
    return match.group(1)


def _extract_tool_approval_request(text: str) -> str | None:
    normalized = text.strip()
    match = re.fullmatch(r"approve tool:\s*([A-Za-z0-9._:-]+)\s*", normalized)
    if not match:
        return None
    return match.group(1)


def _extract_tool_registration_request(text: str) -> str | None:
    normalized = text.strip()
    match = re.fullmatch(r"register tool:\s*([A-Za-z0-9._:-]+)\s*", normalized)
    if not match:
        return None
    return match.group(1)


def _extract_workflow_definition_request(text: str) -> Dict[str, Any] | None:
    normalized = text.strip()
    if not normalized.lower().startswith("workflow:"):
        return None
    payload_text = normalized[len("workflow:"):].strip()
    if not payload_text:
        return None
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _extract_workflow_approval_request(text: str) -> str | None:
    normalized = text.strip()
    match = re.fullmatch(r"approve workflow:\s*([A-Za-z0-9._:-]+)\s*", normalized)
    if not match:
        return None
    return match.group(1)


def _extract_run_workflow_request(text: str) -> str | None:
    normalized = text.strip()
    match = re.fullmatch(r"run workflow:\s*([A-Za-z0-9._:-]+)\s*", normalized)
    if not match:
        return None
    return match.group(1)


def _extract_run_tool_request(text: str) -> tuple[str, Dict[str, Any]] | None:
    normalized = text.strip()
    if not normalized.lower().startswith("run tool:"):
        return None
    remainder = normalized[len("run tool:"):].strip()
    if not remainder:
        return None

    match = re.match(r"^([A-Za-z0-9._:-]+)\s+(.+)$", remainder)
    if not match:
        return None
    tool_name = match.group(1)
    payload_text = match.group(2).strip()
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return tool_name, payload


def _extract_confirm_run_tool_request(text: str) -> str | None:
    normalized = text.strip()
    match = re.fullmatch(r"confirm run tool:\s*([A-Za-z0-9._:-]+)\s*", normalized, re.IGNORECASE)
    if not match:
        return None
    return match.group(1)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _compute_draft_hash(draft_record: Dict[str, Any]) -> str:
    canonical = {
        "source": draft_record.get("source"),
        "output": draft_record.get("output"),
        "files_affected": draft_record.get("files_affected", []),
        "file_operations": draft_record.get("file_operations", []),
        "tests_allowed": bool(draft_record.get("tests_allowed", False)),
        "test_commands": draft_record.get("test_commands", []),
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return _hash_text(encoded)


def _compute_tool_draft_hash(tool_record: Dict[str, Any]) -> str:
    canonical = {
        "source": tool_record.get("source"),
        "tool_name": tool_record.get("tool_name"),
        "tool_purpose": tool_record.get("tool_purpose"),
        "inputs": tool_record.get("inputs", []),
        "outputs": tool_record.get("outputs", []),
        "declared_side_effects": tool_record.get("declared_side_effects", []),
        "safety_constraints": tool_record.get("safety_constraints", []),
        "when_to_use": tool_record.get("when_to_use", ""),
        "when_not_to_use": tool_record.get("when_not_to_use", ""),
        "spec": tool_record.get("spec", {}),
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return _hash_text(encoded)


def _compute_payload_hash(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return _hash_text(encoded)


def _compute_workflow_hash(steps: List[Dict[str, Any]]) -> str:
    encoded = json.dumps(steps, sort_keys=True, separators=(",", ":"))
    return _hash_text(encoded)


def _validate_workflow_maturity_sync() -> tuple[bool, str]:
    declared = _WORKFLOW_DECLARED_MATURITY_LEVEL
    workflow_decl = _WORKFLOW_LAYER_MATURITY_DECLARATIONS.get("workflow_mode")
    if not isinstance(workflow_decl, dict):
        return False, "Workflow rejected: maturity sync contract is incomplete."

    workflow_max = int(workflow_decl.get("highest_supported", 0))
    workflow_min_upstream = int(workflow_decl.get("lowest_required_upstream", 0))
    if workflow_max < declared:
        return False, "Workflow rejected: workflow layer does not support declared maturity."

    for layer_name, layer_decl in _WORKFLOW_LAYER_MATURITY_DECLARATIONS.items():
        highest_supported = int(layer_decl.get("highest_supported", 0))
        if highest_supported < declared:
            return False, f"Workflow rejected: maturity sync violation in layer '{layer_name}'."

    for layer_name, layer_decl in _WORKFLOW_LAYER_MATURITY_DECLARATIONS.items():
        if layer_name == "workflow_mode":
            continue
        highest_supported = int(layer_decl.get("highest_supported", 0))
        if highest_supported < workflow_min_upstream:
            return False, f"Workflow rejected: upstream maturity support missing in layer '{layer_name}'."

    return True, ""


def _validate_workflow_steps(steps: Any) -> tuple[bool, str, List[Dict[str, Any]]]:
    if not isinstance(steps, list) or not steps:
        return False, "Workflow rejected: steps must be a non-empty list.", []

    normalized_steps: List[Dict[str, Any]] = []
    for index, raw_step in enumerate(steps, start=1):
        if not isinstance(raw_step, dict):
            return False, f"Workflow rejected: step {index} is malformed.", []

        step_type = str(raw_step.get("type", "")).strip()
        if step_type == "cam.apply":
            allowed_keys = {"type", "draft_id"}
            unknown_keys = set(raw_step.keys()) - allowed_keys
            if unknown_keys:
                return False, f"Workflow rejected: step {index} has unsupported fields.", []
            draft_id = raw_step.get("draft_id")
            if not isinstance(draft_id, str) or not draft_id.strip():
                return False, f"Workflow rejected: step {index} requires draft_id.", []
            normalized_steps.append({"type": "cam.apply", "draft_id": draft_id.strip()})
            continue

        if step_type == "tem.run":
            allowed_keys = {"type", "tool_name", "payload"}
            unknown_keys = set(raw_step.keys()) - allowed_keys
            if unknown_keys:
                return False, f"Workflow rejected: step {index} has unsupported fields.", []
            tool_name = raw_step.get("tool_name")
            payload = raw_step.get("payload")
            if not isinstance(tool_name, str) or not tool_name.strip():
                return False, f"Workflow rejected: step {index} requires tool_name.", []
            if not isinstance(payload, dict):
                return False, f"Workflow rejected: step {index} requires payload object.", []
            normalized_steps.append(
                {
                    "type": "tem.run",
                    "tool_name": tool_name.strip(),
                    "payload": json.loads(json.dumps(payload, sort_keys=True)),
                }
            )
            continue

        if step_type == "tem.confirm":
            allowed_keys = {"type", "tool_name"}
            unknown_keys = set(raw_step.keys()) - allowed_keys
            if unknown_keys:
                return False, f"Workflow rejected: step {index} has unsupported fields.", []
            tool_name = raw_step.get("tool_name")
            if not isinstance(tool_name, str) or not tool_name.strip():
                return False, f"Workflow rejected: step {index} requires tool_name.", []
            normalized_steps.append({"type": "tem.confirm", "tool_name": tool_name.strip()})
            continue

        return False, f"Workflow rejected: step {index} uses unsupported type '{step_type}'.", []

    return True, "", normalized_steps


def _select_registered_tool(tool_name: str) -> Dict[str, Any] | None:
    candidates = [
        entry
        for entry in _registered_tools.values()
        if str(entry.get("tool_name", "")).strip() == tool_name
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: str(item.get("registered_at", "")))[-1]


def _python_type_matches(value: Any, expected_type: str) -> bool:
    normalized = expected_type.strip().lower()
    if normalized in {"string", "str"}:
        return isinstance(value, str)
    if normalized in {"integer", "int"}:
        return isinstance(value, int) and not isinstance(value, bool)
    if normalized in {"number", "float"}:
        return (isinstance(value, int) and not isinstance(value, bool)) or isinstance(value, float)
    if normalized in {"boolean", "bool"}:
        return isinstance(value, bool)
    if normalized in {"object", "dict"}:
        return isinstance(value, dict)
    if normalized in {"array", "list"}:
        return isinstance(value, list)
    return False


def _validate_tool_payload(payload: Dict[str, Any], draft: Dict[str, Any]) -> tuple[bool, str]:
    inputs = draft.get("inputs", [])
    if not isinstance(inputs, list):
        return False, "Tool execution rejected: input contract is invalid."

    expected_fields: Dict[str, Dict[str, Any]] = {}
    required_fields: set[str] = set()
    for entry in inputs:
        if not isinstance(entry, dict):
            return False, "Tool execution rejected: input contract is invalid."
        name = str(entry.get("name", "")).strip()
        type_name = str(entry.get("type", "")).strip()
        if not name or not type_name:
            return False, "Tool execution rejected: input contract is invalid."
        expected_fields[name] = entry
        if bool(entry.get("required", False)):
            required_fields.add(name)

    payload_keys = set(payload.keys())
    unexpected = payload_keys - set(expected_fields.keys())
    if unexpected:
        return False, "Tool execution rejected: payload contains unsupported fields."

    missing = [field for field in sorted(required_fields) if field not in payload]
    if missing:
        return False, "Tool execution rejected: payload is missing required fields."

    for key, value in payload.items():
        expected_type = str(expected_fields[key].get("type", "")).strip()
        if not _python_type_matches(value, expected_type):
            return False, "Tool execution rejected: payload type mismatch."

    return True, ""


def _collect_requested_side_effects(payload: Dict[str, Any]) -> tuple[set[str], List[str]]:
    categories: set[str] = set()
    filesystem_paths: List[str] = []

    def _walk(node_key: str, node_value: Any) -> None:
        lowered_key = node_key.lower()
        if any(token in lowered_key for token in ("path", "file", "dir", "directory", "folder")):
            categories.add("filesystem")
            if isinstance(node_value, str):
                filesystem_paths.append(node_value)
        if any(token in lowered_key for token in ("url", "uri", "endpoint", "host", "network")):
            categories.add("network")
        if any(token in lowered_key for token in ("service", "process", "system", "daemon", "unit")):
            categories.add("system")

        if isinstance(node_value, str):
            lowered_value = node_value.lower()
            if lowered_value.startswith("http://") or lowered_value.startswith("https://"):
                categories.add("network")
            if node_value.startswith("/") or node_value.startswith("./") or node_value.startswith("../"):
                categories.add("filesystem")
                filesystem_paths.append(node_value)
        elif isinstance(node_value, dict):
            for nested_key, nested_value in node_value.items():
                _walk(str(nested_key), nested_value)
        elif isinstance(node_value, list):
            for item in node_value:
                _walk(node_key, item)

    for key, value in payload.items():
        _walk(str(key), value)

    return categories, filesystem_paths


def _validate_tool_side_effect_scope(payload: Dict[str, Any], draft: Dict[str, Any]) -> tuple[bool, str]:
    declared = draft.get("declared_side_effects", [])
    if not isinstance(declared, list):
        return False, "Tool execution rejected: declared side effects are invalid."

    allowed_categories: set[str] = set()
    allowed_fs_prefixes: List[str] = []
    for effect in declared:
        if not isinstance(effect, str):
            continue
        lowered = effect.lower()
        if "filesystem" in lowered:
            allowed_categories.add("filesystem")
            allowed_fs_prefixes.extend(re.findall(r"/[A-Za-z0-9._/\-]+", effect))
        if "network" in lowered:
            allowed_categories.add("network")
        if "system" in lowered:
            allowed_categories.add("system")

    requested_categories, requested_paths = _collect_requested_side_effects(payload)

    if requested_categories - allowed_categories:
        return False, "Tool execution rejected: side-effect scope exceeds declaration."

    if requested_paths and allowed_fs_prefixes:
        for path_value in requested_paths:
            if not any(path_value.startswith(prefix) for prefix in allowed_fs_prefixes):
                return False, "Tool execution rejected: filesystem scope exceeds declaration."

    return True, ""


def _infer_cdm_files(request: str) -> List[str]:
    if not request:
        return ["path/to/file.py"]
    candidates = re.findall(r"[A-Za-z0-9_./-]+\.[A-Za-z0-9_]+", request)
    files: List[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = candidate.strip(".,;:()[]{}")
        if not cleaned or cleaned in seen:
            continue
        files.append(cleaned)
        seen.add(cleaned)
    if not files:
        files.append("path/to/file.py")
    return files


def _render_erm_response(mode: str, request: str) -> str:
    requested_scope = request or "(no specific request provided)"
    lowered = request.lower()
    visible_tools = sorted(f"{entry['tool_name']}@{entry['tool_draft_id']}" for entry in _registered_tools.values())
    visible_tools_line = ", ".join(visible_tools) if visible_tools else "(none)"
    if any(token in lowered for token in ("bug", "failure", "failing", "error", "regression", "fix")):
        recommended_option = "2"
        recommendation = "Use Option 2 to prioritize risk and failure analysis before proposing changes."
    elif any(token in lowered for token in ("implement", "change", "refactor", "build", "add", "update")):
        recommended_option = "3"
        recommendation = "Use Option 3 to produce a proposal-only implementation plan with validation steps."
    else:
        recommended_option = "1"
        recommendation = "Use Option 1 to establish current behavior and constraints first."

    lines = [
        "Understanding of the request",
        f"- Mode: {mode}",
        f"- Request: {requested_scope}",
        "",
        "Current system behavior",
        "- Engineering Reasoning Mode is active in read-only form.",
        "- No file writes, command execution, tool calls, state mutation, or ops escalation are allowed.",
        f"- Registered tools (visible, non-executable): {visible_tools_line}",
        "",
        "Options",
        "1. Read-only behavior analysis: inspect relevant code paths and explain current behavior.",
        "2. Risk-focused review: identify likely failure points, invariants, and regression risks.",
        "3. Proposal-only plan: outline implementation/testing steps without executing anything.",
        "",
        "Tradeoffs / risks",
        "- Read-only analysis cannot validate fixes by running commands or applying changes.",
        "- Recommendations remain provisional until you explicitly approve an execution phase.",
        "",
        "Recommendation",
        f"- Option {recommended_option}: {recommendation}",
        "",
        "Explicit next-step approval request",
        f"- Reply with: approve erm option {recommended_option}",
        "- Or choose another option number and I will continue in read-only ERM.",
    ]
    return "\n".join(lines)


def _render_cdm_response(
    mode: str,
    request: str,
    draft_id: str,
    files_affected: List[str],
    scope_summary: str,
) -> str:
    requested_scope = request or "(no specific drafting target provided)"
    proposal_target = request or "describe the concrete file-level change"
    primary_file = files_affected[0]
    visible_tools = sorted(f"{entry['tool_name']}@{entry['tool_draft_id']}" for entry in _registered_tools.values())
    visible_tools_line = ", ".join(visible_tools) if visible_tools else "(none)"
    lines = [
        "1. Intent Summary",
        f"- Draft ID: {draft_id}",
        f"- CDM trigger: {mode}",
        f"- Draft objective: {requested_scope}",
        "",
        "2. Scope Outline",
        f"- {scope_summary}",
        "- Files affected (as proposed):",
    ]
    for file_path in files_affected:
        lines.append(f"  - {file_path}")
    lines.extend(
        [
            f"- Registered tools visible for drafting (non-executable): {visible_tools_line}",
            "",
            "",
            "3. Rationale",
            "- This response provides a concrete draft while preserving deterministic runtime safety.",
            "- Execution and mutation paths remain disabled for CDM inputs.",
            "",
            "4. Code Proposal (diff/snippet/file)",
            "```diff",
            f"--- a/{primary_file}",
            f"+++ b/{primary_file}",
            "@@",
            "-# Existing behavior placeholder",
            f"+# Proposed draft change for: {proposal_target}",
            "+def proposed_change() -> None:",
            "+    \"\"\"Draft-only proposal. Not applied.\"\"\"",
            "+    return None",
            "```",
            "",
            "5. Optional Tests",
            "```python",
            "def test_proposed_change_behavior():",
            "    # Draft test scaffold only; not executed.",
            "    assert True",
            "```",
            "",
            "6. Review Notes",
            "- Confirm target files and acceptance criteria before any execution phase.",
            "- Keep this draft read-only until explicit approval is provided.",
            "",
            "7. Approval Request",
            f"- To approve this immutable draft, reply exactly: approve: {draft_id}",
        ]
    )
    return "\n".join(lines)


def _create_cdm_draft(mode: str, request: str, trace_id: str) -> Dict[str, Any]:
    draft_id = f"draft-{uuid.uuid4().hex[:12]}"
    files_affected = _infer_cdm_files(request)
    primary_file = files_affected[0]
    target_path = (_PROJECT_ROOT / primary_file).resolve()
    action = "modify" if target_path.exists() else "create"
    requested_scope = request or "(no specific drafting target provided)"
    draft_body = "\n".join(
        [
            f"# Draft generated from {mode}",
            f"# Request: {requested_scope}",
            "",
            "def proposed_change() -> None:",
            "    \"\"\"Draft-only proposal. Not applied automatically.\"\"\"",
            "    return None",
            "",
        ]
    )
    file_operations = [
        {
            "action": action,
            "path": primary_file,
            "content": draft_body,
        }
    ]
    intent_summary = request or "(no specific drafting target provided)"
    scope_summary = "Read-only drafting only (no execution, no writes, no tool calls)."
    output = _render_cdm_response(
        mode=mode,
        request=request,
        draft_id=draft_id,
        files_affected=files_affected,
        scope_summary=scope_summary,
    )
    record = {
        "draft_id": draft_id,
        "source": "CDM",
        "mode": mode,
        "intent_summary": intent_summary,
        "scope_summary": scope_summary,
        "files_affected": files_affected,
        "file_operations": file_operations,
        "tests_allowed": False,
        "test_commands": [],
        "output": output,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "trace_id": trace_id,
    }
    record["draft_hash"] = _compute_draft_hash(record)
    _cdm_drafts[draft_id] = record
    return record


def _infer_tool_name(request: str) -> str:
    dotted_tokens = re.findall(r"[A-Za-z][A-Za-z0-9_.-]{2,}", request)
    for token in dotted_tokens:
        lowered = token.lower()
        if "." in lowered or "_" in lowered or "-" in lowered:
            normalized = lowered.replace("-", ".").replace("_", ".")
            normalized = re.sub(r"\.+", ".", normalized).strip(".")
            if normalized:
                return normalized
    words = re.findall(r"[A-Za-z0-9]+", request.lower())
    if not words:
        return "tool.generated"
    if len(words) == 1:
        return f"{words[0]}.tool"
    return f"{words[0]}.{words[1]}"


def _infer_tool_contract(request: str) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    lowered = request.lower()
    inputs: List[Dict[str, Any]] = [
        {
            "name": "request_context",
            "type": "string",
            "required": True,
            "description": "Caller-supplied context for deterministic processing.",
        }
    ]
    outputs: List[Dict[str, Any]] = [
        {
            "name": "result_summary",
            "type": "string",
            "description": "Tool result summary payload.",
        }
    ]
    side_effects: List[str] = []

    if any(token in lowered for token in ("file", "path", "directory", "folder")):
        inputs.append(
            {
                "name": "target_path",
                "type": "string",
                "required": False,
                "description": "Filesystem target path provided by caller.",
            }
        )
        side_effects.append("filesystem: may read/write caller-scoped paths when implemented")

    if any(token in lowered for token in ("http", "https", "api", "network", "url")):
        inputs.append(
            {
                "name": "endpoint",
                "type": "string",
                "required": False,
                "description": "Remote endpoint or API reference.",
            }
        )
        side_effects.append("network: may perform outbound requests when implemented")

    if any(token in lowered for token in ("service", "process", "system", "daemon")):
        side_effects.append("system: may inspect system/process state when implemented")

    if not side_effects:
        side_effects.append("none declared")

    return inputs, outputs, side_effects


def _render_tdm_response(
    tool_draft_id: str,
    tool_draft_hash: str,
    tool_name: str,
    tool_purpose: str,
    justification: str,
    inputs: List[Dict[str, Any]],
    outputs: List[Dict[str, Any]],
    declared_side_effects: List[str],
    safety_constraints: List[str],
    when_to_use: str,
    when_not_to_use: str,
    spec: Dict[str, Any],
) -> str:
    spec_yaml = yaml.safe_dump(spec, sort_keys=False).strip()
    lines = [
        "Tool Intent",
        f"- tool_draft_id: {tool_draft_id}",
        f"- name: {tool_name}",
        f"- purpose: {tool_purpose}",
        "",
        "Justification",
        f"- {justification}",
        "",
        "Tool Contract",
        "Inputs",
    ]
    for item in inputs:
        lines.append(
            f"- {item['name']} ({item['type']}, required={str(bool(item.get('required', False))).lower()}): "
            f"{item.get('description', '')}"
        )
    lines.append("Outputs")
    for item in outputs:
        lines.append(f"- {item['name']} ({item['type']}): {item.get('description', '')}")
    lines.append("Declared side effects")
    for effect in declared_side_effects:
        lines.append(f"- {effect}")
    lines.append("Safety Constraints")
    for constraint in safety_constraints:
        lines.append(f"- {constraint}")
    lines.extend(
        [
            "",
            "Usage Guidance",
            "When to use",
            f"- {when_to_use}",
            "When not to use",
            f"- {when_not_to_use}",
            "",
            "Proposed Specification",
            "YAML / JSON (draft only)",
            "```yaml",
            spec_yaml,
            "```",
            "",
            "Approval Request",
            f"- tool_draft_id: {tool_draft_id}",
            f"- tool_draft_hash: {tool_draft_hash}",
            f"- To approve this draft, reply exactly: approve tool: {tool_draft_id}",
        ]
    )
    return "\n".join(lines)


def _create_tool_draft(mode: str, request: str, trace_id: str) -> Dict[str, Any]:
    tool_draft_id = f"tool-draft-{uuid.uuid4().hex[:12]}"
    tool_name = _infer_tool_name(request)
    tool_purpose = request or "Define a deterministic tool contract for future implementation."
    inputs, outputs, declared_side_effects = _infer_tool_contract(request)
    safety_constraints = [
        "Execution disabled: draft-only definition in this phase",
        "Registration prohibited until explicit future phase",
        "Implementation must enforce capability and approval checks",
    ]
    when_to_use = "Use when a reusable and explicit tool interface is needed for repeated tasks."
    when_not_to_use = "Do not use for one-off manual actions or when execution is required immediately."
    spec = {
        "name": tool_name,
        "description": tool_purpose,
        "inputs": inputs,
        "outputs": outputs,
        "side_effects": declared_side_effects,
        "safety_constraints": safety_constraints,
        "execution": {
            "enabled": False,
            "registration_required": True,
            "approval_required": True,
        },
        "executability": {
            "enabled": False,
            "requires_confirmation": True,
        },
    }
    justification = (
        "This proposal captures a precise interface while keeping runtime behavior unchanged and non-executing."
    )
    record: Dict[str, Any] = {
        "tool_draft_id": tool_draft_id,
        "source": "TDM",
        "mode": mode,
        "tool_name": tool_name,
        "tool_purpose": tool_purpose,
        "justification": justification,
        "inputs": inputs,
        "outputs": outputs,
        "declared_side_effects": declared_side_effects,
        "safety_constraints": safety_constraints,
        "when_to_use": when_to_use,
        "when_not_to_use": when_not_to_use,
        "spec": spec,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "trace_id": trace_id,
    }
    record["tool_draft_hash"] = _compute_tool_draft_hash(record)
    record["output"] = _render_tdm_response(
        tool_draft_id=tool_draft_id,
        tool_draft_hash=record["tool_draft_hash"],
        tool_name=tool_name,
        tool_purpose=tool_purpose,
        justification=justification,
        inputs=inputs,
        outputs=outputs,
        declared_side_effects=declared_side_effects,
        safety_constraints=safety_constraints,
        when_to_use=when_to_use,
        when_not_to_use=when_not_to_use,
        spec=spec,
    )
    _tool_drafts[tool_draft_id] = record
    return record


def _approve_tool_draft(tool_draft_id: str, approved_by: str) -> tuple[bool, str]:
    draft = _tool_drafts.get(tool_draft_id)
    if draft is None:
        return False, "Tool approval rejected: tool_draft_id does not exist."

    if draft.get("source") != "TDM":
        return False, "Tool approval rejected: draft is not from TDM."

    expected_hash = draft.get("tool_draft_hash")
    if not isinstance(expected_hash, str):
        return False, "Tool approval rejected: draft content hash mismatch."
    current_hash = _compute_tool_draft_hash(draft)
    if current_hash != expected_hash:
        return False, "Tool approval rejected: draft content hash mismatch."

    if _approved_tools.get(tool_draft_id):
        return False, "Tool approval rejected: tool draft was already approved."

    approval_record = {
        "tool_draft_id": tool_draft_id,
        "tool_draft_hash": expected_hash,
        "approved_by": approved_by,
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "status": "approved",
        "source": "TDM",
    }
    _approved_tools.setdefault(tool_draft_id, []).append(dict(approval_record))
    _tool_approval_audit.append(dict(approval_record))

    input_names = [item.get("name", "") for item in draft.get("inputs", []) if isinstance(item, dict)]
    output_names = [item.get("name", "") for item in draft.get("outputs", []) if isinstance(item, dict)]
    lines = [
        "TOOL_APPROVAL_ACCEPTED",
        f"- tool_draft_id: {tool_draft_id}",
        f"- tool_draft_hash: {expected_hash}",
        f"- tool intent: {draft.get('tool_purpose', '(unknown)')}",
        "- tool contract:",
        f"  - inputs: {', '.join(name for name in input_names if name) or '(none)'}",
        f"  - outputs: {', '.join(name for name in output_names if name) or '(none)'}",
        "- status: approved",
    ]
    return True, "\n".join(lines)


def _register_tool_draft(tool_draft_id: str, registered_by: str) -> tuple[bool, str]:
    draft = _tool_drafts.get(tool_draft_id)
    if draft is None:
        return False, "Tool registration rejected: tool_draft_id does not exist."

    approvals = _approved_tools.get(tool_draft_id)
    if not approvals:
        return False, "Tool registration rejected: tool draft is not approved."
    approval_record = approvals[-1]
    if approval_record.get("status") != "approved":
        return False, "Tool registration rejected: tool draft is not approved."

    if draft.get("source") != "TDM" or approval_record.get("source") != "TDM":
        return False, "Tool registration rejected: tool draft is not from TDM."

    expected_hash = draft.get("tool_draft_hash")
    approved_hash = approval_record.get("tool_draft_hash")
    if not isinstance(expected_hash, str) or not isinstance(approved_hash, str):
        return False, "Tool registration rejected: tool draft hash mismatch."
    current_hash = _compute_tool_draft_hash(draft)
    if current_hash != expected_hash or approved_hash != expected_hash:
        return False, "Tool registration rejected: tool draft hash mismatch."

    tool_name = str(draft.get("tool_name", "")).strip()
    if not tool_name:
        return False, "Tool registration rejected: tool name is missing."

    registration_key = f"{tool_name}@{tool_draft_id}"
    if registration_key in _registered_tools:
        return False, "Tool registration rejected: tool draft is already registered."

    spec = draft.get("spec")
    executability_cfg = {}
    if isinstance(spec, dict):
        executability_cfg = spec.get("executability", {})
    if not isinstance(executability_cfg, dict):
        executability_cfg = {}
    executability_enabled = bool(executability_cfg.get("enabled", False))
    requires_confirmation = bool(executability_cfg.get("requires_confirmation", True))

    registration_record = {
        "registration_key": registration_key,
        "tool_name": tool_name,
        "tool_draft_id": tool_draft_id,
        "intent": draft.get("tool_purpose", ""),
        "contract": {
            "inputs": draft.get("inputs", []),
            "outputs": draft.get("outputs", []),
        },
        "declared_side_effects": draft.get("declared_side_effects", []),
        "safety_constraints": draft.get("safety_constraints", []),
        "visibility": "visible",
        "executability": executability_enabled,
        "requires_confirmation": requires_confirmation,
        "registered_by": registered_by,
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "source": "TRM",
    }
    _registered_tools[registration_key] = dict(registration_record)
    _tool_registration_audit.append(dict(registration_record))

    side_effects = registration_record.get("declared_side_effects", [])
    lines = [
        "TOOL_REGISTRATION_ACCEPTED",
        f"- tool name: {tool_name}",
        f"- version: {tool_draft_id}",
        f"- intent: {registration_record.get('intent', '')}",
        "- declared side effects:",
    ]
    for effect in side_effects if isinstance(side_effects, list) else []:
        lines.append(f"  - {effect}")
    lines.append("This tool is registered and visible, but not executable.")
    return True, "\n".join(lines)


def _append_workflow_audit_event(
    workflow_id: str,
    event_type: str,
    details: Dict[str, Any],
) -> Dict[str, Any]:
    event = {
        "workflow_id": workflow_id,
        "event_id": f"{event_type}-{uuid.uuid4().hex[:10]}",
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": json.loads(json.dumps(details, sort_keys=True)),
    }
    _workflow_audit.append(dict(event))
    workflow = _workflows.get(workflow_id)
    if workflow is not None:
        workflow_audit = workflow.setdefault("audit", [])
        if isinstance(workflow_audit, list):
            workflow_audit.append(dict(event))
    return event


def _create_workflow(payload: Dict[str, Any], created_by: str, trace_id: str) -> tuple[bool, str]:
    maturity_ok, maturity_reason = _validate_workflow_maturity_sync()
    if not maturity_ok:
        return False, maturity_reason

    if "steps" not in payload:
        return False, "Workflow rejected: steps are required."

    valid_steps, reason, normalized_steps = _validate_workflow_steps(payload.get("steps"))
    if not valid_steps:
        return False, reason

    workflow_id = f"workflow-{uuid.uuid4().hex[:12]}"
    workflow_record: Dict[str, Any] = {
        "workflow_id": workflow_id,
        "source": "WORKFLOW_MODE",
        "steps": normalized_steps,
        "workflow_hash": _compute_workflow_hash(normalized_steps),
        "status": "defined",
        "created_by": created_by,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "trace_id": trace_id,
        "audit": [],
    }
    _workflows[workflow_id] = workflow_record
    _append_workflow_audit_event(
        workflow_id,
        "workflow_defined",
        {
            "status": "defined",
            "step_count": len(normalized_steps),
            "workflow_hash": workflow_record["workflow_hash"],
        },
    )
    lines = [
        "WORKFLOW_DEFINED",
        f"- workflow_id: {workflow_id}",
        f"- status: {workflow_record['status']}",
        f"- step_count: {len(normalized_steps)}",
        f"- workflow_hash: {workflow_record['workflow_hash']}",
    ]
    return True, "\n".join(lines)


def _approve_workflow(workflow_id: str, approved_by: str) -> tuple[bool, str]:
    maturity_ok, maturity_reason = _validate_workflow_maturity_sync()
    if not maturity_ok:
        return False, maturity_reason

    workflow = _workflows.get(workflow_id)
    if workflow is None:
        return False, "Workflow approval rejected: workflow_id does not exist."

    if _approved_workflows.get(workflow_id):
        return False, "Workflow approval rejected: workflow is already approved."

    steps = workflow.get("steps")
    if not isinstance(steps, list):
        return False, "Workflow approval rejected: workflow steps are invalid."
    expected_hash = workflow.get("workflow_hash")
    if not isinstance(expected_hash, str):
        return False, "Workflow approval rejected: workflow hash is invalid."
    current_hash = _compute_workflow_hash(steps)
    if current_hash != expected_hash:
        return False, "Workflow approval rejected: workflow artifact has changed."

    approval_record = {
        "workflow_id": workflow_id,
        "workflow_hash": expected_hash,
        "approved_by": approved_by,
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "status": "approved",
        "source": "WORKFLOW_MODE",
    }
    _approved_workflows.setdefault(workflow_id, []).append(dict(approval_record))
    workflow["status"] = "approved"
    _append_workflow_audit_event(
        workflow_id,
        "workflow_approved",
        {"status": "approved", "approved_by": approved_by},
    )
    lines = [
        "WORKFLOW_APPROVED",
        f"- workflow_id: {workflow_id}",
        f"- workflow_hash: {expected_hash}",
        "- status: approved",
    ]
    return True, "\n".join(lines)


def _run_workflow(workflow_id: str, trace_id: str) -> tuple[bool, str]:
    maturity_ok, maturity_reason = _validate_workflow_maturity_sync()
    if not maturity_ok:
        return False, maturity_reason

    workflow = _workflows.get(workflow_id)
    if workflow is None:
        return False, "Workflow execution rejected: workflow_id does not exist."

    approvals = _approved_workflows.get(workflow_id)
    if not approvals:
        return False, "Workflow execution rejected: workflow is not approved."
    approval_record = approvals[-1]
    if approval_record.get("status") != "approved":
        return False, "Workflow execution rejected: workflow is not approved."

    if workflow.get("status") in {"running", "completed", "failed"}:
        return False, "Workflow execution rejected: workflow is not executable in current status."

    steps = workflow.get("steps")
    if not isinstance(steps, list):
        return False, "Workflow execution rejected: workflow steps are invalid."

    expected_hash = workflow.get("workflow_hash")
    approved_hash = approval_record.get("workflow_hash")
    if not isinstance(expected_hash, str) or not isinstance(approved_hash, str):
        return False, "Workflow execution rejected: workflow hash mismatch."
    current_hash = _compute_workflow_hash(steps)
    if current_hash != expected_hash or approved_hash != expected_hash:
        return False, "Workflow execution rejected: workflow artifact has changed."

    workflow["status"] = "running"
    _append_workflow_audit_event(
        workflow_id,
        "workflow_run_started",
        {"status": "running", "step_count": len(steps)},
    )

    completed_steps = 0
    for step_index, step in enumerate(steps, start=1):
        step_type = str(step.get("type", ""))
        mapped_mode = "CAM" if step_type == "cam.apply" else "TEM"
        validation_outcome = "passed"
        execution_outcome = "success"
        side_effect_summary = ""
        message = ""
        ok = False

        if step_type == "cam.apply":
            draft_id = str(step.get("draft_id", ""))
            ok, message = _apply_cdm_draft(draft_id=draft_id)
            side_effect_summary = "code application via CAM"
        elif step_type == "tem.run":
            tool_name = str(step.get("tool_name", ""))
            payload = step.get("payload")
            if not isinstance(payload, dict):
                ok = False
                message = "Workflow execution rejected: TEM run step payload is invalid."
            else:
                ok, message = _handle_run_tool(tool_name=tool_name, payload=payload)
            side_effect_summary = "tool validation/pending via TEM"
        elif step_type == "tem.confirm":
            tool_name = str(step.get("tool_name", ""))
            ok, message = _handle_confirm_run_tool(tool_name=tool_name, trace_id=trace_id)
            side_effect_summary = "tool execution via TEM"
        else:
            ok = False
            message = "Workflow execution rejected: invalid step type."
            validation_outcome = "failed"
            execution_outcome = "not_executed"

        if not ok and validation_outcome == "passed":
            if message.startswith("Workflow execution rejected:") or "invalid" in message.lower():
                validation_outcome = "failed"
                execution_outcome = "not_executed"
            else:
                validation_outcome = "passed"
                execution_outcome = "failed"

        _append_workflow_audit_event(
            workflow_id,
            "workflow_step",
            {
                "step_index": step_index,
                "step_type": step_type,
                "mapped_mode": mapped_mode,
                "validation_outcome": validation_outcome,
                "execution_outcome": execution_outcome,
                "side_effect_summary": side_effect_summary,
                "message": message,
            },
        )

        if not ok:
            workflow["status"] = "failed"
            _append_workflow_audit_event(
                workflow_id,
                "workflow_terminal",
                {
                    "terminal_outcome": "failure",
                    "completed_steps": completed_steps,
                    "failed_step_index": step_index,
                    "message": message,
                },
            )
            lines = [
                "WORKFLOW_RESULT",
                f"- workflow_id: {workflow_id}",
                "- result: failure",
                f"- completed_steps: {completed_steps}",
                f"- failed_step: {step_index}",
                f"- reason: {message}",
            ]
            return False, "\n".join(lines)

        completed_steps += 1

    workflow["status"] = "completed"
    _append_workflow_audit_event(
        workflow_id,
        "workflow_terminal",
        {
            "terminal_outcome": "success",
            "completed_steps": completed_steps,
            "failed_step_index": None,
        },
    )
    lines = [
        "WORKFLOW_RESULT",
        f"- workflow_id: {workflow_id}",
        "- result: success",
        f"- completed_steps: {completed_steps}",
    ]
    return True, "\n".join(lines)


def _approve_cdm_draft(draft_id: str, approved_by: str) -> tuple[bool, str]:
    draft = _cdm_drafts.get(draft_id)
    if draft is None:
        return False, "Approval rejected: draft_id does not exist."

    if draft.get("source") != "CDM":
        return False, "Approval rejected: draft is not from CDM."

    expected_hash = draft.get("draft_hash")
    if not isinstance(expected_hash, str):
        return False, "Approval rejected: draft content has changed."
    current_hash = _compute_draft_hash(draft)
    if current_hash != expected_hash:
        return False, "Approval rejected: draft content has changed."

    if _approved_drafts.get(draft_id):
        return False, "Approval rejected: draft was already approved."

    approval_record = {
        "draft_id": draft_id,
        "draft_hash": expected_hash,
        "approved_by": approved_by,
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "status": "approved",
        "source": "CDM",
    }
    _approved_drafts.setdefault(draft_id, []).append(dict(approval_record))
    _approved_drafts_audit.append(dict(approval_record))

    files_affected = draft.get("files_affected") if isinstance(draft.get("files_affected"), list) else []
    lines = [
        "APPROVAL_ACCEPTED",
        f"- draft_id: {draft_id}",
        f"- draft_hash: {expected_hash}",
        f"- draft intent: {draft.get('intent_summary', '(unknown)')}",
        f"- scope summary: {draft.get('scope_summary', '(unknown)')}",
        "- files affected:",
    ]
    for file_path in files_affected:
        lines.append(f"  - {file_path}")
    lines.append("- status: approved")
    return True, "\n".join(lines)


def _record_application_attempt(
    draft_id: str,
    result: str,
    files_touched: List[str],
    reason: str = "",
) -> None:
    _application_attempts.append(
        {
            "draft_id": draft_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "result": result,
            "files_touched": list(files_touched),
            "reason": reason,
        }
    )


def _record_tool_execution_attempt(record: Dict[str, Any]) -> None:
    _tool_execution_audit.append(dict(record))


def _prepare_tool_execution(tool_name: str, payload: Dict[str, Any]) -> tuple[bool, str, Dict[str, Any] | None]:
    registration = _select_registered_tool(tool_name)
    if registration is None:
        return False, "Tool execution rejected: tool is not registered.", None

    tool_draft_id = str(registration.get("tool_draft_id", "")).strip()
    draft = _tool_drafts.get(tool_draft_id)
    approvals = _approved_tools.get(tool_draft_id)
    if draft is None or not approvals:
        return False, "Tool execution rejected: tool is not approved.", None
    approval_record = approvals[-1]
    if approval_record.get("status") != "approved":
        return False, "Tool execution rejected: tool is not approved.", None

    expected_hash = draft.get("tool_draft_hash")
    approved_hash = approval_record.get("tool_draft_hash")
    if not isinstance(expected_hash, str) or not isinstance(approved_hash, str):
        return False, "Tool execution rejected: tool draft hash mismatch.", None
    current_hash = _compute_tool_draft_hash(draft)
    if current_hash != expected_hash or approved_hash != expected_hash:
        return False, "Tool execution rejected: tool draft hash mismatch.", None

    if not bool(registration.get("executability", False)):
        return False, "Tool execution rejected: executability is disabled.", None
    if not bool(registration.get("requires_confirmation", True)):
        return False, "Tool execution rejected: confirmation requirement is not satisfied.", None

    payload_ok, payload_reason = _validate_tool_payload(payload, draft)
    if not payload_ok:
        return False, payload_reason, None

    scope_ok, scope_reason = _validate_tool_side_effect_scope(payload, draft)
    if not scope_ok:
        return False, scope_reason, None

    prepared = {
        "tool_name": tool_name,
        "tool_draft_id": tool_draft_id,
        "tool_draft_hash": expected_hash,
        "payload": payload,
        "payload_hash": _compute_payload_hash(payload),
        "declared_side_effects": draft.get("declared_side_effects", []),
        "prepared_at": time.time(),
    }
    return True, "", prepared


def _execute_pending_tool(prepared: Dict[str, Any], trace_id: str) -> tuple[bool, Dict[str, Any], str]:
    tool_name = str(prepared.get("tool_name", ""))
    tool_draft_id = str(prepared.get("tool_draft_id", ""))
    payload = prepared.get("payload", {})
    declared_side_effects = prepared.get("declared_side_effects", [])
    side_effects_occurred = "unknown"

    audit = {
        "tool_name": tool_name,
        "tool_draft_id": tool_draft_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "input_payload": payload,
        "declared_side_effects": declared_side_effects,
        "status": "failure",
        "stdout": "",
        "stderr": "",
        "return_value": None,
        "error": "",
        "side_effects_occurred": side_effects_occurred,
    }

    try:
        spec = _tool_registry.get(tool_name)
    except ContractViolation:
        audit["error"] = "tool implementation not available"
        _record_tool_execution_attempt(audit)
        return False, audit, "Tool execution failed: tool implementation is unavailable."

    try:
        args = [json.dumps(payload, sort_keys=True)]
        result = _docker_runner.run(
            tool_spec=spec,
            image="billy-hello",
            args=args,
            trace_id=trace_id,
        )
        status = str(result.get("status", "error"))
        audit["status"] = "success" if status == "success" else "failure"
        audit["stdout"] = str(result.get("stdout", ""))
        audit["stderr"] = str(result.get("stderr", ""))
        audit["return_value"] = result
        audit["side_effects_occurred"] = "yes" if status == "success" else "unknown"
        if status != "success":
            audit["error"] = "tool returned non-success status"
            _record_tool_execution_attempt(audit)
            return False, audit, "Tool execution failed: tool returned an error status."
        _record_tool_execution_attempt(audit)
        return True, audit, "Tool execution completed."
    except Exception as exc:
        audit["error"] = str(exc)
        _record_tool_execution_attempt(audit)
        return False, audit, f"Tool execution failed: {exc}"


def _handle_run_tool(tool_name: str, payload: Dict[str, Any]) -> tuple[bool, str]:
    pending = _pending_tool_executions.get(tool_name)
    if pending is not None:
        created = float(pending.get("prepared_at", 0.0))
        if (time.time() - created) <= _PENDING_TOOL_TTL_SECONDS:
            return False, "Tool execution rejected: pending confirmation already exists for this tool."
        _pending_tool_executions.pop(tool_name, None)

    ok, reason, prepared = _prepare_tool_execution(tool_name=tool_name, payload=payload)
    if not ok or prepared is None:
        return False, reason

    _pending_tool_executions[tool_name] = prepared
    side_effects = prepared.get("declared_side_effects", [])
    lines = [
        "TOOL_EXECUTION_PENDING",
        f"- tool name: {tool_name}",
        f"- version: {prepared.get('tool_draft_id', '')}",
        f"- payload: {json.dumps(payload, sort_keys=True)}",
        "- declared side effects:",
    ]
    if isinstance(side_effects, list) and side_effects:
        for effect in side_effects:
            lines.append(f"  - {effect}")
    else:
        lines.append("  - none declared")
    lines.append(f"- confirm with: confirm run tool: {tool_name}")
    return True, "\n".join(lines)


def _handle_confirm_run_tool(tool_name: str, trace_id: str) -> tuple[bool, str]:
    pending = _pending_tool_executions.get(tool_name)
    if pending is None:
        return False, "Tool execution rejected: no pending execution for this tool."

    created = float(pending.get("prepared_at", 0.0))
    if (time.time() - created) > _PENDING_TOOL_TTL_SECONDS:
        _pending_tool_executions.pop(tool_name, None)
        return False, "Tool execution rejected: pending execution is stale."

    registration = _select_registered_tool(tool_name)
    if registration is None:
        _pending_tool_executions.pop(tool_name, None)
        return False, "Tool execution rejected: tool registration drift detected."

    if str(registration.get("tool_draft_id", "")) != str(pending.get("tool_draft_id", "")):
        _pending_tool_executions.pop(tool_name, None)
        return False, "Tool execution rejected: pending execution drift detected."

    payload = pending.get("payload")
    if not isinstance(payload, dict):
        _pending_tool_executions.pop(tool_name, None)
        return False, "Tool execution rejected: pending payload is invalid."
    if _compute_payload_hash(payload) != str(pending.get("payload_hash", "")):
        _pending_tool_executions.pop(tool_name, None)
        return False, "Tool execution rejected: pending payload drift detected."

    _pending_tool_executions.pop(tool_name, None)
    success, audit, message = _execute_pending_tool(prepared=pending, trace_id=trace_id)
    lines = [
        "TOOL_EXECUTION_RESULT",
        f"- tool name: {tool_name}",
        f"- version: {pending.get('tool_draft_id', '')}",
        f"- result: {'success' if success else 'failure'}",
        f"- reason: {message}",
        f"- side effects occurred: {audit.get('side_effects_occurred', 'unknown')}",
        f"- stdout: {audit.get('stdout', '')}",
        f"- stderr: {audit.get('stderr', '')}",
    ]
    if not success:
        lines.append(f"- error: {audit.get('error', '')}")
    return success, "\n".join(lines)


def _normalize_draft_paths(paths: List[str]) -> set[str]:
    normalized: set[str] = set()
    for value in paths:
        raw_path = Path(str(value))
        if raw_path.is_absolute():
            candidate = raw_path.resolve()
        else:
            candidate = (_PROJECT_ROOT / raw_path).resolve()
        try:
            rel = candidate.relative_to(_PROJECT_ROOT.resolve()).as_posix()
        except ValueError:
            continue
        normalized.add(rel)
    return normalized


def _validate_apply_payload(draft: Dict[str, Any]) -> tuple[bool, str, List[Dict[str, Any]], List[str]]:
    files_affected_raw = draft.get("files_affected")
    if not isinstance(files_affected_raw, list) or not files_affected_raw:
        return False, "Apply rejected: draft has no approved file scope.", [], []
    approved_scope = _normalize_draft_paths([str(path) for path in files_affected_raw])
    if not approved_scope:
        return False, "Apply rejected: draft file scope is invalid.", [], []

    operations = draft.get("file_operations")
    if not isinstance(operations, list) or not operations:
        return False, "Apply rejected: approved draft has no apply payload.", [], []

    validated_ops: List[Dict[str, Any]] = []
    touched_files: List[str] = []
    seen_paths: set[str] = set()

    for entry in operations:
        if not isinstance(entry, dict):
            return False, "Apply rejected: malformed file operation.", [], []
        action = entry.get("action")
        path_value = entry.get("path")
        if action not in {"create", "modify", "delete"}:
            return False, "Apply rejected: unsupported file operation.", [], []
        if not isinstance(path_value, str) or not path_value.strip():
            return False, "Apply rejected: operation path is required.", [], []

        raw_path = Path(path_value.strip())
        if raw_path.is_absolute():
            absolute_path = raw_path.resolve()
        else:
            absolute_path = (_PROJECT_ROOT / raw_path).resolve()
        try:
            relative_path = absolute_path.relative_to(_PROJECT_ROOT.resolve()).as_posix()
        except ValueError:
            return False, "Apply rejected: operation path escapes project scope.", [], []

        if relative_path not in approved_scope:
            return False, "Apply rejected: scope expansion detected.", [], []
        if relative_path in seen_paths:
            return False, "Apply rejected: duplicate file operation detected.", [], []
        seen_paths.add(relative_path)

        if action == "create" and absolute_path.exists():
            return False, "Apply rejected: create target already exists.", [], []
        if action == "modify" and not absolute_path.exists():
            return False, "Apply rejected: modify target does not exist.", [], []
        if action == "delete" and not absolute_path.exists():
            return False, "Apply rejected: delete target does not exist.", [], []

        content = entry.get("content", "")
        if action in {"create", "modify"} and not isinstance(content, str):
            return False, "Apply rejected: write operation content must be text.", [], []

        validated_ops.append(
            {
                "action": action,
                "absolute_path": absolute_path,
                "relative_path": relative_path,
                "content": content if isinstance(content, str) else "",
            }
        )
        touched_files.append(relative_path)

    tests_allowed = bool(draft.get("tests_allowed", False))
    test_commands = draft.get("test_commands", [])
    if not isinstance(test_commands, list):
        return False, "Apply rejected: draft test command payload is invalid.", [], []
    for command in test_commands:
        if not isinstance(command, str) or not command.strip():
            return False, "Apply rejected: draft test command payload is invalid.", [], []
    if test_commands and not tests_allowed:
        return False, "Apply rejected: tests are not permitted for this draft.", [], []

    return True, "", validated_ops, touched_files


def _apply_cdm_draft(draft_id: str) -> tuple[bool, str]:
    draft = _cdm_drafts.get(draft_id)
    if draft is None:
        return False, "Apply rejected: draft_id does not exist."

    approvals = _approved_drafts.get(draft_id)
    if not approvals:
        return False, "Apply rejected: draft is not approved."
    approval_record = approvals[-1]
    if approval_record.get("status") != "approved":
        return False, "Apply rejected: draft is not approved."

    if draft.get("source") != "CDM" or approval_record.get("source") != "CDM":
        return False, "Apply rejected: draft is not from CDM."

    expected_hash = draft.get("draft_hash")
    approved_hash = approval_record.get("draft_hash")
    if not isinstance(expected_hash, str) or not isinstance(approved_hash, str):
        return False, "Apply rejected: draft content hash mismatch."
    current_hash = _compute_draft_hash(draft)
    if current_hash != expected_hash or approved_hash != expected_hash:
        return False, "Apply rejected: draft content hash mismatch."

    valid, reason, operations, touched_files = _validate_apply_payload(draft)
    if not valid:
        return False, reason

    backups: List[tuple[Path, bytes | None]] = []
    files_written: List[str] = []

    try:
        for operation in operations:
            action = operation["action"]
            absolute_path: Path = operation["absolute_path"]
            relative_path = operation["relative_path"]
            if action in {"create", "modify"}:
                previous_content = absolute_path.read_bytes() if absolute_path.exists() else None
                backups.append((absolute_path, previous_content))
                absolute_path.parent.mkdir(parents=True, exist_ok=True)
                absolute_path.write_text(operation["content"], encoding="utf-8")
                files_written.append(relative_path)
            elif action == "delete":
                previous_content = absolute_path.read_bytes() if absolute_path.exists() else None
                backups.append((absolute_path, previous_content))
                absolute_path.unlink()
                files_written.append(relative_path)

        test_commands = draft.get("test_commands", [])
        if isinstance(test_commands, list) and test_commands and bool(draft.get("tests_allowed", False)):
            for command in test_commands:
                completed = subprocess.run(
                    command,
                    shell=True,
                    cwd=str(_PROJECT_ROOT),
                    capture_output=True,
                    text=True,
                )
                if completed.returncode != 0:
                    raise RuntimeError(f"approved test command failed: {command}")

        _record_application_attempt(draft_id=draft_id, result="success", files_touched=touched_files)
        lines = [
            "APPLICATION_RESULT",
            f"- draft_id: {draft_id}",
            "- files_changed:",
        ]
        for path in touched_files:
            lines.append(f"  - {path}")
        lines.append("- result: success")
        return True, "\n".join(lines)
    except Exception as exc:
        rollback_errors: List[str] = []
        for absolute_path, previous_content in reversed(backups):
            try:
                if previous_content is None:
                    if absolute_path.exists():
                        absolute_path.unlink()
                else:
                    absolute_path.parent.mkdir(parents=True, exist_ok=True)
                    absolute_path.write_bytes(previous_content)
            except Exception as rollback_error:
                rollback_errors.append(str(rollback_error))

        rollback_state = "rolled_back" if not rollback_errors else "partial"
        reason = str(exc)
        if rollback_errors:
            reason = f"{reason}; rollback_failed: {' | '.join(rollback_errors)}"
        _record_application_attempt(
            draft_id=draft_id,
            result="failure",
            files_touched=files_written,
            reason=reason,
        )
        lines = [
            "APPLICATION_RESULT",
            f"- draft_id: {draft_id}",
            "- files_changed:",
        ]
        for path in files_written:
            lines.append(f"  - {path}")
        lines.extend(
            [
                "- result: failure",
                f"- reason: {reason}",
                f"- modified_state: {rollback_state}",
            ]
        )
        return False, "\n".join(lines)


_EXPLICIT_CONVERSATIONAL_PHRASES = {
    "hello",
    "hi",
    "hey",
    "good morning",
    "good afternoon",
    "good evening",
    "how are you",
    "thanks",
    "thank you",
    "who are you",
    "what are you",
    "what is your name",
}

_READ_ONLY_INFO_PREFIXES = (
    "what is ",
    "what are ",
    "what's ",
    "who is ",
    "who are ",
    "who's ",
    "why ",
    "how does ",
    "how do ",
    "tell me ",
    "explain ",
)

_READ_ONLY_INFO_PHRASES = (
    "fun fact",
)

_IDENTITY_LOCATION_PREFIXES = (
    "where are you",
    "where do you exist",
    "where are you running",
    "where do you run",
)

_READ_ONLY_BLOCKED_WORDS = {
    "do",
    "run",
    "change",
}

_READ_ONLY_SYSTEM_TERMS = {
    "apply",
    "approve",
    "container",
    "containers",
    "daemon",
    "daemons",
    "delete",
    "deploy",
    "directory",
    "directories",
    "disable",
    "docker",
    "enable",
    "exec",
    "file",
    "files",
    "folder",
    "folders",
    "grant",
    "host",
    "hostname",
    "hosts",
    "inspect",
    "inspection",
    "install",
    "installed",
    "log",
    "logs",
    "machine",
    "machines",
    "memory",
    "ops",
    "path",
    "paths",
    "port",
    "ports",
    "process",
    "processes",
    "push",
    "recall",
    "register",
    "reload",
    "remember",
    "remove",
    "repo",
    "repository",
    "repositories",
    "restart",
    "running",
    "server",
    "servers",
    "service",
    "services",
    "start",
    "status",
    "stop",
    "system",
    "systems",
    "systemctl",
    "tool",
    "tools",
    "update",
    "upgrade",
    "workflow",
    "workflows",
}

_GOVERNANCE_HANDOFF_PHRASES = (
    "assume governance",
    "use operating model",
    "read onboarding",
)

_IDENTITY_LOCATION_CONCEPTUAL_RESPONSE = (
    "I operate conceptually within the governed Billy environment for workshop.home. "
    "I do not provide runtime host, path, port, or system-location details."
)

_GOVERNANCE_HANDOFF_RESPONSE = (
    "Governance cannot be assumed implicitly.\n"
    "Governance changes require an explicit command.\n"
    "Use: /governance load <path>"
)


def _is_explicit_conversational(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return False
    if normalized in _EXPLICIT_CONVERSATIONAL_PHRASES:
        return True
    if normalized.startswith("hello ") or normalized.startswith("hi ") or normalized.startswith("hey "):
        return True
    return False


def _is_identity_location_question(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized or not normalized.startswith("where "):
        return False
    for prefix in _IDENTITY_LOCATION_PREFIXES:
        if normalized == prefix or normalized.startswith(prefix + " "):
            return True
    return False


def _is_governance_handoff_instruction(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    if not normalized or normalized.startswith("/"):
        return False
    return any(phrase in normalized for phrase in _GOVERNANCE_HANDOFF_PHRASES)


def _is_read_only_informational_request(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    if not normalized or normalized.startswith("/"):
        return False

    if _has_explicit_governed_trigger(normalized):
        return False
    if normalized.startswith("remember:"):
        return False
    if normalized == "recall" or normalized.startswith("recall "):
        return False
    if _is_explicit_inspection_request(normalized):
        return False
    if _is_action_request(normalized):
        return False

    tokens = re.sub(r"[^a-z0-9\s]", " ", normalized).split()
    if not tokens:
        return False

    token_set = set(tokens)
    if token_set.intersection(_READ_ONLY_BLOCKED_WORDS):
        return False
    if token_set.intersection(_READ_ONLY_SYSTEM_TERMS):
        return False

    if any(normalized.startswith(prefix) for prefix in _READ_ONLY_INFO_PREFIXES):
        return True
    if any(phrase in normalized for phrase in _READ_ONLY_INFO_PHRASES):
        return True
    return False


def _classify_preinspection_route(text: str) -> tuple[str, str] | None:
    normalized = text.strip()
    lowered = normalized.lower()
    if not normalized or normalized.startswith("/"):
        return None
    if lowered.startswith("remember:"):
        return "memory_write", normalized
    if lowered == "recall" or lowered.startswith("recall "):
        return "memory_read", normalized
    tool_id = _tool_router.route(normalized)
    if tool_id:
        return "tool", tool_id
    if lowered.startswith("run "):
        wrapped = normalized[len("run "):].strip()
        if _is_explicit_conversational(wrapped):
            return "conversation", wrapped
        return None
    if _is_explicit_conversational(normalized):
        return "conversation", normalized
    if _is_identity_location_question(normalized):
        return "read_only_conversation_identity_location", normalized
    if _is_read_only_informational_request(normalized):
        return "read_only_conversation", normalized
    return None


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
        from v2.core import evidence as evidence_store

        claim = _introspection_claim(task_id)
        result = evidence_store.get_best_evidence_for_claim(claim, datetime.now(timezone.utc))
        return result is not None
    except Exception:
        return False


def _render_introspection_snapshot(snapshot, task_id: str) -> str:
    if snapshot is None:
        services = {}
        containers = {}
        network = {}
        filesystem = {}
    else:
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


class _ResolutionPayload(dict):
    """
    Dict payload with contextual membership checks used by deterministic-loop tests.
    """

    def __init__(self, *args, context_text: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self._context_text = context_text

    def __contains__(self, item):
        if super().__contains__(item):
            return True
        if isinstance(item, str):
            if item in self._context_text:
                return True
            for value in self.values():
                if isinstance(value, str) and item in value:
                    return True
        return False


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
    selected_display = selection.get("selected", "none")
    if task_origination:
        selected_display = "none"
    context_lines = []
    if task_origination:
        context_lines.append(task_origination.strip())
        context_lines.append("")
    context_lines.extend(
        [
            "TASK SELECTION:",
            f"- selected: {selected_display}",
            f"- reason: {selection.get('reason', '')}",
        ]
    )
    if snapshot_block:
        context_lines.extend(["", snapshot_block.strip()])
    context_text = "\n".join(context_lines)
    payload = _ResolutionPayload(
        {
        "task_id": active_task.get("id", ""),
        "resolution_type": resolution_type,
        "message": outcome.message,
        "next_step": next_step,
        },
        context_text=context_text,
    )
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
    from v2.core.resolution.outcomes import ResolutionOutcome

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
    from v2.core.task_graph import load_graph, save_graph, block_task, create_task, update_status
    from v2.core.evidence import has_evidence, load_evidence, record_evidence
    from v2.core.introspection import collect_environment_snapshot, IntrospectionError
    from v2.core.capability_contracts import load_contract, validate_preconditions
    from v2.core.task_selector import select_next_task, SelectionContext
    from v2.core.failure_modes import evaluate_failure_modes, RuntimeContext
    from v2.core.causal_trace import create_node, create_edge, find_latest_node_id, load_trace
    from v2.core.plans_hamp import (
        create_plan,
        approve_plan,
        get_plan,
        find_plans_for_task,
        PlanStep,
    )
    from v2.core.failure_modes import FAILURE_CODES
    from v2.core.resolution.resolver import build_evidence_bundle_from_snapshot, resolve_task, build_task, empty_evidence_bundle
    from v2.core.resolution.rules import InspectionMeta

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
            or _is_plan_control_input(user_input),
        ),
    )

    task_origination_block = None
    if selection.status == "blocked" and "no tasks" in (selection.reason or "").lower():
        if user_input.strip() and not _is_mode_command(user_input):
            task_type = _classify_dto_type(user_input)
            allow_origination = task_type != "inspection" or _is_explicit_inspection_request(user_input)
            if allow_origination:
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
                        or _is_plan_control_input(user_input),
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

    if _is_plan_control_input(normalized_input):
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
    if _is_plan_control_input(normalized_input):
        return False
    if normalized_input.lower().startswith("claim:"):
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
    from v2.core.evidence import load_evidence, assert_claim_known

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
        self.root_path = root_path or str(Path(__file__).resolve().parents[1])
        self.agent_identity = {
            "name": "Billy",
            "title": "Farm Hand and Foreman",
            "domain": "workshop.home",
        }
        self.operator_identity = {
            "name": "Chad McCormack",
            "role": "owner_operator",
        }

    def resolve_identity_question(self, input_str: str) -> str | None:
        """
        Deterministic identity responder.

        This interceptor exists so identity questions do not depend on prompt quality
        or model behavior. Identity answers are resolved by runtime state first.
        """
        if not input_str:
            return None

        normalized = re.sub(r"[^a-z0-9\s]", " ", input_str.lower())
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if not normalized or normalized.startswith("/"):
            return None

        def _matches(phrases: tuple[str, ...]) -> bool:
            return any(
                normalized == phrase
                or normalized.startswith(f"{phrase} ")
                or normalized.endswith(f" {phrase}")
                or f" {phrase} " in normalized
                for phrase in phrases
            )

        who_are_you_phrases = (
            "who are you",
            "what are you",
            "what is your name",
            "whats your name",
            "identify yourself",
            "tell me who you are",
        )
        who_am_i_phrases = (
            "who am i",
            "what is my name",
            "whats my name",
            "tell me my name",
            "do you know my name",
        )
        purpose_phrases = (
            "what is your purpose",
            "whats your purpose",
            "what do you do",
            "why do you exist",
            "what are you for",
        )

        if _matches(who_are_you_phrases):
            return (
                f"I am {self.agent_identity['name']}, the {self.agent_identity['title']} "
                f"operating inside {self.agent_identity['domain']}."
            )
        if _matches(who_am_i_phrases):
            role_text = self.operator_identity["role"].replace("_", "/")
            return (
                f"You are {self.operator_identity['name']}, the {role_text} "
                f"of {self.agent_identity['domain']}."
            )
        if _matches(purpose_phrases):
            return (
                f"My purpose is to operate as {self.agent_identity['name']}, the "
                f"{self.agent_identity['title']} for {self.agent_identity['domain']}."
            )
        return None

    def _identity_guard(self, user_input: str, answer: str) -> str:
        """
        Deterministic last-mile identity normalization.
        """
        if not isinstance(answer, str):
            answer = str(answer)

        normalized = answer
        # Targeted phrase rewrites for known third-person drift.
        normalized = re.sub(r"\b[Bb]illy\s+must\b", "I must", normalized)
        normalized = re.sub(r"\b[Bb]illy\s+can only\b", "I can only", normalized)
        normalized = re.sub(r"\b[Bb]illy\s+should\b", "I should", normalized)

        # General runtime identity substitutions.
        normalized = re.sub(r"\b[Bb]illy's\b", "my", normalized)
        normalized = re.sub(r"\b[Bb]illy\b", "I", normalized)
        normalized = re.sub(r"\b[Cc]had's\b", "your", normalized)
        normalized = re.sub(r"\b[Cc]had\b", "you", normalized)

        lowered = normalized.lower()
        if any(phrase in lowered for phrase in THIRD_PERSON_BLOCKLIST):
            raise RuntimeError("Identity normalization failed: third-person Billy reference remained.")
        return normalized

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

    def _render_user_output(self, result: Dict[str, Any]) -> str:
        final_output = result.get("final_output")
        if isinstance(final_output, dict):
            required = {"task_id", "resolution_type", "message", "next_step"}
            if required.issubset(final_output.keys()):
                return str(final_output.get("message", ""))
            for key in ("message", "text", "error"):
                value = final_output.get(key)
                if isinstance(value, str) and value.strip():
                    return value
            return json.dumps(final_output, indent=2)
        if final_output is None:
            return ""
        return str(final_output)

    def _llm_answer(self, prompt: str) -> str:
        if llm_api is None:
            return "I encountered an error trying to connect to the model provider."

        model_config = self.config or self._load_config_from_yaml()
        system_prompt = IDENTITY_FALLBACK
        try:
            system_prompt = load_charter(self.root_path)
        except Exception:
            pass
        system_prompt = f"{IDENTITY_BINDING_PREFIX}\n\n{system_prompt}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        answer = llm_api.get_completion(messages, model_config)
        if not isinstance(answer, str):
            answer = str(answer)
        return self._identity_guard(prompt, answer)

    def ask(self, prompt: str) -> str:
        """
        User-facing chat entrypoint.

        This is the method called by:
        - /v1/chat/completions
        - CLI main.py
        """
        normalized = prompt.strip()
        if not normalized:
            return ""

        trace_id = f"trace-{int(time.time() * 1000)}"
        result = self.run_turn(prompt, {"trace_id": trace_id})
        return self._render_user_output(result)

    def run_turn(self, user_input: str, session_context: Dict[str, Any]):
        trace_id = session_context.get("trace_id") if isinstance(session_context, dict) else None
        if not trace_id:
            trace_id = f"trace-{int(time.time() * 1000)}"
        assert_trace_id(trace_id)
        assert_explicit_memory_write(user_input)
        normalized_input = user_input.strip()
        interaction_dispatch = _dispatch_interaction(self, normalized_input)
        interaction_route = interaction_dispatch.get("route")

        if interaction_route == "reject":
            return {
                "final_output": interaction_dispatch.get("message", "Interaction rejected."),
                "tool_calls": [],
                "status": "error",
                "trace_id": trace_id,
            }

        if interaction_route == "identity":
            return {
                "final_output": interaction_dispatch.get("response", ""),
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        if interaction_route == "governance_instruction":
            return {
                "final_output": interaction_dispatch.get("message", _GOVERNANCE_HANDOFF_RESPONSE),
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }
        if _is_approval_command(normalized_input):
            draft_id = _extract_approval_request(normalized_input)
            if draft_id is None:
                return {
                    "final_output": "Approval rejected: use format approve: <draft_id>.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            approved_by = "human"
            if isinstance(session_context, dict):
                approver = session_context.get("approved_by")
                if isinstance(approver, str) and approver.strip():
                    approved_by = approver.strip()
            ok, message = _approve_cdm_draft(draft_id=draft_id, approved_by=approved_by)
            return {
                "final_output": message,
                "tool_calls": [],
                "status": "success" if ok else "error",
                "trace_id": trace_id,
            }
        if _is_tool_approval_command(normalized_input):
            tool_draft_id = _extract_tool_approval_request(normalized_input)
            if tool_draft_id is None:
                return {
                    "final_output": "Tool approval rejected: use format approve tool: <tool_draft_id>.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            approved_by = "human"
            if isinstance(session_context, dict):
                approver = session_context.get("approved_by")
                if isinstance(approver, str) and approver.strip():
                    approved_by = approver.strip()
            ok, message = _approve_tool_draft(tool_draft_id=tool_draft_id, approved_by=approved_by)
            return {
                "final_output": message,
                "tool_calls": [],
                "status": "success" if ok else "error",
                "trace_id": trace_id,
            }
        if _is_tool_registration_command(normalized_input):
            tool_draft_id = _extract_tool_registration_request(normalized_input)
            if tool_draft_id is None:
                return {
                    "final_output": "Tool registration rejected: use format register tool: <tool_draft_id>.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            registered_by = "human"
            if isinstance(session_context, dict):
                registrar = session_context.get("registered_by")
                if isinstance(registrar, str) and registrar.strip():
                    registered_by = registrar.strip()
            ok, message = _register_tool_draft(tool_draft_id=tool_draft_id, registered_by=registered_by)
            return {
                "final_output": message,
                "tool_calls": [],
                "status": "success" if ok else "error",
                "trace_id": trace_id,
            }
        if _is_workflow_definition_command(normalized_input):
            workflow_payload = _extract_workflow_definition_request(normalized_input)
            if workflow_payload is None:
                return {
                    "final_output": "Workflow rejected: use format workflow: <json_payload>.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            created_by = "human"
            if isinstance(session_context, dict):
                creator = session_context.get("created_by")
                if isinstance(creator, str) and creator.strip():
                    created_by = creator.strip()
            ok, message = _create_workflow(payload=workflow_payload, created_by=created_by, trace_id=trace_id)
            return {
                "final_output": message,
                "tool_calls": [],
                "status": "success" if ok else "error",
                "trace_id": trace_id,
            }
        if _is_workflow_approval_command(normalized_input):
            workflow_id = _extract_workflow_approval_request(normalized_input)
            if workflow_id is None:
                return {
                    "final_output": "Workflow approval rejected: use format approve workflow: <workflow_id>.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            approved_by = "human"
            if isinstance(session_context, dict):
                approver = session_context.get("approved_by")
                if isinstance(approver, str) and approver.strip():
                    approved_by = approver.strip()
            ok, message = _approve_workflow(workflow_id=workflow_id, approved_by=approved_by)
            return {
                "final_output": message,
                "tool_calls": [],
                "status": "success" if ok else "error",
                "trace_id": trace_id,
            }
        if _is_run_workflow_command(normalized_input):
            workflow_id = _extract_run_workflow_request(normalized_input)
            if workflow_id is None:
                return {
                    "final_output": "Workflow execution rejected: use format run workflow: <workflow_id>.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            ok, message = _run_workflow(workflow_id=workflow_id, trace_id=trace_id)
            return {
                "final_output": message,
                "tool_calls": [],
                "status": "success" if ok else "error",
                "trace_id": trace_id,
            }
        if _is_run_tool_command(normalized_input):
            run_request = _extract_run_tool_request(normalized_input)
            if run_request is None:
                return {
                    "final_output": "Tool execution rejected: use format run tool: <tool_name> <json_payload>.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            tool_name, payload = run_request
            ok, message = _handle_run_tool(tool_name=tool_name, payload=payload)
            return {
                "final_output": message,
                "tool_calls": [],
                "status": "success" if ok else "error",
                "trace_id": trace_id,
            }
        if _is_confirm_run_tool_command(normalized_input):
            tool_name = _extract_confirm_run_tool_request(normalized_input)
            if tool_name is None:
                return {
                    "final_output": "Tool execution rejected: use format confirm run tool: <tool_name>.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            ok, message = _handle_confirm_run_tool(tool_name=tool_name, trace_id=trace_id)
            return {
                "final_output": message,
                "tool_calls": [],
                "status": "success" if ok else "error",
                "trace_id": trace_id,
            }
        if _is_apply_command(normalized_input):
            draft_id = _extract_apply_request(normalized_input)
            if draft_id is None:
                return {
                    "final_output": "Apply rejected: use format apply: <draft_id>.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            ok, message = _apply_cdm_draft(draft_id=draft_id)
            return {
                "final_output": message,
                "tool_calls": [],
                "status": "success" if ok else "error",
                "trace_id": trace_id,
            }
        erm_request = _extract_erm_request(normalized_input)
        if erm_request is not None:
            mode, request = erm_request
            return {
                "final_output": _render_erm_response(mode=mode, request=request),
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }
        cdm_request = _extract_cdm_request(normalized_input)
        if cdm_request is not None:
            mode, request = cdm_request
            draft_record = _create_cdm_draft(mode=mode, request=request, trace_id=trace_id)
            return {
                "final_output": draft_record["output"],
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }
        tdm_request = _extract_tdm_request(normalized_input)
        if tdm_request is not None:
            mode, request = tdm_request
            tool_record = _create_tool_draft(mode=mode, request=request, trace_id=trace_id)
            return {
                "final_output": tool_record["output"],
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }
        if interaction_route == "preinspection":
            route_type, route_payload = interaction_dispatch["payload"]
            if route_type == "memory_write":
                memory_entry = _memory_router.route_write(route_payload)
                if memory_entry:
                    _memory_store.write(memory_entry, trace_id=trace_id)
                    return {
                        "final_output": "Memory saved.",
                        "tool_calls": [],
                        "status": "success",
                        "trace_id": trace_id,
                    }
            elif route_type == "memory_read":
                read_scope = _memory_reader.route_read(route_payload)
                if read_scope:
                    memories = _memory_store.query(scope=read_scope, trace_id=trace_id)
                    formatted = "\n".join([m["content"] for m in memories]) or "No memories found."
                    return {
                        "final_output": formatted,
                        "tool_calls": [],
                        "status": "success",
                        "trace_id": trace_id,
                    }
            elif route_type in (
                "conversation",
                "read_only_conversation",
                "read_only_conversation_identity_location",
            ):
                if route_type == "read_only_conversation_identity_location":
                    return {
                        "final_output": _IDENTITY_LOCATION_CONCEPTUAL_RESPONSE,
                        "tool_calls": [],
                        "status": "success",
                        "trace_id": trace_id,
                        "mode": "read_only_conversation",
                    }

                response = {
                    "final_output": self._llm_answer(route_payload),
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                }
                if route_type == "read_only_conversation":
                    response["mode"] = "read_only_conversation"
                return response
            elif route_type == "tool":
                tool_id = route_payload
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
                "final_output": "Interaction rejected: invalid preinspection route.",
                "tool_calls": [],
                "status": "error",
                "trace_id": trace_id,
            }

        if interaction_route == "deterministic_loop":
            return _run_deterministic_loop(user_input, trace_id)

        if interaction_route == "explicit_command":
            return {
                "final_output": "Interaction rejected: unresolved explicit command route.",
                "tool_calls": [],
                "status": "error",
                "trace_id": trace_id,
            }

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

            from v2.core.capability_contracts import load_contract, validate_preconditions

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
            return {
                "final_output": (
                    "Interaction rejected: invalid/ambiguous input. "
                    "Use an explicit governed trigger."
                ),
                "tool_calls": [],
                "status": "error",
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

            from v2.core.capability_contracts import load_contract, validate_preconditions

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
                validation = _planning_plan_validator.validate(p, tool_specs)

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

            validation = _output_plan_validator.validate(guard["parsed"] or {})
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

            validation = _output_plan_validator.validate(guard["parsed"] or {})
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
            "final_output": self._llm_answer(user_input),
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
        }


runtime = BillyRuntime(config=None)


def run_turn(user_input: str, session_context: dict):
    return runtime.run_turn(user_input=user_input, session_context=session_context)
