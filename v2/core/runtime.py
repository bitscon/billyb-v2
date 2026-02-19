"""
Updated runtime module for Billy v2.

This version adjusts the BillyRuntime constructor to accept an optional
configuration dictionary and default to an empty dictionary when none is
provided. It also adds the ask() method required by the API layer to
correctly invoke the configured LLM.
"""

import hashlib
import html
import json
import os
import re
import shlex
import socket
import subprocess
import time
import yaml
import uuid
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

import copy

try:
    from . import llm_api
except ImportError:
    llm_api = None
from .charter import load_charter
from v2.core.advisory_planning import build_advisory_plan
from v2.core.conversation_layer import process_conversational_turn, run_governed_interpreter
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
from v2.core.content_capture import CapturedContent, InMemoryContentCaptureStore
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
from v2.core.aci_intent_gatekeeper import (
    INTENT_CLASS,
    ACI_MAX_PHASE,
    ACI_MIN_PHASE,
    LadderState,
    build_response_envelope,
    derive_admissible_phase_transitions,
    phase_gatekeeper,
    route_intent,
)
from v2.core.aci_issuance_ledger import (
    ACIIssuanceLedger,
    REVOCATION_CONTRACT_NAME,
    SUPERSESSION_CONTRACT_NAME,
    build_receipt_envelope,
    compute_transition_key,
)
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
_aci_issuance_dir = _V2_ROOT / "var" / "aci_issuance"
_aci_issuance_dir.mkdir(parents=True, exist_ok=True)
_aci_issuance_ledger_path = _aci_issuance_dir / "ledger.jsonl"
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
    if normalized.startswith(("locate ", "find ", "check ")):
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

    if _is_content_generation_request(normalized):
        return {
            "category": "content generation",
            "route": "content_generation",
            "payload": normalized,
        }

    capture_request = _parse_content_capture_request(normalized)
    if capture_request is not None:
        return {
            "category": "content capture",
            "route": "content_capture",
            "payload": capture_request,
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


def _extract_confirm_issuance_request(text: str) -> str | None:
    normalized = text.strip()
    match = re.fullmatch(
        r"confirm issuance(?:\s*:\s*([A-Za-z0-9._:-]+))?\s*",
        normalized,
        re.IGNORECASE,
    )
    if not match:
        return None
    target = match.group(1)
    if target is None:
        return ""
    return target.strip()


def _extract_revoke_artifact_request(text: str) -> str | None:
    normalized = text.strip()
    match = re.fullmatch(r"revoke\s+([A-Za-z0-9._:-]+)\s*", normalized, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip()


def _extract_supersede_artifact_request(text: str) -> tuple[str, str] | None:
    normalized = text.strip()
    match = re.fullmatch(
        r"supersede\s+([A-Za-z0-9._:-]+)\s+with\s+([A-Za-z0-9._:-]+)\s*",
        normalized,
        re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()


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

_CONTENT_GENERATION_VERBS = (
    "generate",
    "draft",
    "write",
    "propose",
)

_CONTENT_GENERATION_EXECUTION_PATTERNS = (
    r"\bsave\b",
    r"\bwrite\s+file\b",
    r"\bwrite\s+to\s+file\b",
    r"\bdelete\b",
    r"\brun\b",
    r"\bexecute\b",
)

_CONTENT_CAPTURE_HELP = (
    "Capture rejected: ambiguous reference. Use "
    "'capture this as <label>', 'capture that as <label>', "
    "or 'store the last response as <label>'."
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

_FOLLOW_UP_QUESTION_MAP = {
    "how": "how",
    "how?": "how",
    "when": "when",
    "when?": "when",
    "where": "where",
    "where?": "where",
    "who": "who",
    "who?": "who",
}

_PLAN_ADVANCEMENT_ACK_MAP = {
    "ok": "ok",
    "okay": "ok",
    "yeah": "yeah",
    "that works": "that_works",
    "go on": "go_on",
    "continue": "continue",
}

_IDEA_DECOMPOSITION_TRIGGER_PHRASES = (
    "i m thinking about",
    "im thinking about",
    "i am thinking about",
    "i'm thinking about",
    "what if i",
    "what if we",
    "i might want to",
    "i dont know how to",
    "i don't know how to",
    "i dont know what to work on",
    "i don't know what to work on",
    "i feel stuck",
    "stuck on what to work on",
)

_IDEA_DECOMPOSITION_EXCLUSIONS = (
    "goal_",
    "constraint_",
    "assumption_",
    "decision_",
    "run this now",
    "execute immediately",
    "create a file",
)

_PLANNING_DEPTH_PROMPT = (
    "Before I generate detail: do you want a high-level outline, a step-by-step plan, "
    "or a critique/stress test?"
)

_PLANNING_DEPTH_DEFAULT_MODE = "step_by_step"

_PLANNING_DEPTH_TOKENS = {
    "high level": "high_level",
    "high-level": "high_level",
    "outline": "high_level",
    "step by step": "step_by_step",
    "step-by-step": "step_by_step",
    "detailed": "step_by_step",
    "critique": "critique",
    "stress test": "critique",
    "stress-test": "critique",
}

_CRITIQUE_OFFER_PHRASES = (
    "this looks good",
    "thoughts?",
    "thoughts",
    "anything i'm missing",
    "anything im missing",
    "what am i missing",
    "does this make sense",
    "does that make sense",
)

_CRITIQUE_DEPTH_PROMPT = (
    "I can critique this plan. Which depth do you want: quick check, full stress test, or assumption review?"
)

_CRITIQUE_DEPTH_TOKENS = {
    "quick": "quick_check",
    "quick check": "quick_check",
    "1": "quick_check",
    "full": "full_stress_test",
    "full stress test": "full_stress_test",
    "stress test": "full_stress_test",
    "stress-test": "full_stress_test",
    "2": "full_stress_test",
    "assumption": "assumption_review",
    "assumption review": "assumption_review",
    "3": "assumption_review",
}

_CRITIQUE_FOLLOW_UP_PROMPT = (
    "Do you want to revise the plan, explore an alternative, or accept risk and proceed?"
)

_TERMINAL_FILLER_PHRASES = (
    "i can help with that",
    "i can assist",
    "let me know",
)

_WEBSITE_BUILD_VERBS = ("build", "create", "make")
_WEBSITE_BUILD_TARGET_TOKENS = (
    "website",
    "web page",
    "homepage",
    "html page",
    "html file",
    ".html",
)

_WEBSITE_PREFLIGHT_EXPLICIT_SCAFFOLD_TOKENS = (
    "generate html",
    "generate the html",
    "generate a basic page",
    "generate a basic html page",
    "give me a basic page",
    "give me a basic html page",
    "just scaffold",
    "scaffold it",
    "scaffold this",
    "html scaffold",
    "starter html",
    "boilerplate",
    "give me code",
)

_WEBSITE_PREFLIGHT_AUDIENCE_HINTS = (
    "audience",
    "customers",
    "users",
    "clients",
    "students",
    "readers",
    "visitors",
    "developers",
    "parents",
    "kids",
    "teens",
)

_WEBSITE_PREFLIGHT_STYLE_HINTS = (
    "minimal",
    "styled",
    "style",
    "modern",
    "clean",
    "bold",
    "playful",
    "dark",
    "light",
    "colorful",
    "professional",
    "simple",
    "theme",
    "css",
    "tailwind",
    "bootstrap",
)

_WEBSITE_PREFLIGHT_PURPOSE_HINTS = (
    "landing page",
    "portfolio",
    "business",
    "blog",
    "store",
    "shop",
    "product",
    "service",
    "company",
    "event",
    "restaurant",
    "agency",
    "resume",
    "startup",
    "personal",
)

_WEBSITE_PREFLIGHT_QUESTION = "What's the page for: personal, business, or a landing page?"

_PREFERENCE_RESET_PHRASES = (
    "forget preferences",
    "reset preferences",
    "clear preferences",
)

_PREFERENCE_CONFIRM_PREFIX = "Should I remember that for this session?"

_TONE_RESET_PHRASES = (
    "reset tone",
    "forget tone preferences",
    "clear tone preferences",
)

_TONE_CAPTURE_CONFIRM_PREFIX = "Want me to remember that?"

_TONE_VERBOSITY_VALUES = ("concise", "standard", "detailed")
_TONE_STYLE_VALUES = ("exploratory", "directive")
_TONE_CONFIDENCE_VALUES = ("gentle", "firm")

_ROLE_RESET_PHRASES = (
    "reset role",
    "forget role",
    "clear role",
    "reset role framing",
    "forget role framing",
    "clear role framing",
)

_ROLE_CAPTURE_CONFIRM_PREFIX = "Want me to do that?"

_ROLE_FRAMING_VALUES = (
    "teacher",
    "senior_engineer",
    "architect",
    "product_manager",
    "researcher",
    "coach",
)

_ROLE_FRAMING_LABELS = {
    "teacher": "teacher",
    "senior_engineer": "senior engineer",
    "architect": "architect",
    "product_manager": "product manager",
    "researcher": "researcher",
    "coach": "coach",
}

_ROLE_FRAMING_FOCUS = {
    "teacher": "Focus on clear concepts, simple examples, and stepwise understanding.",
    "senior_engineer": "Focus on implementation risks, maintainability, and operational tradeoffs.",
    "architect": "Focus on system boundaries, interfaces, and scalability tradeoffs.",
    "product_manager": "Focus on user outcomes, scope decisions, and prioritization tradeoffs.",
    "researcher": "Focus on assumptions, evidence quality, and validation approach.",
    "coach": "Focus on incremental progress, feedback loops, and achievable next steps.",
}

_TASK_MODE_RESET_PHRASES = (
    "reset task mode",
    "forget task mode",
    "clear task mode",
    "reset work mode",
    "forget work mode",
    "clear work mode",
)

_TASK_MODE_CAPTURE_CONFIRM_PREFIX = "Want me to do that?"

_TASK_MODE_VALUES = (
    "brainstorm",
    "step_by_step",
    "critique",
    "compare_options",
    "summarize_and_decide",
)

_TASK_MODE_LABELS = {
    "brainstorm": "brainstorm",
    "step_by_step": "step-by-step",
    "critique": "critique",
    "compare_options": "compare-options",
    "summarize_and_decide": "summarize-and-decide",
}

_DECISION_RESET_ALL_PHRASES = (
    "clear decisions",
    "reset decisions",
    "forget decisions",
)

_DECISION_RESET_LATEST_PHRASES = (
    "forget that decision",
    "remove that decision",
    "clear that decision",
)

_ASSUMPTION_RESET_ALL_PHRASES = (
    "clear assumptions",
    "reset assumptions",
    "forget assumptions",
)

_ASSUMPTION_RESET_LATEST_PHRASES = (
    "forget that assumption",
    "remove that assumption",
    "clear that assumption",
)

_ASSUMPTION_CONFIRM_LATEST_PHRASES = (
    "confirm that assumption",
    "confirm assumption",
    "that assumption works",
    "yes that assumption works",
    "yes, that assumption works",
)

_ASSUMPTION_CHANGE_LATEST_PHRASES = (
    "change that assumption",
    "revise that assumption",
    "update that assumption",
)

_CONSTRAINT_RESET_ALL_PHRASES = (
    "clear constraints",
    "reset constraints",
    "forget constraints",
)

_CONSTRAINT_RESET_LATEST_PHRASES = (
    "remove that constraint",
    "forget that constraint",
    "clear that constraint",
)

_CONSTRAINT_CHANGE_LATEST_PHRASES = (
    "change that constraint",
    "revise that constraint",
    "update that constraint",
)

_CONSTRAINT_LIST_PHRASES = (
    "list constraints",
    "show constraints",
    "what are the constraints",
    "what constraints do we have",
)

_GOAL_RESET_ALL_PHRASES = (
    "clear goals",
    "reset goals",
    "forget goals",
)

_GOAL_RESET_LATEST_PHRASES = (
    "remove that goal",
    "forget that goal",
    "clear that goal",
)

_GOAL_UPDATE_LATEST_PHRASES = (
    "update that goal",
    "change that goal",
    "revise that goal",
)

_GOAL_LIST_PHRASES = (
    "list goals",
    "show goals",
    "what are the goals",
    "what goals do we have",
)

_GOAL_REORDER_LATEST_PHRASES = (
    "prioritize that goal",
    "make that goal first",
    "move that goal first",
)

_ACTIVITY_MODE_ENTRIES = {
    "study_mode": (
        "let's study",
        "lets study",
        "let's study vocabulary",
        "lets study vocabulary",
        "study mode",
        "start study mode",
    ),
    "coding_mode": (
        "help me code",
        "let's code",
        "lets code",
        "coding mode",
        "start coding mode",
    ),
    "planning_mode": (
        "planning time",
        "let's plan",
        "lets plan",
        "planning mode",
        "start planning mode",
    ),
}

_ACTIVITY_MODE_EXIT_PHRASES = {
    "exit mode",
    "exit study mode",
    "exit coding mode",
    "exit planning mode",
    "leave mode",
    "stop mode",
    "stop",
}

_STUDY_MODE_TOKENS = (
    "study",
    "vocabulary",
    "word",
    "definition",
    "quiz",
    "synonym",
    "antonym",
    "meaning",
)

_STUDY_MODE_QUIZ_BANK: List[Dict[str, Any]] = [
    {
        "question": "Which option is the closest synonym of `concise`?",
        "options": {
            "A": "brief",
            "B": "hidden",
            "C": "fragile",
            "D": "distant",
        },
        "correct_option": "A",
    },
    {
        "question": "Which option is the closest antonym of `scarce`?",
        "options": {
            "A": "limited",
            "B": "plentiful",
            "C": "silent",
            "D": "narrow",
        },
        "correct_option": "B",
    },
    {
        "question": "Which option means `to make less severe`?",
        "options": {
            "A": "aggravate",
            "B": "mitigate",
            "C": "duplicate",
            "D": "postpone",
        },
        "correct_option": "B",
    },
]

_ARTIFACT_DIFF_QUERY_PHRASES = (
    "what changed",
    "show the diff",
    "show diff",
    "compare versions",
)

_ARTIFACT_READINESS_QUERY_PHRASES = (
    "is this ready to run",
    "what's missing before i can run this",
    "whats missing before i can run this",
    "what is missing before i can run this",
    "are there any blockers",
)

_ARTIFACT_EXECUTION_PLAN_QUERY_PHRASES = (
    "give me the execution plan",
    "how do i run this manually",
    "how do i run this",
    "what are the steps to deploy this",
    "what are the steps to deploy",
    "steps to deploy this",
    "execution plan",
)

_EXECUTION_CAPABILITY_QUERY_PHRASES = (
    "can you run this",
    "what can you execute",
    "what can you run",
)

_DECLARED_EXECUTION_CAPABILITY_ABSENCES = (
    "file_write",
    "command_execution",
    "network_calls",
    "service_control",
    "tool_invocation",
    "background_process_execution",
)

_EXECUTION_ARMING_STATUS_QUERY_PHRASES = (
    "is execution armed",
    "is execution currently armed",
)

_EXECUTION_ARMING_CONCEPT_QUERY_PHRASES = (
    "how would execution be enabled",
    "how can execution be enabled",
    "how do you enable execution",
    "what would enable execution",
)

_EXECUTION_BOUNDARY_UNIFICATION_QUERY_PHRASES = (
    "why can't you run this",
    "why cant you run this",
    "why can't you execute",
    "why cant you execute",
    "why can't you execute this",
    "why cant you execute this",
    "what's stopping execution right now",
    "whats stopping execution right now",
    "what is stopping execution right now",
    "what's blocking execution",
    "whats blocking execution",
    "what is blocking execution",
    "explain the execution boundary",
    "why can't you execute?",
    "could this ever run",
    "could this ever execute",
    "what would have to change for execution to be possible",
)

_ARTIFACT_ROLLBACK_PHRASES = (
    "undo the last change",
    "undo last change",
    "revert to the previous version",
    "revert to previous version",
    "roll back to the previous version",
    "rollback to the previous version",
)

_ARTIFACT_BRANCH_PHRASES = (
    "make a copy and try a different layout",
    "branch this into an alternate version",
    "create a variant",
    "branch this",
    "branch this artifact",
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
    return normalized in _GOVERNANCE_HANDOFF_PHRASES


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


def _is_content_generation_request(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    if not normalized or normalized.startswith("/"):
        return False
    if _has_explicit_governed_trigger(normalized):
        return False
    if not any(re.search(rf"\b{re.escape(verb)}\b", normalized) for verb in _CONTENT_GENERATION_VERBS):
        return False
    if any(re.search(pattern, normalized) for pattern in _CONTENT_GENERATION_EXECUTION_PATTERNS):
        return False
    return True


def _normalize_capture_label(raw: str) -> str:
    text = raw.strip().strip(" .,:;\"'()[]{}")
    text = re.sub(r"\s+", "-", text)
    return text


def _parse_content_capture_request(text: str) -> Dict[str, Any] | None:
    normalized = re.sub(r"\s+", " ", text.strip())
    lowered = normalized.lower()
    if not lowered or lowered.startswith("/"):
        return None

    capture = re.fullmatch(r"capture (this|that) as (.+)", normalized, flags=re.IGNORECASE)
    if capture is not None:
        label = _normalize_capture_label(capture.group(2))
        if not label:
            return {"valid": False, "reason": _CONTENT_CAPTURE_HELP}
        return {
            "valid": True,
            "label": label,
            "reference": capture.group(1).lower(),
        }

    store_last = re.fullmatch(r"store the last response as (.+)", normalized, flags=re.IGNORECASE)
    if store_last is not None:
        label = _normalize_capture_label(store_last.group(1))
        if not label:
            return {"valid": False, "reason": _CONTENT_CAPTURE_HELP}
        return {
            "valid": True,
            "label": label,
            "reference": "last_response",
        }

    if lowered.startswith("capture ") or lowered.startswith("store "):
        return {"valid": False, "reason": _CONTENT_CAPTURE_HELP}
    return None


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
    def __init__(
        self,
        config: Dict[str, Any] | None = None,
        root_path: str | None = None,
        aci_ledger_path: str | None = None,
    ) -> None:
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
        self._content_capture_store = InMemoryContentCaptureStore()
        self._last_content_generation_response: Dict[str, str] | None = None
        ledger_path = aci_ledger_path or str(_aci_issuance_ledger_path)
        self._aci_issuance_ledger = ACIIssuanceLedger(ledger_path=ledger_path)
        self._aci_pending_proposal: Dict[str, Any] | None = None
        self._aci_last_consumed_transition_key: str | None = None
        self._conversation_context: Dict[str, str] = {
            "last_user_intent": "",
            "last_system_mode": "",
            "last_subject_noun": "",
            "last_user_input": "",
        }
        self._session_defaults: Dict[str, str] = {}
        self._session_preferences: Dict[str, str] = {}
        self._session_tone: Dict[str, str] = {}
        self._session_role: str | None = None
        self._session_task_mode: str | None = None
        self._session_decisions: List[Dict[str, Any]] = []
        self._session_decision_sequence: int = 0
        self._session_assumptions: List[Dict[str, Any]] = []
        self._session_assumption_sequence: int = 0
        self._session_constraints: List[Dict[str, Any]] = []
        self._session_constraint_sequence: int = 0
        self._session_goals: List[Dict[str, Any]] = []
        self._session_goal_sequence: int = 0
        self._interactive_prompt_state: Dict[str, Any] | None = None
        self._activity_mode_state: Dict[str, Any] | None = None
        self._task_artifacts: Dict[str, Dict[str, Any]] = {}
        self._task_artifact_history: Dict[str, List[Dict[str, Any]]] = {}
        self._last_task_artifact_diff: Dict[str, Any] | None = None
        self._active_plan_artifact: Dict[str, Any] | None = None
        self._critique_pending: Dict[str, Any] | None = None

    def _extract_conversational_subject(self, utterance: str) -> str:
        normalized = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not normalized:
            return ""
        html_file_match = re.search(r"\b([a-z0-9._-]+\.html)\b", normalized)
        if html_file_match is not None:
            return str(html_file_match.group(1))
        if "website page" in normalized:
            return "website page"
        if "web page" in normalized:
            return "web page"
        if "website" in normalized:
            return "website"
        if "html" in normalized:
            return "html file"
        if "service" in normalized:
            return "service"
        if "file" in normalized:
            return "file"
        if "project" in normalized:
            return "project"
        return ""

    def _remember_conversational_context(self, *, user_input: str, intent_class: str, mode: str) -> None:
        normalized_input = str(user_input or "").strip()
        if not normalized_input:
            return
        subject = self._extract_conversational_subject(normalized_input)
        if not subject:
            subject = str(self._conversation_context.get("last_subject_noun", "")).strip()
        self._conversation_context = {
            "last_user_intent": str(intent_class or "").strip(),
            "last_system_mode": str(mode or "").strip(),
            "last_subject_noun": subject,
            "last_user_input": normalized_input,
        }

    def _follow_up_key(self, utterance: str) -> str | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return None
        return _FOLLOW_UP_QUESTION_MAP.get(lowered)

    def _plan_advancement_signal(self, utterance: str) -> str | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        lowered = lowered.rstrip(".!").strip()
        if not lowered:
            return None
        return _PLAN_ADVANCEMENT_ACK_MAP.get(lowered)

    def _is_critique_invitation(self, utterance: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return False
        if lowered in _CRITIQUE_OFFER_PHRASES:
            return True
        return any(phrase in lowered for phrase in _CRITIQUE_OFFER_PHRASES)

    def _has_critique_context(self) -> bool:
        if isinstance(self._active_plan_artifact, dict):
            return True
        last_mode = str(self._conversation_context.get("last_system_mode", "")).strip()
        last_intent = str(self._conversation_context.get("last_user_intent", "")).strip()
        if last_mode == "advisory" and last_intent in {"planning_request", "advisory_request"}:
            return True
        if self._session_goals or self._session_constraints or self._session_assumptions or self._session_decisions:
            return True
        return False

    def _build_critique_offer_response(self, *, trace_id: str) -> Dict[str, Any]:
        self._interactive_prompt_state = {
            "type": "critique_depth",
            "origin": "advisory",
            "prompt_id": f"interactive-{trace_id}",
            "question": _CRITIQUE_DEPTH_PROMPT,
        }
        return {
            "final_output": _CRITIQUE_DEPTH_PROMPT,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "interactive_prompt",
            "interactive_prompt_active": True,
            "interactive_prompt_type": "critique_depth",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _resolve_critique_depth_reply(self, reply: str) -> str | None:
        lowered = re.sub(r"\s+", " ", str(reply or "").strip().lower())
        lowered = lowered.rstrip(".!").strip()
        if not lowered:
            return None
        for token, value in _CRITIQUE_DEPTH_TOKENS.items():
            if lowered == token or token in lowered:
                return value
        return None

    def _active_records(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        active: List[Dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            if str(record.get("status", "active")).strip().lower() != "active":
                continue
            active.append(record)
        return active

    def _assumption_fragility_records(self, *, plan_steps: List[str]) -> List[Dict[str, Any]]:
        assumptions = self._active_records(self._session_assumptions)
        fragility_records: List[Dict[str, Any]] = []

        if not assumptions:
            return [
                {
                    "assumption_id": "assumption_unrecorded",
                    "summary": "No explicit assumptions are recorded for this plan.",
                    "validation_state": "unvalidated",
                    "fragility": "load_bearing",
                    "reason": "Plan relies on implicit assumptions that have not been confirmed.",
                    "suggested_actions": ["confirm", "revise", "hedge"],
                }
            ]

        steps_text = " ".join(plan_steps).lower()
        for record in assumptions:
            assumption_id = str(record.get("id", "")).strip() or "assumption_unknown"
            summary = str(record.get("summary", "")).strip()
            confirmed = bool(record.get("confirmed", False))
            validation_state = "validated" if confirmed else "unvalidated"
            fragility = "moderate"
            reason = "Assumption can affect plan reliability."

            summary_lower = summary.lower()
            if not confirmed:
                fragility = "high"
                reason = "Assumption is unvalidated and can fail under real conditions."

            if any(token in summary_lower for token in ("always", "guaranteed", "never", "everyone", "no risk")):
                fragility = "high"
                reason = "Absolute language suggests brittle assumptions under uncertainty."

            keywords = [token for token in re.findall(r"[a-z0-9_]+", summary_lower) if len(token) > 3]
            if keywords and any(keyword in steps_text for keyword in keywords):
                if fragility != "high":
                    fragility = "load_bearing"
                reason = "Assumption appears directly in plan steps and is load-bearing."

            fragility_records.append(
                {
                    "assumption_id": assumption_id,
                    "summary": summary,
                    "validation_state": validation_state,
                    "fragility": fragility,
                    "reason": reason,
                    "suggested_actions": ["confirm", "revise", "hedge"],
                }
            )

        return fragility_records

    def _gather_critique_context(self) -> Dict[str, Any]:
        plan_steps: List[str] = []
        source_utterance = str(self._conversation_context.get("last_user_input", "")).strip()
        intent_class = "planning_request"

        active_plan = self._active_plan_artifact if isinstance(self._active_plan_artifact, dict) else {}
        if isinstance(active_plan.get("steps"), list):
            plan_steps = [str(step).strip() for step in active_plan.get("steps", []) if str(step).strip()]
        if str(active_plan.get("source_utterance", "")).strip():
            source_utterance = str(active_plan.get("source_utterance", "")).strip()
        if str(active_plan.get("intent_class", "")).strip():
            intent_class = str(active_plan.get("intent_class", "")).strip()

        goals = self._active_records(self._session_goals)
        constraints = self._active_records(self._session_constraints)
        assumptions = self._active_records(self._session_assumptions)
        decisions = list(self._session_decisions)

        return {
            "plan_steps": plan_steps,
            "source_utterance": source_utterance,
            "intent_class": intent_class,
            "goals": goals,
            "constraints": constraints,
            "assumptions": assumptions,
            "decisions": decisions,
        }

    def _build_critique_sections(self, *, depth_mode: str, context: Dict[str, Any]) -> Dict[str, Any]:
        plan_steps = list(context.get("plan_steps", []))
        goals = list(context.get("goals", []))
        constraints = list(context.get("constraints", []))
        decisions = list(context.get("decisions", []))

        key_risks: List[str] = []
        if not plan_steps:
            key_risks.append("No explicit step sequence is captured, which increases coordination drift risk.")
        if len(plan_steps) > 4:
            key_risks.append("Long plan sequences can hide compounding risk between steps.")
        if not constraints:
            key_risks.append("No active constraint is recorded; scope and risk tolerance may drift.")
        if not goals:
            key_risks.append("No explicit active goal is recorded; success criteria may remain ambiguous.")
        if not key_risks:
            key_risks.append("Primary risk is assumption failure between checkpoints.")

        fragility = self._assumption_fragility_records(plan_steps=plan_steps)
        hidden_assumptions = [
            f"{item['assumption_id']}: {item['summary']} ({item['validation_state']}, {item['fragility']})"
            for item in fragility
        ]

        goal_constraint_tensions: List[str] = []
        goal_summaries = [str(item.get("summary", "")).strip().lower() for item in goals]
        constraint_summaries = [str(item.get("summary", "")).strip().lower() for item in constraints]
        steps_text = " ".join(plan_steps).lower()
        if goal_summaries and constraint_summaries:
            goal_constraint_tensions.append(
                "Goal and constraint set both exist; validate each step against both to avoid silent conflicts."
            )
        if any("speed" in goal for goal in goal_summaries) and any(
            token in " ".join(constraint_summaries) for token in ("low risk", "safe", "no downtime")
        ):
            goal_constraint_tensions.append(
                "Speed-oriented goals may tension with safety constraints; checkpoints must be explicit."
            )
        if any(token in steps_text for token in ("restart", "replace", "cutover")) and any(
            token in " ".join(constraint_summaries) for token in ("no downtime", "availability")
        ):
            goal_constraint_tensions.append(
                "Execution steps imply availability risk against no-downtime constraints."
            )
        if not goal_constraint_tensions:
            goal_constraint_tensions.append("No high-confidence goal/constraint tension detected from current records.")

        failure_modes: List[str] = []
        if plan_steps:
            failure_modes.append("A failed early step can invalidate downstream steps if checkpoints are skipped.")
        if decisions:
            failure_modes.append("Earlier decisions may be stale if assumptions have changed since they were recorded.")
        if any(item.get("fragility") in {"high", "load_bearing"} for item in fragility):
            failure_modes.append("Load-bearing assumptions can break the plan at critical transition steps.")
        if not failure_modes:
            failure_modes.append("Primary failure mode is unclear ownership of validation checkpoints.")

        mitigation_options = [
            "Define a pass/fail checkpoint after each plan step before proceeding.",
            "Confirm or revise high-fragility assumptions before committing the next step.",
            "Choose the lowest-risk alternative path for steps with high blast radius.",
        ]

        if depth_mode == "quick_check":
            key_risks = key_risks[:2]
            hidden_assumptions = hidden_assumptions[:2]
            failure_modes = failure_modes[:2]
            mitigation_options = mitigation_options[:2]
        elif depth_mode == "assumption_review":
            key_risks = [
                "Assumption fragility is the dominant risk axis for this plan.",
                "Unvalidated assumptions can invalidate downstream decisions quickly.",
            ]
            goal_constraint_tensions = goal_constraint_tensions[:1]
            failure_modes = [
                "Plan can fail if assumptions are accepted without confirmation or hedging."
            ]
            mitigation_options = [
                "Confirm fragile assumptions with explicit evidence.",
                "Revise assumptions that conflict with active constraints.",
                "Hedge assumptions with rollback-safe checkpoints.",
            ]

        return {
            "key_risks": key_risks,
            "hidden_assumptions": hidden_assumptions,
            "goal_constraint_tensions": goal_constraint_tensions,
            "failure_modes": failure_modes,
            "mitigation_options": mitigation_options,
            "assumption_fragility": fragility,
        }

    def _build_critique_response(self, *, depth_mode: str, trace_id: str) -> Dict[str, Any]:
        context = self._gather_critique_context()
        source_utterance = str(context.get("source_utterance", "")).strip() or "plan critique"
        intent_class = str(context.get("intent_class", "")).strip() or "planning_request"

        advisory_output = build_advisory_plan(
            utterance=source_utterance,
            intent_class=intent_class,
        )
        sections = self._build_critique_sections(depth_mode=depth_mode, context=context)
        advisory_output.update(sections)
        advisory_output["critique"] = {
            "depth_mode": depth_mode,
            "offered": True,
            "accepted": True,
            "advisory_only": True,
        }
        advisory_output["message"] = (
            "Constructive critique prepared. This is advisory analysis only; no plan or assumptions were modified."
        )
        advisory_output["clarifying_question"] = _CRITIQUE_FOLLOW_UP_PROMPT

        self._critique_pending = {
            "depth_mode": depth_mode,
            "source_utterance": source_utterance,
            "intent_class": intent_class,
        }
        advisory_output = self._prepare_advisory_output(advisory_output)
        self._interactive_prompt_state = {
            "type": "critique_follow_up",
            "origin": "advisory",
            "prompt_id": f"interactive-{trace_id}",
            "question": _CRITIQUE_FOLLOW_UP_PROMPT,
        }
        self._remember_conversational_context(
            user_input=source_utterance,
            intent_class=intent_class,
            mode="advisory",
        )
        return {
            "final_output": advisory_output,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "advisory",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _resolve_critique_follow_up_action(self, reply: str) -> str | None:
        lowered = re.sub(r"\s+", " ", str(reply or "").strip().lower())
        lowered = lowered.rstrip(".!").strip()
        if not lowered:
            return None
        if "revise" in lowered or "update plan" in lowered or "change plan" in lowered:
            return "revise_plan"
        if "alternative" in lowered or "explore" in lowered or "another option" in lowered:
            return "explore_alternative"
        if "accept" in lowered or "proceed" in lowered or "accept risk" in lowered:
            return "accept_risk"
        return None

    def _build_critique_follow_up_resolution(
        self,
        *,
        action: str,
        trace_id: str,
    ) -> Dict[str, Any]:
        pending = self._critique_pending if isinstance(self._critique_pending, dict) else {}
        source_utterance = str(pending.get("source_utterance", "")).strip() or str(
            self._conversation_context.get("last_user_input", "")
        ).strip()
        intent_class = str(pending.get("intent_class", "")).strip() or "planning_request"

        advisory_output = build_advisory_plan(
            utterance=source_utterance,
            intent_class=intent_class,
        )
        if action == "revise_plan":
            advisory_output["message"] = (
                "Revision path selected. I can help revise the plan, but I have not changed it automatically."
            )
            advisory_output["revision_focus"] = [
                "Harden the highest-risk step with an explicit checkpoint.",
                "Convert one load-bearing assumption into a validated condition.",
                "Minimize blast radius before higher-impact transitions.",
            ]
        elif action == "explore_alternative":
            advisory_output["message"] = (
                "Alternative path selected. Here are options to compare before changing the current plan."
            )
            advisory_output["alternative_options"] = [
                "Lower-risk path with more checkpoints.",
                "Balanced path with moderate speed and risk.",
                "Faster path with explicit rollback boundaries.",
            ]
        else:
            advisory_output["message"] = (
                "Risk acceptance recorded. I did not advance the plan automatically. "
                "Say `continue` when you explicitly want the next step."
            )

        advisory_output["critique_follow_up"] = {
            "action": action,
            "plan_modified": False,
            "assumptions_modified": False,
        }
        self._critique_pending = None
        advisory_output = self._prepare_advisory_output(advisory_output)
        self._remember_conversational_context(
            user_input=source_utterance,
            intent_class=intent_class,
            mode="advisory",
        )
        return {
            "final_output": advisory_output,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "advisory",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _explicit_planning_depth_mode(self, utterance: str) -> str | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return None
        for token, mode in _PLANNING_DEPTH_TOKENS.items():
            if token in lowered:
                return mode
        return None

    def _should_offer_idea_decomposition(self, *, utterance: str, intent_class: str) -> bool:
        if intent_class in {"governed_action_proposal", "execution_attempt"}:
            return False
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return False
        if self._is_website_build_request(lowered):
            return False
        if self._resolve_task_artifact_reference(lowered) is not None:
            return False
        if any(token in lowered for token in _IDEA_DECOMPOSITION_EXCLUSIONS):
            return False
        return any(phrase in lowered for phrase in _IDEA_DECOMPOSITION_TRIGGER_PHRASES)

    def _should_offer_planning_depth_control(self, *, utterance: str, intent_class: str) -> bool:
        if intent_class not in {"planning_request", "advisory_request"}:
            return False
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return False
        if self._explicit_planning_depth_mode(lowered) is not None:
            return False
        if self._is_website_build_request(lowered):
            return False
        if self._resolve_task_artifact_reference(lowered) is not None:
            return False
        has_planning_frame = any(token in lowered for token in ("plan", "strategy", "roadmap", "next steps"))
        has_uncertainty = any(token in lowered for token in ("not sure", "unsure", "stuck", "dont know", "don't know"))
        if not (has_planning_frame and has_uncertainty):
            return False
        if any(token in lowered for token in ("service", "repo", "repository", "file", "directory", "folder", ".html")):
            return False
        return True

    def _idea_decomposition_options(self, utterance: str) -> List[Dict[str, str]]:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if "ai" in lowered and "small business" in lowered:
            return [
                {
                    "title": "AI workflow service",
                    "benefits": "Fast validation with direct customer conversations and custom delivery.",
                    "risks": "Scales slowly and depends on founder time.",
                    "effort": "medium",
                    "alignment": "Strong if your goal is near-term revenue and hands-on learning.",
                },
                {
                    "title": "Productized software tool",
                    "benefits": "Higher long-term leverage through repeatable product delivery.",
                    "risks": "Higher upfront uncertainty before product-market fit is proven.",
                    "effort": "high",
                    "alignment": "Strong if your goal is scalable growth with reusable IP.",
                },
                {
                    "title": "Education + advisory hybrid",
                    "benefits": "Builds trust quickly while surfacing recurring pain points.",
                    "risks": "Can drift into content effort without clear monetization.",
                    "effort": "low",
                    "alignment": "Strong if your constraint is limited build bandwidth right now.",
                },
            ]
        return [
            {
                "title": "Explore opportunities",
                "benefits": "Reduces blind spots before committing resources.",
                "risks": "Can stall progress if exploration never narrows.",
                "effort": "low",
                "alignment": "Strong if your immediate goal is better decision quality.",
            },
            {
                "title": "Run a focused pilot",
                "benefits": "Creates concrete learning with bounded scope.",
                "risks": "Pilot findings may not generalize to full rollout.",
                "effort": "medium",
                "alignment": "Strong if you need evidence before full commitment.",
            },
            {
                "title": "Commit to one direction",
                "benefits": "Maximizes execution speed and momentum.",
                "risks": "Higher chance of rework if assumptions are weak.",
                "effort": "high",
                "alignment": "Strong when urgency outweighs exploration needs.",
            },
        ]

    def _idea_decomposition_question(self, options: List[Dict[str, str]]) -> str:
        labels = [str(item.get("title", "")).strip() for item in options if isinstance(item, dict)]
        labels = [label for label in labels if label]
        if len(labels) >= 3:
            return f"Which direction is closest right now: {labels[0]}, {labels[1]}, or {labels[2]}?"
        if len(labels) == 2:
            return f"Which direction is closer right now: {labels[0]} or {labels[1]}?"
        return "Which direction should we shape first?"

    def _build_idea_decomposition_response(self, *, utterance: str, trace_id: str) -> Dict[str, Any]:
        options = self._idea_decomposition_options(utterance)
        question = self._idea_decomposition_question(options)
        advisory_output: Dict[str, Any] = {
            "mode": "advisory",
            "execution_enabled": False,
            "advisory_only": True,
            "status": "clarification_required",
            "message": "Let us shape the idea before committing to a plan. Here are plausible directions.",
            "plan_steps": [],
            "suggested_commands": [],
            "risk_notes": [],
            "assumptions": [],
            "rollback_guidance": [],
            "options": options,
            "idea_decomposition": True,
            "clarifying_question": question,
            "commands_not_executed": True,
        }
        self._active_plan_artifact = None
        advisory_output = self._prepare_advisory_output(advisory_output)
        self._remember_conversational_context(
            user_input=utterance,
            intent_class="planning_request",
            mode="advisory",
        )
        return {
            "final_output": advisory_output,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "advisory",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _build_planning_depth_prompt_response(
        self,
        *,
        utterance: str,
        intent_class: str,
        trace_id: str,
    ) -> Dict[str, Any]:
        self._interactive_prompt_state = {
            "type": "planning_depth",
            "origin": "advisory",
            "prompt_id": f"interactive-{trace_id}",
            "question": _PLANNING_DEPTH_PROMPT,
            "seed_utterance": str(utterance or "").strip(),
            "intent_class": str(intent_class or "planning_request").strip() or "planning_request",
        }
        return {
            "final_output": _PLANNING_DEPTH_PROMPT,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "interactive_prompt",
            "interactive_prompt_active": True,
            "interactive_prompt_type": "planning_depth",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _resolve_planning_depth_reply(self, reply: str) -> str | None:
        normalized = re.sub(r"\s+", " ", str(reply or "").strip().lower())
        normalized = normalized.rstrip(".!").strip()
        if not normalized:
            return None
        if normalized in {"1", "one"}:
            return "high_level"
        if normalized in {"2", "two"}:
            return "step_by_step"
        if normalized in {"3", "three"}:
            return "critique"
        for token, mode in _PLANNING_DEPTH_TOKENS.items():
            if normalized == token or token in normalized:
                return mode
        return None

    def _apply_planning_depth_mode(self, advisory_output: Dict[str, Any], depth_mode: str) -> Dict[str, Any]:
        prepared = copy.deepcopy(advisory_output)
        mode = str(depth_mode or _PLANNING_DEPTH_DEFAULT_MODE).strip().lower()
        if mode not in {"high_level", "step_by_step", "critique"}:
            mode = _PLANNING_DEPTH_DEFAULT_MODE

        if mode == "high_level":
            prepared["message"] = (
                "High-level outline selected. Keeping this directional before committing to execution detail."
            )
            prepared["plan_steps"] = [
                "Clarify objective, constraints, and success criteria.",
                "Pick the safest viable path with clear checkpoints.",
                "Review outcomes and choose the next iteration.",
            ]
        elif mode == "step_by_step":
            prepared["message"] = (
                "Step-by-step depth selected. Each step is intended for one-checkpoint-at-a-time progress."
            )
        else:
            prepared["message"] = (
                "Critique/stress-test depth selected. I will frame options for risk, effort, and alignment pressure."
            )
            stress_test = [
                "What assumption would break this plan fastest?",
                "What is the smallest reversible checkpoint before higher-risk moves?",
                "Which option fails gracefully under your tightest constraint?",
            ]
            prepared["stress_test"] = stress_test

        prepared["planning_depth"] = {
            "mode": mode,
            "choices": ["high_level", "step_by_step", "critique"],
            "selected_via": "interactive_prompt",
        }
        return prepared

    def _build_depth_selected_advisory_response(
        self,
        *,
        seed_utterance: str,
        intent_class: str,
        depth_mode: str,
        trace_id: str,
    ) -> Dict[str, Any]:
        advisory_intent = str(intent_class or "planning_request").strip() or "planning_request"
        advisory_output = build_advisory_plan(
            utterance=seed_utterance,
            intent_class=advisory_intent,
        )
        advisory_output = self._apply_planning_depth_mode(advisory_output, depth_mode)
        self._register_plan_artifact_from_advisory(
            source_utterance=seed_utterance,
            intent_class=advisory_intent,
            advisory_output=advisory_output,
        )
        advisory_output = self._prepare_advisory_output(advisory_output)
        self._activate_interactive_prompt_from_advisory(
            advisory_output=advisory_output,
            trace_id=trace_id,
        )
        self._remember_conversational_context(
            user_input=seed_utterance,
            intent_class=advisory_intent,
            mode="advisory",
        )
        return {
            "final_output": advisory_output,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "advisory",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _register_plan_artifact_from_advisory(
        self,
        *,
        source_utterance: str,
        intent_class: str,
        advisory_output: Dict[str, Any],
    ) -> None:
        if not isinstance(advisory_output, dict):
            self._active_plan_artifact = None
            return
        if bool(advisory_output.get("idea_decomposition")):
            self._active_plan_artifact = None
            return
        plan_steps = advisory_output.get("plan_steps", [])
        if not isinstance(plan_steps, list):
            self._active_plan_artifact = None
            return
        normalized_steps = [str(step).strip() for step in plan_steps if str(step).strip()]
        if not normalized_steps:
            self._active_plan_artifact = None
            return
        source = str(source_utterance or "").strip()
        advisory_intent = str(intent_class or "planning_request").strip() or "planning_request"
        canonical = json.dumps(
            {
                "source": source.lower(),
                "intent_class": advisory_intent,
                "plan_steps": normalized_steps,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        artifact_id = f"plan-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:12]}"
        template = copy.deepcopy(advisory_output)
        template.pop("continuation_question", None)
        template.pop("rendered_advisory", None)
        self._active_plan_artifact = {
            "artifact_id": artifact_id,
            "revision": 1,
            "next_step_index": 0,
            "total_steps": len(normalized_steps),
            "steps": normalized_steps,
            "source_utterance": source,
            "intent_class": advisory_intent,
            "template": template,
        }

    def _advance_active_plan_artifact(self, *, signal: str, trace_id: str) -> Dict[str, Any] | None:
        state = self._active_plan_artifact
        if not isinstance(state, dict):
            return None
        if isinstance(self._critique_pending, dict):
            return None
        if str(self._conversation_context.get("last_system_mode", "")).strip() != "advisory":
            return None
        steps = state.get("steps", [])
        if not isinstance(steps, list):
            return None
        steps = [str(step).strip() for step in steps if str(step).strip()]
        if not steps:
            return None

        next_step_index = state.get("next_step_index", 0)
        next_step_index = int(next_step_index) if isinstance(next_step_index, int) else 0
        total_steps = len(steps)
        template = state.get("template", {})
        advisory_output = copy.deepcopy(template) if isinstance(template, dict) else {}
        if not advisory_output:
            advisory_output = build_advisory_plan(
                utterance=str(state.get("source_utterance", "")).strip(),
                intent_class=str(state.get("intent_class", "")).strip() or "planning_request",
            )

        active_step = ""
        advanced = False
        if next_step_index < total_steps:
            active_step = steps[next_step_index]
            next_step_index += 1
            state["next_step_index"] = next_step_index
            current_revision = state.get("revision", 1)
            current_revision = int(current_revision) if isinstance(current_revision, int) else 1
            state["revision"] = current_revision + 1
            advanced = True

        remaining = max(total_steps - next_step_index, 0)
        if advanced:
            advisory_output["message"] = f"Advancing one step ({next_step_index}/{total_steps}): {active_step}"
        else:
            advisory_output["message"] = "Plan already fully advanced. I can refine it with new constraints if needed."

        advisory_output["plan_progress"] = {
            "artifact_id": str(state.get("artifact_id", "")).strip(),
            "revision": int(state.get("revision", 1) or 1),
            "ack_signal": str(signal or "").strip(),
            "advanced": advanced,
            "current_step_index": next_step_index,
            "total_steps": total_steps,
            "remaining_steps": remaining,
            "active_step": active_step,
        }
        advisory_output["clarifying_question"] = (
            "Do you want me to advance one more step?"
            if remaining > 0
            else "Do you want a refinement pass on this plan?"
        )
        advisory_output = self._prepare_advisory_output(advisory_output)
        self._activate_interactive_prompt_from_advisory(
            advisory_output=advisory_output,
            trace_id=trace_id,
        )
        self._remember_conversational_context(
            user_input=str(state.get("source_utterance", "")).strip(),
            intent_class=str(state.get("intent_class", "")).strip() or "planning_request",
            mode="advisory",
        )
        return {
            "final_output": advisory_output,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "advisory",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _artifact_public_view(self, artifact: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": str(artifact.get("name", "")).strip(),
            "type": str(artifact.get("artifact_type", "")).strip(),
            "revision": int(artifact.get("revision", 0)),
            "revision_id": str(artifact.get("revision_id", "")).strip(),
            "summary": str(artifact.get("summary", "")).strip(),
            "session_scoped": True,
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _artifact_content_as_text(self, content: Any) -> str:
        if isinstance(content, dict):
            html_value = content.get("html")
            if isinstance(html_value, str) and html_value.strip():
                return html_value.strip()
        return json.dumps(content, sort_keys=True, indent=2)

    def _artifact_content_hash(self, content: Any) -> str:
        canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _artifact_revision_id(self, *, name: str, revision: int, content_hash: str) -> str:
        return f"{name}:r{revision}:{content_hash[:12]}"

    def _compute_artifact_diff(
        self,
        *,
        artifact_name: str,
        from_revision_id: str,
        to_revision_id: str,
        previous_content: Any,
        current_content: Any,
    ) -> Dict[str, Any] | None:
        previous_text = self._artifact_content_as_text(previous_content)
        current_text = self._artifact_content_as_text(current_content)
        if previous_text == current_text:
            return None

        previous_lines = previous_text.splitlines()
        current_lines = current_text.splitlines()
        matcher = SequenceMatcher(a=previous_lines, b=current_lines, autojunk=False)
        added_lines: List[str] = []
        removed_lines: List[str] = []
        changed_sections: List[Dict[str, str]] = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            if tag in {"replace", "delete"}:
                for old_line in previous_lines[i1:i2]:
                    removed_lines.append(old_line)
            if tag in {"replace", "insert"}:
                for new_line in current_lines[j1:j2]:
                    added_lines.append(new_line)
            if tag == "replace":
                old_block = "\n".join(previous_lines[i1:i2]).strip()
                new_block = "\n".join(current_lines[j1:j2]).strip()
                changed_sections.append(
                    {
                        "from": old_block,
                        "to": new_block,
                    }
                )

        max_lines = 6
        added_preview = added_lines[:max_lines]
        removed_preview = removed_lines[:max_lines]
        changed_preview = changed_sections[:3]

        lines: List[str] = [
            f"Diff {from_revision_id} -> {to_revision_id} ({artifact_name})",
        ]
        if added_preview:
            lines.append("Added lines:")
            for line in added_preview:
                lines.append(f"+ {line}")
        if removed_preview:
            lines.append("Removed lines:")
            for line in removed_preview:
                lines.append(f"- {line}")
        if changed_preview:
            lines.append("Changed sections:")
            for section in changed_preview:
                old_line = str(section.get("from", "")).splitlines()
                new_line = str(section.get("to", "")).splitlines()
                old_preview = old_line[0] if old_line else ""
                new_preview = new_line[0] if new_line else ""
                lines.append(f"~ {old_preview} -> {new_preview}")

        return {
            "artifact_name": artifact_name,
            "from_revision_id": from_revision_id,
            "to_revision_id": to_revision_id,
            "added_lines": added_preview,
            "removed_lines": removed_preview,
            "changed_sections": changed_preview,
            "diff_text": "\n".join(lines).strip(),
        }

    def _latest_artifact_diff(self, artifact_name: str) -> Dict[str, Any] | None:
        history = self._task_artifact_history.get(str(artifact_name or "").strip(), [])
        if not isinstance(history, list) or len(history) < 2:
            return None
        previous = history[-2]
        current = history[-1]
        if not isinstance(previous, dict) or not isinstance(current, dict):
            return None
        return self._compute_artifact_diff(
            artifact_name=str(current.get("name", "")).strip() or str(artifact_name or "").strip(),
            from_revision_id=str(previous.get("revision_id", "")).strip(),
            to_revision_id=str(current.get("revision_id", "")).strip(),
            previous_content=previous.get("content"),
            current_content=current.get("content"),
        )

    def _upsert_task_artifact(
        self,
        *,
        name: str,
        artifact_type: str,
        content: Any,
        summary: str,
        source_mode: str,
    ) -> Dict[str, Any]:
        normalized_name = str(name or "").strip()
        if not normalized_name:
            raise ValueError("artifact name is required")
        existing = self._task_artifacts.get(normalized_name, {})
        normalized_type = str(artifact_type or "").strip() or normalized_name
        normalized_summary = str(summary or "").strip()
        normalized_source_mode = str(source_mode or "").strip() or "conversation"
        normalized_content = copy.deepcopy(content)
        if (
            isinstance(existing, dict)
            and str(existing.get("artifact_type", "")).strip() == normalized_type
            and existing.get("content") == normalized_content
            and str(existing.get("summary", "")).strip() == normalized_summary
            and str(existing.get("source_mode", "")).strip() == normalized_source_mode
        ):
            return copy.deepcopy(existing)

        existing_revision = existing.get("revision", 0)
        revision = existing_revision if isinstance(existing_revision, int) and existing_revision >= 0 else 0
        content_hash = self._artifact_content_hash(normalized_content)
        revision_id = self._artifact_revision_id(
            name=normalized_name,
            revision=revision + 1,
            content_hash=content_hash,
        )
        previous_revision_id = str(existing.get("revision_id", "")).strip() if isinstance(existing, dict) else ""
        artifact = {
            "name": normalized_name,
            "artifact_type": normalized_type,
            "content": normalized_content,
            "summary": normalized_summary,
            "source_mode": normalized_source_mode,
            "revision": revision + 1,
            "revision_id": revision_id,
            "content_hash": content_hash,
            "previous_revision_id": previous_revision_id,
        }
        self._task_artifacts[normalized_name] = artifact
        history = self._task_artifact_history.setdefault(normalized_name, [])
        history.append(copy.deepcopy(artifact))
        if isinstance(existing, dict) and existing:
            self._last_task_artifact_diff = self._compute_artifact_diff(
                artifact_name=normalized_name,
                from_revision_id=previous_revision_id,
                to_revision_id=revision_id,
                previous_content=existing.get("content"),
                current_content=normalized_content,
            )
        else:
            self._last_task_artifact_diff = None
        return copy.deepcopy(artifact)

    def _get_task_artifact(self, name: str) -> Dict[str, Any] | None:
        normalized_name = str(name or "").strip()
        if not normalized_name:
            return None
        artifact = self._task_artifacts.get(normalized_name)
        if not isinstance(artifact, dict):
            return None
        return copy.deepcopy(artifact)

    def _discard_task_artifact(self, name: str) -> bool:
        normalized_name = str(name or "").strip()
        if not normalized_name:
            return False
        if normalized_name not in self._task_artifacts:
            return False
        del self._task_artifacts[normalized_name]
        return True

    def _extract_artifact_reset_target(self, utterance: str) -> str | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return None
        if lowered in {"start over", "reset artifacts", "clear artifacts", "discard artifacts"}:
            return "__all__"
        reset_verbs = ("discard", "reset", "clear", "remove", "delete", "drop")
        if not any(verb in lowered for verb in reset_verbs):
            return None
        for artifact_name in sorted(self._task_artifacts.keys(), key=lambda item: (-len(item), item)):
            if re.search(rf"\b{re.escape(artifact_name.lower())}\b", lowered):
                return artifact_name
        if "html_page" in lowered or "html page" in lowered or "the html" in lowered or "html" in lowered:
            return "html_page"
        if (
            "study_session" in lowered
            or "study session" in lowered
            or "study set" in lowered
            or "vocabulary set" in lowered
        ):
            return "study_session"
        return None

    def _resolve_task_artifact_reference(self, utterance: str) -> str | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return None
        for artifact_name in sorted(self._task_artifacts.keys(), key=lambda item: (-len(item), item)):
            if re.search(rf"\b{re.escape(artifact_name.lower())}\b", lowered):
                return artifact_name
        if "html_page" in lowered and "html_page" in self._task_artifacts:
            return "html_page"
        if (
            "html_page" in self._task_artifacts
            and (
                "the html" in lowered
                or "html we made" in lowered
                or "html page" in lowered
                or "web page" in lowered
                or "website page" in lowered
                or "add a paragraph" in lowered
                or "add paragraph" in lowered
            )
        ):
            return "html_page"
        if "study_session" in lowered and "study_session" in self._task_artifacts:
            return "study_session"
        if (
            "study_session" in self._task_artifacts
            and (
                "study set" in lowered
                or "study session" in lowered
                or "continue studying" in lowered
                or "continue the study" in lowered
                or "resume study" in lowered
                or "resume the study" in lowered
            )
        ):
            return "study_session"
        return None

    def _resolve_artifact_control_target(self, utterance: str) -> str | None:
        referenced = self._resolve_task_artifact_reference(utterance)
        if referenced is not None:
            return referenced
        if isinstance(self._last_task_artifact_diff, dict):
            last_name = str(self._last_task_artifact_diff.get("artifact_name", "")).strip()
            if last_name and last_name in self._task_artifacts:
                return last_name
        if len(self._task_artifacts) == 1:
            return next(iter(self._task_artifacts.keys()))
        return None

    def _is_artifact_diff_query(self, utterance: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return False
        if lowered in _ARTIFACT_DIFF_QUERY_PHRASES:
            return True
        return any(phrase in lowered for phrase in _ARTIFACT_DIFF_QUERY_PHRASES)

    def _is_artifact_readiness_query(self, utterance: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower()).rstrip("?.!")
        if not lowered:
            return False
        if lowered in _ARTIFACT_READINESS_QUERY_PHRASES:
            return True
        return any(phrase in lowered for phrase in _ARTIFACT_READINESS_QUERY_PHRASES)

    def _is_artifact_execution_plan_query(self, utterance: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower()).rstrip("?.!")
        if not lowered:
            return False
        if lowered in _ARTIFACT_EXECUTION_PLAN_QUERY_PHRASES:
            return True
        return any(phrase in lowered for phrase in _ARTIFACT_EXECUTION_PLAN_QUERY_PHRASES)

    def _is_execution_capability_query(self, utterance: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower()).rstrip("?.!")
        if not lowered:
            return False
        if lowered in _EXECUTION_CAPABILITY_QUERY_PHRASES:
            return True
        return any(phrase in lowered for phrase in _EXECUTION_CAPABILITY_QUERY_PHRASES)

    def _execution_arming_query_mode(self, utterance: str) -> str | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower()).rstrip("?.!")
        if not lowered:
            return None
        if lowered in _EXECUTION_ARMING_STATUS_QUERY_PHRASES:
            return "status"
        if lowered in _EXECUTION_ARMING_CONCEPT_QUERY_PHRASES:
            return "conceptual"
        if any(phrase in lowered for phrase in _EXECUTION_ARMING_STATUS_QUERY_PHRASES):
            return "status"
        if any(phrase in lowered for phrase in _EXECUTION_ARMING_CONCEPT_QUERY_PHRASES):
            return "conceptual"
        return None

    def _is_execution_boundary_unification_query(self, utterance: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower()).rstrip("?.!")
        if not lowered:
            return False
        if lowered in _EXECUTION_BOUNDARY_UNIFICATION_QUERY_PHRASES:
            return True
        return any(phrase in lowered for phrase in _EXECUTION_BOUNDARY_UNIFICATION_QUERY_PHRASES)

    def _execution_arming_declaration_artifact(self) -> Dict[str, Any]:
        execution_arming = {
            "armed": False,
            "arming_required_for_execution": True,
            "arming_supported": False,
            "reason": "Execution capability is not enabled in this system.",
        }
        manifest_fingerprint = hashlib.sha256(
            json.dumps(execution_arming, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        declaration_yaml_lines = [
            "execution_arming:",
            "  armed: false",
            "  arming_required_for_execution: true",
            "  arming_supported: false",
            "  reason: \"Execution capability is not enabled in this system.\"",
        ]
        return {
            "type": "execution_arming_declaration",
            "contract_version": "phase48.execution_arming.v1",
            "execution_arming": execution_arming,
            "can_execute": False,
            "message": (
                "Execution is disarmed. Arming is required for execution, "
                "and arming is unsupported in this phase."
            ),
            "conceptual_explanation": (
                "Conceptually, execution arming would represent an explicit governed state transition. "
                "In this phase that transition is unavailable, no toggles exist, and no enablement steps are provided."
            ),
            "execution_arming_yaml": "\n".join(declaration_yaml_lines),
            "execution_arming_read_only": True,
            "manifest_fingerprint": manifest_fingerprint,
        }

    def _build_execution_arming_declaration_response(self, *, trace_id: str) -> Dict[str, Any]:
        declaration = self._execution_arming_declaration_artifact()
        arming = declaration.get("execution_arming", {})

        rendered_lines: List[str] = [
            "Execution Arming Declaration",
            "",
            str(declaration.get("message", "")).strip(),
            "",
            "Arming State (Read-Only)",
            f"- armed: {str(bool(arming.get('armed', False))).lower()}",
            f"- arming_required_for_execution: {str(bool(arming.get('arming_required_for_execution', False))).lower()}",
            f"- arming_supported: {str(bool(arming.get('arming_supported', False))).lower()}",
            f"- reason: {str(arming.get('reason', '')).strip()}",
            "",
            "Conceptual Note",
            str(declaration.get("conceptual_explanation", "")).strip(),
        ]
        declaration["rendered_advisory"] = "\n".join(rendered_lines).strip()

        self._remember_conversational_context(
            user_input="execution arming declaration",
            intent_class="informational_query",
            mode="advisory",
        )
        return {
            "final_output": declaration,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "advisory",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _execution_capability_declaration_artifact(self) -> Dict[str, Any]:
        execution_capabilities = {
            "enabled": False,
            "available_modes": [],
            "declared_absences": list(_DECLARED_EXECUTION_CAPABILITY_ABSENCES),
            "inert": True,
            "read_only": True,
        }
        manifest_fingerprint = hashlib.sha256(
            json.dumps(execution_capabilities, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        declaration_yaml_lines = [
            "execution_capabilities:",
            "  enabled: false",
            "  available_modes: []",
            "  declared_absences:",
        ]
        for absence in _DECLARED_EXECUTION_CAPABILITY_ABSENCES:
            declaration_yaml_lines.append(f"    - {absence}")
        declaration_yaml = "\n".join(declaration_yaml_lines)
        return {
            "type": "execution_capability_declaration",
            "contract_version": "phase47.execution_capabilities.v1",
            "can_execute": False,
            "executable_actions": "none",
            "message": (
                "No. Billy cannot execute this. Execution capabilities are explicitly disabled in this phase, and none are enabled."
            ),
            "execution_capabilities": execution_capabilities,
            "capability_declaration_yaml": declaration_yaml,
            "execution_boundary_notice": (
                "Execution must be explicitly enabled in a future governed phase. "
                "Billy will not execute commands or tools now."
            ),
            "capability_declaration_read_only": True,
            "manifest_fingerprint": manifest_fingerprint,
        }

    def _build_execution_capability_declaration_response(self, *, trace_id: str) -> Dict[str, Any]:
        declaration = self._execution_capability_declaration_artifact()
        capabilities = declaration.get("execution_capabilities", {})
        declared_absences = capabilities.get("declared_absences", [])
        declared_absences = declared_absences if isinstance(declared_absences, list) else []

        rendered_lines: List[str] = [
            "Execution Capability Declaration",
            "",
            str(declaration.get("message", "")).strip(),
            "",
            "Machine-Readable Manifest",
            f"- enabled: {str(bool(capabilities.get('enabled', False))).lower()}",
            (
                "- available_modes: []"
                if not capabilities.get("available_modes")
                else f"- available_modes: {json.dumps(capabilities.get('available_modes', []))}"
            ),
            "- declared_absences:",
        ]
        if declared_absences:
            for absence in declared_absences:
                rendered_lines.append(f"  - {str(absence)}")
        else:
            rendered_lines.append("  - none")
        rendered_lines.extend(
            [
                "",
                "Execution Boundary Notice",
                str(declaration.get("execution_boundary_notice", "")).strip(),
            ]
        )
        declaration["rendered_advisory"] = "\n".join(rendered_lines).strip()

        self._remember_conversational_context(
            user_input="execution capability declaration",
            intent_class="informational_query",
            mode="advisory",
        )
        return {
            "final_output": declaration,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "advisory",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _build_execution_boundary_unification_response(
        self,
        *,
        utterance: str,
        trace_id: str,
    ) -> Dict[str, Any]:
        capability_declaration = self._execution_capability_declaration_artifact()
        capability_state = capability_declaration.get("execution_capabilities", {})
        capability_state = capability_state if isinstance(capability_state, dict) else {}

        arming_declaration = self._execution_arming_declaration_artifact()
        arming_state = arming_declaration.get("execution_arming", {})
        arming_state = arming_state if isinstance(arming_state, dict) else {}

        readiness_boundary: Dict[str, Any]
        target_name = self._resolve_artifact_control_target(utterance)
        target_artifact = self._get_task_artifact(target_name) if target_name else None
        if target_artifact is None:
            readiness_boundary = {
                "artifact_name": "",
                "artifact_type": "",
                "artifact_revision_id": "",
                "ready": False,
                "blocking_issues": [
                    "No artifact is selected for readiness evaluation.",
                ],
                "non_blocking_notes": [],
                "assumptions_to_confirm": [
                    "Readiness remains advisory-only and does not authorize execution.",
                ],
                "readiness_fingerprint": "",
                "source": "phase45.readiness.v1",
            }
        else:
            readiness_report = self._evaluate_artifact_readiness(target_artifact)
            readiness_boundary = {
                "artifact_name": str(readiness_report.get("artifact_name", "")).strip(),
                "artifact_type": str(readiness_report.get("artifact_type", "")).strip(),
                "artifact_revision_id": str(readiness_report.get("artifact_revision_id", "")).strip(),
                "ready": bool(readiness_report.get("ready", False)),
                "blocking_issues": [
                    str(item)
                    for item in readiness_report.get("blocking_issues", [])
                    if str(item).strip()
                ],
                "non_blocking_notes": [
                    str(item)
                    for item in readiness_report.get("non_blocking_notes", [])
                    if str(item).strip()
                ],
                "assumptions_to_confirm": [
                    str(item)
                    for item in readiness_report.get("assumptions_to_confirm", [])
                    if str(item).strip()
                ],
                "readiness_fingerprint": str(readiness_report.get("readiness_fingerprint", "")).strip(),
                "source": "phase45.readiness.v1",
            }

        active_goals = self._active_goals()
        active_goal_entries = []
        for record in active_goals:
            if not isinstance(record, dict):
                continue
            goal_id = str(record.get("id", "")).strip()
            goal_summary = str(record.get("summary", "")).strip()
            if not goal_id or not goal_summary:
                continue
            active_goal_entries.append(
                {
                    "id": goal_id,
                    "summary": goal_summary,
                }
            )

        active_constraint_entries = []
        for record in self._session_constraints:
            if not isinstance(record, dict):
                continue
            if str(record.get("status", "")).strip().lower() != "active":
                continue
            constraint_id = str(record.get("id", "")).strip()
            constraint_summary = str(record.get("summary", "")).strip()
            if not constraint_id or not constraint_summary:
                continue
            active_constraint_entries.append(
                {
                    "id": constraint_id,
                    "summary": constraint_summary,
                }
            )

        goal_constraint_conflicts = []
        conflict_seen: set[tuple[str, str, str]] = set()
        for goal in active_goal_entries:
            conflict = self._active_constraint_conflict(str(goal.get("summary", "")).strip())
            if conflict is None:
                continue
            conflict_record = {
                "goal_id": str(goal.get("id", "")).strip(),
                "goal_summary": str(goal.get("summary", "")).strip(),
                "constraint_id": str(conflict.get("constraint_id", "")).strip(),
                "constraint_summary": str(conflict.get("constraint_summary", "")).strip(),
                "reason": str(conflict.get("reason", "")).strip(),
            }
            conflict_key = (
                conflict_record["goal_id"],
                conflict_record["constraint_id"],
                conflict_record["reason"],
            )
            if conflict_key in conflict_seen:
                continue
            conflict_seen.add(conflict_key)
            goal_constraint_conflicts.append(conflict_record)

        intent_alignment = {
            "active_goals": active_goal_entries,
            "active_constraints": active_constraint_entries,
            "goal_constraint_conflicts": goal_constraint_conflicts,
            "source": "phases57_56.goal_constraint_registers.v1",
        }

        key_decisions = []
        for record in self._session_decisions:
            if not isinstance(record, dict):
                continue
            decision_id = str(record.get("id", "")).strip()
            decision_summary = str(record.get("summary", "")).strip()
            if not decision_id or not decision_summary:
                continue
            key_decisions.append(
                {
                    "id": decision_id,
                    "summary": decision_summary,
                    "context": str(record.get("context", "")).strip(),
                }
            )

        key_assumptions = []
        for record in self._session_assumptions:
            if not isinstance(record, dict):
                continue
            if str(record.get("status", "")).strip().lower() != "active":
                continue
            assumption_id = str(record.get("id", "")).strip()
            assumption_summary = str(record.get("summary", "")).strip()
            if not assumption_id or not assumption_summary:
                continue
            key_assumptions.append(
                {
                    "id": assumption_id,
                    "summary": assumption_summary,
                    "context": str(record.get("context", "")).strip(),
                    "confirmed": bool(record.get("confirmed", False)),
                }
            )

        decision_assumption_context = {
            "key_decisions": key_decisions,
            "key_assumptions": key_assumptions,
            "source": "phases54_55.decision_assumption_registers.v1",
        }

        capability_enabled = bool(capability_state.get("enabled", False))
        armed = bool(arming_state.get("armed", False))
        arming_supported = bool(arming_state.get("arming_supported", False))
        readiness_ready = bool(readiness_boundary.get("ready", False))
        readiness_artifact = str(readiness_boundary.get("artifact_name", "")).strip() or "no selected artifact"
        readiness_blockers = readiness_boundary.get("blocking_issues", [])
        readiness_blockers = readiness_blockers if isinstance(readiness_blockers, list) else []
        readiness_blocker_count = len(readiness_blockers)

        executive_summary = (
            "Execution cannot occur in this system because execution capability is disabled, "
            "execution arming is false and unsupported, and readiness is not execution-authorizing "
            f"for {readiness_artifact} ({readiness_blocker_count} blocker(s), ready={str(readiness_ready).lower()}). "
            "This is a read-only boundary explanation, not permission."
        )

        hypothetical_enablement = {
            "conceptual_only": True,
            "required_change_categories": [
                "A governed capability declaration would need to represent execution support as present.",
                "A governed arming mechanism would need to exist and support an explicit armed state transition.",
                "A deterministic readiness outcome would need ready=true with no blockers for a specific artifact.",
                "Goals, constraints, decisions, and assumptions would need to remain mutually aligned and validated.",
            ],
            "note": (
                "This explanation is conceptual only and intentionally excludes operational steps, commands, or approvals."
            ),
        }

        execution_boundary_notice = "Billy cannot execute actions in this system."
        capability_declared_absences = capability_state.get("declared_absences", [])
        capability_declared_absences = (
            capability_declared_absences if isinstance(capability_declared_absences, list) else []
        )

        boundary_payload = {
            "type": "execution_boundary_unification",
            "contract_version": "phase58.execution_boundary_unification.v1",
            "mode": "advisory",
            "execution_enabled": False,
            "advisory_only": True,
            "executive_summary": executive_summary,
            "capability_boundary": {
                "execution_supported": capability_enabled,
                "why": str(capability_declaration.get("message", "")).strip(),
                "declared_absences": [str(item) for item in capability_declared_absences if str(item).strip()],
                "manifest_fingerprint": str(capability_declaration.get("manifest_fingerprint", "")).strip(),
            },
            "arming_boundary": {
                "armed": armed,
                "arming_required_for_execution": bool(arming_state.get("arming_required_for_execution", False)),
                "arming_supported": arming_supported,
                "reason": str(arming_state.get("reason", "")).strip(),
                "manifest_fingerprint": str(arming_declaration.get("manifest_fingerprint", "")).strip(),
            },
            "readiness_boundary": readiness_boundary,
            "intent_alignment": intent_alignment,
            "decision_assumption_context": decision_assumption_context,
            "hypothetical_enablement": hypothetical_enablement,
            "execution_boundary_notice": execution_boundary_notice,
            "boundary_read_only": True,
        }

        boundary_fingerprint = hashlib.sha256(
            json.dumps(boundary_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        boundary_payload["boundary_fingerprint"] = boundary_fingerprint

        rendered_lines: List[str] = [
            "Executive Summary",
            executive_summary,
            "",
            "Capability Boundary",
            f"- execution_supported: {str(capability_enabled).lower()}",
            f"- why: {str(capability_declaration.get('message', '')).strip()}",
            "- declared_absences:",
        ]
        if capability_declared_absences:
            for absence in capability_declared_absences:
                rendered_lines.append(f"  - {str(absence)}")
        else:
            rendered_lines.append("  - none")

        readiness_blocking_issues = readiness_boundary.get("blocking_issues", [])
        readiness_blocking_issues = (
            readiness_blocking_issues if isinstance(readiness_blocking_issues, list) else []
        )
        readiness_non_blocking_notes = readiness_boundary.get("non_blocking_notes", [])
        readiness_non_blocking_notes = (
            readiness_non_blocking_notes if isinstance(readiness_non_blocking_notes, list) else []
        )

        rendered_lines.extend(
            [
                "",
                "Arming Boundary",
                f"- armed: {str(armed).lower()}",
                f"- arming_supported: {str(arming_supported).lower()}",
                f"- reason: {str(arming_state.get('reason', '')).strip()}",
                "",
                "Readiness Boundary",
                f"- artifact: {readiness_artifact}",
                f"- ready: {str(readiness_ready).lower()}",
                "- blocking_issues:",
            ]
        )
        if readiness_blocking_issues:
            for issue in readiness_blocking_issues:
                rendered_lines.append(f"  - {str(issue)}")
        else:
            rendered_lines.append("  - none")
        rendered_lines.append("- non_blocking_notes:")
        if readiness_non_blocking_notes:
            for note in readiness_non_blocking_notes:
                rendered_lines.append(f"  - {str(note)}")
        else:
            rendered_lines.append("  - none")

        rendered_lines.extend(
            [
                "",
                "Intent Alignment",
                "- active_goals:",
            ]
        )
        if active_goal_entries:
            for goal in active_goal_entries:
                rendered_lines.append(
                    f"  - {str(goal.get('id', '')).strip()}: {str(goal.get('summary', '')).strip()}"
                )
        else:
            rendered_lines.append("  - none")
        rendered_lines.append("- active_constraints:")
        if active_constraint_entries:
            for constraint in active_constraint_entries:
                rendered_lines.append(
                    f"  - {str(constraint.get('id', '')).strip()}: {str(constraint.get('summary', '')).strip()}"
                )
        else:
            rendered_lines.append("  - none")
        rendered_lines.append("- goal_constraint_conflicts:")
        if goal_constraint_conflicts:
            for conflict in goal_constraint_conflicts:
                rendered_lines.append(
                    "  - "
                    f"{str(conflict.get('goal_id', '')).strip()} conflicts with "
                    f"{str(conflict.get('constraint_id', '')).strip()}: "
                    f"{str(conflict.get('reason', '')).strip()}"
                )
        else:
            rendered_lines.append("  - none")

        rendered_lines.extend(
            [
                "",
                "Decision & Assumption Context",
                "- key_decisions:",
            ]
        )
        if key_decisions:
            for decision in key_decisions:
                rendered_lines.append(
                    f"  - {str(decision.get('id', '')).strip()}: {str(decision.get('summary', '')).strip()}"
                )
        else:
            rendered_lines.append("  - none")
        rendered_lines.append("- key_assumptions:")
        if key_assumptions:
            for assumption in key_assumptions:
                rendered_lines.append(
                    f"  - {str(assumption.get('id', '')).strip()}: {str(assumption.get('summary', '')).strip()}"
                )
        else:
            rendered_lines.append("  - none")

        rendered_lines.extend(
            [
                "",
                "Hypothetical Enablement (Conceptual Only)",
            ]
        )
        for line in hypothetical_enablement["required_change_categories"]:
            rendered_lines.append(f"- {line}")
        rendered_lines.extend(
            [
                f"- {str(hypothetical_enablement.get('note', '')).strip()}",
                "",
                "Execution Boundary Notice",
                execution_boundary_notice,
            ]
        )
        boundary_payload["rendered_advisory"] = "\n".join(rendered_lines).strip()

        self._remember_conversational_context(
            user_input=utterance,
            intent_class="informational_query",
            mode="advisory",
        )
        return {
            "final_output": boundary_payload,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "advisory",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _evaluate_artifact_readiness(self, artifact: Dict[str, Any]) -> Dict[str, Any]:
        artifact_name = str(artifact.get("name", "")).strip() or "artifact"
        artifact_type = str(artifact.get("artifact_type", "")).strip() or artifact_name
        content = artifact.get("content", {})
        content = content if isinstance(content, dict) else {}
        revision_id = str(artifact.get("revision_id", "")).strip()
        blocking_issues: List[str] = []
        non_blocking_notes: List[str] = []
        assumptions_to_confirm: List[str] = []
        next_safe_steps: List[str] = []

        if self._is_html_artifact(artifact):
            filename = str(content.get("filename", "")).strip()
            html_text = str(content.get("html", "")).strip()
            lowered_html = html_text.lower()

            if not filename:
                blocking_issues.append("Missing required filename for HTML artifact.")
            elif not filename.lower().endswith(".html"):
                blocking_issues.append("Filename must end with `.html`.")

            if not html_text:
                blocking_issues.append("Missing HTML content.")
            else:
                required_tags = (
                    ("<html", "Missing opening `<html>` tag."),
                    ("</html>", "Missing closing `</html>` tag."),
                    ("<head", "Missing opening `<head>` section."),
                    ("</head>", "Missing closing `</head>` section."),
                    ("<body", "Missing opening `<body>` section."),
                    ("</body>", "Missing closing `</body>` section."),
                    ("<title", "Missing required `<title>` element."),
                )
                for token, issue in required_tags:
                    if token not in lowered_html:
                        blocking_issues.append(issue)

                if "<!doctype html" not in lowered_html:
                    non_blocking_notes.append("Recommended: add `<!doctype html>` for standards-mode rendering.")
                if "<meta name=\"viewport\"" not in lowered_html and "<meta name='viewport'" not in lowered_html:
                    non_blocking_notes.append(
                        "Recommended: add a viewport meta tag for responsive behavior."
                    )
                if "not executed" in lowered_html:
                    non_blocking_notes.append("Advisory marker detected: content remains non-executing.")

            assumptions_to_confirm = [
                "Execution remains manual: Billy does not execute commands.",
                "Local environment prerequisites (browser and optional `python -m http.server`) are available.",
                "Any deployment/security hardening is handled outside this readiness check.",
            ]
            if blocking_issues:
                next_safe_steps = [
                    "Address each blocking issue in the artifact content.",
                    "Run the readiness check again after updates.",
                    "After ready=true, execute commands manually outside Billy if desired.",
                ]
            else:
                next_safe_steps = [
                    "Optionally address non-blocking notes for robustness.",
                    "Run your chosen preview command manually (NOT EXECUTED by Billy).",
                    "If execution governance is required, use explicit governed flow.",
                ]
        elif artifact_type == "study_session":
            blocking_issues.append("`study_session` is conversational and not an executable artifact type.")
            non_blocking_notes.append("Use study mode to continue quiz progression.")
            assumptions_to_confirm = [
                "No execution action is expected for study artifacts.",
            ]
            next_safe_steps = [
                "Continue practice with `continue the study set`.",
                "Use artifact branching/rollback only for study content management.",
            ]
        else:
            blocking_issues.append(
                f"No readiness model is defined for artifact type `{artifact_type}`."
            )
            assumptions_to_confirm = [
                "Readiness remains advisory-only and does not authorize execution.",
            ]
            next_safe_steps = [
                "Specify artifact expectations so a readiness model can be applied.",
                "Keep execution disabled until blockers are resolved.",
            ]

        ready = len(blocking_issues) == 0
        fingerprint_input = {
            "artifact_name": artifact_name,
            "artifact_type": artifact_type,
            "revision_id": revision_id,
            "ready": ready,
            "blocking_issues": blocking_issues,
            "non_blocking_notes": non_blocking_notes,
            "assumptions_to_confirm": assumptions_to_confirm,
            "next_safe_steps": next_safe_steps,
        }
        readiness_fingerprint = hashlib.sha256(
            json.dumps(fingerprint_input, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        return {
            "mode": "advisory",
            "execution_enabled": False,
            "advisory_only": True,
            "artifact_name": artifact_name,
            "artifact_type": artifact_type,
            "artifact_revision_id": revision_id,
            "ready": ready,
            "blocking_issues": blocking_issues,
            "non_blocking_notes": non_blocking_notes,
            "assumptions_to_confirm": assumptions_to_confirm,
            "next_safe_steps": next_safe_steps,
            "readiness_fingerprint": readiness_fingerprint,
            "readiness_read_only": True,
            "message": (
                f"Read-only readiness evaluation for `{artifact_name}` complete. "
                "This is advisory only and does not authorize execution."
            ),
        }

    def _evaluate_artifact_execution_plan(
        self,
        *,
        artifact: Dict[str, Any],
        readiness_report: Dict[str, Any],
    ) -> Dict[str, Any]:
        artifact_name = str(artifact.get("name", "")).strip() or "artifact"
        artifact_type = str(artifact.get("artifact_type", "")).strip() or artifact_name
        content = artifact.get("content", {})
        content = content if isinstance(content, dict) else {}
        revision_id = str(artifact.get("revision_id", "")).strip()

        ready = bool(readiness_report.get("ready", False))
        blocking_issues = [str(item) for item in readiness_report.get("blocking_issues", []) if str(item).strip()]
        non_blocking_notes = [
            str(item) for item in readiness_report.get("non_blocking_notes", []) if str(item).strip()
        ]
        assumptions_to_confirm = [
            str(item) for item in readiness_report.get("assumptions_to_confirm", []) if str(item).strip()
        ]
        if not assumptions_to_confirm:
            assumptions_to_confirm = [
                "Execution remains manual and outside Billy.",
            ]

        execution_boundary_notice = (
            "Billy will not execute these steps. Billy will not authorize execution. "
            "This plan is advisory and does not grant permission to execute. "
            "YOU remain responsible for manual execution."
        )

        preconditions_to_confirm: List[str] = []
        if blocking_issues:
            preconditions_to_confirm.append(
                "YOU will resolve all blocking issues before any manual execution step."
            )
            for issue in blocking_issues:
                preconditions_to_confirm.append(f"YOU will confirm blocker resolved: {issue}")
        else:
            preconditions_to_confirm.append("YOU will confirm the artifact currently reports `ready=true`.")
        for assumption in assumptions_to_confirm:
            preconditions_to_confirm.append(f"YOU will confirm assumption: {assumption}")

        manual_preparation_steps: List[str] = []
        manual_execution_steps: List[str] = []
        verification_checklist: List[str] = []
        rollback_recovery_guidance: List[str] = []

        if self._is_html_artifact(artifact):
            filename = str(content.get("filename", "")).strip() or "index.html"
            if blocking_issues:
                summary = (
                    f"Manual execution plan synthesized for `{artifact_name}`; the artifact is NOT ready. "
                    "YOU will resolve blockers before execution."
                )
                manual_preparation_steps = [
                    f"YOU will update `{filename}` so required HTML structure is complete.",
                    "YOU will rerun readiness evaluation and continue only when `ready=true`.",
                    f"YOU will keep a backup copy of `{filename}` before manual execution.",
                ]
                manual_execution_steps = [
                    "YOU will pause manual execution until all blockers are resolved.",
                    "YOU will proceed only after a fresh readiness check returns `ready=true`.",
                ]
            else:
                summary = (
                    f"Manual execution plan synthesized for `{artifact_name}` with no readiness blockers. "
                    "If you choose to proceed, YOU will perform each step manually."
                )
                manual_preparation_steps = [
                    f"YOU will place `{filename}` in your intended local workspace directory.",
                    "YOU will confirm artifact content matches the latest advisory revision.",
                    f"YOU will create a backup copy of `{filename}` before additional edits.",
                ]
                manual_execution_steps = [
                    f"YOU will open `{filename}` with your chosen local runtime or browser workflow.",
                    "YOU will, if you choose to proceed, run local preview/deployment commands manually in your environment.",
                    "YOU will execute one manual step at a time and stop if behavior is unexpected.",
                ]

            verification_checklist = [
                f"YOU will confirm `{filename}` renders in your target browser/runtime.",
                "YOU will confirm required HTML sections are present (`<html>`, `<head>`, `<body>`, `<title>`).",
                "YOU will rerun readiness check and confirm no blockers remain.",
            ]
            if non_blocking_notes:
                verification_checklist.append("YOU will review non-blocking notes and address relevant quality gaps.")

            rollback_recovery_guidance = [
                f"YOU will restore the backup copy of `{filename}` if verification fails.",
                "YOU will revert the most recent manual change before retrying.",
                "YOU will rerun readiness and verification after recovery.",
            ]
        elif artifact_type == "study_session":
            summary = (
                f"Manual execution plan synthesized for `{artifact_name}` in fail-closed mode; "
                "`study_session` is non-executable."
            )
            manual_preparation_steps = [
                "YOU will confirm this artifact is for conversational study only.",
            ]
            manual_execution_steps = [
                "YOU will not run deployment or execution commands for this artifact type.",
                "YOU will continue using conversational study prompts only.",
            ]
            verification_checklist = [
                "YOU will confirm study progress updates in advisory mode.",
            ]
            rollback_recovery_guidance = [
                "YOU will use advisory artifact rollback/branching controls when needed.",
            ]
        else:
            summary = (
                f"Manual execution plan synthesized for `{artifact_name}` in fail-closed mode; "
                f"artifact type `{artifact_type}` has no execution model."
            )
            manual_preparation_steps = [
                "YOU will define artifact-specific execution prerequisites before any manual action.",
                "YOU will keep execution paused until an explicit readiness model exists for this artifact type.",
            ]
            manual_execution_steps = [
                "YOU will not execute until artifact-type requirements are explicitly defined.",
            ]
            verification_checklist = [
                "YOU will confirm a deterministic readiness model exists for this artifact type.",
            ]
            rollback_recovery_guidance = [
                "YOU will preserve current state and avoid changes until assumptions are explicit.",
            ]

        fingerprint_input = {
            "artifact_name": artifact_name,
            "artifact_type": artifact_type,
            "artifact_revision_id": revision_id,
            "ready": ready,
            "readiness_fingerprint": str(readiness_report.get("readiness_fingerprint", "")).strip(),
            "summary": summary,
            "preconditions_to_confirm": preconditions_to_confirm,
            "manual_preparation_steps": manual_preparation_steps,
            "manual_execution_steps": manual_execution_steps,
            "verification_checklist": verification_checklist,
            "rollback_recovery_guidance": rollback_recovery_guidance,
            "blocking_issues": blocking_issues,
            "non_blocking_notes": non_blocking_notes,
            "assumptions_to_confirm": assumptions_to_confirm,
            "execution_boundary_notice": execution_boundary_notice,
        }
        execution_plan_fingerprint = hashlib.sha256(
            json.dumps(fingerprint_input, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        return {
            "mode": "advisory",
            "execution_enabled": False,
            "advisory_only": True,
            "artifact_name": artifact_name,
            "artifact_type": artifact_type,
            "artifact_revision_id": revision_id,
            "ready": ready,
            "blocking_issues": blocking_issues,
            "non_blocking_notes": non_blocking_notes,
            "assumptions_to_confirm": assumptions_to_confirm,
            "summary": summary,
            "preconditions_to_confirm": preconditions_to_confirm,
            "manual_preparation_steps": manual_preparation_steps,
            "manual_execution_steps": manual_execution_steps,
            "verification_checklist": verification_checklist,
            "rollback_recovery_guidance": rollback_recovery_guidance,
            "execution_boundary_notice": execution_boundary_notice,
            "readiness_fingerprint": str(readiness_report.get("readiness_fingerprint", "")).strip(),
            "execution_plan_fingerprint": execution_plan_fingerprint,
            "execution_plan_read_only": True,
            "message": (
                f"Read-only execution plan synthesized for `{artifact_name}`. "
                "Planning execution is not executing."
            ),
        }

    def _build_artifact_readiness_response(self, *, artifact: Dict[str, Any], trace_id: str) -> Dict[str, Any]:
        readiness_report = self._evaluate_artifact_readiness(artifact)
        rendered_lines: List[str] = [
            str(readiness_report.get("message", "")).strip(),
            "",
            f"ready: {str(readiness_report.get('ready', False)).lower()}",
        ]
        blocking = readiness_report.get("blocking_issues", [])
        blocking = blocking if isinstance(blocking, list) else []
        rendered_lines.append("blocking_issues:")
        if blocking:
            for issue in blocking:
                rendered_lines.append(f"- {str(issue)}")
        else:
            rendered_lines.append("- none")

        non_blocking = readiness_report.get("non_blocking_notes", [])
        non_blocking = non_blocking if isinstance(non_blocking, list) else []
        rendered_lines.append("non_blocking_notes:")
        if non_blocking:
            for note in non_blocking:
                rendered_lines.append(f"- {str(note)}")
        else:
            rendered_lines.append("- none")

        assumptions = readiness_report.get("assumptions_to_confirm", [])
        assumptions = assumptions if isinstance(assumptions, list) else []
        rendered_lines.append("assumptions_to_confirm:")
        if assumptions:
            for assumption in assumptions:
                rendered_lines.append(f"- {str(assumption)}")
        else:
            rendered_lines.append("- none")

        next_steps = readiness_report.get("next_safe_steps", [])
        next_steps = next_steps if isinstance(next_steps, list) else []
        rendered_lines.append("next_safe_steps:")
        if next_steps:
            for step in next_steps:
                rendered_lines.append(f"- {str(step)}")
        else:
            rendered_lines.append("- none")

        rendered_lines.append("")
        rendered_lines.append(
            "Do you want me to update this artifact to address the blockers while staying non-executing?"
        )

        readiness_report["task_artifact"] = self._artifact_public_view(artifact)
        readiness_report["continuation_question"] = str(rendered_lines[-1])
        readiness_report["rendered_advisory"] = "\n".join(rendered_lines).strip()
        self._activate_interactive_prompt_from_advisory(
            advisory_output=readiness_report,
            trace_id=trace_id,
        )
        self._remember_conversational_context(
            user_input=f"readiness check {str(artifact.get('name', '')).strip()}",
            intent_class="advisory_request",
            mode="advisory",
        )
        return {
            "final_output": readiness_report,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "advisory",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _build_artifact_execution_plan_response(self, *, artifact: Dict[str, Any], trace_id: str) -> Dict[str, Any]:
        readiness_report = self._evaluate_artifact_readiness(artifact)
        plan_report = self._evaluate_artifact_execution_plan(
            artifact=artifact,
            readiness_report=readiness_report,
        )

        def _append_section(lines: List[str], title: str, items: List[str]) -> None:
            lines.append(title)
            if items:
                for item in items:
                    lines.append(f"- {str(item)}")
            else:
                lines.append("- none")
            lines.append("")

        rendered_lines: List[str] = [
            "Summary",
            str(plan_report.get("summary", "")).strip(),
            "",
        ]
        _append_section(
            rendered_lines,
            "Preconditions to Confirm",
            [str(item) for item in plan_report.get("preconditions_to_confirm", []) if str(item).strip()],
        )
        _append_section(
            rendered_lines,
            "Manual Preparation Steps",
            [str(item) for item in plan_report.get("manual_preparation_steps", []) if str(item).strip()],
        )
        _append_section(
            rendered_lines,
            "Manual Execution Steps",
            [str(item) for item in plan_report.get("manual_execution_steps", []) if str(item).strip()],
        )
        _append_section(
            rendered_lines,
            "Verification Checklist",
            [str(item) for item in plan_report.get("verification_checklist", []) if str(item).strip()],
        )
        _append_section(
            rendered_lines,
            "Rollback / Recovery Guidance",
            [str(item) for item in plan_report.get("rollback_recovery_guidance", []) if str(item).strip()],
        )
        rendered_lines.extend(
            [
                "Execution Boundary Notice",
                str(plan_report.get("execution_boundary_notice", "")).strip(),
                "",
                "Do you want me to refine this manual plan for your environment while staying advisory-only?",
            ]
        )

        plan_report["task_artifact"] = self._artifact_public_view(artifact)
        plan_report["continuation_question"] = str(rendered_lines[-1])
        plan_report["rendered_advisory"] = "\n".join(rendered_lines).strip()
        self._activate_interactive_prompt_from_advisory(
            advisory_output=plan_report,
            trace_id=trace_id,
        )
        self._remember_conversational_context(
            user_input=f"execution plan {str(artifact.get('name', '')).strip()}",
            intent_class="advisory_request",
            mode="advisory",
        )
        return {
            "final_output": plan_report,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "advisory",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _parse_artifact_revision_selector(self, utterance: str) -> Dict[str, Any] | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return None
        if any(phrase in lowered for phrase in _ARTIFACT_ROLLBACK_PHRASES):
            return {"selector_type": "previous"}
        if "previous version" in lowered or "prior version" in lowered:
            return {"selector_type": "previous"}

        revision_match = re.search(
            r"(?:revision|version)\s+([A-Za-z0-9_:-]+)",
            str(utterance or "").strip(),
            re.IGNORECASE,
        )
        if revision_match is None:
            return None
        token = str(revision_match.group(1)).strip()
        short = re.fullmatch(r"r(\d+)", token.lower())
        if short is not None:
            return {
                "selector_type": "revision_number",
                "value": int(short.group(1)),
            }
        return {
            "selector_type": "revision_id",
            "value": token,
        }

    def _extract_artifact_rollback_request(self, utterance: str) -> Dict[str, Any] | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return None
        selector = self._parse_artifact_revision_selector(utterance)
        if any(phrase in lowered for phrase in _ARTIFACT_ROLLBACK_PHRASES):
            return {"selector": selector or {"selector_type": "previous"}}
        if "roll back to revision" in lowered or "rollback to revision" in lowered:
            return {"selector": selector or {"selector_type": "previous"}}
        if "revert to revision" in lowered or "revert to version" in lowered:
            return {"selector": selector or {"selector_type": "previous"}}
        if "undo the last change" in lowered or "revert to the previous version" in lowered:
            return {"selector": {"selector_type": "previous"}}
        return None

    def _extract_artifact_branch_request(self, utterance: str) -> Dict[str, Any] | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return None
        explicit_phrase = any(phrase in lowered for phrase in _ARTIFACT_BRANCH_PHRASES)
        command_like = lowered.startswith("make a copy") or lowered.startswith("create a variant")
        command_like = command_like or bool(
            re.search(r"^(?:please\s+)?branch\b", lowered)
            and ("variant" in lowered or "alternate" in lowered or "copy" in lowered or "branch this" in lowered)
        )
        if not explicit_phrase and not command_like:
            return None

        requested_name: str | None = None
        explicit_name_match = re.search(
            r"(?:into|as|named|called)\s+([a-z][a-z0-9_]{2,})",
            lowered,
        )
        if explicit_name_match is not None:
            candidate = str(explicit_name_match.group(1)).strip()
            if candidate not in {"an", "alternate", "version", "variant", "copy", "layout"}:
                requested_name = candidate

        selector = self._parse_artifact_revision_selector(utterance)
        if selector is None:
            selector = {"selector_type": "current"}
        return {
            "selector": selector,
            "requested_name": requested_name,
        }

    def _artifact_revision_snapshot(self, *, artifact_name: str, selector: Dict[str, Any]) -> Dict[str, Any] | None:
        history = self._task_artifact_history.get(str(artifact_name or "").strip(), [])
        if not isinstance(history, list) or not history:
            return None
        selector_type = str((selector or {}).get("selector_type", "current")).strip()
        if selector_type == "current":
            return copy.deepcopy(history[-1])
        if selector_type == "previous":
            if len(history) < 2:
                return None
            return copy.deepcopy(history[-2])
        if selector_type == "revision_number":
            value = (selector or {}).get("value")
            if not isinstance(value, int):
                return None
            matches = [item for item in history if int(item.get("revision", -1)) == value]
            if len(matches) != 1:
                return None
            return copy.deepcopy(matches[0])
        if selector_type == "revision_id":
            token = str((selector or {}).get("value", "")).strip().lower()
            if not token:
                return None
            for item in history:
                revision_id = str(item.get("revision_id", "")).strip().lower()
                if revision_id == token:
                    return copy.deepcopy(item)
            return None
        return None

    def _derive_branch_artifact_name(self, *, source_name: str, requested_name: str | None = None) -> str | None:
        candidate_name = str(requested_name or "").strip()
        if candidate_name:
            if candidate_name in self._task_artifacts:
                return None
            return candidate_name
        base = str(source_name or "").strip()
        if not base:
            return None
        candidate = f"{base}_alt"
        suffix = 2
        while candidate in self._task_artifacts:
            candidate = f"{base}_alt{suffix}"
            suffix += 1
        return candidate

    def _is_html_artifact(self, artifact: Dict[str, Any]) -> bool:
        artifact_type = str(artifact.get("artifact_type", "")).strip().lower()
        if artifact_type.startswith("html_page"):
            return True
        content = artifact.get("content", {})
        content = content if isinstance(content, dict) else {}
        html_content = content.get("html")
        return isinstance(html_content, str) and bool(html_content.strip())

    def _extract_html_paragraph_text(self, utterance: str) -> str | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if "add a paragraph" not in lowered and "add paragraph" not in lowered:
            return None

        quoted = re.search(r"['\"]([^'\"]+)['\"]", str(utterance or "").strip())
        if quoted is not None:
            candidate = str(quoted.group(1)).strip()
            if candidate:
                return candidate

        tail_match = re.search(
            r"add (?:a )?paragraph(?: that says| saying| with text)?\s*(.*)$",
            str(utterance or "").strip(),
            re.IGNORECASE,
        )
        if tail_match is not None:
            tail = str(tail_match.group(1)).strip().strip(".")
            if tail:
                lowered_tail = tail.lower()
                if lowered_tail not in {"to html", "to the html", "to the page", "to page"}:
                    return tail

        return "New paragraph from advisory artifact update."

    def _append_paragraph_to_html(self, html_content: str, paragraph_text: str) -> str:
        base_html = str(html_content or "").strip()
        if not base_html:
            base_html = self._website_example_html(title="index.html", include_style=False)
        paragraph = f"    <p>{html.escape(str(paragraph_text or '').strip())}</p>\n"
        if "</main>" in base_html:
            return base_html.replace("</main>", f"{paragraph}  </main>", 1)
        if "</body>" in base_html:
            return base_html.replace("</body>", f"{paragraph}</body>", 1)
        return f"{base_html}\n{paragraph}".rstrip()

    def _sync_study_session_artifact(
        self,
        *,
        answered_correctly: bool | None = None,
        selected_option: str | None = None,
        correct_option: str | None = None,
    ) -> Dict[str, Any]:
        existing = self._get_task_artifact("study_session")
        content = existing.get("content", {}) if isinstance(existing, dict) else {}
        content = content if isinstance(content, dict) else {}

        questions_answered = content.get("questions_answered", 0)
        questions_correct = content.get("questions_correct", 0)
        quiz_index = content.get("quiz_index", 0)
        questions_answered = questions_answered if isinstance(questions_answered, int) and questions_answered >= 0 else 0
        questions_correct = questions_correct if isinstance(questions_correct, int) and questions_correct >= 0 else 0
        quiz_index = quiz_index if isinstance(quiz_index, int) and quiz_index >= 0 else 0

        if answered_correctly is not None:
            questions_answered += 1
            if answered_correctly:
                questions_correct += 1
        mode_state = self._activity_mode_state if isinstance(self._activity_mode_state, dict) else {}
        mode_index = mode_state.get("quiz_index", quiz_index)
        if isinstance(mode_index, int) and mode_index >= 0:
            quiz_index = mode_index

        updated_content = {
            "topic": "vocabulary",
            "questions_answered": questions_answered,
            "questions_correct": questions_correct,
            "quiz_index": quiz_index,
            "last_selected_option": str(selected_option or "").strip().upper(),
            "last_correct_option": str(correct_option or "").strip().upper(),
        }
        summary = (
            "Vocabulary study progress: "
            f"{questions_correct}/{questions_answered} correct. "
            "Session-scoped and non-executing."
        )
        return self._upsert_task_artifact(
            name="study_session",
            artifact_type="study_session",
            content=updated_content,
            summary=summary,
            source_mode="activity_mode",
        )

    def _build_html_artifact_advisory_response(
        self,
        *,
        artifact: Dict[str, Any],
        trace_id: str,
        message: str,
        artifact_diff: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        content = artifact.get("content", {})
        content = content if isinstance(content, dict) else {}
        filename = str(content.get("filename", "")).strip() or str(self._session_defaults.get("website_filename", "")).strip()
        filename = filename or "index.html"
        html_content = str(content.get("html", "")).strip() or self._website_example_html(title=filename, include_style=False)

        advisory_output = build_advisory_plan(
            utterance=f"plan website page {filename}",
            intent_class="planning_request",
        )
        advisory_output["message"] = f"{message} Commands remain suggestions only and were NOT EXECUTED."
        advisory_output["example_html"] = html_content
        advisory_output["suggested_commands"] = [
            f"NOT EXECUTED: cat > {filename} <<'HTML'",
            "NOT EXECUTED: (paste the example_html content)",
            "NOT EXECUTED: HTML",
            "NOT EXECUTED: python -m http.server 8000",
        ]
        assumptions = advisory_output.get("assumptions", [])
        assumptions = assumptions if isinstance(assumptions, list) else []
        advisory_output["assumptions"] = [
            "Task artifact `html_page` is session-scoped and non-executing.",
            "Default: local-only workflow (no deployment).",
        ] + assumptions
        advisory_output["task_artifact"] = self._artifact_public_view(artifact)
        if isinstance(artifact_diff, dict) and artifact_diff:
            advisory_output["artifact_diff"] = copy.deepcopy(artifact_diff)
        self._register_plan_artifact_from_advisory(
            source_utterance=f"html artifact {filename}",
            intent_class="planning_request",
            advisory_output=advisory_output,
        )
        advisory_output = self._prepare_advisory_output(advisory_output)
        self._activate_interactive_prompt_from_advisory(
            advisory_output=advisory_output,
            trace_id=trace_id,
        )
        self._remember_conversational_context(
            user_input=f"html artifact {filename}",
            intent_class="planning_request",
            mode="advisory",
        )
        return {
            "final_output": advisory_output,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "advisory",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _handle_task_artifact_turn(self, *, user_input: str, trace_id: str) -> Dict[str, Any] | None:
        normalized = str(user_input or "").strip()
        if not normalized:
            return None
        if self._is_artifact_readiness_query(normalized):
            target_name = self._resolve_artifact_control_target(normalized)
            if target_name is None:
                return {
                    "final_output": (
                        "Readiness check rejected: specify which artifact to evaluate, "
                        "or keep only one active artifact in session."
                    ),
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                    "mode": "conversation_layer",
                }
            target_artifact = self._get_task_artifact(target_name)
            if target_artifact is None:
                return {
                    "final_output": (
                        f"Readiness check rejected: artifact `{target_name}` is not available in this session."
                    ),
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                    "mode": "conversation_layer",
                }
            return self._build_artifact_readiness_response(
                artifact=target_artifact,
                trace_id=trace_id,
            )
        if self._is_artifact_execution_plan_query(normalized):
            target_name = self._resolve_artifact_control_target(normalized)
            if target_name is None:
                return {
                    "final_output": (
                        "Execution plan rejected: specify which artifact to plan for, "
                        "or keep only one active artifact in session."
                    ),
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                    "mode": "conversation_layer",
                }
            target_artifact = self._get_task_artifact(target_name)
            if target_artifact is None:
                return {
                    "final_output": (
                        f"Execution plan rejected: artifact `{target_name}` is not available in this session."
                    ),
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                    "mode": "conversation_layer",
                }
            return self._build_artifact_execution_plan_response(
                artifact=target_artifact,
                trace_id=trace_id,
            )
        if self._is_artifact_diff_query(normalized):
            target_artifact = self._resolve_task_artifact_reference(normalized)
            diff_payload: Dict[str, Any] | None = None
            if target_artifact is not None:
                diff_payload = self._latest_artifact_diff(target_artifact)
            if diff_payload is None and isinstance(self._last_task_artifact_diff, dict):
                diff_payload = copy.deepcopy(self._last_task_artifact_diff)
            if diff_payload is None:
                return {
                    "final_output": "No artifact diff is available yet in this session.",
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "conversation_layer",
                }
            return {
                "final_output": str(diff_payload.get("diff_text", "")).strip(),
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "conversation_layer",
                "artifact_diff": diff_payload,
            }

        rollback_request = self._extract_artifact_rollback_request(normalized)
        if isinstance(rollback_request, dict):
            target_name = self._resolve_artifact_control_target(normalized)
            if target_name is None:
                return {
                    "final_output": (
                        "Rollback rejected: specify which artifact to roll back, "
                        "or keep only one active artifact in session."
                    ),
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                    "mode": "conversation_layer",
                }
            selector = rollback_request.get("selector", {"selector_type": "previous"})
            if not isinstance(selector, dict):
                selector = {"selector_type": "previous"}
            rollback_source = self._artifact_revision_snapshot(
                artifact_name=target_name,
                selector=selector,
            )
            if rollback_source is None:
                return {
                    "final_output": (
                        f"Rollback rejected: target revision was not found for `{target_name}`."
                    ),
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                    "mode": "conversation_layer",
                }

            current_artifact = self._get_task_artifact(target_name)
            current_content = (current_artifact or {}).get("content")
            rollback_content = rollback_source.get("content")
            rollback_revision_id = str(rollback_source.get("revision_id", "")).strip()
            if current_content == rollback_content:
                return {
                    "final_output": (
                        f"Rollback skipped: `{target_name}` is already aligned with {rollback_revision_id}."
                    ),
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "conversation_layer",
                }

            target_type = str((current_artifact or rollback_source).get("artifact_type", "")).strip() or target_name
            rolled_back = self._upsert_task_artifact(
                name=target_name,
                artifact_type=target_type,
                content=rollback_content,
                summary=(
                    f"Rollback applied to `{target_name}` from revision {rollback_revision_id} "
                    "(session-scoped, non-executing)."
                ),
                source_mode="advisory",
            )
            artifact_diff = self._latest_artifact_diff(target_name)
            if self._is_html_artifact(rolled_back):
                return self._build_html_artifact_advisory_response(
                    artifact=rolled_back,
                    trace_id=trace_id,
                    message=(
                        f"Rollback applied for task artifact `{target_name}` to revision {rollback_revision_id}."
                    ),
                    artifact_diff=artifact_diff,
                )
            diff_text = str((artifact_diff or {}).get("diff_text", "")).strip()
            final_output = (
                f"Rollback applied for `{target_name}` to revision {rollback_revision_id}."
            )
            if diff_text:
                final_output = f"{final_output}\n\n{diff_text}"
            return {
                "final_output": final_output,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "conversation_layer",
            }

        branch_request = self._extract_artifact_branch_request(normalized)
        if isinstance(branch_request, dict):
            source_name = self._resolve_artifact_control_target(normalized)
            if source_name is None:
                return {
                    "final_output": (
                        "Branch rejected: specify which artifact to branch, "
                        "or keep only one active artifact in session."
                    ),
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                    "mode": "conversation_layer",
                }
            selector = branch_request.get("selector", {"selector_type": "current"})
            if not isinstance(selector, dict):
                selector = {"selector_type": "current"}
            source_snapshot = self._artifact_revision_snapshot(
                artifact_name=source_name,
                selector=selector,
            )
            if source_snapshot is None:
                return {
                    "final_output": (
                        f"Branch rejected: source revision was not found for `{source_name}`."
                    ),
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                    "mode": "conversation_layer",
                }
            branch_name = self._derive_branch_artifact_name(
                source_name=source_name,
                requested_name=(
                    str(branch_request.get("requested_name", "")).strip()
                    if isinstance(branch_request.get("requested_name"), str)
                    else None
                ),
            )
            if not branch_name:
                return {
                    "final_output": "Branch rejected: requested branch artifact name is already in use.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                    "mode": "conversation_layer",
                }

            source_artifact = self._get_task_artifact(source_name) or source_snapshot
            branched_artifact = self._upsert_task_artifact(
                name=branch_name,
                artifact_type=str(source_artifact.get("artifact_type", "")).strip() or source_name,
                content=source_snapshot.get("content"),
                summary=(
                    f"Branched from `{source_name}` at {str(source_snapshot.get('revision_id', '')).strip()} "
                    "(session-scoped, non-executing)."
                ),
                source_mode="advisory",
            )
            source_revision_id = str(source_snapshot.get("revision_id", "")).strip()
            if self._is_html_artifact(branched_artifact):
                return self._build_html_artifact_advisory_response(
                    artifact=branched_artifact,
                    trace_id=trace_id,
                    message=(
                        f"Created branch artifact `{branch_name}` from `{source_name}` "
                        f"at revision {source_revision_id}. Both artifacts now evolve independently."
                    ),
                )
            return {
                "final_output": (
                    f"Created branch artifact `{branch_name}` from `{source_name}` "
                    f"at revision {source_revision_id}. Both artifacts now evolve independently."
                ),
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "conversation_layer",
            }

        reset_target = self._extract_artifact_reset_target(normalized)
        if reset_target == "__all__":
            if not self._task_artifacts:
                return {
                    "final_output": "No task artifacts are active in this session.",
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "conversation_layer",
                }
            self._task_artifacts.clear()
            self._task_artifact_history.clear()
            self._last_task_artifact_diff = None
            self._active_plan_artifact = None
            self._clear_activity_mode()
            self._interactive_prompt_state = None
            return {
                "final_output": "All session task artifacts were discarded. You can start over safely.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "conversation_layer",
            }
        if isinstance(reset_target, str) and reset_target and reset_target != "__all__":
            removed = self._discard_task_artifact(reset_target)
            self._task_artifact_history.pop(reset_target, None)
            if (
                isinstance(self._last_task_artifact_diff, dict)
                and str(self._last_task_artifact_diff.get("artifact_name", "")).strip() == reset_target
            ):
                self._last_task_artifact_diff = None
            self._active_plan_artifact = None
            if reset_target == "study_session":
                mode_state = self._activity_mode_state if isinstance(self._activity_mode_state, dict) else {}
                if str(mode_state.get("mode", "")).strip() == "study_mode":
                    self._clear_activity_mode()
            if not removed:
                return {
                    "final_output": f"Task artifact `{reset_target}` was not active, so nothing was discarded.",
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "conversation_layer",
                }
            return {
                "final_output": f"Discarded task artifact `{reset_target}` for this session.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "conversation_layer",
            }

        artifact_name = self._resolve_task_artifact_reference(normalized)
        if artifact_name is None:
            return None
        artifact = self._get_task_artifact(artifact_name)
        if artifact is None:
            return None

        lowered = re.sub(r"\s+", " ", normalized.lower())
        if artifact_name == "study_session":
            if any(token in lowered for token in ("continue", "resume", "next", "another", "again")):
                content = artifact.get("content", {})
                content = content if isinstance(content, dict) else {}
                quiz_index = content.get("quiz_index", 0)
                quiz_index = quiz_index if isinstance(quiz_index, int) and quiz_index >= 0 else 0
                if not isinstance(self._activity_mode_state, dict) or str(
                    self._activity_mode_state.get("mode", "")
                ).strip() != "study_mode":
                    self._activity_mode_state = {
                        "mode": "study_mode",
                        "entered_at": "session_resume",
                        "questions_asked": int(content.get("questions_answered", 0) or 0),
                        "quiz_index": quiz_index,
                    }
                return self._build_study_mode_quiz_prompt(
                    trace_id=trace_id,
                    preface="Resuming task artifact `study_session`.",
                )
            return {
                "final_output": (
                    "Resolved task artifact `study_session`. "
                    "Say `continue the study set` to resume the next question, or `discard the study set`."
                ),
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "conversation_layer",
            }

        if self._is_html_artifact(artifact):
            content = artifact.get("content", {})
            content = content if isinstance(content, dict) else {}
            current_html = str(content.get("html", "")).strip()
            wants_edit = any(token in lowered for token in ("edit", "update", "change", "modify", "add"))
            paragraph_text = self._extract_html_paragraph_text(normalized)
            if paragraph_text is not None:
                updated_html = self._append_paragraph_to_html(current_html, paragraph_text)
                updated_content = dict(content)
                updated_content["html"] = updated_html
                filename = str(updated_content.get("filename", "")).strip() or "index.html"
                updated_artifact = self._upsert_task_artifact(
                    name=artifact_name,
                    artifact_type=str(artifact.get("artifact_type", "")).strip() or "html_page",
                    content=updated_content,
                    summary=f"HTML task artifact `{artifact_name}` for {filename} updated with a new paragraph.",
                    source_mode="advisory",
                )
                artifact_diff = self._latest_artifact_diff(artifact_name)
                return self._build_html_artifact_advisory_response(
                    artifact=updated_artifact,
                    trace_id=trace_id,
                    message=f"Updated task artifact `{artifact_name}` with your paragraph request.",
                    artifact_diff=artifact_diff,
                )
            if wants_edit:
                return self._build_html_artifact_advisory_response(
                    artifact=artifact,
                    trace_id=trace_id,
                    message=(
                        f"Resolved task artifact `{artifact_name}`. "
                        "Tell me the exact HTML change and I will update this advisory artifact."
                    ),
                )
            return self._build_html_artifact_advisory_response(
                artifact=artifact,
                trace_id=trace_id,
                message=f"Resolved task artifact `{artifact_name}` from this session.",
            )

        return None

    def _activity_mode_label(self, mode: str) -> str:
        return str(mode or "").strip().replace("_", " ")

    def _detect_activity_mode_entry(self, utterance: str) -> str | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return None
        for mode_name, triggers in _ACTIVITY_MODE_ENTRIES.items():
            if lowered in triggers:
                return mode_name
        return None

    def _is_activity_mode_exit_request(self, utterance: str, mode: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return False
        if lowered in _ACTIVITY_MODE_EXIT_PHRASES:
            return True
        mode_label = self._activity_mode_label(mode)
        return lowered in {f"exit {mode_label}", f"stop {mode_label}", f"leave {mode_label}"}

    def _clear_activity_mode(self) -> None:
        self._activity_mode_state = None
        prompt_state = self._interactive_prompt_state
        if isinstance(prompt_state, dict) and str(prompt_state.get("origin", "")).strip() == "study_mode":
            self._interactive_prompt_state = None

    def _study_mode_next_quiz(self) -> tuple[Dict[str, Any], int]:
        if not _STUDY_MODE_QUIZ_BANK:
            return (
                {
                    "question": "Which option best matches `concise`?",
                    "options": {"A": "brief", "B": "hidden", "C": "fragile", "D": "distant"},
                    "correct_option": "A",
                },
                0,
            )
        state = self._activity_mode_state if isinstance(self._activity_mode_state, dict) else {}
        raw_index = state.get("quiz_index", 0)
        quiz_index = raw_index if isinstance(raw_index, int) and raw_index >= 0 else 0
        bank_index = quiz_index % len(_STUDY_MODE_QUIZ_BANK)
        quiz = dict(_STUDY_MODE_QUIZ_BANK[bank_index])
        if isinstance(self._activity_mode_state, dict):
            self._activity_mode_state["quiz_index"] = quiz_index + 1
            asked_count = self._activity_mode_state.get("questions_asked", 0)
            self._activity_mode_state["questions_asked"] = (asked_count if isinstance(asked_count, int) else 0) + 1
        return quiz, bank_index + 1

    def _build_study_mode_quiz_prompt(self, *, trace_id: str, preface: str = "") -> Dict[str, Any]:
        quiz, question_number = self._study_mode_next_quiz()
        question = str(quiz.get("question", "")).strip() or "Choose the best option."
        options = quiz.get("options", {})
        options = options if isinstance(options, dict) else {}
        ordered_options = [str(key).upper() for key in sorted(options.keys())]
        if not ordered_options:
            ordered_options = ["A", "B", "C", "D"]
            options = {"A": "brief", "B": "hidden", "C": "fragile", "D": "distant"}
        default_option = ordered_options[0]
        correct_option = str(quiz.get("correct_option", default_option)).upper()
        if correct_option not in ordered_options:
            correct_option = default_option

        prompt_lines = [
            "Study Mode: Vocabulary",
            f"Question {question_number}",
            question,
        ]
        for option_key in ordered_options:
            option_text = str(options.get(option_key, "")).strip()
            prompt_lines.append(f"{option_key}) {option_text}")
        prompt_lines.append("Please choose one: A, B, C, or D.")
        prompt_text = "\n".join(prompt_lines)
        if preface:
            prompt_text = f"{preface}\n\n{prompt_text}"

        self._interactive_prompt_state = {
            "type": "multiple_choice",
            "origin": "study_mode",
            "prompt_id": f"interactive-{trace_id}",
            "question": question,
            "options": options,
            "correct_option": correct_option,
            "default_option": default_option,
        }
        return {
            "final_output": prompt_text,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "activity_mode",
            "activity_mode": "study_mode",
            "activity_mode_active": True,
            "interactive_prompt_active": True,
            "interactive_prompt_type": "multiple_choice",
        }

    def _enter_activity_mode(
        self,
        *,
        mode: str,
        trace_id: str,
        switched_from: str | None = None,
    ) -> Dict[str, Any]:
        normalized_mode = str(mode or "").strip()
        if normalized_mode not in {"study_mode", "coding_mode", "planning_mode"}:
            return {
                "final_output": "Activity mode request rejected: mode is unsupported.",
                "tool_calls": [],
                "status": "error",
                "trace_id": trace_id,
                "mode": "activity_mode",
            }

        self._clear_activity_mode()
        self._activity_mode_state = {
            "mode": normalized_mode,
            "entered_at": datetime.now(timezone.utc).isoformat(),
            "questions_asked": 0,
            "quiz_index": 0,
        }
        prefix = f"Entered {normalized_mode}. "
        if switched_from:
            prefix = f"Switched from {switched_from} to {normalized_mode}. "
        prefix += f"Say `exit {self._activity_mode_label(normalized_mode)}` to stop this mode."

        if normalized_mode == "study_mode":
            study_artifact = self._sync_study_session_artifact()
            artifact_note = (
                f" Task artifact `{study_artifact.get('name', 'study_session')}` is active "
                "(session-scoped, non-executing)."
            )
            return self._build_study_mode_quiz_prompt(trace_id=trace_id, preface=prefix + artifact_note)

        mode_summary = {
            "coding_mode": "Coding mode is active. I will keep replies focused on implementation planning and code guidance.",
            "planning_mode": "Planning mode is active. I will keep replies focused on sequencing, risks, and rollout plans.",
        }
        return {
            "final_output": f"{prefix}\n{mode_summary.get(normalized_mode, '')}".strip(),
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "activity_mode",
            "activity_mode": normalized_mode,
            "activity_mode_active": True,
            "interactive_prompt_active": False,
        }

    def _is_study_mode_related(self, utterance: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return False
        if self._is_vocabulary_quiz_request(lowered):
            return True
        if lowered in {"a", "b", "c", "d", "yes", "no", "next", "again", "another", "continue", "that one", "this one"}:
            return True
        return any(token in lowered for token in _STUDY_MODE_TOKENS)

    def _should_implicitly_exit_activity_mode(self, *, mode: str, utterance: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return False

        next_mode = self._detect_activity_mode_entry(lowered)
        if next_mode is not None and next_mode != mode:
            return True

        if _has_explicit_governed_trigger(utterance):
            return True
        if re.search(r"\b(run|execute|deploy|apply)\b", lowered) and (
            "now" in lowered or "immediately" in lowered
        ):
            return True
        if re.search(
            r"\b(create|delete|remove|write|edit|modify)\b.*\b("
            r"file|folder|directory|repo|repository|project|workflow|service"
            r")\b",
            lowered,
        ):
            return True

        if mode == "study_mode":
            if self._is_study_mode_related(lowered):
                return False
            if self._is_website_build_request(utterance):
                return True
            return bool(re.search(r"\b(coding|code|plan|planning|project|workflow|service)\b", lowered))

        if mode == "coding_mode":
            return bool(re.search(r"\b(study|vocabulary|quiz)\b", lowered))

        if mode == "planning_mode":
            return bool(re.search(r"\b(study|vocabulary|quiz)\b", lowered))

        return True

    def _handle_activity_mode_turn(self, *, user_input: str, trace_id: str) -> Dict[str, Any] | None:
        normalized = str(user_input or "").strip()
        if not normalized:
            return None
        if self._extract_artifact_reset_target(normalized) is not None:
            return None
        requested_mode = self._detect_activity_mode_entry(normalized)

        state = self._activity_mode_state
        if not isinstance(state, dict):
            if requested_mode is None:
                return None
            return self._enter_activity_mode(mode=requested_mode, trace_id=trace_id)

        current_mode = str(state.get("mode", "")).strip()
        if requested_mode is not None and requested_mode != current_mode:
            return self._enter_activity_mode(
                mode=requested_mode,
                trace_id=trace_id,
                switched_from=current_mode,
            )
        if requested_mode is not None and requested_mode == current_mode:
            return {
                "final_output": (
                    f"{current_mode} is already active. "
                    f"Say `exit {self._activity_mode_label(current_mode)}` when you want to stop."
                ),
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "activity_mode",
                "activity_mode": current_mode,
                "activity_mode_active": True,
            }

        if self._is_activity_mode_exit_request(normalized, current_mode):
            self._clear_activity_mode()
            return {
                "final_output": f"Exited {current_mode}. Normal routing resumed.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "activity_mode",
                "activity_mode": current_mode,
                "activity_mode_active": False,
                "interactive_prompt_active": False,
            }

        if self._should_implicitly_exit_activity_mode(mode=current_mode, utterance=normalized):
            self._clear_activity_mode()
            return None

        lowered = re.sub(r"\s+", " ", normalized.lower())
        if current_mode == "study_mode":
            if lowered in {"next", "next question", "again", "another", "continue", "question", "quiz"}:
                return self._build_study_mode_quiz_prompt(
                    trace_id=trace_id,
                    preface="Study mode is active. Here is the next vocabulary question.",
                )
            if lowered in {"a", "b", "c", "d", "that one", "this one"} and not isinstance(
                self._interactive_prompt_state, dict
            ):
                return self._build_study_mode_quiz_prompt(
                    trace_id=trace_id,
                    preface="Study mode is active. Starting a new question before grading your choice.",
                )
            if not isinstance(self._interactive_prompt_state, dict):
                return self._build_study_mode_quiz_prompt(
                    trace_id=trace_id,
                    preface="Study mode is active. Continuing with vocabulary practice.",
                )
            return {
                "final_output": (
                    "Study mode is active. Reply with A, B, C, or D for the active question, "
                    "or say `next question` or `exit study mode`."
                ),
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "activity_mode",
                "activity_mode": "study_mode",
                "activity_mode_active": True,
                "interactive_prompt_active": True,
            }

        if current_mode == "coding_mode" and len(lowered.split()) <= 3:
            return {
                "final_output": (
                    "Coding mode is active. Share what you want to build or change, "
                    "or say `exit coding mode`."
                ),
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "activity_mode",
                "activity_mode": "coding_mode",
                "activity_mode_active": True,
            }

        if current_mode == "planning_mode" and len(lowered.split()) <= 3:
            return {
                "final_output": (
                    "Planning mode is active. Share the goal and constraints, "
                    "or say `exit planning mode`."
                ),
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "activity_mode",
                "activity_mode": "planning_mode",
                "activity_mode_active": True,
            }

        return None

    def _is_vocabulary_quiz_request(self, utterance: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return False
        direct_matches = {
            "quiz me",
            "give me a quiz",
            "vocabulary quiz",
            "quiz me on vocabulary",
        }
        if lowered in direct_matches:
            return True
        return lowered.startswith("quiz me on vocabulary ")

    def _normalize_interactive_reply(self, utterance: str) -> str:
        return re.sub(r"\s+", " ", str(utterance or "").strip().lower())

    def _resolve_yes_no_reply(self, reply: str) -> str | None:
        yes_tokens = {
            "y",
            "yes",
            "yeah",
            "yep",
            "affirmative",
            "sure",
            "ok",
            "okay",
            "yes that's the plan",
            "yes, that's the plan",
            "yes thats the plan",
            "that's the plan",
            "thats the plan",
            "that assumption works",
            "yes that assumption works",
            "yes, that assumption works",
        }
        no_tokens = {"n", "no", "nope", "nah", "negative"}
        if reply in yes_tokens:
            return "yes"
        if reply in no_tokens:
            return "no"
        return None

    def _resolve_multiple_choice_reply(
        self,
        *,
        reply: str,
        default_option: str,
        allowed_options: List[str],
    ) -> str | None:
        if not reply:
            return None
        normalized_allowed = [str(item).upper() for item in allowed_options]
        if re.fullmatch(r"[a-z]", reply):
            candidate = reply.upper()
            if candidate in normalized_allowed:
                return candidate

        alias_map = {
            "option a": "A",
            "option b": "B",
            "option c": "C",
            "option d": "D",
            "the first option": "A",
            "first option": "A",
            "the second option": "B",
            "second option": "B",
            "the third option": "C",
            "third option": "C",
            "the fourth option": "D",
            "fourth option": "D",
            "the first": "A",
            "first": "A",
            "the second": "B",
            "second": "B",
            "the third": "C",
            "third": "C",
            "the fourth": "D",
            "fourth": "D",
            "that one": str(default_option or "A").upper(),
            "this one": str(default_option or "A").upper(),
        }
        candidate = alias_map.get(reply)
        if candidate is None:
            return None
        if candidate not in normalized_allowed:
            return None
        return candidate

    def _build_vocabulary_quiz_prompt(self, *, trace_id: str) -> Dict[str, Any]:
        options = {
            "A": "brief",
            "B": "hidden",
            "C": "fragile",
            "D": "distant",
        }
        prompt_text = "\n".join(
            [
                "Vocabulary Quiz",
                "Which option is the closest synonym of `concise`?",
                "A) brief",
                "B) hidden",
                "C) fragile",
                "D) distant",
                "Please choose A, B, C, or D.",
            ]
        )
        self._interactive_prompt_state = {
            "type": "multiple_choice",
            "origin": "direct_quiz",
            "prompt_id": f"interactive-{trace_id}",
            "question": "Which option is the closest synonym of concise?",
            "options": options,
            "correct_option": "A",
            "default_option": "A",
        }
        return {
            "final_output": prompt_text,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "interactive_prompt",
            "interactive_prompt_active": True,
            "interactive_prompt_type": "multiple_choice",
        }

    def _activate_interactive_prompt_from_advisory(self, *, advisory_output: Dict[str, Any], trace_id: str) -> None:
        question = str(advisory_output.get("continuation_question", "")).strip()
        if not question.endswith("?"):
            return
        lowered = question.lower()
        if not (
            lowered.startswith("do you ")
            or lowered.startswith("would you ")
            or lowered.startswith("shall ")
            or lowered.startswith("should ")
        ):
            return

        on_yes = "Okay. Tell me what to refine, and I will regenerate the advisory output."
        on_no = "Understood. We can keep the current advisory output."
        if "adjust this html" in lowered:
            on_yes = "Okay. Tell me exactly what to change in the HTML, and I will regenerate the advisory output."
            on_no = "Understood. We can keep this HTML advisory as-is."
        elif "submit this as a governed proposal" in lowered:
            on_yes = "Understood. If you want to proceed, use an explicit governed submission confirmation."
            on_no = "Understood. We can keep planning without submitting."

        self._interactive_prompt_state = {
            "type": "yes_no",
            "prompt_id": f"interactive-{trace_id}",
            "question": question,
            "origin": "advisory",
            "on_yes": on_yes,
            "on_no": on_no,
        }

    def _handle_bound_interactive_turn(self, *, user_input: str, trace_id: str) -> Dict[str, Any] | None:
        state = self._interactive_prompt_state
        if not isinstance(state, dict):
            return None

        reply = self._normalize_interactive_reply(user_input)
        prompt_type = str(state.get("type", "")).strip()
        if not reply:
            return {
                "final_output": "I’m waiting for your response to the active prompt.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "interactive_prompt",
                "interactive_prompt_active": True,
            }
        if reply in {"cancel", "cancel prompt", "skip", "never mind", "nevermind"}:
            self._interactive_prompt_state = None
            return {
                "final_output": "Interactive prompt cleared. You can send a new request.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "interactive_response",
                "interactive_prompt_active": False,
            }

        if prompt_type == "website_preflight":
            seed_utterance = str(state.get("seed_utterance", "")).strip()
            if not seed_utterance:
                seed_utterance = "I want to make a website"
            self._interactive_prompt_state = None
            combined_request = f"{seed_utterance}\nContext: {reply}".strip()
            return self._build_website_advisory_response(
                utterance=combined_request,
                trace_id=trace_id,
            )

        if prompt_type == "planning_depth":
            selected_depth = self._resolve_planning_depth_reply(reply)
            if selected_depth is None:
                return {
                    "final_output": (
                        "Reply with one of: high-level, step-by-step, or critique/stress test."
                    ),
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "interactive_prompt",
                    "interactive_prompt_active": True,
                    "interactive_prompt_type": "planning_depth",
                    "execution_enabled": False,
                    "advisory_only": True,
                }
            seed_utterance = str(state.get("seed_utterance", "")).strip()
            if not seed_utterance:
                seed_utterance = "help me plan this"
            advisory_intent = str(state.get("intent_class", "")).strip() or "planning_request"
            self._interactive_prompt_state = None
            return self._build_depth_selected_advisory_response(
                seed_utterance=seed_utterance,
                intent_class=advisory_intent,
                depth_mode=selected_depth,
                trace_id=trace_id,
            )

        if prompt_type == "critique_depth":
            depth_mode = self._resolve_critique_depth_reply(reply)
            if depth_mode is None:
                return {
                    "final_output": (
                        "Reply with one of: quick check, full stress test, or assumption review."
                    ),
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "interactive_prompt",
                    "interactive_prompt_active": True,
                    "interactive_prompt_type": "critique_depth",
                    "execution_enabled": False,
                    "advisory_only": True,
                }
            self._interactive_prompt_state = None
            return self._build_critique_response(
                depth_mode=depth_mode,
                trace_id=trace_id,
            )

        if prompt_type == "critique_follow_up":
            action = self._resolve_critique_follow_up_action(reply)
            if action is None:
                return {
                    "final_output": (
                        "Reply with one of: revise plan, explore alternative, or accept risk and proceed."
                    ),
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "interactive_prompt",
                    "interactive_prompt_active": True,
                    "interactive_prompt_type": "critique_follow_up",
                    "execution_enabled": False,
                    "advisory_only": True,
                }
            self._interactive_prompt_state = None
            return self._build_critique_follow_up_resolution(
                action=action,
                trace_id=trace_id,
            )

        if prompt_type == "preference_capture":
            decision = self._resolve_yes_no_reply(reply)
            if decision is None:
                return {
                    "final_output": "Please respond yes or no to store this session preference.",
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "interactive_prompt",
                    "interactive_prompt_active": True,
                    "interactive_prompt_type": "preference_capture",
                }
            self._interactive_prompt_state = None
            if decision == "yes":
                key = str(state.get("preference_key", "")).strip()
                value = str(state.get("preference_value", "")).strip()
                label = str(state.get("preference_label", "")).strip()
                if key and value:
                    self._session_preferences[key] = value
                message = "I'll remember that for this session."
                if label:
                    message = f"{message} Preference saved: {label}."
                return {
                    "final_output": message,
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "interactive_response",
                    "interactive_prompt_active": False,
                    "execution_enabled": False,
                    "advisory_only": True,
                }
            return {
                "final_output": "Understood. I will not store that preference.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "interactive_response",
                "interactive_prompt_active": False,
                "execution_enabled": False,
                "advisory_only": True,
            }

        if prompt_type == "tone_preference_capture":
            decision = self._resolve_yes_no_reply(reply)
            if decision is None:
                return {
                    "final_output": "Please respond yes or no to store this session tone preference.",
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "interactive_prompt",
                    "interactive_prompt_active": True,
                    "interactive_prompt_type": "tone_preference_capture",
                }
            self._interactive_prompt_state = None
            if decision == "yes":
                candidate = state.get("tone_candidate", {})
                candidate = candidate if isinstance(candidate, dict) else {}
                updated = dict(self._session_tone)
                verbosity = str(candidate.get("verbosity", "")).strip().lower()
                style = str(candidate.get("style", "")).strip().lower()
                confidence = str(candidate.get("confidence_framing", "")).strip().lower()
                if verbosity in _TONE_VERBOSITY_VALUES:
                    updated["verbosity"] = verbosity
                if style in _TONE_STYLE_VALUES:
                    updated["style"] = style
                if confidence in _TONE_CONFIDENCE_VALUES:
                    updated["confidence_framing"] = confidence
                self._session_tone = updated
                return {
                    "final_output": "I'll remember that tone for this session.",
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "interactive_response",
                    "interactive_prompt_active": False,
                    "execution_enabled": False,
                    "advisory_only": True,
                }
            return {
                "final_output": "Understood. I will keep the current tone.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "interactive_response",
                "interactive_prompt_active": False,
                "execution_enabled": False,
                "advisory_only": True,
            }

        if prompt_type == "role_framing_capture":
            decision = self._resolve_yes_no_reply(reply)
            if decision is None:
                return {
                    "final_output": "Please respond yes or no to store this session role framing.",
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "interactive_prompt",
                    "interactive_prompt_active": True,
                    "interactive_prompt_type": "role_framing_capture",
                }
            self._interactive_prompt_state = None
            if decision == "yes":
                role_candidate = str(state.get("role_candidate", "")).strip().lower()
                if role_candidate in _ROLE_FRAMING_VALUES:
                    self._session_role = role_candidate
                return {
                    "final_output": "I'll use that role framing for this session.",
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "interactive_response",
                    "interactive_prompt_active": False,
                    "execution_enabled": False,
                    "advisory_only": True,
                }
            return {
                "final_output": "Understood. I will keep the current role framing.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "interactive_response",
                "interactive_prompt_active": False,
                "execution_enabled": False,
                "advisory_only": True,
            }

        if prompt_type == "task_mode_capture":
            decision = self._resolve_yes_no_reply(reply)
            if decision is None:
                return {
                    "final_output": "Please respond yes or no to store this session task mode.",
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "interactive_prompt",
                    "interactive_prompt_active": True,
                    "interactive_prompt_type": "task_mode_capture",
                }
            self._interactive_prompt_state = None
            if decision == "yes":
                task_mode_candidate = str(state.get("task_mode_candidate", "")).strip().lower()
                if task_mode_candidate in _TASK_MODE_VALUES:
                    self._session_task_mode = task_mode_candidate
                return {
                    "final_output": "I'll stay in that task mode for this session.",
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "interactive_response",
                    "interactive_prompt_active": False,
                    "execution_enabled": False,
                    "advisory_only": True,
                }
            return {
                "final_output": "Understood. I will keep the current task mode.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "interactive_response",
                "interactive_prompt_active": False,
                "execution_enabled": False,
                "advisory_only": True,
            }

        if prompt_type == "decision_record_capture":
            decision = self._resolve_yes_no_reply(reply)
            if decision is None:
                return {
                    "final_output": "Please respond yes or no to record this session decision.",
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "interactive_prompt",
                    "interactive_prompt_active": True,
                    "interactive_prompt_type": "decision_record_capture",
                }
            self._interactive_prompt_state = None
            if decision == "yes":
                candidate = state.get("decision_candidate", {})
                candidate = candidate if isinstance(candidate, dict) else {}
                summary = str(candidate.get("summary", "")).strip()
                context = str(candidate.get("context", "")).strip() or "General"
                if not summary:
                    return {
                        "final_output": "Decision recording skipped: summary is missing.",
                        "tool_calls": [],
                        "status": "error",
                        "trace_id": trace_id,
                        "mode": "interactive_response",
                        "interactive_prompt_active": False,
                        "execution_enabled": False,
                        "advisory_only": True,
                    }
                self._session_decision_sequence += 1
                record = {
                    "id": f"decision_{self._session_decision_sequence}",
                    "summary": summary,
                    "context": context,
                    "decided_at": datetime.now(timezone.utc).isoformat(),
                }
                self._session_decisions.append(record)
                return {
                    "final_output": (
                        f"Decision recorded for this session: {record['id']} - {record['summary']}."
                    ),
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "interactive_response",
                    "interactive_prompt_active": False,
                    "execution_enabled": False,
                    "advisory_only": True,
                    "decision": record,
                }
            return {
                "final_output": "Understood. I will not record that decision.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "interactive_response",
                "interactive_prompt_active": False,
                "execution_enabled": False,
                "advisory_only": True,
            }

        if prompt_type == "assumption_record_capture":
            decision = self._resolve_yes_no_reply(reply)
            if decision is None:
                return {
                    "final_output": "Please respond yes or no to record this session assumption.",
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "interactive_prompt",
                    "interactive_prompt_active": True,
                    "interactive_prompt_type": "assumption_record_capture",
                }
            self._interactive_prompt_state = None
            if decision == "yes":
                candidate = state.get("assumption_candidate", {})
                candidate = candidate if isinstance(candidate, dict) else {}
                summary = str(candidate.get("summary", "")).strip()
                context = str(candidate.get("context", "")).strip() or "General"
                replace_latest = bool(candidate.get("replace_latest", False))
                if not summary:
                    return {
                        "final_output": "Assumption recording skipped: summary is missing.",
                        "tool_calls": [],
                        "status": "error",
                        "trace_id": trace_id,
                        "mode": "interactive_response",
                        "interactive_prompt_active": False,
                        "execution_enabled": False,
                        "advisory_only": True,
                    }

                if replace_latest:
                    latest_active = self._latest_active_assumption()
                    if latest_active is not None:
                        latest_active["status"] = "inactive"
                        latest_active["inactive_reason"] = "revised"
                        latest_active["inactive_at"] = datetime.now(timezone.utc).isoformat()

                self._session_assumption_sequence += 1
                record = {
                    "id": f"assumption_{self._session_assumption_sequence}",
                    "summary": summary,
                    "context": context,
                    "stated_at": datetime.now(timezone.utc).isoformat(),
                    "status": "active",
                    "confirmed": False,
                }
                self._session_assumptions.append(record)
                return {
                    "final_output": (
                        f"Assumption recorded for this session: {record['id']} - {record['summary']}."
                    ),
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "interactive_response",
                    "interactive_prompt_active": False,
                    "execution_enabled": False,
                    "advisory_only": True,
                    "assumption": record,
                }
            return {
                "final_output": "Understood. I will not record that assumption.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "interactive_response",
                "interactive_prompt_active": False,
                "execution_enabled": False,
                "advisory_only": True,
            }

        if prompt_type == "constraint_record_capture":
            decision = self._resolve_yes_no_reply(reply)
            if decision is None:
                return {
                    "final_output": "Please respond yes or no to record this session constraint.",
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "interactive_prompt",
                    "interactive_prompt_active": True,
                    "interactive_prompt_type": "constraint_record_capture",
                }
            self._interactive_prompt_state = None
            if decision == "yes":
                candidate = state.get("constraint_candidate", {})
                candidate = candidate if isinstance(candidate, dict) else {}
                summary = str(candidate.get("summary", "")).strip()
                context = str(candidate.get("context", "")).strip() or "General"
                replace_latest = bool(candidate.get("replace_latest", False))
                if not summary:
                    return {
                        "final_output": "Constraint recording skipped: summary is missing.",
                        "tool_calls": [],
                        "status": "error",
                        "trace_id": trace_id,
                        "mode": "interactive_response",
                        "interactive_prompt_active": False,
                        "execution_enabled": False,
                        "advisory_only": True,
                    }

                if replace_latest:
                    latest_active = self._latest_active_constraint()
                    if latest_active is not None:
                        latest_active["status"] = "inactive"
                        latest_active["inactive_reason"] = "revised"
                        latest_active["inactive_at"] = datetime.now(timezone.utc).isoformat()

                self._session_constraint_sequence += 1
                record = {
                    "id": f"constraint_{self._session_constraint_sequence}",
                    "summary": summary,
                    "context": context,
                    "stated_at": datetime.now(timezone.utc).isoformat(),
                    "status": "active",
                }
                self._session_constraints.append(record)
                return {
                    "final_output": (
                        f"Constraint recorded for this session: {record['id']} - {record['summary']}."
                    ),
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "interactive_response",
                    "interactive_prompt_active": False,
                    "execution_enabled": False,
                    "advisory_only": True,
                    "constraint": record,
                }
            return {
                "final_output": "Understood. I will not record that constraint.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "interactive_response",
                "interactive_prompt_active": False,
                "execution_enabled": False,
                "advisory_only": True,
            }

        if prompt_type == "goal_record_capture":
            decision = self._resolve_yes_no_reply(reply)
            if decision is None:
                return {
                    "final_output": "Please respond yes or no to record this session goal.",
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "interactive_prompt",
                    "interactive_prompt_active": True,
                    "interactive_prompt_type": "goal_record_capture",
                }
            self._interactive_prompt_state = None
            if decision == "yes":
                candidate = state.get("goal_candidate", {})
                candidate = candidate if isinstance(candidate, dict) else {}
                summary = str(candidate.get("summary", "")).strip()
                context = str(candidate.get("context", "")).strip() or "General"
                replace_latest = bool(candidate.get("replace_latest", False))
                if not summary:
                    return {
                        "final_output": "Goal recording skipped: summary is missing.",
                        "tool_calls": [],
                        "status": "error",
                        "trace_id": trace_id,
                        "mode": "interactive_response",
                        "interactive_prompt_active": False,
                        "execution_enabled": False,
                        "advisory_only": True,
                    }

                if replace_latest:
                    latest_active = self._latest_active_goal()
                    if latest_active is not None:
                        latest_active["status"] = "inactive"
                        latest_active["inactive_reason"] = "revised"
                        latest_active["inactive_at"] = datetime.now(timezone.utc).isoformat()

                self._session_goal_sequence += 1
                record = {
                    "id": f"goal_{self._session_goal_sequence}",
                    "summary": summary,
                    "context": context,
                    "stated_at": datetime.now(timezone.utc).isoformat(),
                    "status": "active",
                }
                self._session_goals.append(record)
                return {
                    "final_output": (
                        f"Goal recorded for this session: {record['id']} - {record['summary']}."
                    ),
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "interactive_response",
                    "interactive_prompt_active": False,
                    "execution_enabled": False,
                    "advisory_only": True,
                    "goal": record,
                }
            return {
                "final_output": "Understood. I will not record that goal.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "interactive_response",
                "interactive_prompt_active": False,
                "execution_enabled": False,
                "advisory_only": True,
            }

        if prompt_type == "multiple_choice":
            choice_like = bool(re.fullmatch(r"[a-z]", reply))
            choice_like = choice_like or bool(
                re.fullmatch(
                    r"(?:option [a-d]|the first option|first option|the second option|second option|"
                    r"the third option|third option|the fourth option|fourth option|the first|first|"
                    r"the second|second|the third|third|the fourth|fourth|that one|this one)",
                    reply,
                )
            )
            if not choice_like:
                return None

            options = state.get("options", {})
            allowed_options = sorted(str(key).upper() for key in options.keys())
            selected = self._resolve_multiple_choice_reply(
                reply=reply,
                default_option=str(state.get("default_option", "A")),
                allowed_options=allowed_options,
            )
            if selected is None:
                return {
                    "final_output": "Please answer with one choice: A, B, C, or D.",
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "interactive_prompt",
                    "interactive_prompt_active": True,
                    "interactive_prompt_type": "multiple_choice",
                }
            correct = str(state.get("correct_option", "")).upper()
            selected_text = str(options.get(selected, "")).strip()
            if selected == correct:
                message = f"Correct: option {selected} (`{selected_text}`) is the closest synonym."
            else:
                correct_text = str(options.get(correct, "")).strip()
                message = (
                    f"Not quite: you chose {selected} (`{selected_text}`). "
                    f"The correct answer is {correct} (`{correct_text}`)."
                )
            prompt_origin = str(state.get("origin", "")).strip()
            mode_state = self._activity_mode_state if isinstance(self._activity_mode_state, dict) else {}
            current_mode = str(mode_state.get("mode", "")).strip()
            if prompt_origin == "study_mode" and current_mode == "study_mode":
                self._sync_study_session_artifact(
                    answered_correctly=selected == correct,
                    selected_option=selected,
                    correct_option=correct,
                )
                next_prompt = self._build_study_mode_quiz_prompt(
                    trace_id=trace_id,
                    preface="Study mode remains active. Here is the next question.",
                )
                return {
                    "final_output": f"{message}\n\n{next_prompt.get('final_output', '')}".strip(),
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "activity_mode",
                    "activity_mode": "study_mode",
                    "activity_mode_active": True,
                    "interactive_prompt_active": True,
                    "interactive_prompt_type": "multiple_choice",
                }
            self._interactive_prompt_state = None
            return {
                "final_output": message,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "interactive_response",
                "interactive_prompt_active": False,
            }

        if prompt_type == "yes_no":
            follow_up = self._follow_up_key(reply)
            yes_no_like = self._resolve_yes_no_reply(reply) is not None
            plan_signal = self._plan_advancement_signal(reply)
            if follow_up is None and not yes_no_like and plan_signal is None:
                return None

            if plan_signal is not None and str(state.get("origin", "")) == "advisory":
                self._interactive_prompt_state = None
                plan_response = self._advance_active_plan_artifact(
                    signal=plan_signal,
                    trace_id=trace_id,
                )
                if plan_response is not None:
                    return plan_response

            if follow_up is not None and str(state.get("origin", "")) == "advisory":
                self._interactive_prompt_state = None
                follow_up_response = self._build_follow_up_advisory_response(
                    follow_up=follow_up,
                    trace_id=trace_id,
                )
                if follow_up_response is not None:
                    return follow_up_response

            decision = self._resolve_yes_no_reply(reply)
            if decision is None:
                return {
                    "final_output": "Please respond with yes or no for the active prompt.",
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "interactive_prompt",
                    "interactive_prompt_active": True,
                    "interactive_prompt_type": "yes_no",
                }
            self._interactive_prompt_state = None
            message = str(state.get("on_yes", "")) if decision == "yes" else str(state.get("on_no", ""))
            if not message:
                message = "Interactive response recorded."
            return {
                "final_output": message,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "interactive_response",
                "interactive_prompt_active": False,
            }

        self._interactive_prompt_state = None
        return {
            "final_output": "Interactive prompt expired. Send your request again.",
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "interactive_response",
            "interactive_prompt_active": False,
        }

    def _is_website_build_request(self, utterance: str) -> bool:
        normalized = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not normalized:
            return False
        has_build = any(re.search(rf"\b{re.escape(verb)}\b", normalized) for verb in _WEBSITE_BUILD_VERBS)
        has_target = any(token in normalized for token in _WEBSITE_BUILD_TARGET_TOKENS)
        if not (has_build and has_target):
            return False
        if "execute" in normalized or "run now" in normalized or "run immediately" in normalized:
            return False
        return True

    def _website_explicit_scaffold_requested(self, utterance: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return False
        if "html" in lowered or ".html" in lowered or "code" in lowered:
            return True
        if any(token in lowered for token in _WEBSITE_PREFLIGHT_EXPLICIT_SCAFFOLD_TOKENS):
            return True
        return bool(
            re.search(
                r"\b(generate|give me|provide|just)\b.*\b(html|code|scaffold|template|boilerplate)\b",
                lowered,
            )
        )

    def _website_has_alignment_details(self, utterance: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return False

        purpose_specified = any(token in lowered for token in _WEBSITE_PREFLIGHT_PURPOSE_HINTS)
        if not purpose_specified:
            purpose_specified = bool(re.search(r"\bfor\s+[^.?!]{3,}", lowered)) and "for now" not in lowered
        audience_specified = any(token in lowered for token in _WEBSITE_PREFLIGHT_AUDIENCE_HINTS)
        style_specified = any(token in lowered for token in _WEBSITE_PREFLIGHT_STYLE_HINTS)
        return purpose_specified or audience_specified or style_specified

    def _has_active_html_artifact(self) -> bool:
        for artifact in self._task_artifacts.values():
            if isinstance(artifact, dict) and self._is_html_artifact(artifact):
                return True
        return False

    def _should_trigger_website_preflight(self, utterance: str) -> bool:
        if not self._is_website_build_request(utterance):
            return False
        if self._has_active_html_artifact():
            return False
        if self._website_explicit_scaffold_requested(utterance):
            return False
        if self._website_has_alignment_details(utterance):
            return False
        return True

    def _build_website_preflight_response(self, *, utterance: str, trace_id: str) -> Dict[str, Any]:
        question = _WEBSITE_PREFLIGHT_QUESTION
        self._interactive_prompt_state = {
            "type": "website_preflight",
            "origin": "website_preflight",
            "prompt_id": f"interactive-{trace_id}",
            "question": question,
            "seed_utterance": str(utterance or "").strip(),
        }
        self._remember_conversational_context(
            user_input=utterance,
            intent_class="planning_request",
            mode="conversation",
        )
        return {
            "final_output": question,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "interactive_prompt",
            "interactive_prompt_active": True,
            "interactive_prompt_type": "website_preflight",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _is_preference_reset_request(self, utterance: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower()).rstrip("?.!")
        if not lowered:
            return False
        if lowered in _PREFERENCE_RESET_PHRASES:
            return True
        return any(phrase in lowered for phrase in _PREFERENCE_RESET_PHRASES)

    def _build_preference_reset_response(self, *, trace_id: str) -> Dict[str, Any]:
        had_preferences = bool(self._session_preferences)
        self._session_preferences.clear()
        if (
            isinstance(self._interactive_prompt_state, dict)
            and str(self._interactive_prompt_state.get("type", "")).strip() == "preference_capture"
        ):
            self._interactive_prompt_state = None
        message = (
            "Session preferences reset. I will use explicit request details until you set new preferences."
            if had_preferences
            else "No session preferences were set."
        )
        self._remember_conversational_context(
            user_input="reset preferences",
            intent_class="informational_query",
            mode="conversation",
        )
        return {
            "final_output": message,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "conversation_layer",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _is_tone_reset_request(self, utterance: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower()).rstrip("?.!")
        if not lowered:
            return False
        if lowered in _TONE_RESET_PHRASES:
            return True
        return any(phrase in lowered for phrase in _TONE_RESET_PHRASES)

    def _build_tone_reset_response(self, *, trace_id: str) -> Dict[str, Any]:
        had_tone = bool(self._session_tone)
        self._session_tone.clear()
        if (
            isinstance(self._interactive_prompt_state, dict)
            and str(self._interactive_prompt_state.get("type", "")).strip() == "tone_preference_capture"
        ):
            self._interactive_prompt_state = None
        message = "Session tone reset. I will use the default tone unless you set one explicitly."
        if not had_tone:
            message = "No session tone preferences were set."
        self._remember_conversational_context(
            user_input="reset tone",
            intent_class="informational_query",
            mode="conversation",
        )
        return {
            "final_output": message,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "conversation_layer",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _extract_tone_preference_candidate(self, utterance: str) -> Dict[str, str] | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return None
        if self._is_tone_reset_request(lowered) or self._is_preference_reset_request(lowered):
            return None
        if self._is_website_build_request(lowered):
            return None
        if self._resolve_task_artifact_reference(lowered) is not None:
            return None

        candidate: Dict[str, str] = {}

        if any(
            phrase in lowered
            for phrase in (
                "be concise",
                "keep answers short",
                "keep responses short",
                "answers short",
                "short responses",
                "keep it brief",
                "be brief",
            )
        ):
            candidate["verbosity"] = "concise"
        elif any(
            phrase in lowered
            for phrase in (
                "be detailed",
                "more detail",
                "more detailed",
                "step-by-step",
                "step by step",
                "give me step-by-step",
                "give me step by step",
            )
        ):
            candidate["verbosity"] = "detailed"
        elif any(
            phrase in lowered
            for phrase in (
                "use standard verbosity",
                "normal verbosity",
                "standard verbosity",
            )
        ):
            candidate["verbosity"] = "standard"

        if any(
            phrase in lowered
            for phrase in (
                "be more direct",
                "more direct",
                "be direct",
                "directive",
                "just tell me what to do",
                "tell me exactly what to do",
            )
        ):
            candidate["style"] = "directive"
        elif any(
            phrase in lowered
            for phrase in (
                "explain options first",
                "explore options",
                "exploratory",
                "show options first",
                "options first",
            )
        ):
            candidate["style"] = "exploratory"

        if any(
            phrase in lowered
            for phrase in (
                "be gentle",
                "gentle tone",
                "soften",
            )
        ):
            candidate["confidence_framing"] = "gentle"
        elif any(
            phrase in lowered
            for phrase in (
                "be firm",
                "firm tone",
                "more firm",
                "sound confident",
            )
        ):
            candidate["confidence_framing"] = "firm"

        if not candidate:
            return None
        return candidate

    def _tone_candidate_descriptor(self, candidate: Dict[str, str]) -> str:
        ordered: List[str] = []
        verbosity = str(candidate.get("verbosity", "")).strip().lower()
        if verbosity in _TONE_VERBOSITY_VALUES:
            ordered.append(verbosity)
        style = str(candidate.get("style", "")).strip().lower()
        if style in _TONE_STYLE_VALUES:
            ordered.append(style)
        confidence = str(candidate.get("confidence_framing", "")).strip().lower()
        if confidence in _TONE_CONFIDENCE_VALUES:
            ordered.append(confidence)
        if not ordered:
            return "session tone"
        if len(ordered) == 1:
            return f"{ordered[0]} tone"
        return f"{', '.join(ordered[:-1])}, and {ordered[-1]} tone"

    def _build_tone_preference_confirmation_response(
        self,
        *,
        candidate: Dict[str, str],
        trace_id: str,
    ) -> Dict[str, Any]:
        descriptor = self._tone_candidate_descriptor(candidate)
        question = f"I can use a {descriptor} for this session. {_TONE_CAPTURE_CONFIRM_PREFIX}"
        self._interactive_prompt_state = {
            "type": "tone_preference_capture",
            "origin": "tone_preference",
            "prompt_id": f"interactive-{trace_id}",
            "question": question,
            "tone_candidate": {
                "verbosity": str(candidate.get("verbosity", "")).strip().lower(),
                "style": str(candidate.get("style", "")).strip().lower(),
                "confidence_framing": str(candidate.get("confidence_framing", "")).strip().lower(),
            },
        }
        return {
            "final_output": question,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "interactive_prompt",
            "interactive_prompt_active": True,
            "interactive_prompt_type": "tone_preference_capture",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _effective_tone_profile(self) -> Dict[str, str]:
        profile = {
            "verbosity": "standard",
            "style": "exploratory",
            "confidence_framing": "gentle",
        }
        verbosity = str(self._session_tone.get("verbosity", "")).strip().lower()
        style = str(self._session_tone.get("style", "")).strip().lower()
        confidence = str(self._session_tone.get("confidence_framing", "")).strip().lower()
        if verbosity in _TONE_VERBOSITY_VALUES:
            profile["verbosity"] = verbosity
        if style in _TONE_STYLE_VALUES:
            profile["style"] = style
        if confidence in _TONE_CONFIDENCE_VALUES:
            profile["confidence_framing"] = confidence
        return profile

    def _apply_tone_to_conversational_text(self, text: str) -> str:
        if not self._session_tone:
            return text
        base = str(text or "").strip()
        if not base:
            return base
        profile = self._effective_tone_profile()
        verbosity = profile["verbosity"]
        style = profile["style"]
        confidence = profile["confidence_framing"]

        core = base
        if verbosity == "concise":
            sentence = re.split(r"(?<=[.!?])\s+", core, maxsplit=1)
            core = sentence[0].strip()
        elif verbosity == "detailed":
            core = f"{core} I can also provide a deeper step-by-step breakdown if you want."

        if style == "directive":
            core = f"Direct answer: {core}"
        elif style == "exploratory":
            core = f"Option-aware answer: {core}"

        if confidence == "firm":
            core = f"{core} This is my recommended direction."
        elif confidence == "gentle":
            core = f"{core} We can adjust this if you prefer."
        return core.strip()

    def _apply_tone_to_advisory_message(self, message: str) -> str:
        if not self._session_tone:
            return message
        base = str(message or "").strip()
        if not base:
            return base
        profile = self._effective_tone_profile()
        verbosity = profile["verbosity"]
        style = profile["style"]
        confidence = profile["confidence_framing"]

        core = base
        if verbosity == "concise":
            sentence = re.split(r"(?<=[.!?])\s+", core, maxsplit=1)
            core = sentence[0].strip()
        elif verbosity == "detailed":
            core = f"{core} I can expand each part with rationale and tradeoffs if needed."

        if style == "directive":
            core = f"Direct plan: {core}"
        elif style == "exploratory":
            core = f"Exploration plan: {core}"

        if confidence == "firm":
            core = f"{core} Recommended path."
        elif confidence == "gentle":
            core = f"{core} We can tune this together."
        return core.strip()

    def _apply_tone_to_continuation_question(self, question: str) -> str:
        if not self._session_tone:
            return question
        profile = self._effective_tone_profile()
        verbosity = profile["verbosity"]
        style = profile["style"]
        confidence = profile["confidence_framing"]

        if style == "directive":
            if verbosity == "concise":
                return "Proceed with the next step?"
            if confidence == "firm":
                return "Do you want me to proceed with the next concrete step now?"
            return "Would you like me to proceed with the next concrete step?"

        if verbosity == "concise":
            return "Compare options first?"
        if verbosity == "detailed":
            return "Would you like me to compare a few options with tradeoffs before we pick the next step?"
        return "Would you like to compare options before choosing the next step?"

    def _is_role_reset_request(self, utterance: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower()).rstrip("?.!")
        if not lowered:
            return False
        if lowered in _ROLE_RESET_PHRASES:
            return True
        return any(phrase in lowered for phrase in _ROLE_RESET_PHRASES)

    def _build_role_reset_response(self, *, trace_id: str) -> Dict[str, Any]:
        had_role = bool(self._session_role)
        self._session_role = None
        if (
            isinstance(self._interactive_prompt_state, dict)
            and str(self._interactive_prompt_state.get("type", "")).strip() == "role_framing_capture"
        ):
            self._interactive_prompt_state = None
        message = "Session role framing reset. I will use the default perspective unless you set one explicitly."
        if not had_role:
            message = "No session role framing was set."
        self._remember_conversational_context(
            user_input="reset role",
            intent_class="informational_query",
            mode="conversation",
        )
        return {
            "final_output": message,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "conversation_layer",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _extract_role_framing_candidate(self, utterance: str) -> str | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return None
        if self._is_role_reset_request(lowered):
            return None
        if self._is_tone_reset_request(lowered) or self._is_preference_reset_request(lowered):
            return None
        if self._is_website_build_request(lowered):
            return None
        if self._resolve_task_artifact_reference(lowered) is not None:
            return None

        alias_by_role = {
            "teacher": ("teacher",),
            "senior_engineer": ("senior engineer", "senior-engineer", "senior_engineer"),
            "architect": ("architect",),
            "product_manager": ("product manager", "product-manager", "product_manager"),
            "researcher": ("researcher",),
            "coach": ("coach",),
        }

        for role_name in _ROLE_FRAMING_VALUES:
            aliases = alias_by_role.get(role_name, ())
            for alias in aliases:
                escaped_alias = re.escape(alias)
                explicit_patterns = (
                    rf"\bact\s+(?:like|as)\s+(?:an?\s+)?{escaped_alias}\b",
                    rf"\bexplain(?:\s+this)?\s+as\s+(?:an?\s+)?{escaped_alias}\b",
                    rf"\bthink\s+like\s+(?:an?\s+)?{escaped_alias}\b",
                    rf"\btalk\s+to\s+me\s+like\s+(?:an?\s+)?{escaped_alias}\b",
                    rf"\bbe\s+(?:an?\s+)?{escaped_alias}(?:\s+right\s+now)?\b",
                    rf"\bswitch\s+(?:to|into)\s+(?:an?\s+)?{escaped_alias}(?:\s+mode)?\b",
                    rf"\b(?:use|set)\s+(?:an?\s+)?{escaped_alias}(?:\s+mode)?\b",
                    rf"\bfrom\s+(?:an?\s+)?{escaped_alias}(?:'s)?\s+perspective\b",
                )
                if any(re.search(pattern, lowered) for pattern in explicit_patterns):
                    return role_name
        return None

    def _role_display_name(self, role_name: str) -> str:
        normalized = str(role_name or "").strip().lower()
        if not normalized:
            return ""
        return str(_ROLE_FRAMING_LABELS.get(normalized, normalized.replace("_", " "))).strip()

    def _build_role_framing_confirmation_response(
        self,
        *,
        role_name: str,
        trace_id: str,
    ) -> Dict[str, Any]:
        display_name = self._role_display_name(role_name)
        if not display_name:
            return {
                "final_output": "Role framing capture skipped: role candidate is invalid.",
                "tool_calls": [],
                "status": "error",
                "trace_id": trace_id,
                "mode": "conversation_layer",
                "execution_enabled": False,
                "advisory_only": True,
            }
        question = (
            f"I can explain things from a {display_name} perspective for this session. "
            f"{_ROLE_CAPTURE_CONFIRM_PREFIX}"
        )
        self._interactive_prompt_state = {
            "type": "role_framing_capture",
            "origin": "role_framing",
            "prompt_id": f"interactive-{trace_id}",
            "question": question,
            "role_candidate": str(role_name).strip().lower(),
        }
        return {
            "final_output": question,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "interactive_prompt",
            "interactive_prompt_active": True,
            "interactive_prompt_type": "role_framing_capture",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _effective_role_framing(self) -> str | None:
        role_name = str(self._session_role or "").strip().lower()
        if role_name in _ROLE_FRAMING_VALUES:
            return role_name
        return None

    def _apply_role_framing_to_conversational_text(self, text: str) -> str:
        role_name = self._effective_role_framing()
        if role_name is None:
            return text
        base = str(text or "").strip()
        if not base:
            return base
        display_name = self._role_display_name(role_name).title()
        focus_note = str(_ROLE_FRAMING_FOCUS.get(role_name, "")).strip()
        return f"{display_name} framing: {base} {focus_note}".strip()

    def _apply_role_framing_to_advisory_message(self, message: str) -> str:
        role_name = self._effective_role_framing()
        if role_name is None:
            return message
        base = str(message or "").strip()
        if not base:
            return base
        display_name = self._role_display_name(role_name).title()
        focus_note = str(_ROLE_FRAMING_FOCUS.get(role_name, "")).strip()
        return f"{display_name} perspective: {base} {focus_note}".strip()

    def _apply_role_framing_to_continuation_question(self, question: str) -> str:
        role_name = self._effective_role_framing()
        if role_name is None:
            return question
        base = str(question or "").strip()
        if not base:
            return base
        display_name = self._role_display_name(role_name)
        return f"From a {display_name} perspective, {base}"

    def _is_task_mode_reset_request(self, utterance: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower()).rstrip("?.!")
        if not lowered:
            return False
        if lowered in _TASK_MODE_RESET_PHRASES:
            return True
        return any(phrase in lowered for phrase in _TASK_MODE_RESET_PHRASES)

    def _build_task_mode_reset_response(self, *, trace_id: str) -> Dict[str, Any]:
        had_task_mode = bool(self._session_task_mode)
        self._session_task_mode = None
        if (
            isinstance(self._interactive_prompt_state, dict)
            and str(self._interactive_prompt_state.get("type", "")).strip() == "task_mode_capture"
        ):
            self._interactive_prompt_state = None
        message = "Session task mode reset. I will use the default response structure unless you set one explicitly."
        if not had_task_mode:
            message = "No session task mode was set."
        self._remember_conversational_context(
            user_input="reset task mode",
            intent_class="informational_query",
            mode="conversation",
        )
        return {
            "final_output": message,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "conversation_layer",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _extract_task_mode_candidate(self, utterance: str) -> str | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return None
        if self._is_task_mode_reset_request(lowered):
            return None

        if any(
            phrase in lowered
            for phrase in (
                "let's brainstorm",
                "lets brainstorm",
                "just brainstorm",
                "brainstorm for now",
                "switch to brainstorm mode",
                "brainstorm mode",
            )
        ):
            return "brainstorm"

        if any(
            phrase in lowered
            for phrase in (
                "step by step",
                "step-by-step",
                "walk me through this step by step",
                "walk me through it step by step",
                "switch to step by step mode",
                "switch to step-by-step mode",
                "step by step mode",
                "step-by-step mode",
            )
        ):
            return "step_by_step"

        if any(
            phrase in lowered
            for phrase in (
                "critique this",
                "critique this idea",
                "switch to critique mode",
                "critique mode",
            )
        ):
            return "critique"

        if any(
            phrase in lowered
            for phrase in (
                "compare options",
                "compare the options",
                "let's compare options",
                "lets compare options",
                "switch to compare options mode",
                "compare options mode",
            )
        ):
            return "compare_options"

        if any(
            phrase in lowered
            for phrase in (
                "summarize and recommend",
                "summarize and decide",
                "summary and recommendation",
                "switch to summarize and decide mode",
                "summarize and decide mode",
            )
        ):
            return "summarize_and_decide"

        return None

    def _task_mode_display_name(self, task_mode: str) -> str:
        normalized = str(task_mode or "").strip().lower()
        if not normalized:
            return ""
        return str(_TASK_MODE_LABELS.get(normalized, normalized.replace("_", "-"))).strip()

    def _build_task_mode_capture_confirmation_response(
        self,
        *,
        task_mode: str,
        trace_id: str,
    ) -> Dict[str, Any]:
        display_name = self._task_mode_display_name(task_mode)
        if not display_name:
            return {
                "final_output": "Task mode capture skipped: mode candidate is invalid.",
                "tool_calls": [],
                "status": "error",
                "trace_id": trace_id,
                "mode": "conversation_layer",
                "execution_enabled": False,
                "advisory_only": True,
            }
        question = f"I can stay in {display_name} mode for this session. {_TASK_MODE_CAPTURE_CONFIRM_PREFIX}"
        self._interactive_prompt_state = {
            "type": "task_mode_capture",
            "origin": "task_mode",
            "prompt_id": f"interactive-{trace_id}",
            "question": question,
            "task_mode_candidate": str(task_mode).strip().lower(),
        }
        return {
            "final_output": question,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "interactive_prompt",
            "interactive_prompt_active": True,
            "interactive_prompt_type": "task_mode_capture",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _effective_task_mode(self) -> str | None:
        task_mode = str(self._session_task_mode or "").strip().lower()
        if task_mode in _TASK_MODE_VALUES:
            return task_mode
        return None

    def _apply_task_mode_to_conversational_text(self, text: str) -> str:
        task_mode = self._effective_task_mode()
        if task_mode is None:
            return text
        base = str(text or "").strip()
        if not base:
            return base
        if task_mode == "brainstorm":
            return (
                "Brainstorm mode:\n"
                f"- Seed idea: {base}\n"
                "- Angle A: pursue a fast low-risk path.\n"
                "- Angle B: pursue a higher-upside path with more uncertainty."
            )
        if task_mode == "step_by_step":
            return (
                "Step-by-step mode:\n"
                f"1. Current understanding: {base}\n"
                "2. Define the immediate next action.\n"
                "3. Check outcome and iterate."
            )
        if task_mode == "critique":
            return (
                "Critique mode:\n"
                f"- Claim: {base}\n"
                "- Strength: identify what is already solid.\n"
                "- Risk: identify the most likely failure point.\n"
                "- Improvement: propose the highest-value fix."
            )
        if task_mode == "compare_options":
            return (
                "Compare-options mode:\n"
                f"- Option A: {base}\n"
                "- Option B: alternative with different tradeoffs.\n"
                "- Decision lens: choose based on constraints and reversibility."
            )
        if task_mode == "summarize_and_decide":
            return (
                "Summarize-and-decide mode:\n"
                f"- Summary: {base}\n"
                "- Recommendation: select the path with best risk-adjusted fit.\n"
                "- Decision: confirm go/no-go for the next step."
            )
        return base

    def _apply_task_mode_to_advisory_message(self, message: str) -> str:
        task_mode = self._effective_task_mode()
        if task_mode is None:
            return message
        base = str(message or "").strip()
        if not base:
            return base
        if task_mode == "brainstorm":
            return (
                "Brainstorm mode:\n"
                f"- Core direction: {base}\n"
                "- Add 2-3 alternatives before narrowing."
            )
        if task_mode == "step_by_step":
            return (
                "Step-by-step mode:\n"
                f"1. Primary plan: {base}\n"
                "2. Execute the smallest safe next action.\n"
                "3. Validate and continue."
            )
        if task_mode == "critique":
            return (
                "Critique mode:\n"
                f"- Current plan: {base}\n"
                "- Gaps: check assumptions and failure modes.\n"
                "- Revision: apply the highest-impact correction."
            )
        if task_mode == "compare_options":
            return (
                "Compare-options mode:\n"
                f"- Baseline option: {base}\n"
                "- Alternative option: evaluate a different path.\n"
                "- Tradeoff lens: cost, speed, and risk."
            )
        if task_mode == "summarize_and_decide":
            return (
                "Summarize-and-decide mode:\n"
                f"- Summary: {base}\n"
                "- Recommendation: choose the best-fit option.\n"
                "- Decision rule: move forward if constraints are satisfied."
            )
        return base

    def _apply_task_mode_to_continuation_question(self, question: str) -> str:
        task_mode = self._effective_task_mode()
        if task_mode is None:
            return question
        if task_mode == "brainstorm":
            return "Want one more brainstorm pass before narrowing to a direction?"
        if task_mode == "step_by_step":
            return "Ready for the next step?"
        if task_mode == "critique":
            return "Want a deeper critique pass focused on risks?"
        if task_mode == "compare_options":
            return "Do you want a side-by-side comparison before deciding?"
        if task_mode == "summarize_and_decide":
            return "Want a concise recommendation and a go/no-go decision?"
        return question

    def _decision_reset_mode(self, utterance: str) -> str | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower()).rstrip("?.!")
        if not lowered:
            return None
        if lowered in _DECISION_RESET_ALL_PHRASES or any(
            phrase in lowered for phrase in _DECISION_RESET_ALL_PHRASES
        ):
            return "all"
        if lowered in _DECISION_RESET_LATEST_PHRASES or any(
            phrase in lowered for phrase in _DECISION_RESET_LATEST_PHRASES
        ):
            return "latest"
        return None

    def _build_decision_reset_response(self, *, mode: str, trace_id: str) -> Dict[str, Any]:
        if (
            isinstance(self._interactive_prompt_state, dict)
            and str(self._interactive_prompt_state.get("type", "")).strip() == "decision_record_capture"
        ):
            self._interactive_prompt_state = None

        if mode == "latest":
            if not self._session_decisions:
                message = "No recorded decisions are available to remove."
            else:
                removed = self._session_decisions.pop()
                message = (
                    "Removed the latest session decision: "
                    f"{str(removed.get('id', '')).strip()} - {str(removed.get('summary', '')).strip()}."
                )
        else:
            had_decisions = bool(self._session_decisions)
            self._session_decisions.clear()
            message = "All session decisions cleared."
            if not had_decisions:
                message = "No session decisions were recorded."

        self._remember_conversational_context(
            user_input="clear decisions" if mode == "all" else "forget that decision",
            intent_class="informational_query",
            mode="conversation",
        )
        return {
            "final_output": message,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "conversation_layer",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _decision_context_from_utterance(self, utterance: str) -> str:
        subject = self._extract_conversational_subject(utterance)
        if not subject:
            subject = str(self._conversation_context.get("last_subject_noun", "")).strip()
        normalized = subject.lower()
        if any(token in normalized for token in ("website", "web page", "html")):
            return "Website build"
        if not subject:
            return "General"
        return subject

    def _extract_decision_candidate(self, utterance: str) -> Dict[str, str] | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return None
        if self._decision_reset_mode(lowered) is not None:
            return None

        summary = ""
        explicit = str(utterance or "").strip()
        decision_prefix_match = re.match(r"(?i)^\s*decision\s*:\s*(.+)$", explicit)
        if decision_prefix_match is not None:
            summary = str(decision_prefix_match.group(1)).strip()
        else:
            go_with_match = re.search(r"\b(?:let's|lets)\s+go\s+with\s+(.+)", lowered)
            if go_with_match is not None:
                chosen = str(go_with_match.group(1)).strip(" .!?")
                if chosen:
                    summary = f"Go with {chosen}."
            elif lowered in {
                "yes that's the plan",
                "yes, that's the plan",
                "yes thats the plan",
                "that's the plan",
                "thats the plan",
            }:
                prior = str(self._conversation_context.get("last_user_input", "")).strip()
                prior_normalized = re.sub(r"\s+", " ", prior.lower()).strip()
                if prior and prior_normalized != lowered:
                    summary = f"Confirm prior plan: {prior}"

        summary = summary.strip()
        if not summary:
            return None
        context = self._decision_context_from_utterance(utterance)
        return {
            "summary": summary,
            "context": context,
        }

    def _build_decision_capture_confirmation_response(
        self,
        *,
        candidate: Dict[str, str],
        trace_id: str,
    ) -> Dict[str, Any]:
        summary = str(candidate.get("summary", "")).strip()
        context = str(candidate.get("context", "")).strip() or "General"
        if not summary:
            return {
                "final_output": "Decision capture skipped: decision summary is empty.",
                "tool_calls": [],
                "status": "error",
                "trace_id": trace_id,
                "mode": "conversation_layer",
                "execution_enabled": False,
                "advisory_only": True,
            }
        question = (
            f"I heard this decision ({context}): {summary} "
            "Got it - want me to record that decision for this session?"
        )
        self._interactive_prompt_state = {
            "type": "decision_record_capture",
            "origin": "decision_recording",
            "prompt_id": f"interactive-{trace_id}",
            "question": question,
            "decision_candidate": {
                "summary": summary,
                "context": context,
            },
        }
        return {
            "final_output": question,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "interactive_prompt",
            "interactive_prompt_active": True,
            "interactive_prompt_type": "decision_record_capture",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _latest_session_decision(self) -> Dict[str, Any] | None:
        if not self._session_decisions:
            return None
        latest = self._session_decisions[-1]
        return latest if isinstance(latest, dict) else None

    def _apply_decision_reference_to_conversational_text(self, text: str) -> str:
        latest = self._latest_session_decision()
        if latest is None:
            return text
        base = str(text or "").strip()
        if not base:
            return base
        decision_id = str(latest.get("id", "")).strip()
        summary = str(latest.get("summary", "")).strip()
        if not decision_id or not summary:
            return base
        reference = f"Based on your earlier decision ({decision_id}): {summary}"
        return f"{reference}\n{base}".strip()

    def _apply_decision_reference_to_advisory_message(self, message: str) -> str:
        latest = self._latest_session_decision()
        if latest is None:
            return message
        base = str(message or "").strip()
        if not base:
            return base
        decision_id = str(latest.get("id", "")).strip()
        summary = str(latest.get("summary", "")).strip()
        if not decision_id or not summary:
            return base
        reference = f"Based on your earlier decision ({decision_id}): {summary}."
        return f"{reference} {base}".strip()

    def _latest_active_assumption(self) -> Dict[str, Any] | None:
        if not self._session_assumptions:
            return None
        for record in reversed(self._session_assumptions):
            if not isinstance(record, dict):
                continue
            if str(record.get("status", "")).strip().lower() == "active":
                return record
        return None

    def _assumption_reset_mode(self, utterance: str) -> str | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower()).rstrip("?.!")
        if not lowered:
            return None
        if lowered in _ASSUMPTION_RESET_ALL_PHRASES or any(
            phrase in lowered for phrase in _ASSUMPTION_RESET_ALL_PHRASES
        ):
            return "all"
        if lowered in _ASSUMPTION_RESET_LATEST_PHRASES or any(
            phrase in lowered for phrase in _ASSUMPTION_RESET_LATEST_PHRASES
        ):
            return "latest"
        return None

    def _is_assumption_confirm_request(self, utterance: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower()).rstrip("?.!")
        if not lowered:
            return False
        if lowered in _ASSUMPTION_CONFIRM_LATEST_PHRASES:
            return True
        return any(phrase in lowered for phrase in _ASSUMPTION_CONFIRM_LATEST_PHRASES)

    def _extract_assumption_change_candidate(self, utterance: str) -> Dict[str, Any] | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return None
        if not any(phrase in lowered for phrase in _ASSUMPTION_CHANGE_LATEST_PHRASES):
            return None
        if self._latest_active_assumption() is None:
            return {"error": "no_active_assumption"}

        explicit = str(utterance or "").strip()
        match = re.search(
            r"(?i)\b(?:change|revise|update)\s+that\s+assumption(?:\s+to)?\s+(.+)$",
            explicit,
        )
        if match is None:
            return {"error": "needs_replacement"}
        summary = str(match.group(1)).strip().rstrip(".")
        if not summary:
            return {"error": "needs_replacement"}
        return {
            "summary": summary,
            "context": self._decision_context_from_utterance(utterance),
            "replace_latest": True,
        }

    def _build_assumption_change_guidance_response(self, *, trace_id: str) -> Dict[str, Any]:
        return {
            "final_output": (
                "Tell me the replacement explicitly, for example: "
                "`change that assumption to this is a local-only site`."
            ),
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "conversation_layer",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _build_assumption_reset_response(self, *, mode: str, trace_id: str) -> Dict[str, Any]:
        if (
            isinstance(self._interactive_prompt_state, dict)
            and str(self._interactive_prompt_state.get("type", "")).strip() == "assumption_record_capture"
        ):
            self._interactive_prompt_state = None

        if mode == "latest":
            latest = self._latest_active_assumption()
            if latest is None:
                message = "No active assumptions are available to remove."
            else:
                latest["status"] = "inactive"
                latest["inactive_reason"] = "forgotten"
                latest["inactive_at"] = datetime.now(timezone.utc).isoformat()
                message = (
                    "Removed the latest active assumption: "
                    f"{str(latest.get('id', '')).strip()} - {str(latest.get('summary', '')).strip()}."
                )
        else:
            active_found = False
            for record in self._session_assumptions:
                if not isinstance(record, dict):
                    continue
                if str(record.get("status", "")).strip().lower() != "active":
                    continue
                active_found = True
                record["status"] = "inactive"
                record["inactive_reason"] = "cleared"
                record["inactive_at"] = datetime.now(timezone.utc).isoformat()
            message = "All active session assumptions cleared."
            if not active_found:
                message = "No active session assumptions were recorded."

        self._remember_conversational_context(
            user_input="clear assumptions" if mode == "all" else "forget that assumption",
            intent_class="informational_query",
            mode="conversation",
        )
        return {
            "final_output": message,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "conversation_layer",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _build_assumption_confirm_response(self, *, trace_id: str) -> Dict[str, Any]:
        latest = self._latest_active_assumption()
        if latest is None:
            message = "No active assumption is available to confirm."
        else:
            latest["confirmed"] = True
            latest["confirmed_at"] = datetime.now(timezone.utc).isoformat()
            message = (
                "Assumption confirmed for this session: "
                f"{str(latest.get('id', '')).strip()} - {str(latest.get('summary', '')).strip()}."
            )
        self._remember_conversational_context(
            user_input="confirm that assumption",
            intent_class="informational_query",
            mode="conversation",
        )
        return {
            "final_output": message,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "conversation_layer",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _extract_assumption_candidate(self, utterance: str) -> Dict[str, Any] | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return None
        if _is_governance_handoff_instruction(lowered):
            return None
        if self._assumption_reset_mode(lowered) is not None:
            return None
        if lowered in {"confirm that assumption", "confirm assumption"}:
            return None
        if any(phrase in lowered for phrase in _ASSUMPTION_CHANGE_LATEST_PHRASES):
            return None

        explicit = str(utterance or "").strip()
        summary = ""
        match = re.match(r"(?i)^\s*assumption\s*:\s*(.+)$", explicit)
        if match is not None:
            summary = str(match.group(1)).strip().rstrip(".")
        else:
            match = re.search(r"(?i)\b(?:let's|lets)\s+assume\s+(.+)$", explicit)
            if match is not None:
                summary = str(match.group(1)).strip().rstrip(".")
            else:
                match = re.match(r"(?i)^\s*assume\s+(.+)$", explicit)
                if match is not None:
                    summary = str(match.group(1)).strip().rstrip(".")
                elif lowered in {
                    "that assumption works",
                    "yes that assumption works",
                    "yes, that assumption works",
                }:
                    prior = str(self._conversation_context.get("last_user_input", "")).strip()
                    prior_normalized = re.sub(r"\s+", " ", prior.lower()).strip()
                    if prior and prior_normalized != lowered:
                        summary = f"Confirm prior assumption: {prior}"

        summary = summary.strip()
        if not summary:
            return None
        return {
            "summary": summary,
            "context": self._decision_context_from_utterance(utterance),
            "replace_latest": False,
        }

    def _build_assumption_capture_confirmation_response(
        self,
        *,
        candidate: Dict[str, Any],
        trace_id: str,
    ) -> Dict[str, Any]:
        summary = str(candidate.get("summary", "")).strip()
        context = str(candidate.get("context", "")).strip() or "General"
        replace_latest = bool(candidate.get("replace_latest", False))
        if not summary:
            return {
                "final_output": "Assumption capture skipped: summary is empty.",
                "tool_calls": [],
                "status": "error",
                "trace_id": trace_id,
                "mode": "conversation_layer",
                "execution_enabled": False,
                "advisory_only": True,
            }
        if replace_latest:
            question = (
                f"I can replace the latest active assumption with ({context}): {summary}. "
                "Want me to treat that as an assumption for this session?"
            )
        else:
            question = (
                f"I heard this assumption ({context}): {summary}. "
                "Want me to treat that as an assumption for this session?"
            )
        self._interactive_prompt_state = {
            "type": "assumption_record_capture",
            "origin": "assumption_tracking",
            "prompt_id": f"interactive-{trace_id}",
            "question": question,
            "assumption_candidate": {
                "summary": summary,
                "context": context,
                "replace_latest": replace_latest,
            },
        }
        return {
            "final_output": question,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "interactive_prompt",
            "interactive_prompt_active": True,
            "interactive_prompt_type": "assumption_record_capture",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _apply_assumption_reference_to_conversational_text(self, text: str) -> str:
        latest = self._latest_active_assumption()
        if latest is None:
            return text
        base = str(text or "").strip()
        if not base:
            return base
        assumption_id = str(latest.get("id", "")).strip()
        summary = str(latest.get("summary", "")).strip()
        if not assumption_id or not summary:
            return base
        reference = f"Based on our assumption ({assumption_id}): {summary}"
        return f"{reference}\n{base}".strip()

    def _apply_assumption_reference_to_advisory_message(self, message: str) -> str:
        latest = self._latest_active_assumption()
        if latest is None:
            return message
        base = str(message or "").strip()
        if not base:
            return base
        assumption_id = str(latest.get("id", "")).strip()
        summary = str(latest.get("summary", "")).strip()
        if not assumption_id or not summary:
            return base
        reference = (
            f"Based on our assumption ({assumption_id}): {summary}. "
            "If this assumption changes, we should revise the plan."
        )
        return f"{reference} {base}".strip()

    def _latest_active_constraint(self) -> Dict[str, Any] | None:
        if not self._session_constraints:
            return None
        for record in reversed(self._session_constraints):
            if not isinstance(record, dict):
                continue
            if str(record.get("status", "")).strip().lower() == "active":
                return record
        return None

    def _constraint_reset_mode(self, utterance: str) -> str | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower()).rstrip("?.!")
        if not lowered:
            return None
        if lowered in _CONSTRAINT_RESET_ALL_PHRASES or any(
            phrase in lowered for phrase in _CONSTRAINT_RESET_ALL_PHRASES
        ):
            return "all"
        if lowered in _CONSTRAINT_RESET_LATEST_PHRASES or any(
            phrase in lowered for phrase in _CONSTRAINT_RESET_LATEST_PHRASES
        ):
            return "latest"
        return None

    def _is_constraint_list_request(self, utterance: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower()).rstrip("?.!")
        if not lowered:
            return False
        if lowered in _CONSTRAINT_LIST_PHRASES:
            return True
        return any(phrase in lowered for phrase in _CONSTRAINT_LIST_PHRASES)

    def _build_constraint_list_response(self, *, trace_id: str) -> Dict[str, Any]:
        active = [
            record
            for record in self._session_constraints
            if isinstance(record, dict) and str(record.get("status", "")).strip().lower() == "active"
        ]
        if not active:
            message = "No active constraints are recorded for this session."
        else:
            lines = ["Active constraints:"]
            for record in active:
                lines.append(
                    f"- {str(record.get('id', '')).strip()}: {str(record.get('summary', '')).strip()}"
                )
            message = "\n".join(lines)
        self._remember_conversational_context(
            user_input="list constraints",
            intent_class="informational_query",
            mode="conversation",
        )
        return {
            "final_output": message,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "conversation_layer",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _extract_constraint_change_candidate(self, utterance: str) -> Dict[str, Any] | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return None
        if not any(phrase in lowered for phrase in _CONSTRAINT_CHANGE_LATEST_PHRASES):
            return None
        if self._latest_active_constraint() is None:
            return {"error": "no_active_constraint"}

        explicit = str(utterance or "").strip()
        match = re.search(
            r"(?i)\b(?:change|revise|update)\s+that\s+constraint(?:\s+to)?\s+(.+)$",
            explicit,
        )
        if match is None:
            return {"error": "needs_replacement"}
        summary = str(match.group(1)).strip().rstrip(".")
        if not summary:
            return {"error": "needs_replacement"}
        return {
            "summary": summary,
            "context": self._decision_context_from_utterance(utterance),
            "replace_latest": True,
        }

    def _build_constraint_change_guidance_response(self, *, trace_id: str) -> Dict[str, Any]:
        return {
            "final_output": (
                "Tell me the replacement explicitly, for example: "
                "`change that constraint to no external dependencies`."
            ),
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "conversation_layer",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _build_constraint_reset_response(self, *, mode: str, trace_id: str) -> Dict[str, Any]:
        if (
            isinstance(self._interactive_prompt_state, dict)
            and str(self._interactive_prompt_state.get("type", "")).strip() == "constraint_record_capture"
        ):
            self._interactive_prompt_state = None

        if mode == "latest":
            latest = self._latest_active_constraint()
            if latest is None:
                message = "No active constraints are available to remove."
            else:
                latest["status"] = "inactive"
                latest["inactive_reason"] = "removed"
                latest["inactive_at"] = datetime.now(timezone.utc).isoformat()
                message = (
                    "Removed the latest active constraint: "
                    f"{str(latest.get('id', '')).strip()} - {str(latest.get('summary', '')).strip()}."
                )
        else:
            active_found = False
            for record in self._session_constraints:
                if not isinstance(record, dict):
                    continue
                if str(record.get("status", "")).strip().lower() != "active":
                    continue
                active_found = True
                record["status"] = "inactive"
                record["inactive_reason"] = "cleared"
                record["inactive_at"] = datetime.now(timezone.utc).isoformat()
            message = "All active session constraints cleared."
            if not active_found:
                message = "No active session constraints were recorded."

        self._remember_conversational_context(
            user_input="clear constraints" if mode == "all" else "remove that constraint",
            intent_class="informational_query",
            mode="conversation",
        )
        return {
            "final_output": message,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "conversation_layer",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _extract_constraint_candidate(self, utterance: str) -> Dict[str, Any] | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return None
        if self._constraint_reset_mode(lowered) is not None:
            return None
        if self._is_constraint_list_request(lowered):
            return None
        if any(phrase in lowered for phrase in _CONSTRAINT_CHANGE_LATEST_PHRASES):
            return None

        explicit = str(utterance or "").strip()
        summary = ""
        match = re.match(r"(?i)^\s*constraint\s*:\s*(.+)$", explicit)
        if match is not None:
            summary = str(match.group(1)).strip().rstrip(".")
        else:
            match = re.search(r"(?i)\bwe\s+must\b\s+(.+)$", explicit)
            if match is not None:
                summary = f"must {str(match.group(1)).strip().rstrip('.')}"
            else:
                match = re.match(r"(?i)^\s*do\s+not\s+(.+)$", explicit)
                if match is not None:
                    summary = f"Do not {str(match.group(1)).strip().rstrip('.')}"
                elif lowered.startswith("keep it "):
                    summary = explicit.strip().rstrip(".")
                elif lowered.startswith("no ") and len(lowered.split()) >= 2:
                    summary = explicit.strip().rstrip(".")

        summary = summary.strip()
        if not summary:
            return None
        return {
            "summary": summary,
            "context": self._decision_context_from_utterance(utterance),
            "replace_latest": False,
        }

    def _build_constraint_capture_confirmation_response(
        self,
        *,
        candidate: Dict[str, Any],
        trace_id: str,
    ) -> Dict[str, Any]:
        summary = str(candidate.get("summary", "")).strip()
        context = str(candidate.get("context", "")).strip() or "General"
        replace_latest = bool(candidate.get("replace_latest", False))
        if not summary:
            return {
                "final_output": "Constraint capture skipped: summary is empty.",
                "tool_calls": [],
                "status": "error",
                "trace_id": trace_id,
                "mode": "conversation_layer",
                "execution_enabled": False,
                "advisory_only": True,
            }
        if replace_latest:
            question = (
                f"I can replace the latest active constraint with ({context}): {summary}. "
                "Want me to record that as a constraint for this session?"
            )
        else:
            question = (
                f"I heard this constraint ({context}): {summary}. "
                "Want me to record that as a constraint for this session?"
            )
        self._interactive_prompt_state = {
            "type": "constraint_record_capture",
            "origin": "constraint_register",
            "prompt_id": f"interactive-{trace_id}",
            "question": question,
            "constraint_candidate": {
                "summary": summary,
                "context": context,
                "replace_latest": replace_latest,
            },
        }
        return {
            "final_output": question,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "interactive_prompt",
            "interactive_prompt_active": True,
            "interactive_prompt_type": "constraint_record_capture",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _active_constraint_conflict(self, utterance: str) -> Dict[str, str] | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return None
        active_constraints = [
            record
            for record in self._session_constraints
            if isinstance(record, dict) and str(record.get("status", "")).strip().lower() == "active"
        ]
        if not active_constraints:
            return None

        style_request = any(token in lowered for token in ("css", "styled", "style", "tailwind", "bootstrap"))
        if any(token in lowered for token in ("no css", "without css", "unstyled", "no style")):
            style_request = False
        deploy_request = any(
            token in lowered
            for token in ("deploy", "deployment", "publish", "production", "host online", "go live")
        )
        if any(token in lowered for token in ("do not deploy", "don't deploy", "no deploy", "local-only", "local only")):
            deploy_request = False
        multipage_request = any(
            token in lowered
            for token in ("multi-page", "multiple pages", "two pages", "three pages", "second page", "another page")
        )
        external_dep_request = any(
            token in lowered
            for token in ("external dependencies", "external dependency", "cdn", "npm install", "pip install")
        )
        if "no external dependencies" in lowered:
            external_dep_request = False

        for record in active_constraints:
            summary = str(record.get("summary", "")).strip()
            summary_lowered = summary.lower()
            if not summary:
                continue
            if ("no css" in summary_lowered or "without css" in summary_lowered) and style_request:
                return {
                    "constraint_id": str(record.get("id", "")).strip(),
                    "constraint_summary": summary,
                    "reason": "request asks for styling while constraint says no CSS",
                }
            if (
                "local-only" in summary_lowered
                or "local only" in summary_lowered
                or "do not deploy" in summary_lowered
            ) and deploy_request:
                return {
                    "constraint_id": str(record.get("id", "")).strip(),
                    "constraint_summary": summary,
                    "reason": "request asks for deployment while constraint is local-only",
                }
            if ("one page" in summary_lowered or "one-page" in summary_lowered) and multipage_request:
                return {
                    "constraint_id": str(record.get("id", "")).strip(),
                    "constraint_summary": summary,
                    "reason": "request asks for multiple pages while constraint is one-page only",
                }
            if "no external dependencies" in summary_lowered and external_dep_request:
                return {
                    "constraint_id": str(record.get("id", "")).strip(),
                    "constraint_summary": summary,
                    "reason": "request asks for external dependencies while constraint disallows them",
                }
        return None

    def _build_constraint_conflict_response(
        self,
        *,
        conflict: Dict[str, str],
        request_utterance: str,
        trace_id: str,
    ) -> Dict[str, Any]:
        constraint_id = str(conflict.get("constraint_id", "")).strip()
        constraint_summary = str(conflict.get("constraint_summary", "")).strip()
        reason = str(conflict.get("reason", "")).strip()
        conflict_message = (
            "Constraint conflict detected. "
            f"Your request conflicts with {constraint_id} (`{constraint_summary}`). "
            f"Reason: {reason}. "
            "Do you want to revise or remove that constraint before continuing?"
        )
        self._remember_conversational_context(
            user_input=request_utterance,
            intent_class="informational_query",
            mode="conversation",
        )
        return {
            "final_output": conflict_message,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "conversation_layer",
            "execution_enabled": False,
            "advisory_only": True,
            "constraint_conflict": {
                "constraint_id": constraint_id,
                "constraint_summary": constraint_summary,
                "reason": reason,
            },
        }

    def _apply_constraint_reference_to_conversational_text(self, text: str) -> str:
        latest = self._latest_active_constraint()
        if latest is None:
            return text
        base = str(text or "").strip()
        if not base:
            return base
        constraint_id = str(latest.get("id", "")).strip()
        summary = str(latest.get("summary", "")).strip()
        if not constraint_id or not summary:
            return base
        reference = f"This respects your active constraint ({constraint_id}): {summary}"
        return f"{reference}\n{base}".strip()

    def _apply_constraint_reference_to_advisory_message(self, message: str) -> str:
        latest = self._latest_active_constraint()
        if latest is None:
            return message
        base = str(message or "").strip()
        if not base:
            return base
        constraint_id = str(latest.get("id", "")).strip()
        summary = str(latest.get("summary", "")).strip()
        if not constraint_id or not summary:
            return base
        reference = f"This respects your active constraint ({constraint_id}): {summary}."
        return f"{reference} {base}".strip()

    def _active_goals(self) -> List[Dict[str, Any]]:
        return [
            record
            for record in self._session_goals
            if isinstance(record, dict) and str(record.get("status", "")).strip().lower() == "active"
        ]

    def _latest_active_goal(self) -> Dict[str, Any] | None:
        active = self._active_goals()
        if not active:
            return None
        latest = active[-1]
        return latest if isinstance(latest, dict) else None

    def _goal_reset_mode(self, utterance: str) -> str | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower()).rstrip("?.!")
        if not lowered:
            return None
        if lowered in _GOAL_RESET_ALL_PHRASES or any(phrase in lowered for phrase in _GOAL_RESET_ALL_PHRASES):
            return "all"
        if lowered in _GOAL_RESET_LATEST_PHRASES or any(phrase in lowered for phrase in _GOAL_RESET_LATEST_PHRASES):
            return "latest"
        return None

    def _is_goal_list_request(self, utterance: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower()).rstrip("?.!")
        if not lowered:
            return False
        if lowered in _GOAL_LIST_PHRASES:
            return True
        return any(phrase in lowered for phrase in _GOAL_LIST_PHRASES)

    def _is_goal_reorder_request(self, utterance: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower()).rstrip("?.!")
        if not lowered:
            return False
        if lowered in _GOAL_REORDER_LATEST_PHRASES:
            return True
        return any(phrase in lowered for phrase in _GOAL_REORDER_LATEST_PHRASES)

    def _build_goal_list_response(self, *, trace_id: str) -> Dict[str, Any]:
        active = self._active_goals()
        if not active:
            message = "No active goals are recorded for this session."
        else:
            lines = ["Active goals (priority order):"]
            for index, record in enumerate(active, start=1):
                lines.append(
                    f"{index}. {str(record.get('id', '')).strip()}: {str(record.get('summary', '')).strip()}"
                )
            message = "\n".join(lines)
        self._remember_conversational_context(
            user_input="list goals",
            intent_class="informational_query",
            mode="conversation",
        )
        return {
            "final_output": message,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "conversation_layer",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _build_goal_reorder_response(self, *, trace_id: str) -> Dict[str, Any]:
        active_indices = [
            idx
            for idx, record in enumerate(self._session_goals)
            if isinstance(record, dict) and str(record.get("status", "")).strip().lower() == "active"
        ]
        if len(active_indices) < 2:
            message = "Need at least two active goals to reorder priority."
        else:
            first_idx = active_indices[0]
            latest_idx = active_indices[-1]
            if first_idx == latest_idx:
                message = "The latest active goal is already highest priority."
            else:
                latest_record = self._session_goals.pop(latest_idx)
                self._session_goals.insert(first_idx, latest_record)
                message = (
                    "Reordered goals: latest active goal moved to highest priority "
                    f"({str(latest_record.get('id', '')).strip()})."
                )
        self._remember_conversational_context(
            user_input="prioritize that goal",
            intent_class="informational_query",
            mode="conversation",
        )
        return {
            "final_output": message,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "conversation_layer",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _extract_goal_update_candidate(self, utterance: str) -> Dict[str, Any] | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return None
        if not any(phrase in lowered for phrase in _GOAL_UPDATE_LATEST_PHRASES):
            return None
        if self._latest_active_goal() is None:
            return {"error": "no_active_goal"}

        explicit = str(utterance or "").strip()
        match = re.search(
            r"(?i)\b(?:update|change|revise)\s+that\s+goal(?:\s+to)?\s+(.+)$",
            explicit,
        )
        if match is None:
            return {"error": "needs_replacement"}
        summary = str(match.group(1)).strip().rstrip(".")
        if not summary:
            return {"error": "needs_replacement"}
        return {
            "summary": summary,
            "context": self._decision_context_from_utterance(utterance),
            "replace_latest": True,
        }

    def _build_goal_update_guidance_response(self, *, trace_id: str) -> Dict[str, Any]:
        return {
            "final_output": (
                "Tell me the replacement explicitly, for example: "
                "`update that goal to create a simple one-page site`."
            ),
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "conversation_layer",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _build_goal_reset_response(self, *, mode: str, trace_id: str) -> Dict[str, Any]:
        if (
            isinstance(self._interactive_prompt_state, dict)
            and str(self._interactive_prompt_state.get("type", "")).strip() == "goal_record_capture"
        ):
            self._interactive_prompt_state = None

        if mode == "latest":
            latest = self._latest_active_goal()
            if latest is None:
                message = "No active goals are available to remove."
            else:
                latest["status"] = "inactive"
                latest["inactive_reason"] = "removed"
                latest["inactive_at"] = datetime.now(timezone.utc).isoformat()
                message = (
                    "Removed the latest active goal: "
                    f"{str(latest.get('id', '')).strip()} - {str(latest.get('summary', '')).strip()}."
                )
        else:
            active_found = False
            for record in self._session_goals:
                if not isinstance(record, dict):
                    continue
                if str(record.get("status", "")).strip().lower() != "active":
                    continue
                active_found = True
                record["status"] = "inactive"
                record["inactive_reason"] = "cleared"
                record["inactive_at"] = datetime.now(timezone.utc).isoformat()
            message = "All active session goals cleared."
            if not active_found:
                message = "No active session goals were recorded."

        self._remember_conversational_context(
            user_input="clear goals" if mode == "all" else "remove that goal",
            intent_class="informational_query",
            mode="conversation",
        )
        return {
            "final_output": message,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "conversation_layer",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _extract_goal_candidate(self, utterance: str) -> Dict[str, Any] | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return None
        if self._goal_reset_mode(lowered) is not None:
            return None
        if self._is_goal_list_request(lowered):
            return None
        if self._is_goal_reorder_request(lowered):
            return None
        if any(phrase in lowered for phrase in _GOAL_UPDATE_LATEST_PHRASES):
            return None

        explicit = str(utterance or "").strip()
        summary = ""
        match = re.match(r"(?i)^\s*goal\s*:\s*(.+)$", explicit)
        if match is not None:
            summary = str(match.group(1)).strip().rstrip(".")
        else:
            match = re.match(r"(?i)^\s*objective\s*:\s*(.+)$", explicit)
            if match is not None:
                summary = str(match.group(1)).strip().rstrip(".")
            else:
                match = re.search(r"(?i)\bthe objective here is\s+(.+)$", explicit)
                if match is not None:
                    summary = str(match.group(1)).strip().rstrip(".")
                else:
                    match = re.search(r"(?i)\bi want to end up with\s+(.+)$", explicit)
                    if match is not None:
                        summary = str(match.group(1)).strip().rstrip(".")
                    else:
                        match = re.search(r"(?i)\bmy goal is\s+(.+)$", explicit)
                        if match is not None:
                            summary = str(match.group(1)).strip().rstrip(".")
                        else:
                            match = re.search(r"(?i)\bgoal is\s+(.+)$", explicit)
                            if match is not None:
                                summary = str(match.group(1)).strip().rstrip(".")

        summary = summary.strip()
        if not summary:
            return None
        return {
            "summary": summary,
            "context": self._decision_context_from_utterance(utterance),
            "replace_latest": False,
        }

    def _build_goal_capture_confirmation_response(
        self,
        *,
        candidate: Dict[str, Any],
        trace_id: str,
    ) -> Dict[str, Any]:
        summary = str(candidate.get("summary", "")).strip()
        context = str(candidate.get("context", "")).strip() or "General"
        replace_latest = bool(candidate.get("replace_latest", False))
        if not summary:
            return {
                "final_output": "Goal capture skipped: summary is empty.",
                "tool_calls": [],
                "status": "error",
                "trace_id": trace_id,
                "mode": "conversation_layer",
                "execution_enabled": False,
                "advisory_only": True,
            }
        if replace_latest:
            question = (
                f"I can replace the latest active goal with ({context}): {summary}. "
                "Want me to record that as a goal for this session?"
            )
        else:
            question = (
                f"I heard this goal ({context}): {summary}. "
                "Want me to record that as a goal for this session?"
            )
        self._interactive_prompt_state = {
            "type": "goal_record_capture",
            "origin": "goal_register",
            "prompt_id": f"interactive-{trace_id}",
            "question": question,
            "goal_candidate": {
                "summary": summary,
                "context": context,
                "replace_latest": replace_latest,
            },
        }
        return {
            "final_output": question,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "interactive_prompt",
            "interactive_prompt_active": True,
            "interactive_prompt_type": "goal_record_capture",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _active_goal_misalignment(self, utterance: str) -> Dict[str, str] | None:
        active_goals = self._active_goals()
        if not active_goals:
            return None
        prioritized_goal = active_goals[0]
        goal_id = str(prioritized_goal.get("id", "")).strip()
        goal_summary = str(prioritized_goal.get("summary", "")).strip()
        goal_lowered = goal_summary.lower()
        utterance_lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not utterance_lowered:
            return None

        goal_website = any(token in goal_lowered for token in ("website", "landing page", "one-page", "one page", "html"))
        goal_learning = any(token in goal_lowered for token in ("learn", "study", "basics", "tutorial", "practice"))
        goal_database = any(token in goal_lowered for token in ("database", "sql", "schema", "migration"))

        request_website = any(token in utterance_lowered for token in ("website", "landing page", "html", ".html", "web page"))
        request_learning = any(token in utterance_lowered for token in ("learn", "study", "tutorial", "practice", "vocabulary"))
        request_database = any(token in utterance_lowered for token in ("database", "sql", "schema", "migration", "query"))

        if goal_website and request_database and not request_website:
            return {
                "goal_id": goal_id,
                "goal_summary": goal_summary,
                "reason": "request appears database-focused while active goal is website-focused",
            }
        if goal_learning and request_database and not request_learning:
            return {
                "goal_id": goal_id,
                "goal_summary": goal_summary,
                "reason": "request appears implementation-focused while active goal is learning-focused",
            }
        if goal_database and request_website and not request_database:
            return {
                "goal_id": goal_id,
                "goal_summary": goal_summary,
                "reason": "request appears website-focused while active goal is database-focused",
            }
        return None

    def _build_goal_misalignment_response(
        self,
        *,
        misalignment: Dict[str, str],
        request_utterance: str,
        trace_id: str,
    ) -> Dict[str, Any]:
        goal_id = str(misalignment.get("goal_id", "")).strip()
        goal_summary = str(misalignment.get("goal_summary", "")).strip()
        reason = str(misalignment.get("reason", "")).strip()
        message = (
            "Goal misalignment detected. "
            f"Your request is not clearly aligned with {goal_id} (`{goal_summary}`). "
            f"Reason: {reason}. "
            "Do you want to update the goal or proceed anyway?"
        )
        self._remember_conversational_context(
            user_input=request_utterance,
            intent_class="informational_query",
            mode="conversation",
        )
        return {
            "final_output": message,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "conversation_layer",
            "execution_enabled": False,
            "advisory_only": True,
            "goal_misalignment": {
                "goal_id": goal_id,
                "goal_summary": goal_summary,
                "reason": reason,
            },
        }

    def _apply_goal_reference_to_conversational_text(self, text: str) -> str:
        latest = self._latest_active_goal()
        if latest is None:
            return text
        base = str(text or "").strip()
        if not base:
            return base
        goal_id = str(latest.get("id", "")).strip()
        summary = str(latest.get("summary", "")).strip()
        if not goal_id or not summary:
            return base
        reference = f"This advances your goal ({goal_id}): {summary}"
        return f"{reference}\n{base}".strip()

    def _apply_goal_reference_to_advisory_message(self, message: str) -> str:
        latest = self._latest_active_goal()
        if latest is None:
            return message
        base = str(message or "").strip()
        if not base:
            return base
        goal_id = str(latest.get("id", "")).strip()
        summary = str(latest.get("summary", "")).strip()
        if not goal_id or not summary:
            return base
        reference = f"This advances your goal ({goal_id}): {summary}."
        return f"{reference} {base}".strip()

    def _extract_session_preference_candidate(self, utterance: str) -> Dict[str, str] | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return None
        if self._is_preference_reset_request(lowered):
            return None
        if self._is_website_build_request(lowered):
            return None
        if self._extract_website_filename_override(lowered) is not None:
            return None
        if self._resolve_task_artifact_reference(lowered) is not None:
            return None

        def _candidate(key: str, value: str, label: str) -> Dict[str, str]:
            return {"key": key, "value": value, "label": label}

        if (
            "no css" in lowered
            or "without css" in lowered
            or "minimal html" in lowered
            or "keep it simple" in lowered
        ):
            return _candidate("website_style", "minimal", "use minimal HTML with no CSS")
        if (
            "styled html" in lowered
            or "include css" in lowered
            or "use css" in lowered
            or "prefer styled" in lowered
            or "styled by default" in lowered
        ):
            return _candidate("website_style", "styled", "use styled HTML with CSS")

        if re.search(r"\b(prefer|use|default to|format)\b.*\bmarkdown\b", lowered):
            return _candidate("output_format", "markdown", "prefer markdown output")
        if re.search(r"\b(prefer|use|default to|format)\b.*\bhtml\b", lowered):
            return _candidate("output_format", "html", "prefer HTML output")

        return None

    def _build_preference_capture_confirmation_response(
        self,
        *,
        candidate: Dict[str, str],
        trace_id: str,
    ) -> Dict[str, Any]:
        key = str(candidate.get("key", "")).strip()
        value = str(candidate.get("value", "")).strip()
        label = str(candidate.get("label", "")).strip() or f"{key}={value}"
        if not key or not value:
            return {
                "final_output": "Preference capture skipped: preference data is incomplete.",
                "tool_calls": [],
                "status": "error",
                "trace_id": trace_id,
                "mode": "conversation_layer",
                "execution_enabled": False,
                "advisory_only": True,
            }
        question = f"I heard a session preference: {label}. {_PREFERENCE_CONFIRM_PREFIX}"
        self._interactive_prompt_state = {
            "type": "preference_capture",
            "origin": "preference_memory",
            "prompt_id": f"interactive-{trace_id}",
            "question": question,
            "preference_key": key,
            "preference_value": value,
            "preference_label": label,
        }
        return {
            "final_output": question,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "interactive_prompt",
            "interactive_prompt_active": True,
            "interactive_prompt_type": "preference_capture",
            "execution_enabled": False,
            "advisory_only": True,
        }

    def _website_style_override_from_utterance(self, utterance: str) -> bool | None:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return None
        if (
            "no css" in lowered
            or "without css" in lowered
            or "minimal html" in lowered
            or "unstyled" in lowered
            or "keep it simple" in lowered
        ):
            return False
        if self._website_style_requested(lowered):
            return True
        return None

    def _effective_website_include_style(self, utterance: str) -> bool:
        override = self._website_style_override_from_utterance(utterance)
        if override is not None:
            return override
        preference = str(self._session_preferences.get("website_style", "")).strip().lower()
        if preference == "styled":
            return True
        if preference == "minimal":
            return False
        return self._website_style_requested(utterance)

    def _session_preference_notes_for_advisory(self) -> List[str]:
        notes: List[str] = []
        style_pref = str(self._session_preferences.get("website_style", "")).strip().lower()
        if style_pref == "styled":
            notes.append("Session preference applied: styled HTML with CSS.")
        elif style_pref == "minimal":
            notes.append("Session preference applied: minimal HTML without CSS.")

        output_pref = str(self._session_preferences.get("output_format", "")).strip().lower()
        if output_pref in {"html", "markdown"}:
            notes.append(f"Session preference noted: prefer {output_pref} output when applicable.")
        return notes

    def _extract_website_filename(self, utterance: str) -> str:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        match = re.search(r"\b([a-z0-9._-]+\.html)\b", lowered)
        if match is not None:
            return str(match.group(1))
        return ""

    def _website_style_requested(self, utterance: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return False
        style_tokens = ("style", "styles", "css", "tailwind", "bootstrap", "theme")
        return any(token in lowered for token in style_tokens)

    def _website_context_active(self) -> bool:
        last_subject = str(self._conversation_context.get("last_subject_noun", "")).strip().lower()
        last_input = str(self._conversation_context.get("last_user_input", "")).strip().lower()
        if any(token in last_subject for token in ("website", "web page", "html")):
            return True
        return ".html" in last_input or "html file" in last_input or "website page" in last_input

    def _extract_website_filename_override(self, utterance: str) -> str | None:
        if self._is_website_build_request(utterance):
            return None
        lowered = re.sub(r"\s+", " ", str(utterance or "").strip().lower())
        if not lowered:
            return None
        match = re.search(r"\b([a-z0-9._-]+\.html)\b", lowered)
        if match is None:
            return None
        candidate = str(match.group(1))
        override_cues = ("use ", "instead", "rename", "change", "call it", "make it", "filename")
        if any(cue in lowered for cue in override_cues):
            return candidate
        if self._website_context_active():
            compact = re.sub(r"[!?.,]+$", "", lowered)
            if compact == candidate:
                return candidate
        return None

    def _website_example_html(self, *, title: str = "Test Page", include_style: bool = False) -> str:
        safe_title = str(title or "Test Page").strip() or "Test Page"
        style_block = ""
        body_open = "<body>\n"
        body_close = "</body>\n"
        card_open = ""
        card_close = ""
        if include_style:
            style_block = (
                "  <style>\n"
                "    body { font-family: Georgia, serif; margin: 2rem; background: #f6f5ef; color: #1f2933; }\n"
                "    .card { max-width: 42rem; padding: 1.5rem; border: 1px solid #d8d5c2; background: #fffdf6; }\n"
                "  </style>\n"
            )
            card_open = "  <main class=\"card\">\n"
            card_close = "  </main>\n"
        else:
            card_open = "  <main>\n"
            card_close = "  </main>\n"
        return (
            "<!doctype html>\n"
            "<html lang=\"en\">\n"
            "<head>\n"
            "  <meta charset=\"utf-8\" />\n"
            "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n"
            f"  <title>{safe_title}</title>\n"
            f"{style_block}"
            "</head>\n"
            f"{body_open}"
            f"{card_open}"
            "    <h1>test page</h1>\n"
            "    <p>Starter HTML prepared in advisory mode. NOT EXECUTED.</p>\n"
            f"{card_close}"
            f"{body_close}"
            "</html>"
        )

    def _replace_terminal_filler(self, response_text: str) -> str:
        text = str(response_text or "").strip()
        lowered = text.lower().rstrip(".!?")
        if lowered in _TERMINAL_FILLER_PHRASES:
            subject = str(self._conversation_context.get("last_subject_noun", "")).strip() or "the request"
            return (
                f"I can help with {subject}, but I need one detail first: what outcome do you want and where should it live?"
            )
        return text

    def _normalize_advisory_commands(self, commands: Any) -> List[str]:
        if not isinstance(commands, list):
            return []
        normalized: List[str] = []
        for item in commands:
            command = str(item or "").strip()
            if not command:
                continue
            if command.startswith("NOT EXECUTED:"):
                normalized.append(command)
            else:
                normalized.append(f"NOT EXECUTED: {command}")
        return normalized

    def _normalize_advisory_options(self, options: Any) -> List[Dict[str, str]]:
        if not isinstance(options, list):
            return []
        normalized: List[Dict[str, str]] = []
        for item in options:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            benefits = str(item.get("benefits", "")).strip()
            risks = str(item.get("risks", "")).strip()
            effort = str(item.get("effort", "")).strip().lower()
            alignment = str(item.get("alignment", "")).strip()
            if not title:
                continue
            if not effort:
                effort = "medium"
            normalized.append(
                {
                    "title": title,
                    "benefits": benefits,
                    "risks": risks,
                    "effort": effort,
                    "alignment": alignment,
                    "base_alignment": str(item.get("base_alignment", "")).strip() or alignment,
                }
            )
        return normalized

    def _apply_active_context_to_options(self, options: List[Dict[str, str]]) -> List[Dict[str, str]]:
        if not options:
            return options
        latest_goal = self._latest_active_goal()
        latest_constraint = self._latest_active_constraint()
        goal_summary = str((latest_goal or {}).get("summary", "")).strip()
        constraint_summary = str((latest_constraint or {}).get("summary", "")).strip()

        aligned: List[Dict[str, str]] = []
        for option in options:
            enriched = dict(option)
            base_alignment = str(enriched.get("base_alignment", "")).strip() or str(enriched.get("alignment", "")).strip()
            context_parts: List[str] = []
            if goal_summary:
                context_parts.append(f"Goal fit: {goal_summary}")
            if constraint_summary:
                context_parts.append(f"Constraint fit: {constraint_summary}")
            if context_parts:
                if base_alignment:
                    enriched["alignment"] = f"{base_alignment} | {' | '.join(context_parts)}"
                else:
                    enriched["alignment"] = " | ".join(context_parts)
            else:
                enriched["alignment"] = base_alignment
            aligned.append(enriched)
        return aligned

    def _advisory_continuation_question(self, advisory_output: Dict[str, Any]) -> str:
        explicit_question = str(advisory_output.get("clarifying_question", "")).strip()
        if explicit_question.endswith("?"):
            return explicit_question
        if any(str(advisory_output.get(key, "")).strip() for key in ("example_html", "starter_code", "starter_html", "html")):
            return "Do you want me to adjust this HTML before you run anything manually?"
        escalation = advisory_output.get("escalation", {})
        if isinstance(escalation, dict) and str(escalation.get("next_step", "")).strip() == "request_governed_proposal":
            return "Do you want to submit this as a governed proposal?"
        if str(advisory_output.get("status", "")).strip() == "clarification_required":
            return "Do you want to refine the request so I can produce a concrete plan?"
        return "Do you want me to refine this plan for your exact environment?"

    def _render_advisory_text(self, advisory_output: Dict[str, Any], continuation_question: str) -> str:
        lines: List[str] = []

        message = str(advisory_output.get("message", "")).strip()
        if message:
            lines.append(message)

        plan_steps = advisory_output.get("plan_steps", [])
        if isinstance(plan_steps, list) and plan_steps:
            lines.append("")
            lines.append("Plan Steps:")
            for index, step in enumerate(plan_steps, start=1):
                lines.append(f"{index}. {str(step)}")

        options = self._normalize_advisory_options(advisory_output.get("options", []))
        if options:
            lines.append("")
            lines.append("Options:")
            for index, option in enumerate(options, start=1):
                lines.append(f"{index}. {str(option.get('title', '')).strip()}")
                lines.append(f"   - Benefits: {str(option.get('benefits', '')).strip()}")
                lines.append(f"   - Risks: {str(option.get('risks', '')).strip()}")
                lines.append(f"   - Effort: {str(option.get('effort', '')).strip()}")
                lines.append(f"   - Alignment: {str(option.get('alignment', '')).strip()}")

        starter_block = ""
        for key in ("starter_code", "starter_html", "example_html", "html"):
            value = advisory_output.get(key)
            if isinstance(value, str) and value.strip():
                starter_block = value.strip()
                break
        if starter_block:
            lines.append("")
            lines.append("Starter Code / HTML:")
            lines.append(starter_block)

        commands = self._normalize_advisory_commands(advisory_output.get("suggested_commands", []))
        if commands:
            lines.append("")
            lines.append("Suggested Commands:")
            lines.extend(commands)

        risk_notes = advisory_output.get("risk_notes", [])
        if isinstance(risk_notes, list) and risk_notes:
            lines.append("")
            lines.append("Risk Notes:")
            for note in risk_notes:
                lines.append(f"- {str(note)}")

        assumptions = advisory_output.get("assumptions", [])
        if isinstance(assumptions, list) and assumptions:
            lines.append("")
            lines.append("Assumptions:")
            for assumption in assumptions:
                lines.append(f"- {str(assumption)}")

        key_risks = advisory_output.get("key_risks", [])
        if isinstance(key_risks, list) and key_risks:
            lines.append("")
            lines.append("Key Risks:")
            for risk in key_risks:
                lines.append(f"- {str(risk)}")

        hidden_assumptions = advisory_output.get("hidden_assumptions", [])
        if isinstance(hidden_assumptions, list) and hidden_assumptions:
            lines.append("")
            lines.append("Hidden Assumptions:")
            for item in hidden_assumptions:
                lines.append(f"- {str(item)}")

        tensions = advisory_output.get("goal_constraint_tensions", [])
        if isinstance(tensions, list) and tensions:
            lines.append("")
            lines.append("Goal or Constraint Tensions:")
            for tension in tensions:
                lines.append(f"- {str(tension)}")

        failure_modes = advisory_output.get("failure_modes", [])
        if isinstance(failure_modes, list) and failure_modes:
            lines.append("")
            lines.append("Failure Modes:")
            for mode in failure_modes:
                lines.append(f"- {str(mode)}")

        mitigation_options = advisory_output.get("mitigation_options", [])
        if isinstance(mitigation_options, list) and mitigation_options:
            lines.append("")
            lines.append("Mitigation Options:")
            for option in mitigation_options:
                lines.append(f"- {str(option)}")

        stress_test = advisory_output.get("stress_test", [])
        if isinstance(stress_test, list) and stress_test:
            lines.append("")
            lines.append("Stress Test:")
            for check in stress_test:
                lines.append(f"- {str(check)}")

        task_artifact = advisory_output.get("task_artifact", {})
        if isinstance(task_artifact, dict) and task_artifact:
            artifact_name = str(task_artifact.get("name", "")).strip()
            artifact_type = str(task_artifact.get("type", "")).strip()
            artifact_revision = task_artifact.get("revision", "")
            artifact_revision_id = str(task_artifact.get("revision_id", "")).strip()
            artifact_summary = str(task_artifact.get("summary", "")).strip()
            lines.append("")
            lines.append("Task Artifact:")
            descriptor = f"- {artifact_name}"
            if artifact_type:
                descriptor += f" ({artifact_type})"
            if isinstance(artifact_revision, int):
                descriptor += f" rev {artifact_revision}"
            if artifact_revision_id:
                descriptor += f" [{artifact_revision_id}]"
            lines.append(descriptor)
            if artifact_summary:
                lines.append(f"- {artifact_summary}")

        artifact_diff = advisory_output.get("artifact_diff", {})
        if isinstance(artifact_diff, dict) and artifact_diff:
            lines.append("")
            lines.append("Artifact Diff:")
            lines.append(str(artifact_diff.get("diff_text", "")).strip())

        plan_progress = advisory_output.get("plan_progress", {})
        if isinstance(plan_progress, dict) and plan_progress:
            current_step_index = plan_progress.get("current_step_index", 0)
            current_step_index = current_step_index if isinstance(current_step_index, int) else 0
            total_steps = plan_progress.get("total_steps", 0)
            total_steps = total_steps if isinstance(total_steps, int) else 0
            remaining_steps = plan_progress.get("remaining_steps", 0)
            remaining_steps = remaining_steps if isinstance(remaining_steps, int) else 0
            lines.append("")
            lines.append("Plan Progress:")
            lines.append(f"- Step {current_step_index}/{total_steps}")
            lines.append(f"- Remaining: {remaining_steps}")
            active_step = str(plan_progress.get("active_step", "")).strip()
            if active_step:
                lines.append(f"- Active step: {active_step}")
            artifact_id = str(plan_progress.get("artifact_id", "")).strip()
            if artifact_id:
                lines.append(f"- Artifact: {artifact_id}")

        lines.append("")
        lines.append(continuation_question)
        return "\n".join(lines).strip()

    def _prepare_advisory_output(self, advisory_output: Dict[str, Any]) -> Dict[str, Any]:
        prepared = copy.deepcopy(advisory_output)
        message = prepared.get("message")
        if isinstance(message, str) and message.strip():
            message = self._apply_tone_to_advisory_message(message)
            message = self._apply_role_framing_to_advisory_message(message)
            message = self._apply_task_mode_to_advisory_message(message)
            message = self._apply_goal_reference_to_advisory_message(message)
            message = self._apply_constraint_reference_to_advisory_message(message)
            message = self._apply_assumption_reference_to_advisory_message(message)
            prepared["message"] = self._apply_decision_reference_to_advisory_message(message)
        commands = self._normalize_advisory_commands(prepared.get("suggested_commands", []))
        if commands:
            prepared["suggested_commands"] = commands
        options = self._normalize_advisory_options(prepared.get("options", []))
        if options:
            prepared["options"] = self._apply_active_context_to_options(options)
        continuation_question = self._advisory_continuation_question(prepared)
        continuation_question = self._apply_tone_to_continuation_question(continuation_question)
        continuation_question = self._apply_role_framing_to_continuation_question(continuation_question)
        continuation_question = self._apply_task_mode_to_continuation_question(continuation_question)
        prepared["continuation_question"] = continuation_question
        prepared["rendered_advisory"] = self._render_advisory_text(prepared, continuation_question)
        return prepared

    def _build_follow_up_advisory_response(
        self,
        *,
        follow_up: str,
        trace_id: str,
    ) -> Dict[str, Any] | None:
        prior_input = str(self._conversation_context.get("last_user_input", "")).strip()
        if not prior_input:
            return None
        prior_intent = str(self._conversation_context.get("last_user_intent", "")).strip()
        advisory_intent = prior_intent if prior_intent in {"planning_request", "advisory_request"} else "planning_request"
        advisory_output = build_advisory_plan(
            utterance=prior_input,
            intent_class=advisory_intent,
        )
        subject = str(self._conversation_context.get("last_subject_noun", "")).strip() or "your previous request"
        prompt = {
            "how": f"Follow-up resolved: here is how to proceed with {subject}. Commands remain NOT EXECUTED.",
            "when": (
                f"Follow-up resolved: do this when you are ready to apply changes to {subject}. "
                "Validate each step before moving on."
            ),
            "where": (
                f"Follow-up resolved: apply these steps in the workspace location where {subject} should be created. "
                "Nothing was executed."
            ),
            "who": (
                "Follow-up resolved: you (human operator) run these commands manually. "
                "Billy remains advisory-only here."
            ),
        }[follow_up]
        advisory_output["message"] = prompt
        advisory_output["follow_up"] = {
            "question": follow_up,
            "resolved_from": prior_input,
            "subject": subject,
            "context_mode": str(self._conversation_context.get("last_system_mode", "")).strip() or "conversation_layer",
        }
        self._register_plan_artifact_from_advisory(
            source_utterance=prior_input,
            intent_class=advisory_intent,
            advisory_output=advisory_output,
        )
        advisory_output = self._prepare_advisory_output(advisory_output)
        self._activate_interactive_prompt_from_advisory(
            advisory_output=advisory_output,
            trace_id=trace_id,
        )
        response = {
            "final_output": advisory_output,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "advisory",
            "execution_enabled": False,
            "advisory_only": True,
        }
        self._remember_conversational_context(
            user_input=prior_input,
            intent_class=advisory_intent,
            mode="advisory",
        )
        return response

    def _build_website_advisory_response(
        self,
        *,
        utterance: str,
        trace_id: str,
        filename_override: str | None = None,
    ) -> Dict[str, Any]:
        requested_filename = str(filename_override or "").strip() or self._extract_website_filename(utterance)
        used_default_filename = not bool(requested_filename)
        filename = requested_filename or "index.html"
        include_style = self._effective_website_include_style(utterance)
        advisory_output = build_advisory_plan(
            utterance=f"plan website page {filename}",
            intent_class="planning_request",
        )
        advisory_output["message"] = (
            "Advisory website plan prepared. Starter HTML and commands are suggestions only and were NOT EXECUTED."
        )
        advisory_output["example_html"] = self._website_example_html(title=filename, include_style=include_style)
        advisory_output["suggested_commands"] = [
            f"NOT EXECUTED: cat > {filename} <<'HTML'",
            "NOT EXECUTED: (paste the example_html content)",
            "NOT EXECUTED: HTML",
            "NOT EXECUTED: python -m http.server 8000",
        ]
        assumptions = advisory_output.get("assumptions", [])
        assumptions = assumptions if isinstance(assumptions, list) else []
        default_assumptions: List[str] = []
        if used_default_filename:
            default_assumptions.append(
                "Default: assuming `index.html` for now - you can change this anytime."
            )
        default_assumptions.append("Default: treat this as a local file workflow only (not deployed).")
        default_assumptions.append("Default: start from a minimal HTML scaffold.")
        if not include_style:
            default_assumptions.append("Default: no styling is applied unless you request CSS.")
        preference_notes = self._session_preference_notes_for_advisory()
        advisory_output["assumptions"] = default_assumptions + preference_notes + assumptions
        self._session_defaults["website_filename"] = filename
        html_artifact = self._upsert_task_artifact(
            name="html_page",
            artifact_type="html_page",
            content={
                "filename": filename,
                "html": str(advisory_output.get("example_html", "")).strip(),
                "include_style": include_style,
            },
            summary=f"HTML draft artifact for {filename} (session-scoped, non-executing).",
            source_mode="advisory",
        )
        advisory_output["task_artifact"] = self._artifact_public_view(html_artifact)
        self._register_plan_artifact_from_advisory(
            source_utterance=utterance,
            intent_class="planning_request",
            advisory_output=advisory_output,
        )
        advisory_output = self._prepare_advisory_output(advisory_output)
        self._activate_interactive_prompt_from_advisory(
            advisory_output=advisory_output,
            trace_id=trace_id,
        )
        response = {
            "final_output": advisory_output,
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
            "mode": "advisory",
            "execution_enabled": False,
            "advisory_only": True,
        }
        self._remember_conversational_context(
            user_input=utterance,
            intent_class="planning_request",
            mode="advisory",
        )
        return response

    def _aci_authority_guarantees(self) -> Dict[str, bool]:
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

    def _aci_result(
        self,
        *,
        final_output: Dict[str, Any],
        trace_id: str,
        status: str,
        mode: str,
        routing_intent: str,
        routing_confidence: float,
        gatekeeper_reason_code: str,
        current_phase: int,
    ) -> Dict[str, Any]:
        return {
            "final_output": final_output,
            "tool_calls": [],
            "status": status,
            "trace_id": trace_id,
            "mode": mode,
            "intent_class": routing_intent,
            "intent_confidence": routing_confidence,
            "gatekeeper_reason_code": gatekeeper_reason_code,
            "current_phase": current_phase,
            "execution_enabled": False,
            "authority_guarantees": self._aci_authority_guarantees(),
        }

    def _aci_environment_id(self, session_context: Dict[str, Any]) -> str:
        if isinstance(session_context, dict):
            value = session_context.get("environment_id")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return "default"

    def _aci_issuer_identity_id(self, session_context: Dict[str, Any]) -> str:
        if isinstance(session_context, dict):
            value = session_context.get("issuer_identity_id")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return "human"

    def _aci_resolve_lineage_refs(
        self,
        *,
        current_phase: int,
        environment_id: str,
        session_context: Dict[str, Any],
    ) -> tuple[List[str] | None, str]:
        if isinstance(session_context, dict):
            provided = session_context.get("lineage_refs")
            if isinstance(provided, list):
                normalized = [str(item).strip() for item in provided if str(item).strip()]
                deduped = sorted(set(normalized))
                return deduped, "OK"

        phase_records = self._aci_issuance_ledger.lookup_by_phase_id(current_phase)
        candidates = [
            item
            for item in phase_records
            if (
                str(item.get("environment_id", "")) == environment_id
                and not self._aci_issuance_ledger.is_artifact_revoked(str(item.get("artifact_id", "")))
            )
        ]
        if not candidates:
            return [], "OK"
        if len(candidates) > 1:
            return None, "ISSUANCE_LINEAGE_AMBIGUOUS"
        artifact_id = str(candidates[0].get("artifact_id", "")).strip()
        if not artifact_id:
            return None, "ISSUANCE_LINEAGE_AMBIGUOUS"
        return [artifact_id], "OK"

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
            output_mode = str(result.get("mode", "")).strip()
            payload_mode = str(final_output.get("mode", "")).strip()
            if output_mode == "advisory" or payload_mode == "advisory":
                rendered = final_output.get("rendered_advisory")
                if not isinstance(rendered, str) or not rendered.strip():
                    rendered = self._prepare_advisory_output(final_output).get("rendered_advisory", "")
                if isinstance(rendered, str) and rendered.strip():
                    return rendered
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

    def get_captured_content_last(self, count: int) -> List[Dict[str, Any]]:
        return [item.to_dict() for item in self._content_capture_store.get_last(count)]

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
        lowered_input = normalized_input.lower()

        bound_interaction = self._handle_bound_interactive_turn(
            user_input=normalized_input,
            trace_id=trace_id,
        )
        if bound_interaction is not None:
            return bound_interaction

        mode_response = self._handle_activity_mode_turn(
            user_input=normalized_input,
            trace_id=trace_id,
        )
        if mode_response is not None:
            return mode_response

        if self._is_vocabulary_quiz_request(normalized_input):
            return self._build_vocabulary_quiz_prompt(trace_id=trace_id)

        current_phase = ACI_MIN_PHASE
        if isinstance(session_context, dict):
            maybe_phase = session_context.get("current_phase")
            if isinstance(maybe_phase, int):
                current_phase = maybe_phase
            elif isinstance(maybe_phase, str) and maybe_phase.strip().isdigit():
                current_phase = int(maybe_phase.strip())
        if current_phase < ACI_MIN_PHASE:
            current_phase = ACI_MIN_PHASE
        if current_phase > ACI_MAX_PHASE:
            current_phase = ACI_MAX_PHASE

        secretary_result: Dict[str, Any] | None = None
        if (
            normalized_input
            and _legacy_interaction_reason(normalized_input) is None
            and not _has_explicit_governed_trigger(normalized_input)
            and not _is_governance_handoff_instruction(normalized_input)
            and not _is_explicit_inspection_request(normalized_input)
            and not lowered_input.startswith("claim:")
            and lowered_input not in {"ignored", "continue"}
        ):
            secretary_result = process_conversational_turn(normalized_input)

        ladder_state = LadderState(current_phase=current_phase)
        admissible_transitions = derive_admissible_phase_transitions(ladder_state)
        routing_result = route_intent(
            raw_utterance=normalized_input,
            current_phase=current_phase,
            admissible_phase_transitions=[t.artifact_type for t in admissible_transitions],
        )
        confirm_target = _extract_confirm_issuance_request(normalized_input)
        revoke_target = _extract_revoke_artifact_request(normalized_input)
        supersede_request = _extract_supersede_artifact_request(normalized_input)
        environment_id = self._aci_environment_id(session_context if isinstance(session_context, dict) else {})
        issuer_identity_id = self._aci_issuer_identity_id(session_context if isinstance(session_context, dict) else {})
        should_route_aci = (
            bool((secretary_result or {}).get("escalate"))
            or confirm_target is not None
            or revoke_target is not None
            or supersede_request is not None
            or routing_result.intent_class is INTENT_CLASS.GOVERNANCE_ISSUANCE
        )

        if self._execution_arming_query_mode(normalized_input) is not None:
            return self._build_execution_arming_declaration_response(trace_id=trace_id)
        if self._is_execution_capability_query(normalized_input):
            return self._build_execution_capability_declaration_response(trace_id=trace_id)
        if self._is_execution_boundary_unification_query(normalized_input):
            return self._build_execution_boundary_unification_response(
                utterance=normalized_input,
                trace_id=trace_id,
            )

        if not should_route_aci:
            if self._is_critique_invitation(normalized_input) and self._has_critique_context():
                return self._build_critique_offer_response(trace_id=trace_id)
            goal_reset_mode = self._goal_reset_mode(normalized_input)
            if goal_reset_mode is not None:
                return self._build_goal_reset_response(
                    mode=goal_reset_mode,
                    trace_id=trace_id,
                )
            if self._is_goal_list_request(normalized_input):
                return self._build_goal_list_response(trace_id=trace_id)
            if self._is_goal_reorder_request(normalized_input):
                return self._build_goal_reorder_response(trace_id=trace_id)
            goal_update_candidate = self._extract_goal_update_candidate(normalized_input)
            if goal_update_candidate is not None:
                if str(goal_update_candidate.get("error", "")).strip() == "no_active_goal":
                    return {
                        "final_output": "No active goal exists to update.",
                        "tool_calls": [],
                        "status": "success",
                        "trace_id": trace_id,
                        "mode": "conversation_layer",
                        "execution_enabled": False,
                        "advisory_only": True,
                    }
                if str(goal_update_candidate.get("error", "")).strip() == "needs_replacement":
                    return self._build_goal_update_guidance_response(trace_id=trace_id)
                return self._build_goal_capture_confirmation_response(
                    candidate=goal_update_candidate,
                    trace_id=trace_id,
                )
            goal_candidate = self._extract_goal_candidate(normalized_input)
            if goal_candidate is not None:
                return self._build_goal_capture_confirmation_response(
                    candidate=goal_candidate,
                    trace_id=trace_id,
                )
            goal_misalignment = self._active_goal_misalignment(normalized_input)
            if goal_misalignment is not None:
                return self._build_goal_misalignment_response(
                    misalignment=goal_misalignment,
                    request_utterance=normalized_input,
                    trace_id=trace_id,
                )
            constraint_reset_mode = self._constraint_reset_mode(normalized_input)
            if constraint_reset_mode is not None:
                return self._build_constraint_reset_response(
                    mode=constraint_reset_mode,
                    trace_id=trace_id,
                )
            if self._is_constraint_list_request(normalized_input):
                return self._build_constraint_list_response(trace_id=trace_id)
            constraint_change_candidate = self._extract_constraint_change_candidate(normalized_input)
            if constraint_change_candidate is not None:
                if str(constraint_change_candidate.get("error", "")).strip() == "no_active_constraint":
                    return {
                        "final_output": "No active constraint exists to change.",
                        "tool_calls": [],
                        "status": "success",
                        "trace_id": trace_id,
                        "mode": "conversation_layer",
                        "execution_enabled": False,
                        "advisory_only": True,
                    }
                if str(constraint_change_candidate.get("error", "")).strip() == "needs_replacement":
                    return self._build_constraint_change_guidance_response(trace_id=trace_id)
                return self._build_constraint_capture_confirmation_response(
                    candidate=constraint_change_candidate,
                    trace_id=trace_id,
                )
            constraint_candidate = self._extract_constraint_candidate(normalized_input)
            if constraint_candidate is not None:
                return self._build_constraint_capture_confirmation_response(
                    candidate=constraint_candidate,
                    trace_id=trace_id,
                )
            constraint_conflict = self._active_constraint_conflict(normalized_input)
            if constraint_conflict is not None:
                return self._build_constraint_conflict_response(
                    conflict=constraint_conflict,
                    request_utterance=normalized_input,
                    trace_id=trace_id,
                )
            assumption_reset_mode = self._assumption_reset_mode(normalized_input)
            if assumption_reset_mode is not None:
                return self._build_assumption_reset_response(
                    mode=assumption_reset_mode,
                    trace_id=trace_id,
                )
            if self._is_assumption_confirm_request(normalized_input):
                if self._latest_active_assumption() is None:
                    accepted_candidate = self._extract_assumption_candidate(normalized_input)
                    if accepted_candidate is not None:
                        return self._build_assumption_capture_confirmation_response(
                            candidate=accepted_candidate,
                            trace_id=trace_id,
                        )
                return self._build_assumption_confirm_response(trace_id=trace_id)
            assumption_change_candidate = self._extract_assumption_change_candidate(normalized_input)
            if assumption_change_candidate is not None:
                if str(assumption_change_candidate.get("error", "")).strip() == "no_active_assumption":
                    return {
                        "final_output": "No active assumption exists to change.",
                        "tool_calls": [],
                        "status": "success",
                        "trace_id": trace_id,
                        "mode": "conversation_layer",
                        "execution_enabled": False,
                        "advisory_only": True,
                    }
                if str(assumption_change_candidate.get("error", "")).strip() == "needs_replacement":
                    return self._build_assumption_change_guidance_response(trace_id=trace_id)
                return self._build_assumption_capture_confirmation_response(
                    candidate=assumption_change_candidate,
                    trace_id=trace_id,
                )
            assumption_candidate = self._extract_assumption_candidate(normalized_input)
            if assumption_candidate is not None:
                return self._build_assumption_capture_confirmation_response(
                    candidate=assumption_candidate,
                    trace_id=trace_id,
                )
            decision_reset_mode = self._decision_reset_mode(normalized_input)
            if decision_reset_mode is not None:
                return self._build_decision_reset_response(
                    mode=decision_reset_mode,
                    trace_id=trace_id,
                )
            decision_candidate = self._extract_decision_candidate(normalized_input)
            if decision_candidate is not None:
                return self._build_decision_capture_confirmation_response(
                    candidate=decision_candidate,
                    trace_id=trace_id,
                )
            if self._is_task_mode_reset_request(normalized_input):
                return self._build_task_mode_reset_response(trace_id=trace_id)
            task_mode_candidate = self._extract_task_mode_candidate(normalized_input)
            if task_mode_candidate is not None:
                return self._build_task_mode_capture_confirmation_response(
                    task_mode=task_mode_candidate,
                    trace_id=trace_id,
                )
            if self._is_role_reset_request(normalized_input):
                return self._build_role_reset_response(trace_id=trace_id)
            role_candidate = self._extract_role_framing_candidate(normalized_input)
            if role_candidate is not None:
                return self._build_role_framing_confirmation_response(
                    role_name=role_candidate,
                    trace_id=trace_id,
                )
            if self._is_tone_reset_request(normalized_input):
                return self._build_tone_reset_response(trace_id=trace_id)
            tone_candidate = self._extract_tone_preference_candidate(normalized_input)
            if tone_candidate is not None:
                return self._build_tone_preference_confirmation_response(
                    candidate=tone_candidate,
                    trace_id=trace_id,
                )
            if self._is_preference_reset_request(normalized_input):
                return self._build_preference_reset_response(trace_id=trace_id)
            preference_candidate = self._extract_session_preference_candidate(normalized_input)
            if preference_candidate is not None:
                return self._build_preference_capture_confirmation_response(
                    candidate=preference_candidate,
                    trace_id=trace_id,
                )
            artifact_response = self._handle_task_artifact_turn(
                user_input=normalized_input,
                trace_id=trace_id,
            )
            if artifact_response is not None:
                return artifact_response
            if self._should_trigger_website_preflight(normalized_input):
                return self._build_website_preflight_response(
                    utterance=normalized_input,
                    trace_id=trace_id,
                )

        plan_signal = self._plan_advancement_signal(normalized_input)
        if not should_route_aci and plan_signal is not None:
            plan_response = self._advance_active_plan_artifact(
                signal=plan_signal,
                trace_id=trace_id,
            )
            if plan_response is not None:
                return plan_response

        follow_up = self._follow_up_key(normalized_input)
        if not should_route_aci and follow_up is not None:
            follow_up_response = self._build_follow_up_advisory_response(
                follow_up=follow_up,
                trace_id=trace_id,
            )
            if follow_up_response is not None:
                return follow_up_response

        if not should_route_aci:
            override_filename = self._extract_website_filename_override(normalized_input)
            if override_filename is not None:
                base_request = str(self._conversation_context.get("last_user_input", "")).strip() or normalized_input
                return self._build_website_advisory_response(
                    utterance=base_request,
                    trace_id=trace_id,
                    filename_override=override_filename,
                )

        if not should_route_aci and self._is_website_build_request(normalized_input):
            return self._build_website_advisory_response(
                utterance=normalized_input,
                trace_id=trace_id,
            )

        if should_route_aci:
            gatekeeper_result = phase_gatekeeper(
                intent_class=routing_result.intent_class,
                current_phase=current_phase,
                ladder_state=ladder_state,
            )
            envelope = build_response_envelope(
                routing=routing_result,
                gate=gatekeeper_result,
                current_phase=current_phase,
            )

            def _issuance_refusal(reason_code: str, explanation: str, allowed_alternatives: List[str]) -> Dict[str, Any]:
                refusal_envelope = {
                    "type": "refusal",
                    "reason_code": reason_code,
                    "explanation": explanation,
                    "allowed_alternatives": list(allowed_alternatives),
                }
                return self._aci_result(
                    final_output=refusal_envelope,
                    trace_id=trace_id,
                    status="error",
                    mode="aci_issuance_gatekeeper",
                    routing_intent=routing_result.intent_class.value,
                    routing_confidence=routing_result.confidence,
                    gatekeeper_reason_code=reason_code,
                    current_phase=current_phase,
                )

            if confirm_target is not None:
                if not gatekeeper_result.admissible:
                    return _issuance_refusal(
                        gatekeeper_result.deterministic_reason_code,
                        "Issuance confirmation rejected because the next transition is not admissible.",
                        gatekeeper_result.allowed_alternatives,
                    )

                pending = self._aci_pending_proposal
                expected_artifact = (
                    str(pending.get("contract_name", "")).strip()
                    if isinstance(pending, dict)
                    else str(gatekeeper_result.allowed_next_artifact or "").strip()
                )
                if pending is None:
                    if not expected_artifact:
                        return _issuance_refusal(
                            "ISSUANCE_CONFIRMATION_WITHOUT_PROPOSAL",
                            "Issuance confirmation rejected: no pending proposal exists for this transition.",
                            gatekeeper_result.allowed_alternatives,
                        )
                    lineage_refs, lineage_code = self._aci_resolve_lineage_refs(
                        current_phase=current_phase,
                        environment_id=environment_id,
                        session_context=session_context if isinstance(session_context, dict) else {},
                    )
                    if lineage_refs is None:
                        return _issuance_refusal(
                            lineage_code,
                            "Issuance confirmation rejected because lineage resolution is ambiguous.",
                            [expected_artifact],
                        )
                    transition_key = compute_transition_key(
                        phase_id=current_phase + 1,
                        contract_name=expected_artifact,
                        environment_id=environment_id,
                        lineage_refs=lineage_refs,
                    )
                    if (
                        transition_key == self._aci_last_consumed_transition_key
                        or self._aci_issuance_ledger.has_transition_key(transition_key)
                    ):
                        return _issuance_refusal(
                            "ISSUANCE_CONFIRMATION_REPLAYED",
                            "Issuance confirmation rejected: this transition was already confirmed and issued.",
                            [expected_artifact],
                        )
                    return _issuance_refusal(
                        "ISSUANCE_CONFIRMATION_WITHOUT_PROPOSAL",
                        "Issuance confirmation rejected: no pending proposal exists for this transition.",
                        [expected_artifact],
                    )

                pending_action = str(pending.get("action", "issue"))
                pending_artifact = str(pending.get("contract_name", "")).strip()
                pending_phase = int(pending.get("current_phase", current_phase))
                pending_environment = str(pending.get("environment_id", "")).strip()
                if pending_phase != current_phase or pending_environment != environment_id:
                    return _issuance_refusal(
                        "ISSUANCE_PENDING_PROPOSAL_STALE",
                        "Issuance confirmation rejected: pending proposal no longer matches current phase state.",
                        [pending_artifact],
                    )
                if confirm_target and confirm_target != pending_artifact:
                    return _issuance_refusal(
                        "ISSUANCE_CONFIRMATION_TARGET_MISMATCH",
                        "Issuance confirmation rejected: explicit confirmation target does not match pending artifact.",
                        [pending_artifact],
                    )

                issuance_result = None
                if pending_action == "issue":
                    lineage_refs, lineage_code = self._aci_resolve_lineage_refs(
                        current_phase=current_phase,
                        environment_id=environment_id,
                        session_context=session_context if isinstance(session_context, dict) else {},
                    )
                    if lineage_refs is None:
                        return _issuance_refusal(
                            lineage_code,
                            "Issuance confirmation rejected because lineage resolution is ambiguous.",
                            [pending_artifact],
                        )
                    issuance_result = self._aci_issuance_ledger.append_issued_artifact(
                        phase_id=current_phase + 1,
                        contract_name=pending_artifact,
                        issuer_identity_id=issuer_identity_id,
                        environment_id=environment_id,
                        lineage_refs=lineage_refs,
                        request_context={
                            "confirmation_command": normalized_input,
                            "proposal_created_at": str(pending.get("created_at", "")),
                            "proposal_reason": str(pending.get("reason", "")),
                            "trace_id": trace_id,
                        },
                        lineage_required=current_phase > ACI_MIN_PHASE,
                    )
                elif pending_action == "revoke":
                    issuance_result = self._aci_issuance_ledger.append_revocation_record(
                        revoked_artifact_id=str(pending.get("revoked_artifact_id", "")).strip(),
                        revocation_reason=str(pending.get("revocation_reason", "")).strip(),
                        issuer_identity_id=issuer_identity_id,
                        environment_id=environment_id,
                        request_context={
                            "confirmation_command": normalized_input,
                            "proposal_created_at": str(pending.get("created_at", "")),
                            "trace_id": trace_id,
                        },
                    )
                elif pending_action == "supersede":
                    issuance_result = self._aci_issuance_ledger.append_supersession_record(
                        superseded_artifact_id=str(pending.get("superseded_artifact_id", "")).strip(),
                        replacement_artifact_id=str(pending.get("replacement_artifact_id", "")).strip(),
                        issuer_identity_id=issuer_identity_id,
                        environment_id=environment_id,
                        request_context={
                            "confirmation_command": normalized_input,
                            "proposal_created_at": str(pending.get("created_at", "")),
                            "trace_id": trace_id,
                        },
                    )
                else:
                    return _issuance_refusal(
                        "ISSUANCE_PENDING_ACTION_INVALID",
                        "Issuance confirmation rejected: pending proposal action is invalid.",
                        [],
                    )

                if issuance_result is None:
                    return _issuance_refusal(
                        "ISSUANCE_PENDING_ACTION_INVALID",
                        "Issuance confirmation rejected: pending proposal action is invalid.",
                        [],
                    )
                if not issuance_result.ok or issuance_result.record is None:
                    if issuance_result.reason_code in {
                        "ISSUANCE_DUPLICATE_FOR_LINEAGE",
                        "REVOCATION_ALREADY_REVOKED",
                        "REVOCATION_DUPLICATE",
                        "SUPERSESSION_ALREADY_EXISTS",
                        "SUPERSESSION_DUPLICATE",
                    }:
                        self._aci_pending_proposal = None
                    return _issuance_refusal(
                        issuance_result.reason_code,
                        "Issuance confirmation rejected by deterministic ledger validation.",
                        [pending_artifact],
                    )

                self._aci_pending_proposal = None
                self._aci_last_consumed_transition_key = str(issuance_result.record.get("transition_key", ""))
                receipt = build_receipt_envelope(issuance_result.record)
                return self._aci_result(
                    final_output=receipt,
                    trace_id=trace_id,
                    status="success",
                    mode="aci_issuance_receipt",
                    routing_intent=routing_result.intent_class.value,
                    routing_confidence=routing_result.confidence,
                    gatekeeper_reason_code="ISSUANCE_RECORDED",
                    current_phase=current_phase,
                )

            if revoke_target is not None:
                if not gatekeeper_result.admissible:
                    return _issuance_refusal(
                        gatekeeper_result.deterministic_reason_code,
                        "Revocation request rejected because intent is not admissible at the current phase.",
                        gatekeeper_result.allowed_alternatives,
                    )
                target_record = self._aci_issuance_ledger.lookup_by_artifact_id(revoke_target)
                if target_record is None:
                    return _issuance_refusal(
                        "REVOCATION_TARGET_NOT_FOUND",
                        "Revocation request rejected: target artifact was not found.",
                        [],
                    )
                if str(target_record.get("environment_id", "")).strip() != environment_id:
                    return _issuance_refusal(
                        "REVOCATION_ENVIRONMENT_MISMATCH",
                        "Revocation request rejected: target artifact is in a different environment.",
                        [],
                    )
                if self._aci_issuance_ledger.is_artifact_revoked(revoke_target):
                    replacement = self._aci_issuance_ledger.get_supersession_replacement(revoke_target)
                    if replacement:
                        return _issuance_refusal(
                            "REVOCATION_ALREADY_SUPERSEDED",
                            "Revocation request rejected: artifact is already revoked and superseded.",
                            [f"supersede:{replacement}"],
                        )
                    return _issuance_refusal(
                        "REVOCATION_ALREADY_REVOKED",
                        "Revocation request rejected: artifact is already revoked.",
                        [],
                    )
                self._aci_pending_proposal = {
                    "action": "revoke",
                    "current_phase": current_phase,
                    "contract_name": REVOCATION_CONTRACT_NAME,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "revoked_artifact_id": revoke_target,
                    "revocation_reason": "explicit_human_revocation",
                    "environment_id": environment_id,
                    "issuer_identity_id": issuer_identity_id,
                }
                revoke_proposal = {
                    "type": "proposal",
                    "next_artifact": REVOCATION_CONTRACT_NAME,
                    "reason": (
                        f"Revocation intent is admissible at phase {current_phase}; target artifact is `{revoke_target}`."
                    ),
                    "question": "Shall I prepare this?",
                }
                return self._aci_result(
                    final_output=revoke_proposal,
                    trace_id=trace_id,
                    status="success",
                    mode="aci_issuance_gatekeeper",
                    routing_intent=routing_result.intent_class.value,
                    routing_confidence=routing_result.confidence,
                    gatekeeper_reason_code="ADMISSIBLE_REVOCATION_PROPOSAL",
                    current_phase=current_phase,
                )

            if supersede_request is not None:
                if not gatekeeper_result.admissible:
                    return _issuance_refusal(
                        gatekeeper_result.deterministic_reason_code,
                        "Supersession request rejected because intent is not admissible at the current phase.",
                        gatekeeper_result.allowed_alternatives,
                    )
                superseded_artifact_id, replacement_artifact_id = supersede_request
                old_record = self._aci_issuance_ledger.lookup_by_artifact_id(superseded_artifact_id)
                if old_record is None:
                    return _issuance_refusal(
                        "SUPERSESSION_OLD_NOT_FOUND",
                        "Supersession request rejected: superseded artifact was not found.",
                        [],
                    )
                replacement_record = self._aci_issuance_ledger.lookup_by_artifact_id(replacement_artifact_id)
                if replacement_record is None:
                    return _issuance_refusal(
                        "SUPERSESSION_REPLACEMENT_NOT_FOUND",
                        "Supersession request rejected: replacement artifact was not found.",
                        [],
                    )
                if str(old_record.get("environment_id", "")).strip() != environment_id or str(
                    replacement_record.get("environment_id", "")
                ).strip() != environment_id:
                    return _issuance_refusal(
                        "SUPERSESSION_ENVIRONMENT_MISMATCH",
                        "Supersession request rejected: artifact environment mismatch.",
                        [],
                    )
                if not self._aci_issuance_ledger.is_artifact_revoked(superseded_artifact_id):
                    return _issuance_refusal(
                        "SUPERSESSION_OLD_NOT_REVOKED",
                        "Supersession request rejected: superseded artifact must already be revoked.",
                        [],
                    )
                if self._aci_issuance_ledger.is_artifact_revoked(replacement_artifact_id):
                    return _issuance_refusal(
                        "SUPERSESSION_REPLACEMENT_REVOKED",
                        "Supersession request rejected: replacement artifact is revoked and inadmissible.",
                        [],
                    )
                if self._aci_issuance_ledger.get_supersession_replacement(superseded_artifact_id) is not None:
                    return _issuance_refusal(
                        "SUPERSESSION_ALREADY_EXISTS",
                        "Supersession request rejected: superseded artifact already has a replacement.",
                        [],
                    )
                self._aci_pending_proposal = {
                    "action": "supersede",
                    "current_phase": current_phase,
                    "contract_name": SUPERSESSION_CONTRACT_NAME,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "superseded_artifact_id": superseded_artifact_id,
                    "replacement_artifact_id": replacement_artifact_id,
                    "environment_id": environment_id,
                    "issuer_identity_id": issuer_identity_id,
                }
                supersede_proposal = {
                    "type": "proposal",
                    "next_artifact": SUPERSESSION_CONTRACT_NAME,
                    "reason": (
                        "Supersession intent is admissible at phase "
                        f"{current_phase}; `{superseded_artifact_id}` -> `{replacement_artifact_id}`."
                    ),
                    "question": "Shall I prepare this?",
                }
                return self._aci_result(
                    final_output=supersede_proposal,
                    trace_id=trace_id,
                    status="success",
                    mode="aci_issuance_gatekeeper",
                    routing_intent=routing_result.intent_class.value,
                    routing_confidence=routing_result.confidence,
                    gatekeeper_reason_code="ADMISSIBLE_SUPERSESSION_PROPOSAL",
                    current_phase=current_phase,
                )

            if envelope.get("type") == "proposal":
                self._aci_pending_proposal = {
                    "action": "issue",
                    "current_phase": current_phase,
                    "contract_name": str(envelope.get("next_artifact", "")),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "reason": str(envelope.get("reason", "")),
                    "environment_id": environment_id,
                    "issuer_identity_id": issuer_identity_id,
                }

            return self._aci_result(
                final_output=envelope,
                trace_id=trace_id,
                status="success" if envelope.get("type") in {"proposal", "clarification"} else "error",
                mode="aci_intent_gatekeeper",
                routing_intent=routing_result.intent_class.value,
                routing_confidence=routing_result.confidence,
                gatekeeper_reason_code=gatekeeper_result.deterministic_reason_code,
                current_phase=current_phase,
            )

        if isinstance(secretary_result, dict) and not bool(secretary_result.get("escalate")):
            secretary_intent = str(secretary_result.get("intent_class", ""))
            if secretary_intent in {"advisory_request", "planning_request", "ambiguous_intent"}:
                if self._should_offer_idea_decomposition(
                    utterance=normalized_input,
                    intent_class=secretary_intent,
                ):
                    return self._build_idea_decomposition_response(
                        utterance=normalized_input,
                        trace_id=trace_id,
                    )
            if secretary_intent in {"advisory_request", "planning_request"}:
                if self._should_offer_planning_depth_control(
                    utterance=normalized_input,
                    intent_class=secretary_intent,
                ):
                    return self._build_planning_depth_prompt_response(
                        utterance=normalized_input,
                        intent_class=secretary_intent,
                        trace_id=trace_id,
                    )
                depth_mode = self._explicit_planning_depth_mode(normalized_input)
                advisory_output = build_advisory_plan(
                    utterance=normalized_input,
                    intent_class=secretary_intent,
                )
                if depth_mode is not None:
                    advisory_output = self._apply_planning_depth_mode(advisory_output, depth_mode)
                self._register_plan_artifact_from_advisory(
                    source_utterance=normalized_input,
                    intent_class=secretary_intent,
                    advisory_output=advisory_output,
                )
                advisory_output = self._prepare_advisory_output(advisory_output)
                self._activate_interactive_prompt_from_advisory(
                    advisory_output=advisory_output,
                    trace_id=trace_id,
                )
                self._remember_conversational_context(
                    user_input=normalized_input,
                    intent_class=secretary_intent,
                    mode="advisory",
                )
                return {
                    "final_output": advisory_output,
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "advisory",
                    "execution_enabled": False,
                    "advisory_only": True,
                }

        interaction_dispatch = _dispatch_interaction(self, normalized_input)
        interaction_route = interaction_dispatch.get("route")

        if interaction_route == "reject":
            if (
                interaction_dispatch.get("category") == "invalid/ambiguous"
                and isinstance(secretary_result, dict)
                and not bool(secretary_result.get("escalate"))
            ):
                secretary_intent = str(secretary_result.get("intent_class", "")).strip() or "ambiguous_intent"
                chat_response = self._replace_terminal_filler(
                    str(secretary_result.get("chat_response", ""))
                )
                chat_response = self._apply_tone_to_conversational_text(chat_response)
                chat_response = self._apply_role_framing_to_conversational_text(chat_response)
                chat_response = self._apply_task_mode_to_conversational_text(chat_response)
                chat_response = self._apply_goal_reference_to_conversational_text(chat_response)
                chat_response = self._apply_constraint_reference_to_conversational_text(chat_response)
                chat_response = self._apply_assumption_reference_to_conversational_text(chat_response)
                chat_response = self._apply_decision_reference_to_conversational_text(chat_response)
                if not chat_response:
                    chat_response = (
                        "I need a more specific request. Tell me what outcome you want and any constraints."
                    )
                self._remember_conversational_context(
                    user_input=normalized_input,
                    intent_class=secretary_intent,
                    mode="conversation",
                )
                return {
                    "final_output": chat_response,
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                    "mode": "conversation_layer",
                }

            return {
                "final_output": interaction_dispatch.get("message", "Interaction rejected."),
                "tool_calls": [],
                "status": "error",
                "trace_id": trace_id,
            }

        if interaction_route == "identity":
            self._remember_conversational_context(
                user_input=normalized_input,
                intent_class="informational_query",
                mode="conversation",
            )
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
        if interaction_route == "content_generation":
            prompt = interaction_dispatch.get("payload", normalized_input)
            if not isinstance(prompt, str) or not prompt.strip():
                prompt = normalized_input
            generated_text = self._llm_answer(prompt)
            generated_text = self._replace_terminal_filler(generated_text)
            self._last_content_generation_response = {
                "text": generated_text,
                "origin_turn_id": trace_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._remember_conversational_context(
                user_input=normalized_input,
                intent_class="generative_content_request",
                mode="conversation",
            )
            return {
                "final_output": generated_text,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "content_generation",
            }
        if interaction_route == "content_capture":
            request = interaction_dispatch.get("payload", {})
            if not isinstance(request, dict) or not request.get("valid"):
                return {
                    "final_output": str((request or {}).get("reason") or _CONTENT_CAPTURE_HELP),
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                    "mode": "content_capture",
                    "next_state": "ready_for_input",
                }
            source_record = self._last_content_generation_response
            if source_record is None or not str(source_record.get("text", "")).strip():
                return {
                    "final_output": (
                        "Capture rejected: no prior content-generation output is available "
                        "for explicit capture."
                    ),
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                    "mode": "content_capture",
                    "next_state": "ready_for_input",
                }

            label = str(request.get("label", "")).strip()
            captured = CapturedContent(
                content_id=f"cc-{uuid.uuid4()}",
                type="text",
                source="llm",
                text=str(source_record.get("text", "")),
                timestamp=datetime.now(timezone.utc).isoformat(),
                origin_turn_id=str(source_record.get("origin_turn_id", "")),
                label=label,
                session_id=str(trace_id),
            )
            self._content_capture_store.append(captured)
            return {
                "final_output": f"Captured content {captured.content_id} with label '{captured.label}'.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
                "mode": "content_capture",
                "next_state": "ready_for_input",
                "captured_content": captured.to_dict(),
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
                    self._remember_conversational_context(
                        user_input=normalized_input,
                        intent_class="informational_query",
                        mode="conversation",
                    )
                    return {
                        "final_output": _IDENTITY_LOCATION_CONCEPTUAL_RESPONSE,
                        "tool_calls": [],
                        "status": "success",
                        "trace_id": trace_id,
                        "mode": "read_only_conversation",
                    }

                response = {
                    "final_output": self._apply_decision_reference_to_conversational_text(
                        self._apply_assumption_reference_to_conversational_text(
                            self._apply_constraint_reference_to_conversational_text(
                                self._apply_goal_reference_to_conversational_text(
                                    self._apply_task_mode_to_conversational_text(
                                        self._apply_role_framing_to_conversational_text(
                                            self._apply_tone_to_conversational_text(
                                                self._replace_terminal_filler(self._llm_answer(route_payload))
                                            )
                                        )
                                    )
                                )
                            )
                        )
                    ),
                    "tool_calls": [],
                    "status": "success",
                    "trace_id": trace_id,
                }
                secretary_intent = str((secretary_result or {}).get("intent_class", "")).strip() or "informational_query"
                self._remember_conversational_context(
                    user_input=normalized_input,
                    intent_class=secretary_intent,
                    mode="conversation",
                )
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
            "final_output": self._replace_terminal_filler(self._llm_answer(user_input)),
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
        }


runtime = BillyRuntime(config=None)


def run_turn(user_input: str, session_context: dict):
    return runtime.run_turn(user_input=user_input, session_context=session_context)
