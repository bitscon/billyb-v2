"""Command interpreter with deterministic Phase 1 fallback and Phase 2 lane semantics.

This module stays below execution authority:
- no autonomous command execution
- tool invocation only through Phase 5 explicit approval + Phase 6 stub backend
- optional LLM usage is schema-guarded and cannot execute side effects
- no routing side effects beyond envelope interpretation
"""

from __future__ import annotations

import copy
import json
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
import time
from typing import Any, Callable, Dict, List, Protocol
import uuid

import jsonschema
import yaml

from v2.core import llm_api
from v2.core.content_capture import (
    CapturedContent,
    ContentCaptureStore,
    FileBackedContentCaptureStore,
    InMemoryContentCaptureStore,
)
from v2.core.command_memory import (
    FileBackedMemoryStore,
    InMemoryMemoryStore,
    MemoryEvent,
    MemoryStore,
)
from v2.core.metrics import MetricsSummary, get_metrics_summary, increment_metric, record_latency_ms, reset_metrics
from v2.core.observability import (
    current_correlation_id,
    current_session_id,
    ensure_observability_context,
    log_telemetry_event,
    observability_turn,
    reset_telemetry_events,
)
from v2.core.trace_report import TraceReport, build_trace_report


Lane = str
Envelope = Dict[str, Any]


_ACTION_KEYWORDS = (
    "create",
    "make",
    "write",
    "delete",
    "remove",
    "update",
    "modify",
    "rename",
    "move",
    "copy",
)
_CONTENT_GENERATION_KEYWORDS = (
    "generate",
    "propose",
    "draft",
    "write",
    "sketch",
    "suggest",
)
_CONTENT_GENERATION_EXECUTION_TERMS = (
    "execute",
    "run",
    "apply",
    "delete",
    "remove",
    "rename",
    "move",
    "copy",
    "append",
    "save",
    "register",
    "approve",
    "confirm",
)
_CONTENT_GENERATION_EXECUTION_PHRASES = (
    "to file",
    "from file",
    "at path",
    "home directory",
    "workspace",
    "sandbox",
    "run tool",
    "confirm run tool",
    "register tool",
    "approve tool",
)
_FILESYSTEM_INTENTS = {
    "create_file",
    "write_file",
    "append_file",
    "read_file",
    "delete_file",
}
_FILESYSTEM_WRITE_INTENTS = {"create_file", "write_file", "append_file", "delete_file"}
_PHASE19_PERSIST_NOTE_INTENT = "persist_note"
_PHASE19_NOTES_SUBDIR = ("sandbox", "notes")
_PHASE19_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_PHASE21_INTENTS = {"revise_content", "transform_content", "refactor_file"}
_PHASE22_PROJECT_INTENTS = {
    "create_project",
    "update_project",
    "list_project_artifacts",
    "delete_project",
    "open_project_artifact",
    "project_wide_refactor",
    "project_documentation_generate",
}
_PHASE23_GOAL_INTENTS = {
    "define_project_goal",
    "list_project_goals",
    "describe_project_goal",
    "list_project_tasks",
    "task_status",
    "propose_next_tasks",
    "complete_task",
}
_PHASE24_MILESTONE_INTENTS = {
    "define_milestone",
    "list_milestones",
    "describe_milestone",
    "achieve_milestone",
    "project_completion_status",
    "finalize_project",
    "archive_project",
}
_PHASE25_DELEGATION_INTENTS = {
    "delegate_to_agent",
    "list_delegation_capabilities",
    "describe_delegation_result",
}
_PHASE26_WORKFLOW_INTENTS = {
    "define_workflow",
    "list_workflows",
    "describe_workflow",
    "preview_workflow",
    "run_workflow",
    "workflow_status",
    "workflow_cancel",
}
_PHASE20_WORKING_SET_TTL_SECONDS = 1800
_PHASE20_IMPLICIT_REFERENCE_PHRASES = (
    "this",
    "that",
    "current",
    "it",
    "current_working_set",
    "this note",
    "that note",
    "current note",
    "this page",
    "that page",
    "current page",
    "this file",
    "that file",
    "current file",
    "this draft",
    "that draft",
    "current draft",
    "this concept",
    "that concept",
    "current concept",
    "this text",
    "that text",
    "this snippet",
    "that snippet",
    "this thought",
    "that thought",
    "this idea",
    "that idea",
)
_PHASE20_IMPLICIT_REFERENCE_PLACEHOLDERS = {
    "this",
    "that",
    "it",
    "current",
    "current_working_set",
    "this note",
    "that note",
    "current note",
    "this page",
    "that page",
    "current page",
    "this file",
    "that file",
    "current file",
    "this draft",
    "that draft",
    "current draft",
    "this concept",
    "that concept",
    "current concept",
    "this text",
    "that text",
    "this snippet",
    "that snippet",
    "this thought",
    "that thought",
    "this idea",
    "that idea",
}
_PHASE20_CODE_FILE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".m",
    ".mm",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".scala",
    ".sh",
    ".sql",
    ".swift",
    ".ts",
    ".tsx",
}

_CONVERSATIONAL_PREFIXES = (
    "what",
    "who",
    "where",
    "when",
    "why",
    "how",
    "tell me",
    "give me",
)

_SEMANTIC_LANES = ("CHAT", "PLAN", "HELP", "CLARIFY", "CONTENT_GENERATION")
_SEMANTIC_CONFIDENCE_THRESHOLD = 0.70
_PHASE3_MAX_RETRIES = 2
_phase3_enabled = False
_phase4_enabled = False
_phase4_explanation_enabled = False
_phase5_enabled = False
_phase8_enabled = False
_phase19_enabled = True
_phase20_enabled = True
_phase21_enabled = True
_phase22_enabled = True
_phase23_enabled = True
_phase24_enabled = True
_phase25_enabled = True
_phase26_enabled = True
_phase8_approval_mode = "step"

_PHASE5_PENDING_TTL_SECONDS = 300
_PHASE5_APPROVAL_PHRASES = {
    "yes, proceed",
    "approve",
    "approved",
    "go ahead",
    "do it",
}

_PHASE9_ENGINEER_MODE_DEPRECATED_MESSAGE = (
    "Engineer mode is deprecated. Continue in governed mode; approvals are requested automatically when needed."
)
_PHASE8_PENDING_TTL_SECONDS = 300
_PHASE8_RISK_ORDER = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}
_PHASE15_CONSTRAINT_MODES = {"read_only", "bounded_write"}
_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]

_PHASE4_DEFAULT_POLICY = {
    # "privileged" maps to schema-valid "critical".
    "allowed": False,
    "risk_level": "critical",
    "requires_approval": True,
    "reason": "Policy denied by default: no matching deterministic policy rule.",
}


@dataclass
class PendingAction:
    action_id: str
    envelope_snapshot: Envelope
    resolved_tool_contract: "ToolContract | None"
    created_at: str
    expires_at: str
    consumed: bool
    awaiting_next_user_turn: bool


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    description: str
    tool_contract: "ToolContract"
    parameters: Dict[str, Any]
    risk_level: str
    envelope_snapshot: Envelope


@dataclass(frozen=True)
class ExecutionPlan:
    plan_id: str
    intent: str
    steps: List[PlanStep]


@dataclass
class PendingPlan:
    plan: ExecutionPlan
    created_at: str
    expires_at: str
    awaiting_next_user_turn: bool
    next_step_index: int


@dataclass(frozen=True)
class ProjectGoal:
    goal_id: str
    project_id: str
    description: str
    created_at: str
    metadata: Dict[str, Any]


@dataclass(frozen=True)
class ProjectTask:
    task_id: str
    project_id: str
    goal_id: str
    description: str
    status: str
    dependencies: List[str]
    created_at: str
    completed_at: str | None
    metadata: Dict[str, Any]


@dataclass(frozen=True)
class ProjectMilestone:
    milestone_id: str
    project_id: str
    title: str
    description: str
    associated_goals: List[str]
    criteria: List[str]
    status: str
    created_at: str
    achieved_at: str | None


@dataclass(frozen=True)
class DelegationContract:
    delegation_id: str
    agent_type: str
    task_description: str
    allowed_tools: List[str]
    requested_tool: str
    project_id: str
    project_name: str
    created_at: str


@dataclass(frozen=True)
class WorkflowStep:
    step_id: str
    description: str
    intent: str
    parameters: Dict[str, Any]
    depends_on: List[str]


@dataclass(frozen=True)
class Workflow:
    workflow_id: str
    project_id: str
    name: str
    description: str
    parameters_schema: Dict[str, Any]
    steps: List[WorkflowStep]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AutonomyScope:
    allowed_lanes: List[str]
    allowed_intents: List[str]


@dataclass(frozen=True)
class AutonomyConstraints:
    mode: str
    max_risk_level: str
    allowed_tools: List[str]
    blocked_tools: List[str]
    max_actions: int


@dataclass
class AutonomySession:
    session_id: str
    scope: AutonomyScope
    constraints: AutonomyConstraints
    origin: str
    enabled_at: str
    expires_at: str
    active: bool
    stop_reason: str | None
    revoked_at: str | None
    ended_at: str | None
    actions_executed: int
    events: List[Dict[str, Any]]


_pending_action: PendingAction | None = None
_execution_events: List[Dict[str, Any]] = []
_memory_store: MemoryStore = InMemoryMemoryStore()
_capture_store: ContentCaptureStore = InMemoryContentCaptureStore()
_pending_plan: PendingPlan | None = None
_active_autonomy_session_id: str | None = None
_autonomy_sessions: Dict[str, AutonomySession] = {}
_autonomy_session_order: List[str] = []
_phase16_last_response_by_session: Dict[str, Dict[str, Any]] = {}
_phase16_last_response_global: Dict[str, Any] | None = None
_phase20_working_set_by_session: Dict[str, Dict[str, Any]] = {}
_phase22_projects_by_id: Dict[str, Dict[str, Any]] = {}
_phase22_project_context_by_session: Dict[str, Dict[str, Any]] = {}
_phase23_goals_by_project_id: Dict[str, List[Dict[str, Any]]] = {}
_phase23_tasks_by_project_id: Dict[str, List[Dict[str, Any]]] = {}
_phase24_milestones_by_project_id: Dict[str, List[Dict[str, Any]]] = {}
_phase25_contracts_by_id: Dict[str, Dict[str, Any]] = {}
_phase25_last_delegation_by_session: Dict[str, Dict[str, Any]] = {}
_phase25_last_delegation_global: Dict[str, Any] | None = None
_phase26_workflows_by_project_id: Dict[str, List[Dict[str, Any]]] = {}
_phase26_runs_by_id: Dict[str, Dict[str, Any]] = {}
_phase26_active_run_by_session: Dict[str, str] = {}
_phase26_last_run_by_session: Dict[str, str] = {}


@dataclass(frozen=True)
class ToolContract:
    tool_name: str
    intent: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    risk_level: str
    side_effects: bool


class ToolInvoker(Protocol):
    def invoke(self, contract: ToolContract, parameters: Dict[str, Any]) -> Dict[str, Any]:
        ...


class StubToolInvoker:
    """Stub-only backend: validates schemas and returns deterministic mock results."""

    def __init__(self) -> None:
        self._invocations: List[Dict[str, Any]] = []

    def invoke(self, contract: ToolContract, parameters: Dict[str, Any]) -> Dict[str, Any]:
        jsonschema.validate(parameters, contract.input_schema)
        result = self._build_result(contract, parameters)
        jsonschema.validate(result, contract.output_schema)
        self._invocations.append(
            {
                "invocation_id": f"invoke-{uuid.uuid4()}",
                "tool_name": contract.tool_name,
                "intent": contract.intent,
                "parameters": copy.deepcopy(parameters),
                "result": copy.deepcopy(result),
                "invoked_at": _utcnow().isoformat(),
            }
        )
        return copy.deepcopy(result)

    def get_invocations(self) -> List[Dict[str, Any]]:
        return copy.deepcopy(self._invocations)

    def reset(self) -> None:
        self._invocations = []

    @staticmethod
    def _build_result(contract: ToolContract, parameters: Dict[str, Any]) -> Dict[str, Any]:
        if contract.intent == "plan.create_empty_file":
            return {
                "status": "stubbed",
                "created": True,
                "path": str(parameters.get("path", "$HOME/untitled.txt")),
            }
        if contract.intent == "create_file":
            return {
                "status": "stubbed",
                "operation": "create_file",
                "path": str(parameters.get("path", "")),
            }
        if contract.intent == "write_file":
            return {
                "status": "stubbed",
                "operation": "write_file",
                "path": str(parameters.get("path", "")),
            }
        if contract.intent == "append_file":
            return {
                "status": "stubbed",
                "operation": "append_file",
                "path": str(parameters.get("path", "")),
            }
        if contract.intent == "read_file":
            return {
                "status": "stubbed",
                "operation": "read_file",
                "path": str(parameters.get("path", "")),
                "contents": "stubbed file contents",
            }
        if contract.intent == "delete_file":
            return {
                "status": "stubbed",
                "operation": "delete_file",
                "path": str(parameters.get("path", "")),
            }
        return {
            "status": "stubbed",
            "accepted": True,
        }


_tool_invoker: ToolInvoker = StubToolInvoker()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _emit_observability_event(phase: str, event_type: str, metadata: Dict[str, Any] | None = None) -> None:
    log_telemetry_event(phase=phase, event_type=event_type, metadata=metadata or {})


def _envelope_pointer(envelope: Envelope) -> Dict[str, Any]:
    policy = envelope.get("policy", {}) if isinstance(envelope.get("policy"), dict) else {}
    return {
        "lane": str(envelope.get("lane", "")),
        "intent": str(envelope.get("intent", "")),
        "requires_approval": bool(envelope.get("requires_approval", False)),
        "policy_allowed": bool(policy.get("allowed", False)),
        "policy_risk_level": str(policy.get("risk_level", "")),
        "entity_count": len(envelope.get("entities", [])) if isinstance(envelope.get("entities"), list) else 0,
    }


def _phase20_now_iso() -> str:
    return _utcnow().isoformat()


def _phase20_session_key(explicit_session_id: str | None = None) -> str:
    if explicit_session_id is not None and str(explicit_session_id).strip():
        return str(explicit_session_id).strip()
    return str(current_session_id() or "").strip()


def _phase20_parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _phase20_working_set_type_from_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in {".htm", ".html"}:
        return "html_page"
    if suffix in _PHASE20_CODE_FILE_SUFFIXES:
        return "code_file"
    if suffix:
        return "text_note"
    return "other"


def _phase20_working_set_type_from_text(text: str) -> str:
    lowered = _normalize(text).lower()
    if "<html" in lowered or "<!doctype html" in lowered:
        return "html_page"
    if re.search(r"\bdef\s+\w+\s*\(", lowered) or re.search(r"\bfunction\s+\w+\s*\(", lowered):
        return "code_file"
    if lowered:
        return "text_note"
    return "other"


def _phase20_normalize_working_set_type(raw: str) -> str:
    allowed = {"text_note", "html_page", "code_file", "other"}
    normalized = _normalize(raw).lower()
    if normalized in allowed:
        return normalized
    return "other"


def _phase20_prune_expired_working_sets() -> None:
    if not _phase20_working_set_by_session:
        return
    now = _utcnow()
    stale: List[str] = []
    for session_id, record in _phase20_working_set_by_session.items():
        if not isinstance(record, dict):
            stale.append(session_id)
            continue
        updated_at = _phase20_parse_iso(str(record.get("updated_at", "")))
        if updated_at is None:
            stale.append(session_id)
            continue
        if (now - updated_at).total_seconds() > _PHASE20_WORKING_SET_TTL_SECONDS:
            stale.append(session_id)
    for session_id in stale:
        _phase20_working_set_by_session.pop(session_id, None)
        _emit_observability_event(
            phase="phase20",
            event_type="working_set_expired",
            metadata={"session_id": session_id},
        )


def _phase20_get_working_set(session_id: str | None = None) -> Dict[str, Any] | None:
    _phase20_prune_expired_working_sets()
    key = _phase20_session_key(session_id)
    if not key:
        return None
    record = _phase20_working_set_by_session.get(key)
    if not isinstance(record, dict):
        return None
    return copy.deepcopy(record)


def _phase20_set_working_set(record: Dict[str, Any], *, reason: str) -> None:
    if not _phase20_enabled:
        return
    _phase20_prune_expired_working_sets()
    key = _phase20_session_key()
    if not key:
        return
    persisted = copy.deepcopy(record)
    now = _phase20_now_iso()
    persisted["timestamp"] = now
    persisted["updated_at"] = now
    persisted["type"] = _phase20_normalize_working_set_type(str(persisted.get("type", "")))
    _phase20_working_set_by_session[key] = persisted
    project_context = _phase22_get_project_context(key) if _phase22_enabled else None
    if isinstance(project_context, dict):
        project_id = str(project_context.get("project_id", ""))
        project = _phase22_projects_by_id.get(project_id)
        if isinstance(project, dict):
            project["working_set"] = copy.deepcopy(persisted)
            project["updated_at"] = now
    _emit_observability_event(
        phase="phase20",
        event_type="working_set_updated",
        metadata={
            "session_id": key,
            "reason": reason,
            "content_id": str(persisted.get("content_id", "")),
            "label": str(persisted.get("label", "")),
            "path": str(persisted.get("path", "")),
            "type": str(persisted.get("type", "")),
        },
    )


def _phase20_clear_working_set(*, reason: str, session_id: str | None = None) -> bool:
    key = _phase20_session_key(session_id)
    if not key:
        return False
    removed = _phase20_working_set_by_session.pop(key, None)
    if removed is not None:
        _emit_observability_event(
            phase="phase20",
            event_type="working_set_cleared",
            metadata={"session_id": key, "reason": reason},
        )
        return True
    return False


def _phase20_working_set_message(record: Dict[str, Any] | None) -> str:
    if not isinstance(record, dict):
        return "No active working set in this session."
    label = str(record.get("label", "")).strip()
    path = str(record.get("path", "")).strip()
    source = str(record.get("source", "")).strip()
    if label:
        return f"You are currently working on '{label}' ({source or 'session'})."
    if path:
        return f"You are currently working on {path}."
    content_id = str(record.get("content_id", "")).strip()
    if content_id:
        return f"You are currently working on content {content_id}."
    return "You have an active working set in this session."


def get_working_set_diagnostics(session_id: str | None = None) -> Dict[str, Any]:
    record = _phase20_get_working_set(session_id)
    has_working_set = isinstance(record, dict)
    payload = {
        "has_working_set": has_working_set,
        "session_id": _phase20_session_key(session_id),
        "working_set": record if has_working_set else None,
        "message": _phase20_working_set_message(record),
    }
    return payload


def _phase20_implicit_reference_requested(text: str) -> bool:
    lowered = _normalize(text).lower()
    if not lowered:
        return False
    return any(re.search(rf"\b{re.escape(phrase)}\b", lowered) for phrase in _PHASE20_IMPLICIT_REFERENCE_PHRASES)


def _phase20_explicit_label_reference(text: str) -> bool:
    lowered = _normalize(text).lower()
    match = re.search(r"\bthat ([a-z0-9_-]+)\b", lowered)
    if match is None:
        return False
    label = str(match.group(1)).strip()
    generic = {
        "page",
        "text",
        "snippet",
        "thought",
        "idea",
        "note",
        "draft",
        "file",
        "concept",
        "working_set",
        "current_working_set",
        "response",
        "current",
        "it",
        "to",
        "file",
        "in",
        "my",
        "home",
        "directory",
        "workspace",
        "sandbox",
        "named",
        "called",
        "as",
        "a",
        "an",
        "the",
    }
    return label not in generic


def _phase20_placeholder_contents(text: str) -> bool:
    lowered = _normalize(text).lower()
    if lowered in _PHASE20_IMPLICIT_REFERENCE_PLACEHOLDERS:
        return True
    without_article = re.sub(r"^(?:the|a|an)\s+", "", lowered)
    return without_article in _PHASE20_IMPLICIT_REFERENCE_PLACEHOLDERS


def _phase20_reset_request(text: str) -> bool:
    lowered = _normalize(text).lower().strip(" .!?")
    return lowered in {
        "reset current working set",
        "reset current_working_set",
        "reset working set",
        "clear current working set",
        "clear current_working_set",
        "clear working set",
    }


def _phase20_task_completion_request(text: str) -> bool:
    lowered = _normalize(text).lower().strip(" .!?")
    return bool(
        re.fullmatch(
            r"(?:i[' ]?m|i am)\s+done\s+with\s+(?:this|that|the current)\s+page",
            lowered,
        )
    )


def _phase20_diagnostics_request(text: str) -> bool:
    lowered = _normalize(text).lower().strip(" .!?")
    return lowered in {
        "current working set",
        "current_working_set",
        "working set",
        "working set status",
        "what is current working set",
        "what am i working on",
    }


def _phase20_control_response(text: str) -> Dict[str, Any] | None:
    normalized = _normalize(text)
    _phase20_prune_expired_working_sets()
    if _phase20_reset_request(normalized):
        _phase20_clear_working_set(reason="explicit_reset")
        return {
            "type": "working_set_reset",
            "executed": False,
            "message": "Current working set cleared.",
        }
    if _phase20_task_completion_request(normalized):
        _phase20_clear_working_set(reason="task_completion")
        return {
            "type": "working_set_reset",
            "executed": False,
            "message": "Working set reset for this page.",
        }
    if _phase20_diagnostics_request(normalized):
        diagnostics = get_working_set_diagnostics()
        _emit_observability_event(
            phase="phase20",
            event_type="working_set_diagnostics_requested",
            metadata={"has_working_set": bool(diagnostics.get("has_working_set", False))},
        )
        return {
            "type": "working_set_info",
            "executed": False,
            "working_set": diagnostics.get("working_set"),
            "message": str(diagnostics.get("message", "")),
        }
    return None


def _phase22_session_key(explicit_session_id: str | None = None) -> str:
    if explicit_session_id is not None and str(explicit_session_id).strip():
        return str(explicit_session_id).strip()
    return str(current_session_id() or "").strip()


def _phase22_slug(value: str) -> str:
    lowered = _normalize(value).lower()
    lowered = re.sub(r"[^a-z0-9._-]+", "_", lowered)
    lowered = re.sub(r"_+", "_", lowered).strip("._-")
    return lowered or "project"


def _phase22_allowed_project_roots() -> List[Path]:
    return [Path.home().resolve(), _WORKSPACE_ROOT.resolve()]


def _phase22_normalize_project_root(path_value: str, *, location_hint: str) -> tuple[str | None, str | None]:
    return _phase17_normalize_path(path_value, location_hint=location_hint)


def _phase22_artifact_type_from_path(path: str) -> str:
    return _phase20_working_set_type_from_path(path)


def _phase22_scan_artifacts(root_path: str) -> List[Dict[str, Any]]:
    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        return []
    artifacts: List[Dict[str, Any]] = []
    for candidate in sorted(root.rglob("*")):
        if not candidate.is_file():
            continue
        try:
            rel = str(candidate.relative_to(root)).replace("\\", "/")
        except Exception:
            continue
        artifacts.append(
            {
                "path": rel,
                "type": _phase22_artifact_type_from_path(str(candidate)),
                "updated_at": _utcnow().isoformat(),
            }
        )
    return artifacts


def _phase22_set_project_context(project: Dict[str, Any], *, session_id: str | None = None) -> None:
    if not _phase22_enabled:
        return
    key = _phase22_session_key(session_id)
    if not key:
        return
    context = {
        "project_id": str(project.get("project_id", "")),
        "project_name": str(project.get("name", "")),
        "root_path": str(project.get("root_path", "")),
        "updated_at": _utcnow().isoformat(),
    }
    _phase22_project_context_by_session[key] = context
    _emit_observability_event(
        phase="phase22",
        event_type="project_context_updated",
        metadata={
            "session_id": key,
            "project_id": context["project_id"],
            "project_name": context["project_name"],
        },
    )


def _phase22_get_project_context(session_id: str | None = None) -> Dict[str, Any] | None:
    key = _phase22_session_key(session_id)
    if not key:
        return None
    record = _phase22_project_context_by_session.get(key)
    if not isinstance(record, dict):
        return None
    project_id = str(record.get("project_id", "")).strip()
    if project_id and project_id in _phase22_projects_by_id:
        return copy.deepcopy(record)
    return None


def _phase22_clear_project_context(*, session_id: str | None = None) -> bool:
    key = _phase22_session_key(session_id)
    if not key:
        return False
    removed = _phase22_project_context_by_session.pop(key, None)
    return removed is not None


def get_project_context_diagnostics(session_id: str | None = None) -> Dict[str, Any]:
    context = _phase22_get_project_context(session_id)
    if context is None:
        return {
            "has_project_context": False,
            "project": None,
            "message": "No active project in this session.",
        }
    project_id = str(context.get("project_id", ""))
    project = copy.deepcopy(_phase22_projects_by_id.get(project_id, {}))
    if not project:
        return {
            "has_project_context": False,
            "project": None,
            "message": "No active project in this session.",
        }
    return {
        "has_project_context": True,
        "project": project,
        "message": f"You are currently working on project '{project.get('name', '')}'.",
    }


def get_current_project_context(session_id: str | None = None) -> Dict[str, Any] | None:
    return _phase22_get_project_context(session_id)


def _phase22_create_project_record(*, name: str, root_path: str) -> Dict[str, Any]:
    now = _utcnow().isoformat()
    project = {
        "project_id": f"proj-{uuid.uuid4()}",
        "name": name,
        "root_path": root_path,
        "artifacts": _phase22_scan_artifacts(root_path),
        "working_set": _phase20_get_working_set(),
        "state": "active",
        "finalized_at": None,
        "archived_at": None,
        "archive_path": "",
        "completion_confirmed": False,
        "metadata": {},
        "created_at": now,
        "updated_at": now,
    }
    _phase22_projects_by_id[project["project_id"]] = copy.deepcopy(project)
    _phase23_goals_by_project_id[project["project_id"]] = []
    _phase23_tasks_by_project_id[project["project_id"]] = []
    _phase24_milestones_by_project_id[project["project_id"]] = []
    _phase22_set_project_context(project)
    return project


def _phase22_update_project_timestamp(project_id: str) -> None:
    project = _phase22_projects_by_id.get(project_id)
    if not isinstance(project, dict):
        return
    project["updated_at"] = _utcnow().isoformat()
    context = _phase22_get_project_context()
    if isinstance(context, dict) and str(context.get("project_id", "")) == project_id:
        _phase22_set_project_context(project)


def _phase22_project_for_path(path: str) -> Dict[str, Any] | None:
    candidate = Path(path).resolve(strict=False)
    for project in _phase22_projects_by_id.values():
        if not isinstance(project, dict):
            continue
        root = Path(str(project.get("root_path", "")))
        try:
            root_resolved = root.resolve(strict=False)
        except Exception:
            continue
        if _phase17_is_within(candidate, root_resolved):
            return project
    return None


def _phase22_artifact_relpath(project: Dict[str, Any], path: str) -> str:
    root = Path(str(project.get("root_path", ""))).resolve(strict=False)
    candidate = Path(path).resolve(strict=False)
    try:
        return str(candidate.relative_to(root)).replace("\\", "/")
    except Exception:
        return Path(path).name


def _phase22_add_or_update_artifact(project: Dict[str, Any], path: str) -> None:
    rel = _phase22_artifact_relpath(project, path)
    artifacts = project.get("artifacts", [])
    artifacts = artifacts if isinstance(artifacts, list) else []
    now = _utcnow().isoformat()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        if str(artifact.get("path", "")) != rel:
            continue
        artifact["type"] = _phase22_artifact_type_from_path(path)
        artifact["updated_at"] = now
        project["artifacts"] = artifacts
        return
    artifacts.append({"path": rel, "type": _phase22_artifact_type_from_path(path), "updated_at": now})
    project["artifacts"] = artifacts


def _phase22_remove_artifact(project: Dict[str, Any], path: str) -> None:
    rel = _phase22_artifact_relpath(project, path)
    artifacts = project.get("artifacts", [])
    artifacts = artifacts if isinstance(artifacts, list) else []
    project["artifacts"] = [
        artifact
        for artifact in artifacts
        if not (isinstance(artifact, dict) and str(artifact.get("path", "")) == rel)
    ]


def _phase22_reference_requested(text: str) -> bool:
    lowered = _normalize(text).lower()
    return any(
        phrase in lowered
        for phrase in (
            "this project",
            "current project",
            "the project",
            "the site",
            "this site",
            "current site",
        )
    )


def _phase22_extract_named_project(text: str) -> str:
    match = re.search(r"\bproject\s+(?:named|called)\s+([a-zA-Z0-9 _.-]+)", text, flags=re.IGNORECASE)
    if match is None:
        return ""
    return _phase22_slug(match.group(1))


def _phase22_extract_project_name(text: str) -> str:
    named = _phase22_extract_named_project(text)
    if named:
        return named
    create_for = re.search(r"\b(?:create|start|build)\s+(?:a\s+)?(?:new\s+)?project\s+(?:for|as)\s+([a-zA-Z0-9 _.-]+)", text, flags=re.IGNORECASE)
    if create_for is not None:
        return _phase22_slug(create_for.group(1))
    create_plain = re.fullmatch(r"(?:create|start|build)\s+(?:a\s+)?(?:new\s+)?project", _normalize(text), flags=re.IGNORECASE)
    if create_plain is not None:
        return "project"
    return ""


def _phase22_resolve_project_from_utterance(text: str) -> Dict[str, Any] | None:
    named = _phase22_extract_named_project(text)
    if named:
        matches = [project for project in _phase22_projects_by_id.values() if str(project.get("name", "")) == named]
        if len(matches) == 1:
            return copy.deepcopy(matches[0])
    context = _phase22_get_project_context()
    if context is None:
        return None
    project_id = str(context.get("project_id", ""))
    project = _phase22_projects_by_id.get(project_id)
    if not isinstance(project, dict):
        return None
    return copy.deepcopy(project)


def _phase22_control_response(text: str) -> Dict[str, Any] | None:
    lowered = _normalize(text).lower().strip(" .!?")
    if lowered not in {
        "what project am i working on",
        "current project",
        "show files in this project",
        "show next steps for this project",
    }:
        return None
    diagnostics = get_project_context_diagnostics()
    if lowered in {"what project am i working on", "current project"}:
        return {
            "type": "project_info",
            "executed": False,
            "project": diagnostics.get("project"),
            "message": str(diagnostics.get("message", "")),
        }
    project = diagnostics.get("project")
    if not isinstance(project, dict):
        return {
            "type": "no_action",
            "executed": False,
            "envelope": _phase17_clarify_envelope(
                utterance=text,
                message="No active project. Create or select a project first.",
            ),
            "message": "",
        }
    artifacts = project.get("artifacts", [])
    artifacts = artifacts if isinstance(artifacts, list) else []
    if lowered == "show files in this project":
        artifact_paths = [str(item.get("path", "")) for item in artifacts if isinstance(item, dict)]
        message = "\n".join(artifact_paths) if artifact_paths else "No artifacts recorded for this project."
        return {
            "type": "project_artifacts",
            "executed": False,
            "project": project,
            "artifacts": artifact_paths,
            "message": message,
        }
    next_steps = []
    if not artifacts:
        next_steps.append("Add your first artifact to this project.")
    else:
        next_steps.append("Revise existing artifacts or add new pages/files.")
        next_steps.append("Generate project documentation for overview.")
    return {
        "type": "project_next_steps",
        "executed": False,
        "project": project,
        "next_steps": next_steps,
        "message": " ".join(next_steps),
    }


def _phase25_session_key(explicit_session_id: str | None = None) -> str:
    if explicit_session_id is not None and str(explicit_session_id).strip():
        return str(explicit_session_id).strip()
    return str(current_session_id() or "").strip()


@lru_cache(maxsize=1)
def _phase25_capability_registry() -> Dict[str, Dict[str, Any]]:
    path = Path(__file__).resolve().parents[1] / "contracts" / "delegation_capabilities.yaml"
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        payload = {}
    entries = payload.get("delegation_capabilities", [])
    entries = entries if isinstance(entries, list) else []
    registry: Dict[str, Dict[str, Any]] = {}
    for item in entries:
        if not isinstance(item, dict):
            continue
        agent_type = _normalize(str(item.get("agent_type", ""))).upper()
        if not agent_type:
            continue
        allowed_tools = item.get("allowed_tools", [])
        allowed_tools = allowed_tools if isinstance(allowed_tools, list) else []
        normalized_tools = sorted({_normalize(str(tool)) for tool in allowed_tools if _normalize(str(tool))})
        registry[agent_type] = {
            "agent_type": agent_type,
            "allowed_tools": normalized_tools,
            "description": _normalize(str(item.get("description", ""))),
        }
    return registry


def _phase25_capabilities_list() -> List[Dict[str, Any]]:
    return [copy.deepcopy(value) for _, value in sorted(_phase25_capability_registry().items())]


def _phase25_contract_to_dict(contract: DelegationContract) -> Dict[str, Any]:
    return {
        "delegation_id": contract.delegation_id,
        "agent_type": contract.agent_type,
        "task_description": contract.task_description,
        "allowed_tools": list(contract.allowed_tools),
        "requested_tool": contract.requested_tool,
        "project_id": contract.project_id,
        "project_name": contract.project_name,
        "created_at": contract.created_at,
    }


def _phase25_requested_tool(task_description: str) -> str:
    lowered = _normalize(task_description).lower()
    if any(token in lowered for token in ("delete", "remove", "unlink")):
        return "filesystem.delete_file"
    if any(token in lowered for token in ("refactor", "revise", "rewrite")):
        return "revise_content"
    if any(token in lowered for token in ("transform", "convert", "uppercase", "lowercase", "format")):
        return "transform_content"
    if any(token in lowered for token in ("code", "stylesheet", "css", "module", "file", "snippet", "write", "create")):
        return "filesystem.write_file"
    return "content_generation"


def _phase25_extract_agent_type(text: str) -> str:
    normalized = _normalize(text)
    direct = re.search(r"\bto\s+(?:a\s+)?([a-zA-Z_][a-zA-Z0-9_-]*)\s+agent\b", normalized, flags=re.IGNORECASE)
    if direct is not None:
        return _normalize(direct.group(1)).upper()
    named = re.search(r"\bagent\s+type\s+([a-zA-Z_][a-zA-Z0-9_-]*)\b", normalized, flags=re.IGNORECASE)
    if named is not None:
        return _normalize(named.group(1)).upper()
    return ""


def _phase25_extract_task(text: str) -> str:
    normalized = _normalize(text)
    quoted = re.search(r"'([^']+)'|\"([^\"]+)\"", normalized)
    if quoted is not None:
        token = quoted.group(1) if quoted.group(1) is not None else quoted.group(2)
        return _normalize(str(token))
    match = re.search(
        r"\bdelegate\b(?:\s+(?:the\s+)?task(?:\s+of)?|\s+)?\s*(?P<task>.+?)\s+to\s+(?:a\s+)?[a-zA-Z_][a-zA-Z0-9_-]*\s+agent\b",
        normalized,
        flags=re.IGNORECASE,
    )
    if match is not None:
        return _normalize(str(match.group("task")))
    if normalized.lower().startswith("delegate "):
        return _normalize(normalized[len("delegate "):])
    return ""


def _phase25_parse_contract_json(raw: str) -> Dict[str, Any] | None:
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _phase25_result_message(record: Dict[str, Any]) -> str:
    delegation_id = str(record.get("delegation_id", ""))
    agent_type = str(record.get("agent_type", ""))
    summary = _normalize(str(record.get("result_summary", "")))
    if summary:
        return f"Delegation result {delegation_id} ({agent_type}): {summary}"
    return f"Delegation result {delegation_id} ({agent_type}) is available."


def _phase25_last_delegation(session_id: str | None = None) -> Dict[str, Any] | None:
    global _phase25_last_delegation_global
    key = _phase25_session_key(session_id)
    record = _phase25_last_delegation_by_session.get(key) if key else None
    if not isinstance(record, dict):
        if not isinstance(_phase25_last_delegation_global, dict):
            return None
        return copy.deepcopy(_phase25_last_delegation_global)
    return copy.deepcopy(record)


def _phase26_session_key(explicit_session_id: str | None = None) -> str:
    if explicit_session_id is not None and str(explicit_session_id).strip():
        return str(explicit_session_id).strip()
    return str(current_session_id() or "").strip()


def _phase26_supported_step_intents() -> set[str]:
    return {
        "create_file",
        "write_file",
        "append_file",
        "read_file",
        "delete_file",
        "content_generation.draft",
        "capture_content",
        "persist_note",
        "revise_content",
        "transform_content",
        "refactor_file",
        "delegate_to_agent",
        "plan.user_action_request",
    }


def _phase26_parse_json_payload(raw: str) -> Dict[str, Any] | List[Any] | None:
    text = _normalize(raw)
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    if isinstance(parsed, (dict, list)):
        return parsed
    return None


def _phase26_parse_parameter_bindings(raw: str) -> Dict[str, str]:
    text = _normalize(raw)
    if not text:
        return {}
    bindings: Dict[str, str] = {}
    for segment in text.split(","):
        token = segment.strip()
        if not token or "=" not in token:
            continue
        key, value = token.split("=", 1)
        normalized_key = _normalize(key).strip().lower()
        normalized_value = _strip_wrapping_quotes(value.strip())
        if normalized_key and normalized_value:
            bindings[normalized_key] = normalized_value
    return bindings


def _phase26_bind_parameter_value(value: Any, bindings: Dict[str, str]) -> Any:
    if isinstance(value, str):
        pattern = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_-]*)\}")

        def _replace(match: re.Match[str]) -> str:
            key = str(match.group(1)).strip().lower()
            return str(bindings.get(key, match.group(0)))

        return pattern.sub(_replace, value)
    if isinstance(value, list):
        return [_phase26_bind_parameter_value(item, bindings) for item in value]
    if isinstance(value, dict):
        return {str(key): _phase26_bind_parameter_value(val, bindings) for key, val in value.items()}
    return value


def _phase26_schema_required_parameters(schema: Dict[str, Any]) -> List[str]:
    required: List[str] = []
    for name, config in schema.items():
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(config, dict):
            continue
        if bool(config.get("required", False)):
            required.append(name.strip().lower())
    return sorted(set(required))


def _phase26_known_parameter_placeholders(value: Any) -> List[str]:
    found: List[str] = []
    if isinstance(value, str):
        found.extend([str(token).strip().lower() for token in re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_-]*)\}", value)])
    elif isinstance(value, list):
        for item in value:
            found.extend(_phase26_known_parameter_placeholders(item))
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(_phase26_known_parameter_placeholders(item))
    return sorted(set(token for token in found if token))


def _phase26_workflows_for_project(project_id: str) -> List[Dict[str, Any]]:
    key = str(project_id).strip()
    if not key:
        return []
    if key not in _phase26_workflows_by_project_id:
        _phase26_workflows_by_project_id[key] = []
    return _phase26_workflows_by_project_id[key]


def _phase26_active_run(session_id: str | None = None) -> Dict[str, Any] | None:
    key = _phase26_session_key(session_id)
    if not key:
        return None
    run_id = str(_phase26_active_run_by_session.get(key, "")).strip()
    if not run_id:
        return None
    run = _phase26_runs_by_id.get(run_id)
    if not isinstance(run, dict):
        return None
    return run


def _phase26_find_run(run_id: str) -> Dict[str, Any] | None:
    key = str(run_id).strip()
    if not key:
        return None
    run = _phase26_runs_by_id.get(key)
    if not isinstance(run, dict):
        return None
    return run


def _phase26_workflow_message(workflow: Dict[str, Any]) -> str:
    steps = workflow.get("steps", [])
    step_count = len(steps) if isinstance(steps, list) else 0
    return f"Workflow '{workflow.get('name', '')}' has {step_count} steps."


def _phase26_status_message(run: Dict[str, Any]) -> str:
    status = str(run.get("status", "UNKNOWN"))
    workflow_name = str(run.get("workflow_name", "workflow"))
    completed = run.get("completed_steps", [])
    pending = run.get("pending_steps", [])
    completed_count = len(completed) if isinstance(completed, list) else 0
    pending_count = len(pending) if isinstance(pending, list) else 0
    current = str(run.get("current_step_id", "")).strip()
    if status == "RUNNING" and current:
        return (
            f"Workflow '{workflow_name}' is running at step '{current}'. "
            f"Completed {completed_count}, pending {pending_count}."
        )
    if status == "COMPLETED":
        return f"Workflow '{workflow_name}' completed with {completed_count} executed steps."
    if status == "CANCELED":
        return f"Workflow '{workflow_name}' is canceled. Completed {completed_count} steps."
    if status == "FAILED":
        failure = _normalize(str(run.get("failure", "")))
        if failure:
            return f"Workflow '{workflow_name}' failed: {failure}"
        return f"Workflow '{workflow_name}' failed."
    return f"Workflow '{workflow_name}' is pending approval."


def _phase26_status_payload(run: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "workflow_status",
        "executed": False,
        "workflow_run": copy.deepcopy(run),
        "message": _phase26_status_message(run),
    }


def _phase26_validate_schema(schema: Dict[str, Any]) -> str | None:
    if not isinstance(schema, dict):
        return "Workflow parameters schema must be a JSON object."
    for key, value in schema.items():
        if not isinstance(key, str) or not key.strip():
            return "Workflow parameter names must be non-empty strings."
        if not isinstance(value, dict):
            return f"Workflow parameter '{key}' must map to an object."
        if "required" in value and not isinstance(value.get("required"), bool):
            return f"Workflow parameter '{key}' requires a boolean 'required' field."
    return None


def _phase26_validate_steps(*, steps: List[Dict[str, Any]], schema: Dict[str, Any]) -> str | None:
    if not isinstance(steps, list) or not steps:
        return "Workflow must include at least one step."

    supported = _phase26_supported_step_intents()
    seen: set[str] = set()
    dependencies: Dict[str, List[str]] = {}
    schema_keys = {str(name).strip().lower() for name in schema.keys() if isinstance(name, str) and str(name).strip()}
    for item in steps:
        if not isinstance(item, dict):
            return "Workflow steps must be objects."
        step_id = _normalize(str(item.get("step_id", "")))
        if not step_id:
            return "Each workflow step must include step_id."
        if step_id in seen:
            return f"Duplicate workflow step_id '{step_id}'."
        seen.add(step_id)

        intent = _normalize(str(item.get("intent", "")))
        if not intent:
            return f"Workflow step '{step_id}' is missing intent."
        if intent not in supported:
            return f"Workflow step '{step_id}' uses unknown intent '{intent}'."

        params = item.get("parameters", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return f"Workflow step '{step_id}' parameters must be an object."

        placeholders = _phase26_known_parameter_placeholders(params)
        unknown = sorted({token for token in placeholders if token not in schema_keys})
        if unknown:
            return (
                f"Workflow step '{step_id}' references unknown parameters: "
                + ", ".join(unknown)
                + "."
            )

        depends_on = item.get("depends_on", [])
        if depends_on is None:
            depends_on = []
        if not isinstance(depends_on, list):
            return f"Workflow step '{step_id}' depends_on must be a list."
        dependencies[step_id] = [_normalize(str(dep)) for dep in depends_on if _normalize(str(dep))]

    for step_id, deps in dependencies.items():
        for dep in deps:
            if dep not in seen:
                return f"Workflow step '{step_id}' depends on unknown step '{dep}'."

    visiting: set[str] = set()
    visited: set[str] = set()

    def _visit(step_id: str) -> bool:
        if step_id in visited:
            return True
        if step_id in visiting:
            return False
        visiting.add(step_id)
        for dep in dependencies.get(step_id, []):
            if not _visit(dep):
                return False
        visiting.remove(step_id)
        visited.add(step_id)
        return True

    for step_id in dependencies.keys():
        if not _visit(step_id):
            return "Workflow dependency graph contains a cycle."
    return None


def _phase26_order_steps(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    graph: Dict[str, List[str]] = {}
    indegree: Dict[str, int] = {}
    by_id: Dict[str, Dict[str, Any]] = {}
    for step in steps:
        step_id = _normalize(str(step.get("step_id", "")))
        if not step_id:
            continue
        deps = step.get("depends_on", [])
        deps = deps if isinstance(deps, list) else []
        normalized_deps = [_normalize(str(dep)) for dep in deps if _normalize(str(dep))]
        graph[step_id] = normalized_deps
        indegree.setdefault(step_id, 0)
        by_id[step_id] = step
    for step_id, deps in graph.items():
        for dep in deps:
            indegree.setdefault(dep, 0)
            indegree[step_id] = indegree.get(step_id, 0) + 1

    ordered: List[Dict[str, Any]] = []
    ready = sorted([step_id for step_id, degree in indegree.items() if degree == 0])
    while ready:
        step_id = ready.pop(0)
        if step_id in by_id:
            ordered.append(by_id[step_id])
        for candidate, deps in graph.items():
            if step_id not in deps:
                continue
            indegree[candidate] = max(0, indegree.get(candidate, 0) - 1)
            if indegree[candidate] == 0 and candidate not in ready:
                ready.append(candidate)
                ready.sort()
    if len(ordered) != len(by_id):
        return list(steps)
    return ordered


def _phase26_estimated_side_effects(steps: List[Dict[str, Any]]) -> List[str]:
    effects: List[str] = []
    for step in steps:
        intent = _normalize(str(step.get("intent", "")))
        if intent in _FILESYSTEM_WRITE_INTENTS:
            effects.append(f"{intent}: filesystem mutation")
        elif intent == "delegate_to_agent":
            effects.append("delegate_to_agent: delegated content generation/capture")
        elif intent in {"persist_note", "refactor_file"}:
            effects.append(f"{intent}: may route to governed write path")
    return effects


def _phase26_parse_define_payload(normalized: str) -> Dict[str, Any] | None:
    lowered = normalized.lower()
    if not lowered.startswith("define workflow named "):
        return None
    remainder = _normalize(normalized[len("define workflow named "):])
    if not remainder:
        return {"name": "", "description": "", "schema_json": "", "steps_json": ""}

    pieces = remainder.split(maxsplit=1)
    name = _normalize(pieces[0])
    tail = _normalize(pieces[1]) if len(pieces) > 1 else ""
    description = ""
    schema_json = ""
    steps_json = ""

    marker_schema = re.search(r"\bschema\b", tail, flags=re.IGNORECASE)
    marker_steps = re.search(r"\bsteps\b", tail, flags=re.IGNORECASE)

    if marker_schema is not None and marker_steps is not None:
        if marker_schema.start() < marker_steps.start():
            description = _normalize(tail[: marker_schema.start()])
            schema_json = _normalize(tail[marker_schema.end() : marker_steps.start()])
            steps_json = _normalize(tail[marker_steps.end() :])
        else:
            description = _normalize(tail[: marker_steps.start()])
            steps_json = _normalize(tail[marker_steps.end() : marker_schema.start()])
            schema_json = _normalize(tail[marker_schema.end() :])
    elif marker_schema is not None:
        description = _normalize(tail[: marker_schema.start()])
        schema_json = _normalize(tail[marker_schema.end() :])
    elif marker_steps is not None:
        description = _normalize(tail[: marker_steps.start()])
        steps_json = _normalize(tail[marker_steps.end() :])
    else:
        description = tail

    if description.lower().startswith("description "):
        description = _normalize(description[len("description "):])
    return {
        "name": name,
        "description": description,
        "schema_json": schema_json,
        "steps_json": steps_json,
    }


def _phase26_workflow_by_name(project_id: str, workflow_name: str) -> Dict[str, Any] | None:
    name = _normalize(workflow_name).lower()
    if not name:
        return None
    for item in _phase26_workflows_for_project(project_id):
        if not isinstance(item, dict):
            continue
        if _normalize(str(item.get("name", ""))).lower() == name:
            return item
    return None


def _phase26_parse_preview_or_run_params(normalized: str) -> Dict[str, Any]:
    match = re.search(
        r"\b(?:preview|run)\s+workflow\s+[a-zA-Z0-9._-]+\s+with\s+(.+)$",
        normalized,
        flags=re.IGNORECASE,
    )
    if match is None:
        return {}
    return _phase26_parse_parameter_bindings(match.group(1))


def _phase26_required_parameter_error(schema: Dict[str, Any], bindings: Dict[str, str]) -> str | None:
    required = _phase26_schema_required_parameters(schema)
    missing = [name for name in required if name not in bindings]
    if missing:
        return "Missing required workflow parameters: " + ", ".join(sorted(missing)) + "."
    return None


def _phase26_next_step_id(run: Dict[str, Any]) -> str:
    steps = run.get("steps_ordered", [])
    if not isinstance(steps, list):
        return ""
    index = int(run.get("current_step_index", 0) or 0)
    if index < 0 or index >= len(steps):
        return ""
    step = steps[index]
    return _normalize(str(step.get("step_id", "")))


def _phase23_goals_for_project(project_id: str) -> List[Dict[str, Any]]:
    key = str(project_id).strip()
    if not key:
        return []
    if key not in _phase23_goals_by_project_id:
        _phase23_goals_by_project_id[key] = []
    return _phase23_goals_by_project_id[key]


def _phase23_tasks_for_project(project_id: str) -> List[Dict[str, Any]]:
    key = str(project_id).strip()
    if not key:
        return []
    if key not in _phase23_tasks_by_project_id:
        _phase23_tasks_by_project_id[key] = []
    return _phase23_tasks_by_project_id[key]


def _phase23_goal_to_dict(goal: ProjectGoal) -> Dict[str, Any]:
    return {
        "goal_id": goal.goal_id,
        "project_id": goal.project_id,
        "description": goal.description,
        "created_at": goal.created_at,
        "metadata": copy.deepcopy(goal.metadata),
    }


def _phase23_task_to_dict(task: ProjectTask) -> Dict[str, Any]:
    return {
        "task_id": task.task_id,
        "project_id": task.project_id,
        "goal_id": task.goal_id,
        "description": task.description,
        "status": task.status,
        "dependencies": list(task.dependencies),
        "created_at": task.created_at,
        "completed_at": task.completed_at,
        "metadata": copy.deepcopy(task.metadata),
    }


def _phase23_goal_by_id(project_id: str, goal_id: str) -> Dict[str, Any] | None:
    key = str(goal_id).strip()
    if not key:
        return None
    for goal in _phase23_goals_for_project(project_id):
        if not isinstance(goal, dict):
            continue
        if str(goal.get("goal_id", "")) == key:
            return goal
    return None


def _phase23_task_by_id(project_id: str, task_id: str) -> Dict[str, Any] | None:
    key = str(task_id).strip()
    if not key:
        return None
    for task in _phase23_tasks_for_project(project_id):
        if not isinstance(task, dict):
            continue
        if str(task.get("task_id", "")) == key:
            return task
    return None


def _phase23_resolve_goal(project_id: str, goal_ref: str | None) -> tuple[Dict[str, Any] | None, str | None]:
    goals = [goal for goal in _phase23_goals_for_project(project_id) if isinstance(goal, dict)]
    if not goals:
        return None, "No goals defined for this project."
    ref = str(goal_ref or "").strip()
    if ref:
        goal = _phase23_goal_by_id(project_id, ref)
        if goal is not None:
            return goal, None
        ref_lower = _normalize(ref).lower()
        matching = [
            goal
            for goal in goals
            if ref_lower and ref_lower in _normalize(str(goal.get("description", ""))).lower()
        ]
        if len(matching) == 1:
            return matching[0], None
        if len(matching) > 1:
            return None, f"Goal reference '{ref}' is ambiguous. Use goal_id."
        return None, f"Goal '{ref}' was not found."
    if len(goals) == 1:
        return goals[0], None
    return None, "Multiple goals exist. Specify a goal_id."


def _phase23_resolve_task(project_id: str, task_ref: str) -> tuple[Dict[str, Any] | None, str | None]:
    ref = str(task_ref).strip()
    task = _phase23_task_by_id(project_id, ref)
    if task is not None:
        return task, None
    ref_lower = _normalize(ref).lower()
    tasks = [task for task in _phase23_tasks_for_project(project_id) if isinstance(task, dict)]
    matching = [
        task
        for task in tasks
        if ref_lower and ref_lower in _normalize(str(task.get("description", ""))).lower()
    ]
    if len(matching) == 1:
        return matching[0], None
    if len(matching) > 1:
        return None, f"Task reference '{task_ref}' is ambiguous. Use task_id."
    return None, f"Task '{task_ref}' was not found."


def _phase23_task_requires_approval(task: Dict[str, Any]) -> bool:
    metadata = task.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    if bool(metadata.get("requires_approval", False)):
        return True
    if bool(metadata.get("involves_write", False)):
        return True
    return False


def _phase23_refresh_blocked_statuses(project_id: str) -> None:
    tasks = _phase23_tasks_for_project(project_id)
    task_index = {
        str(task.get("task_id", "")): task
        for task in tasks
        if isinstance(task, dict) and str(task.get("task_id", ""))
    }
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if str(task.get("status", "")) == "COMPLETED":
            continue
        dependencies = task.get("dependencies", [])
        dependencies = dependencies if isinstance(dependencies, list) else []
        blocked = False
        for dependency in dependencies:
            dep = task_index.get(str(dependency))
            if not isinstance(dep, dict):
                blocked = True
                break
            if str(dep.get("status", "")) != "COMPLETED":
                blocked = True
                break
        task["status"] = "BLOCKED" if blocked else "PENDING"


def _phase23_order_tasks(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(tasks, key=lambda item: str(item.get("created_at", "")))


def _phase23_task_write_hint(description: str) -> bool:
    lowered = _normalize(description).lower()
    return any(
        re.search(rf"\b{re.escape(token)}\b", lowered)
        for token in ("write", "update", "modify", "refactor", "create", "replace", "add", "convert")
    )


def _phase23_llm_task_descriptions(project_state: Dict[str, Any], goal_description: str) -> List[str]:
    model_config = _load_model_config()
    if llm_api is None or not model_config:
        return []
    artifacts = project_state.get("artifacts", [])
    artifact_paths = [str(item.get("path", "")) for item in artifacts if isinstance(item, dict)]
    prompt_payload = {
        "task": "Propose 3-6 actionable project tasks as plain text lines.",
        "goal": goal_description,
        "project_name": str(project_state.get("name", "")),
        "artifact_paths": artifact_paths[:100],
        "constraints": {
            "max_tasks": 6,
            "return_json": True,
            "output_schema": {"tasks": ["string"]},
        },
    }
    messages = [
        {"role": "system", "content": "Return JSON only with key 'tasks' as an array of short strings."},
        {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=True)},
    ]
    try:
        raw = llm_api.get_completion(messages, model_config)
    except Exception:
        return []
    if not isinstance(raw, str):
        return []
    try:
        payload = json.loads(raw)
    except Exception:
        return []
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        return []
    cleaned = []
    for item in tasks:
        text = _normalize(str(item))
        if text:
            cleaned.append(text)
    return cleaned


def _decompose_goal_to_tasks(project_state: Dict[str, Any], goal_description: str) -> List[ProjectTask]:
    project_id = str(project_state.get("project_id", ""))
    artifacts = project_state.get("artifacts", [])
    artifacts = artifacts if isinstance(artifacts, list) else []
    artifact_paths = [str(item.get("path", "")) for item in artifacts if isinstance(item, dict)]
    now = _utcnow().isoformat()

    descriptions = _phase23_llm_task_descriptions(project_state, goal_description)
    if not descriptions:
        descriptions = []
        if not artifact_paths:
            descriptions.append(f"Create initial project artifacts to support goal: {goal_description}.")
        else:
            if any(path.lower().endswith((".html", ".htm")) for path in artifact_paths):
                descriptions.append("Align HTML pages with the project goal.")
            if any(path.lower().endswith(".css") for path in artifact_paths):
                descriptions.append("Apply stylesheet updates needed for the goal.")
            descriptions.append("Review current artifacts and update content for goal alignment.")
        descriptions.append("Verify cross-artifact consistency and links.")
        descriptions.append("Prepare final readiness checklist for goal completion.")

    tasks: List[ProjectTask] = []
    previous_task_id = ""
    for index, description in enumerate(descriptions, start=1):
        text = _normalize(description)
        if not text:
            continue
        dependencies = [previous_task_id] if previous_task_id else []
        status = "BLOCKED" if dependencies else "PENDING"
        task = ProjectTask(
            task_id=f"task-{uuid.uuid4()}",
            project_id=project_id,
            goal_id="",
            description=text,
            status=status,
            dependencies=dependencies,
            created_at=now,
            completed_at=None,
            metadata={
                "advisory": True,
                "order_index": index,
                "involves_write": _phase23_task_write_hint(text),
            },
        )
        tasks.append(task)
        previous_task_id = task.task_id
    return tasks


def handle_define_project_goal(project: Dict[str, Any], goal_description: str) -> Dict[str, Any]:
    project_id = str(project.get("project_id", ""))
    description = _normalize(goal_description)
    goal = ProjectGoal(
        goal_id=f"goal-{uuid.uuid4()}",
        project_id=project_id,
        description=description,
        created_at=_utcnow().isoformat(),
        metadata={},
    )
    _phase23_goals_for_project(project_id).append(_phase23_goal_to_dict(goal))
    _phase22_update_project_timestamp(project_id)
    return {
        "type": "project_goal_defined",
        "executed": False,
        "project": copy.deepcopy(project),
        "goal": _phase23_goal_to_dict(goal),
        "message": f"Defined goal {goal.goal_id} for project '{project.get('name', '')}': {description}",
    }


def handle_list_project_goals(project: Dict[str, Any]) -> Dict[str, Any]:
    project_id = str(project.get("project_id", ""))
    goals = [copy.deepcopy(goal) for goal in _phase23_goals_for_project(project_id) if isinstance(goal, dict)]
    return {
        "type": "project_goals",
        "executed": False,
        "project": copy.deepcopy(project),
        "goals": goals,
        "message": "\n".join([f"{goal['goal_id']}: {goal['description']}" for goal in goals]) if goals else "No goals defined for this project.",
    }


def handle_describe_project_goal(project: Dict[str, Any], goal: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "project_goal",
        "executed": False,
        "project": copy.deepcopy(project),
        "goal": copy.deepcopy(goal),
        "message": f"{goal.get('goal_id', '')}: {goal.get('description', '')}",
    }


def handle_list_project_tasks(project: Dict[str, Any], goal_id: str | None = None) -> Dict[str, Any]:
    project_id = str(project.get("project_id", ""))
    _phase23_refresh_blocked_statuses(project_id)
    tasks = [task for task in _phase23_tasks_for_project(project_id) if isinstance(task, dict)]
    if goal_id:
        tasks = [task for task in tasks if str(task.get("goal_id", "")) == str(goal_id)]
    ordered = _phase23_order_tasks(tasks)
    return {
        "type": "project_tasks",
        "executed": False,
        "project": copy.deepcopy(project),
        "tasks": copy.deepcopy(ordered),
        "message": "\n".join([f"{task['task_id']} [{task['status']}]: {task['description']}" for task in ordered]) if ordered else "No tasks recorded for this project.",
    }


def handle_task_status(project: Dict[str, Any], task: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "task_status",
        "executed": False,
        "project": copy.deepcopy(project),
        "task": copy.deepcopy(task),
        "message": f"{task.get('task_id', '')} is {task.get('status', '')}.",
    }


def handle_propose_next_tasks(project: Dict[str, Any], goal: Dict[str, Any]) -> Dict[str, Any]:
    project_id = str(project.get("project_id", ""))
    goal_id = str(goal.get("goal_id", ""))
    existing = [task for task in _phase23_tasks_for_project(project_id) if isinstance(task, dict)]
    existing_for_goal = {
        _normalize(str(task.get("description", ""))).lower(): task
        for task in existing
        if str(task.get("goal_id", "")) == goal_id
    }
    candidate_tasks = _decompose_goal_to_tasks(project, str(goal.get("description", "")))
    merged: List[Dict[str, Any]] = []
    for candidate in candidate_tasks:
        description_key = _normalize(candidate.description).lower()
        if description_key in existing_for_goal:
            merged.append(existing_for_goal[description_key])
            continue
        task_dict = _phase23_task_to_dict(
            ProjectTask(
                task_id=candidate.task_id,
                project_id=project_id,
                goal_id=goal_id,
                description=candidate.description,
                status=candidate.status,
                dependencies=candidate.dependencies,
                created_at=candidate.created_at,
                completed_at=candidate.completed_at,
                metadata=candidate.metadata,
            )
        )
        _phase23_tasks_for_project(project_id).append(task_dict)
        merged.append(task_dict)
    _phase23_refresh_blocked_statuses(project_id)
    ordered = _phase23_order_tasks([task for task in _phase23_tasks_for_project(project_id) if str(task.get("goal_id", "")) == goal_id])
    return {
        "type": "project_tasks_proposed",
        "executed": False,
        "capture_eligible": True,
        "project": copy.deepcopy(project),
        "goal": copy.deepcopy(goal),
        "tasks": copy.deepcopy(ordered),
        "message": "\n".join([f"{task['task_id']} [{task['status']}]: {task['description']}" for task in ordered]),
    }


def handle_complete_task(project: Dict[str, Any], task: Dict[str, Any]) -> Dict[str, Any]:
    task["status"] = "COMPLETED"
    task["completed_at"] = _utcnow().isoformat()
    project_id = str(project.get("project_id", ""))
    _phase23_refresh_blocked_statuses(project_id)
    _phase22_update_project_timestamp(project_id)
    return {
        "type": "task_completed",
        "executed": False,
        "project": copy.deepcopy(project),
        "task": copy.deepcopy(task),
        "message": f"Task {task.get('task_id', '')} marked as COMPLETED.",
    }


def _phase24_milestones_for_project(project_id: str) -> List[Dict[str, Any]]:
    key = str(project_id).strip()
    if not key:
        return []
    if key not in _phase24_milestones_by_project_id:
        _phase24_milestones_by_project_id[key] = []
    return _phase24_milestones_by_project_id[key]


def _phase24_milestone_to_dict(milestone: ProjectMilestone) -> Dict[str, Any]:
    return {
        "milestone_id": milestone.milestone_id,
        "project_id": milestone.project_id,
        "title": milestone.title,
        "description": milestone.description,
        "associated_goals": list(milestone.associated_goals),
        "criteria": list(milestone.criteria),
        "status": milestone.status,
        "created_at": milestone.created_at,
        "achieved_at": milestone.achieved_at,
    }


def _phase24_milestone_by_id(project_id: str, milestone_id: str) -> Dict[str, Any] | None:
    key = str(milestone_id).strip()
    if not key:
        return None
    for milestone in _phase24_milestones_for_project(project_id):
        if not isinstance(milestone, dict):
            continue
        if str(milestone.get("milestone_id", "")) == key:
            return milestone
    return None


def _phase24_resolve_milestone(project_id: str, reference: str | None) -> tuple[Dict[str, Any] | None, str | None]:
    milestones = [item for item in _phase24_milestones_for_project(project_id) if isinstance(item, dict)]
    if not milestones:
        return None, "No milestones are defined for this project."
    ref = _normalize(str(reference or ""))
    if not ref:
        if len(milestones) == 1:
            return milestones[0], None
        return None, "Multiple milestones exist. Specify a milestone_id or title."
    direct = _phase24_milestone_by_id(project_id, ref)
    if direct is not None:
        return direct, None
    lowered = ref.lower()
    matching = [
        milestone
        for milestone in milestones
        if lowered in _normalize(str(milestone.get("title", ""))).lower()
        or lowered in _normalize(str(milestone.get("description", ""))).lower()
    ]
    if len(matching) == 1:
        return matching[0], None
    if len(matching) > 1:
        return None, f"Milestone reference '{ref}' is ambiguous. Use milestone_id."
    return None, f"Milestone '{ref}' was not found."


def _phase24_goal_is_complete(project_id: str, goal_id: str) -> bool:
    goal = _phase23_goal_by_id(project_id, goal_id)
    if goal is None:
        return False
    _phase23_refresh_blocked_statuses(project_id)
    tasks = [
        task
        for task in _phase23_tasks_for_project(project_id)
        if isinstance(task, dict) and str(task.get("goal_id", "")) == str(goal_id)
    ]
    if not tasks:
        return False
    return all(str(task.get("status", "")) == "COMPLETED" for task in tasks)


def _phase24_unfinished_tasks_for_goals(project_id: str, goal_ids: List[str]) -> List[Dict[str, Any]]:
    _phase23_refresh_blocked_statuses(project_id)
    goals = [str(goal_id).strip() for goal_id in goal_ids if str(goal_id).strip()]
    tasks = [task for task in _phase23_tasks_for_project(project_id) if isinstance(task, dict)]
    if goals:
        tasks = [task for task in tasks if str(task.get("goal_id", "")) in goals]
    return [task for task in tasks if str(task.get("status", "")) in {"PENDING", "BLOCKED"}]


def _phase24_milestone_compliance(project_id: str, milestone: Dict[str, Any]) -> tuple[bool, List[str]]:
    reasons: List[str] = []
    associated_goals = milestone.get("associated_goals", [])
    associated_goals = associated_goals if isinstance(associated_goals, list) else []
    associated_goal_ids = [str(goal_id).strip() for goal_id in associated_goals if str(goal_id).strip()]
    for goal_id in associated_goal_ids:
        if _phase23_goal_by_id(project_id, goal_id) is None:
            reasons.append(f"Associated goal '{goal_id}' does not exist.")
        elif not _phase24_goal_is_complete(project_id, goal_id):
            reasons.append(f"Associated goal '{goal_id}' is not complete.")
    criteria = milestone.get("criteria", [])
    criteria = criteria if isinstance(criteria, list) else []
    unfinished = _phase24_unfinished_tasks_for_goals(project_id, associated_goal_ids)
    for criterion in criteria:
        text = _normalize(str(criterion)).lower()
        if not text:
            continue
        if "all associated goals" in text and associated_goal_ids:
            if any(not _phase24_goal_is_complete(project_id, goal_id) for goal_id in associated_goal_ids):
                reasons.append("Criterion 'all associated goals' is not satisfied.")
        if "no pending tasks" in text:
            if unfinished:
                reasons.append("Criterion 'no pending tasks' is not satisfied.")
    return not reasons, reasons


def _phase24_project_completion_snapshot(project: Dict[str, Any], *, explicit_confirmation: bool) -> Dict[str, Any]:
    project_id = str(project.get("project_id", ""))
    milestones = [item for item in _phase24_milestones_for_project(project_id) if isinstance(item, dict)]
    achieved = [item for item in milestones if str(item.get("status", "")) == "ACHIEVED"]
    milestone_goal_ids: List[str] = []
    for milestone in milestones:
        goal_ids = milestone.get("associated_goals", [])
        goal_ids = goal_ids if isinstance(goal_ids, list) else []
        for goal_id in goal_ids:
            normalized = str(goal_id).strip()
            if normalized and normalized not in milestone_goal_ids:
                milestone_goal_ids.append(normalized)
    unfinished_tasks = _phase24_unfinished_tasks_for_goals(project_id, milestone_goal_ids)
    persisted_confirmation = bool(project.get("completion_confirmed", False))
    confirmed = persisted_confirmation or bool(explicit_confirmation)
    all_milestones_achieved = bool(milestones) and len(achieved) == len(milestones)
    no_pending = not unfinished_tasks
    complete = all_milestones_achieved and no_pending and confirmed
    next_steps: List[str] = []
    if not milestones:
        next_steps.append("Define at least one milestone.")
    elif not all_milestones_achieved:
        next_steps.append("Achieve all project milestones.")
    if unfinished_tasks:
        next_steps.append("Complete remaining pending/blocked tasks.")
    if not confirmed:
        next_steps.append("Provide explicit completion confirmation (for example: finalize project).")
    return {
        "is_complete": complete,
        "all_milestones_achieved": all_milestones_achieved,
        "no_pending_tasks": no_pending,
        "confirmation_received": confirmed,
        "milestone_count": len(milestones),
        "milestones_achieved": len(achieved),
        "unfinished_task_count": len(unfinished_tasks),
        "unfinished_tasks": copy.deepcopy(unfinished_tasks),
        "next_steps": next_steps,
    }


def _phase24_project_summary_text(project: Dict[str, Any]) -> str:
    project_id = str(project.get("project_id", ""))
    name = str(project.get("name", "project"))
    root = str(project.get("root_path", ""))
    artifacts = project.get("artifacts", [])
    artifacts = artifacts if isinstance(artifacts, list) else []
    goals = [goal for goal in _phase23_goals_for_project(project_id) if isinstance(goal, dict)]
    milestones = [item for item in _phase24_milestones_for_project(project_id) if isinstance(item, dict)]
    lines = [f"# Project Summary: {name}", f"Root: {root}", ""]
    lines.append("## Artifacts")
    if artifacts:
        lines.extend([f"- {item.get('path', '')}" for item in artifacts if isinstance(item, dict)])
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Goals")
    if goals:
        lines.extend([f"- {goal.get('goal_id', '')}: {goal.get('description', '')}" for goal in goals])
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Milestones")
    if milestones:
        lines.extend(
            [
                f"- {item.get('milestone_id', '')} [{item.get('status', '')}]: {item.get('title', '')}"
                for item in milestones
            ]
        )
    else:
        lines.append("- (none)")
    return "\n".join(lines)


def _phase24_archive_root(project: Dict[str, Any]) -> str:
    project_name = _phase22_slug(str(project.get("name", "project")))
    timestamp = _utcnow().strftime("%Y%m%d%H%M%S")
    return str((Path.home() / "sandbox" / "archives" / f"{project_name}_{timestamp}").resolve())


def _phase24_project_state(project: Dict[str, Any]) -> str:
    return _normalize(str(project.get("state", "active"))).lower() or "active"


def _phase24_project_is_writable(project: Dict[str, Any]) -> bool:
    return _phase24_project_state(project) == "active"


def _phase24_project_for_envelope(envelope: Envelope) -> Dict[str, Any] | None:
    explicit_project_id = _entity_string(envelope, "phase22_project_id") or _entity_string(envelope, "project_id")
    if explicit_project_id:
        project = _phase22_projects_by_id.get(explicit_project_id)
        if isinstance(project, dict):
            return project
    path = _entity_string(envelope, "path")
    if not path:
        return None
    return _phase22_project_for_path(path)


def _phase24_apply_write_guard(
    *,
    envelope: Envelope,
    normalized_utterance: str,
) -> tuple[Dict[str, Any] | None, Envelope]:
    if not _phase24_enabled:
        return None, envelope
    intent = str(envelope.get("intent", "")).strip()
    if intent not in _FILESYSTEM_WRITE_INTENTS:
        return None, envelope
    project = _phase24_project_for_envelope(envelope)
    if not isinstance(project, dict):
        return None, envelope
    state = _phase24_project_state(project)
    if state == "active":
        return None, envelope
    return _phase19_clarify_response(
        utterance=normalized_utterance,
        message=(
            f"Project '{project.get('name', '')}' is {state} and read-only. "
            "Reactivate or clone the project before writing."
        ),
    )


def handle_define_milestone(
    project: Dict[str, Any],
    *,
    title: str,
    description: str,
    associated_goals: List[str],
    criteria: List[str],
) -> Dict[str, Any]:
    project_id = str(project.get("project_id", ""))
    milestone = ProjectMilestone(
        milestone_id=f"ms-{uuid.uuid4()}",
        project_id=project_id,
        title=_normalize(title),
        description=_normalize(description),
        associated_goals=[str(goal_id).strip() for goal_id in associated_goals if str(goal_id).strip()],
        criteria=[_normalize(criterion) for criterion in criteria if _normalize(criterion)],
        status="PENDING",
        created_at=_utcnow().isoformat(),
        achieved_at=None,
    )
    _phase24_milestones_for_project(project_id).append(_phase24_milestone_to_dict(milestone))
    _phase22_update_project_timestamp(project_id)
    payload = _phase24_milestone_to_dict(milestone)
    return {
        "type": "project_milestone_defined",
        "executed": False,
        "project": copy.deepcopy(project),
        "milestone": payload,
        "message": f"Defined milestone {payload['milestone_id']}: {payload['title']}",
    }


def handle_list_milestones(project: Dict[str, Any]) -> Dict[str, Any]:
    project_id = str(project.get("project_id", ""))
    milestones = [copy.deepcopy(item) for item in _phase24_milestones_for_project(project_id) if isinstance(item, dict)]
    return {
        "type": "project_milestones",
        "executed": False,
        "project": copy.deepcopy(project),
        "milestones": milestones,
        "message": "\n".join(
            [f"{item.get('milestone_id', '')} [{item.get('status', '')}]: {item.get('title', '')}" for item in milestones]
        ) if milestones else "No milestones are defined for this project.",
    }


def handle_describe_milestone(project: Dict[str, Any], milestone: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "project_milestone",
        "executed": False,
        "project": copy.deepcopy(project),
        "milestone": copy.deepcopy(milestone),
        "message": (
            f"{milestone.get('milestone_id', '')} [{milestone.get('status', '')}]: "
            f"{milestone.get('title', '')}"
        ),
    }


def handle_achieve_milestone(project: Dict[str, Any], milestone: Dict[str, Any]) -> Dict[str, Any]:
    milestone["status"] = "ACHIEVED"
    milestone["achieved_at"] = _utcnow().isoformat()
    project_id = str(project.get("project_id", ""))
    _phase22_update_project_timestamp(project_id)
    return {
        "type": "project_milestone_achieved",
        "executed": False,
        "project": copy.deepcopy(project),
        "milestone": copy.deepcopy(milestone),
        "message": (
            f"Milestone {milestone.get('milestone_id', '')} "
            f"marked as ACHIEVED."
        ),
    }


def handle_project_completion_status(project: Dict[str, Any], *, explicit_confirmation: bool) -> Dict[str, Any]:
    snapshot = _phase24_project_completion_snapshot(project, explicit_confirmation=explicit_confirmation)
    return {
        "type": "project_completion_status",
        "executed": False,
        "project": copy.deepcopy(project),
        "completion": snapshot,
        "message": (
            "Project is complete."
            if snapshot["is_complete"]
            else "Project is not complete. " + " ".join(snapshot.get("next_steps", []))
        ),
    }


def _is_deprecated_engineer_mode_input(text: str) -> bool:
    lowered = _normalize(text).lower()
    return (
        lowered == "/engineer"
        or lowered.startswith("/engineer ")
        or lowered == "engineer mode"
        or lowered == "enter engineer mode"
        or lowered == "switch to engineer mode"
    )


def _phase17_filesystem_override_for_legacy_engineer_input(text: str) -> str | None:
    normalized = _normalize(text)
    lowered = normalized.lower()
    if not lowered.startswith("/engineer "):
        return None
    candidate = _normalize(normalized[len("/engineer "):])
    if not candidate:
        return None
    if _parse_filesystem_intent(candidate) is None:
        return None
    return candidate


def _phase9_normalize_utterance(text: str) -> str:
    normalized = _normalize(text)
    filesystem_override = _phase17_filesystem_override_for_legacy_engineer_input(normalized)
    if filesystem_override is not None:
        return filesystem_override
    if _parse_phase26_intent(normalized) is not None:
        return normalized
    if _parse_phase25_intent(normalized) is not None:
        return normalized
    if _parse_phase24_intent(normalized) is not None:
        return normalized
    if _parse_phase23_intent(normalized) is not None:
        return normalized
    if _parse_phase22_intent(normalized) is not None:
        return normalized
    if _parse_persist_note_intent(normalized) is not None:
        return normalized
    lowered = normalized.lower()
    if _parse_filesystem_intent(normalized) is not None:
        return normalized
    if lowered.startswith("save ") and "file" in lowered and "home directory" in lowered:
        # Route natural-language save requests through existing PLAN policy/approval flow.
        return re.sub(r"(?i)^save\b", "create", normalized, count=1)
    return normalized


def _phase9_engineer_mode_info_response(utterance: str) -> Dict[str, Any]:
    normalized = _normalize(utterance)
    return {
        "type": "mode_info",
        "executed": False,
        "envelope": interpret_utterance(normalized),
        "message": _PHASE9_ENGINEER_MODE_DEPRECATED_MESSAGE,
    }


def _envelope(
    *,
    utterance: str,
    lane: Lane,
    intent: str,
    entities: List[Dict[str, Any]] | None = None,
    confidence: float,
    requires_approval: bool,
    risk_level: str,
    allowed: bool,
    reason: str,
    next_prompt: str,
) -> Envelope:
    # Confidence is deterministic heuristic metadata in [0.0, 1.0].
    return {
        "utterance": utterance,
        "lane": lane,
        "intent": intent,
        "entities": entities or [],
        "confidence": confidence,
        "requires_approval": requires_approval,
        "policy": {
            "risk_level": risk_level,
            "allowed": allowed,
            "reason": reason,
        },
        "next_prompt": next_prompt,
    }


def _looks_ambiguous(normalized: str) -> bool:
    if not normalized:
        return True
    tokens = re.findall(r"[a-zA-Z0-9]+", normalized.lower())
    if len(tokens) <= 1:
        return True
    # Treat nonsense-like two-token inputs as ambiguous by default.
    if len(tokens) == 2 and all(len(t) <= 5 for t in tokens):
        common = {"create", "file", "help", "plan", "engineer", "chat", "hello"}
        if not any(t in common for t in tokens):
            return True
    return False


def _is_action_like(normalized: str) -> bool:
    lowered = normalized.lower()
    return any(keyword in lowered for keyword in _ACTION_KEYWORDS)


def _has_content_generation_trigger(normalized: str) -> bool:
    lowered = normalized.lower()
    return any(re.search(rf"\b{re.escape(keyword)}\b", lowered) for keyword in _CONTENT_GENERATION_KEYWORDS)


def _has_content_generation_execution_signals(normalized: str) -> bool:
    if _parse_filesystem_intent(normalized) is not None:
        return True
    lowered = normalized.lower()
    if any(phrase in lowered for phrase in _CONTENT_GENERATION_EXECUTION_PHRASES):
        return True
    return any(re.search(rf"\b{re.escape(term)}\b", lowered) for term in _CONTENT_GENERATION_EXECUTION_TERMS)


def _is_ambiguous_content_generation_request(normalized: str) -> bool:
    lowered = normalized.lower()
    return bool(
        re.fullmatch(
            r"(?:please\s+)?(?:generate|propose|draft|write|sketch|suggest)(?:\s+please)?",
            lowered,
        )
    )


def _content_generation_route(normalized: str) -> str:
    if not _has_content_generation_trigger(normalized):
        return "none"
    if _has_content_generation_execution_signals(normalized):
        return "none"
    if _is_ambiguous_content_generation_request(normalized):
        return "clarify"
    return "content_generation"


def _is_conversational(normalized: str) -> bool:
    lowered = normalized.lower()
    if lowered in {"hi", "hello", "hey", "thanks", "thank you"}:
        return True
    return any(lowered.startswith(prefix + " ") for prefix in _CONVERSATIONAL_PREFIXES)


def _strip_wrapping_quotes(value: str) -> str:
    text = _normalize(value).strip()
    if len(text) >= 2 and ((text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'"))):
        return text[1:-1].strip()
    return text


def _phase17_location_hint(raw: str | None) -> str:
    lowered = str(raw or "").lower()
    if "home" in lowered:
        return "home"
    if "workspace" in lowered or "sandbox" in lowered:
        return "workspace"
    return "workspace"


def _phase17_allowed_roots() -> List[Path]:
    roots = [Path.home().resolve(), _WORKSPACE_ROOT.resolve()]
    deduped: List[Path] = []
    for root in roots:
        if root not in deduped:
            deduped.append(root)
    return deduped


def _phase17_is_within(path: Path, root: Path) -> bool:
    try:
        return path.is_relative_to(root)
    except Exception:
        return False


def _phase17_normalize_path(raw_path: str, *, location_hint: str) -> tuple[str | None, str | None]:
    path_text = _strip_wrapping_quotes(raw_path)
    if not path_text:
        return None, "Missing file path."

    base = Path.home() if location_hint == "home" else _WORKSPACE_ROOT
    candidate = Path(path_text).expanduser()
    if not candidate.is_absolute():
        candidate = (base / candidate)
    normalized = candidate.resolve(strict=False)

    allowed = any(_phase17_is_within(normalized, root) for root in _phase17_allowed_roots())
    if not allowed:
        return None, f"Path outside allowed scope: {normalized}"
    return str(normalized), None


def _phase17_envelope_for_intent(
    *,
    utterance: str,
    intent: str,
    entities: List[Dict[str, Any]],
    requires_approval: bool,
    risk_level: str,
    reason: str,
) -> Envelope:
    return _envelope(
        utterance=utterance,
        lane="PLAN",
        intent=intent,
        entities=entities,
        confidence=0.96,
        requires_approval=requires_approval,
        risk_level=risk_level,
        allowed=True,
        reason=reason,
        next_prompt="",
    )


def _phase17_clarify_envelope(*, utterance: str, message: str) -> Envelope:
    return _envelope(
        utterance=utterance,
        lane="CLARIFY",
        intent="clarify.request_context",
        entities=[],
        confidence=0.35,
        requires_approval=False,
        risk_level="low",
        allowed=True,
        reason="Filesystem request is missing required parameters.",
        next_prompt=message,
    )


def _phase19_notes_root() -> Path:
    return (Path.home() / Path(*_PHASE19_NOTES_SUBDIR)).resolve()


def _phase19_default_filename() -> str:
    return f"note-{_utcnow().strftime('%Y%m%d-%H%M')}.txt"


def _phase19_normalize_filename(raw: str) -> str | None:
    candidate = _strip_wrapping_quotes(raw).strip()
    if not candidate:
        return None
    if "/" in candidate or "\\" in candidate or ".." in candidate:
        return None
    candidate = re.sub(r"\s+", "-", candidate)
    if not _PHASE19_FILENAME_PATTERN.fullmatch(candidate):
        return None
    if "." not in candidate:
        candidate = f"{candidate}.txt"
    return candidate


def _phase19_extract_filename(normalized: str) -> str:
    named_match = re.search(
        r"(?:file|note)\s+(?:named|called)\s+(?P<filename>[A-Za-z0-9._-]+)",
        normalized,
        flags=re.IGNORECASE,
    )
    if named_match is not None:
        return str(named_match.group("filename"))

    as_match = re.search(r"\bas\s+(?P<filename>[A-Za-z0-9._-]+\.txt)\s*$", normalized, flags=re.IGNORECASE)
    if as_match is not None:
        return str(as_match.group("filename"))
    return ""


def _phase19_extract_inline_content(normalized: str) -> str:
    quoted = re.search(r'"(?P<content>[^"]+)"', normalized)
    if quoted is not None:
        return _strip_wrapping_quotes(quoted.group("content"))

    create_with = re.search(r"\bcreate (?:a )?note with (?P<content>.+)$", normalized, flags=re.IGNORECASE)
    if create_with is not None:
        return _strip_wrapping_quotes(create_with.group("content"))

    suffix = re.search(
        r"(?:idea|thought|text|snippet)\s*[:\-]\s*(?P<content>.+)$",
        normalized,
        flags=re.IGNORECASE,
    )
    if suffix is not None:
        return _strip_wrapping_quotes(suffix.group("content"))
    return ""


def _phase19_generation_hint(normalized: str) -> bool:
    lowered = normalized.lower()
    if re.search(r"\b(?:this|an|a)\s+(?:idea|thought)\b", lowered):
        return True
    if lowered.startswith("create a note") and "with " not in lowered:
        return True
    return False


def _phase19_last_response_reference(normalized: str) -> bool:
    lowered = normalized.lower()
    return any(
        phrase in lowered
        for phrase in (
            "above text",
            "last response",
            "this text",
            "this snippet",
        )
    )


def _phase19_working_set_reference(normalized: str) -> bool:
    lowered = normalized.lower().strip(" .!?")
    simple = re.fullmatch(
        r"(?:please\s+)?(?:save|store|put)\s+"
        r"(?:this|that|it|(?:the\s+)?current(?:\s+(?:note|page|file|draft|concept|text|snippet|thought|idea|working_set))?)"
        r"(?:\s+as\s+(?:a\s+)?note)?(?:\s+please)?",
        lowered,
    )
    return simple is not None


def _phase19_clarify_response(*, utterance: str, message: str) -> tuple[Dict[str, Any], Envelope]:
    envelope = _phase17_clarify_envelope(utterance=utterance, message=message)
    return {
        "type": "no_action",
        "executed": False,
        "envelope": envelope,
        "message": "",
    }, envelope


def _phase19_generate_note_content(utterance: str) -> str:
    model_config = _load_model_config()
    if llm_api is not None and model_config:
        prompt_payload = {
            "task": "Generate a minimal note to persist.",
            "utterance": utterance,
            "constraints": {
                "max_lines": 3,
                "max_chars": 240,
                "return_text_only": True,
            },
        }
        messages = [
            {
                "role": "system",
                "content": "Generate plain text only. No markdown, no code fences.",
            },
            {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=True)},
        ]
        try:
            raw = llm_api.get_completion(messages, model_config)
            if isinstance(raw, str):
                text = raw.strip()
                if text:
                    return text
        except Exception:
            pass
    return "Note saved."


def _phase21_extract_write_target(normalized: str) -> tuple[str, str]:
    target = ""
    location_hint = "workspace"
    explicit = re.search(
        r"(?:to|into)\s+file(?:\s+(?:named|called))?\s+(?P<path>[A-Za-z0-9._/\-]+)"
        r"(?:\s+in\s+(?P<loc>my home directory|home directory|my workspace|workspace|sandbox))?",
        normalized,
        flags=re.IGNORECASE,
    )
    if explicit is not None:
        target = _strip_wrapping_quotes(str(explicit.group("path")))
        location_hint = _phase17_location_hint(explicit.group("loc"))
        return target, location_hint

    named = re.search(
        r"\b(?:file|module)\s+(?:named|called)\s+(?P<path>[A-Za-z0-9._/\-]+)",
        normalized,
        flags=re.IGNORECASE,
    )
    if named is not None:
        target = _strip_wrapping_quotes(str(named.group("path")))
    return target, location_hint


def _phase21_detect_intent(normalized: str) -> str | None:
    lowered = normalized.lower()
    if any(re.search(rf"\b{re.escape(term)}\b", lowered) for term in ("run", "execute", "delete", "remove")):
        return None

    if re.search(r"\brefactor\b", lowered) and re.search(r"\b(file|module)\b", lowered):
        return "refactor_file"
    if "split this file" in lowered or "function names" in lowered:
        return "refactor_file"

    transform_patterns = (
        r"\btransform\b",
        r"\bconvert\b",
        r"\bformat\b",
        r"\buppercase\b",
        r"\blowercase\b",
        r"\bwrap this\b",
        r"\brefactor this snippet\b",
        r"\bextract this into\b",
    )
    if any(re.search(pattern, lowered) for pattern in transform_patterns):
        return "transform_content"

    revise_patterns = (
        r"\brevise\b",
        r"\bupdate\b",
        r"\bchange\b",
        r"\bmake this\b",
        r"\badd a section\b",
        r"\bmake .* more concise\b",
    )
    if any(re.search(pattern, lowered) for pattern in revise_patterns):
        return "revise_content"

    return None


def _phase21_request_requires_write(intent: str, normalized: str) -> bool:
    lowered = normalized.lower()
    if intent == "refactor_file":
        return True
    explicit_write_phrases = (
        "to file",
        "into file",
        "write back",
        "save back",
        "overwrite",
        "rewrite file",
        "replace file",
    )
    if any(phrase in lowered for phrase in explicit_write_phrases):
        return True
    if re.search(r"\b(?:this|that|current)\s+(?:file|page)\b", lowered):
        return True
    return False


def _phase21_is_ambiguous_request(normalized: str, intent: str) -> bool:
    lowered = normalized.lower().strip(" .!?")
    base = r"(?:this|that|it|(?:the\s+)?current(?:\s+(?:note|page|file|draft|concept|text|snippet|thought|idea|working_set))?)"
    if intent == "revise_content":
        return bool(re.fullmatch(rf"(?:please\s+)?(?:revise|update|change|make)\s+{base}(?:\s+please)?", lowered))
    if intent == "transform_content":
        return bool(re.fullmatch(rf"(?:please\s+)?(?:transform|convert|format)\s+{base}(?:\s+please)?", lowered))
    if intent == "refactor_file":
        return bool(re.fullmatch(rf"(?:please\s+)?refactor\s+{base}(?:\s+please)?", lowered))
    return False


def _phase21_extract_instruction(normalized: str, intent: str) -> str:
    lowered = normalized.lower()
    if intent == "transform_content":
        if "uppercase" in lowered:
            return "convert to uppercase"
        if "lowercase" in lowered:
            return "convert to lowercase"
        markdown = re.search(r"\bformat .+ as markdown\b", lowered)
        if markdown is not None:
            return "format as markdown"
        wrap_match = re.search(r"\bwrap .+ in a div with class ([a-zA-Z0-9_-]+)\b", normalized, flags=re.IGNORECASE)
        if wrap_match is not None:
            return f"wrap in div class {wrap_match.group(1)}"
    target_match = re.search(r"\b(?:to|with|into)\s+(.+)$", normalized, flags=re.IGNORECASE)
    if target_match is not None:
        return _normalize(target_match.group(1))
    return normalized


def _phase21_read_content_from_path(path: str) -> str:
    candidate = _normalize(path)
    if not candidate:
        return ""
    try:
        file_path = Path(candidate).resolve()
    except Exception:
        return ""
    if not file_path.exists() or not file_path.is_file():
        return ""
    try:
        roots = _phase17_allowed_roots()
        if not any(_phase17_is_within(file_path, root) for root in roots):
            return ""
    except Exception:
        return ""
    try:
        return file_path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _phase21_generate_transformed_content(
    *,
    original_content: str,
    request: str,
    content_type: str,
    intent: str,
) -> str:
    lowered = request.lower()
    if "uppercase" in lowered:
        return original_content.upper()
    if "lowercase" in lowered:
        return original_content.lower()
    if "format as markdown" in lowered:
        return f"```markdown\n{original_content}\n```"
    div_match = re.search(r"\bdiv class ([a-zA-Z0-9_-]+)\b", request, flags=re.IGNORECASE)
    if div_match is not None:
        klass = div_match.group(1)
        return f'<div class="{klass}">\n{original_content}\n</div>'

    model_config = _load_model_config()
    if llm_api is not None and model_config:
        prompt_payload = {
            "task": "Revise or transform content exactly as requested.",
            "intent": intent,
            "content_type": content_type,
            "request": request,
            "original_content": original_content,
            "constraints": {
                "preserve_intent": True,
                "return_text_only": True,
                "no_explanations": True,
            },
        }
        messages = [
            {
                "role": "system",
                "content": "You revise text, markup, or code. Return only transformed content.",
            },
            {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=True)},
        ]
        try:
            raw = llm_api.get_completion(messages, model_config)
            if isinstance(raw, str):
                text = raw.strip()
                if text:
                    return text
        except Exception:
            pass
    return original_content


def _phase21_next_revision_label(base_label: str) -> str:
    normalized = _normalize_capture_label(base_label or "revision")
    normalized = re.sub(r"_rev\d+$", "", normalized)
    if not normalized:
        normalized = "revision"
    existing = _capture_store.get_last(2000)
    pattern = re.compile(rf"^{re.escape(normalized)}_rev(\d+)$", flags=re.IGNORECASE)
    max_index = 0
    for item in existing:
        label = str(getattr(item, "label", "")).strip()
        match = pattern.fullmatch(label)
        if match is None:
            continue
        try:
            max_index = max(max_index, int(match.group(1)))
        except Exception:
            continue
    return f"{normalized}_rev{max_index + 1}"


def _phase21_capture_revision(
    *,
    revised_text: str,
    original_label: str,
    previous_content_id: str,
    content_type: str,
    source: str,
    previous_path: str,
) -> CapturedContent:
    revision_label = _phase21_next_revision_label(original_label or "revision")
    captured = CapturedContent(
        content_id=f"cc-{uuid.uuid4()}",
        type=content_type or "text_note",
        source=source,
        text=revised_text,
        timestamp=_utcnow().isoformat(),
        origin_turn_id=str(current_correlation_id() or ""),
        label=revision_label,
        session_id=str(current_session_id() or ""),
    )
    _capture_store.append(captured)
    _emit_observability_event(
        phase="phase21",
        event_type="revision_captured",
        metadata={
            "content_id": captured.content_id,
            "label": captured.label,
            "previous_content_id": previous_content_id,
            "source": source,
        },
    )
    _phase20_set_working_set(
        {
            "content_id": captured.content_id,
            "label": captured.label,
            "type": _phase20_normalize_working_set_type(content_type),
            "source": "phase21_revision",
            "path": previous_path,
            "text": revised_text,
            "origin_turn_id": captured.origin_turn_id,
            "previous_content_id": previous_content_id,
            "previous_label": original_label,
        },
        reason="phase21_revision_capture",
    )
    return captured


def _phase21_default_write_path(*, captured: CapturedContent, content_type: str) -> str:
    suffix = ".txt"
    normalized_type = _phase20_normalize_working_set_type(content_type)
    if normalized_type == "html_page":
        suffix = ".html"
    elif normalized_type == "code_file":
        suffix = ".py"
    filename = f"{_normalize_capture_label(captured.label or captured.content_id)}{suffix}"
    return str((_WORKSPACE_ROOT / filename).resolve())


def _phase21_write_summary(*, intent: str, captured: CapturedContent, original_text: str, revised_text: str) -> str:
    label = captured.label or captured.content_id
    return (
        f"Prepared {intent} and captured '{label}'. "
        f"Length {len(original_text)} -> {len(revised_text)} characters."
    )


def _phase22_extract_artifact_hint(normalized: str) -> str:
    lowered = normalized.lower()
    if "stylesheet" in lowered:
        return "*.css"
    if "html" in lowered or "page" in lowered:
        return "*.html"
    if "note" in lowered:
        return "*.txt"
    direct = re.search(r"\bopen\s+([a-zA-Z0-9._/\-]+)\b", normalized, flags=re.IGNORECASE)
    if direct is not None:
        return _strip_wrapping_quotes(direct.group(1))
    return ""


def _phase26_extract_workflow_name(normalized: str, *, verbs: List[str]) -> str:
    for verb in verbs:
        pattern = rf"\b{re.escape(verb)}\s+workflow\s+([a-zA-Z0-9._-]+)\b"
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match is not None:
            return _normalize(match.group(1))
    return ""


def _parse_phase26_intent(normalized: str) -> Envelope | None:
    if not _phase26_enabled:
        return None
    if not normalized:
        return None
    lowered = normalized.lower()

    if lowered.startswith("define workflow named "):
        payload = _phase26_parse_define_payload(normalized) or {}
        entities = [
            {"name": "workflow_name", "value": str(payload.get("name", "")), "normalized": str(payload.get("name", ""))},
            {
                "name": "workflow_description",
                "value": str(payload.get("description", "")),
                "normalized": str(payload.get("description", "")),
            },
            {
                "name": "workflow_schema_json",
                "value": str(payload.get("schema_json", "")),
                "normalized": str(payload.get("schema_json", "")),
            },
            {
                "name": "workflow_steps_json",
                "value": str(payload.get("steps_json", "")),
                "normalized": str(payload.get("steps_json", "")),
            },
        ]
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="define_workflow",
            entities=entities,
            requires_approval=False,
            risk_level="low",
            reason="Workflow definitions are metadata-only.",
        )

    if re.search(r"\b(?:list|show)\s+workflows\b", lowered):
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="list_workflows",
            entities=[],
            requires_approval=False,
            risk_level="low",
            reason="Workflow listing is read-only.",
        )

    if re.search(r"\bworkflow\s+status\b", lowered) or lowered in {"status workflow", "workflow status"}:
        name = _phase26_extract_workflow_name(normalized, verbs=["status", "describe", "show"])
        entities: List[Dict[str, Any]] = []
        if name:
            entities.append({"name": "workflow_name", "value": name, "normalized": name})
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="workflow_status",
            entities=entities,
            requires_approval=False,
            risk_level="low",
            reason="Workflow status checks are read-only.",
        )

    if re.search(r"\bdescribe\s+workflow\b", lowered):
        name = _phase26_extract_workflow_name(normalized, verbs=["describe"])
        entities = []
        if name:
            entities.append({"name": "workflow_name", "value": name, "normalized": name})
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="describe_workflow",
            entities=entities,
            requires_approval=False,
            risk_level="low",
            reason="Workflow description is read-only.",
        )

    if re.search(r"\bpreview\s+workflow\b", lowered):
        name = _phase26_extract_workflow_name(normalized, verbs=["preview"])
        params = _phase26_parse_preview_or_run_params(normalized)
        entities = []
        if name:
            entities.append({"name": "workflow_name", "value": name, "normalized": name})
        if params:
            encoded = json.dumps(params, ensure_ascii=True)
            entities.append({"name": "workflow_parameters_json", "value": encoded, "normalized": encoded})
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="preview_workflow",
            entities=entities,
            requires_approval=False,
            risk_level="low",
            reason="Workflow preview is dry-run only.",
        )

    if re.search(r"\brun\s+workflow\b", lowered):
        name = _phase26_extract_workflow_name(normalized, verbs=["run"])
        params = _phase26_parse_preview_or_run_params(normalized)
        entities = []
        if name:
            entities.append({"name": "workflow_name", "value": name, "normalized": name})
        if params:
            encoded = json.dumps(params, ensure_ascii=True)
            entities.append({"name": "workflow_parameters_json", "value": encoded, "normalized": encoded})
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="run_workflow",
            entities=entities,
            requires_approval=True,
            risk_level="medium",
            reason="Workflow run requires explicit approval.",
        )

    if re.search(r"\b(?:cancel\s+(?:the\s+)?(?:current\s+)?workflow|workflow\s+cancel)\b", lowered):
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="workflow_cancel",
            entities=[],
            requires_approval=True,
            risk_level="medium",
            reason="Workflow cancellation requires explicit approval.",
        )

    return None


def _parse_phase25_intent(normalized: str) -> Envelope | None:
    if not _phase25_enabled:
        return None
    if not normalized:
        return None
    lowered = normalized.lower()

    if re.search(r"\b(?:list|show|what are)\s+delegation\s+capabilities\b", lowered):
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="list_delegation_capabilities",
            entities=[],
            requires_approval=False,
            risk_level="low",
            reason="Delegation capability listing is read-only.",
        )

    if re.search(r"\bdescribe\s+(?:the\s+)?result\s+of\s+(?:the\s+)?last\s+delegation\b", lowered) or re.search(
        r"\bdescribe\s+(?:the\s+)?last\s+delegation\s+result\b",
        lowered,
    ):
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="describe_delegation_result",
            entities=[],
            requires_approval=False,
            risk_level="low",
            reason="Delegation result description is read-only.",
        )

    if "delegate" not in lowered:
        return None
    agent_type = _phase25_extract_agent_type(normalized)
    task = _phase25_extract_task(normalized)
    entities: List[Dict[str, Any]] = []
    if agent_type:
        entities.append({"name": "delegation_agent_type", "value": agent_type, "normalized": agent_type})
    if task:
        entities.append({"name": "delegation_task", "value": task, "normalized": task})
    return _phase17_envelope_for_intent(
        utterance=normalized,
        intent="delegate_to_agent",
        entities=entities,
        requires_approval=True,
        risk_level="medium",
        reason="Delegation orchestration requires explicit approval before sub-agent execution.",
    )


def _phase24_extract_milestone_definition(normalized: str) -> Dict[str, Any] | None:
    patterns = (
        r"\bdefine\s+(?:a\s+)?milestone\s*:?\s*(?P<title>.+?)(?:\s+with\s+criteria\s+(?P<criteria>.+))?$",
        r"\bcreate\s+(?:a\s+)?milestone\s*:?\s*(?P<title>.+?)(?:\s+with\s+criteria\s+(?P<criteria>.+))?$",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match is None:
            continue
        title = _strip_wrapping_quotes(str(match.group("title")))
        if not title:
            continue
        criteria_text = _strip_wrapping_quotes(str(match.group("criteria") or ""))
        criteria = []
        if criteria_text:
            criteria = [
                _normalize(part)
                for part in re.split(r"(?:;|,|\band\b)", criteria_text, flags=re.IGNORECASE)
                if _normalize(part)
            ]
        goals = re.findall(r"\b(goal-[a-z0-9-]+)\b", normalized, flags=re.IGNORECASE)
        goals = [str(goal).strip() for goal in goals if str(goal).strip()]
        if goals and not criteria:
            criteria = ["all associated goals completed"]
        return {
            "title": title,
            "description": title,
            "criteria": criteria,
            "associated_goals": goals,
        }
    return None


def _phase24_extract_milestone_reference(normalized: str) -> str:
    milestone_id = re.search(r"\b(ms-[a-z0-9-]+)\b", normalized, flags=re.IGNORECASE)
    if milestone_id is not None:
        return str(milestone_id.group(1))
    named = re.search(r"\bmilestone\s+(?:named|called)\s+(.+)$", normalized, flags=re.IGNORECASE)
    if named is not None:
        return _strip_wrapping_quotes(str(named.group(1)))
    generic = re.search(r"\bmilestone\s+(.+)$", normalized, flags=re.IGNORECASE)
    if generic is not None:
        return _strip_wrapping_quotes(str(generic.group(1)))
    return ""


def _phase24_has_explicit_completion_confirmation(normalized: str) -> bool:
    lowered = normalized.lower()
    return bool(
        re.search(
            r"\b(i confirm|confirm project completion|mark (?:this|the) project as complete|yes[, ]+it is complete)\b",
            lowered,
        )
    )


def _parse_phase24_intent(normalized: str) -> Envelope | None:
    if not _phase24_enabled:
        return None
    if not normalized:
        return None
    lowered = normalized.lower()

    definition = _phase24_extract_milestone_definition(normalized)
    if definition is not None:
        entities: List[Dict[str, Any]] = [
            {"name": "milestone_title", "value": definition["title"], "normalized": definition["title"]},
            {"name": "milestone_description", "value": definition["description"], "normalized": definition["description"]},
            {
                "name": "milestone_criteria_json",
                "value": json.dumps(definition["criteria"], ensure_ascii=True),
                "normalized": json.dumps(definition["criteria"], ensure_ascii=True),
            },
            {
                "name": "milestone_goal_ids_json",
                "value": json.dumps(definition["associated_goals"], ensure_ascii=True),
                "normalized": json.dumps(definition["associated_goals"], ensure_ascii=True),
            },
        ]
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="define_milestone",
            entities=entities,
            requires_approval=False,
            risk_level="low",
            reason="Milestone definition updates project metadata only.",
        )

    if re.search(r"\b(?:list|show)\s+milestones?\b", lowered):
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="list_milestones",
            entities=[],
            requires_approval=False,
            risk_level="low",
            reason="Milestone listing is read-only.",
        )

    if re.search(r"\b(?:describe|show|explain)\s+milestone\b", lowered):
        reference = _phase24_extract_milestone_reference(normalized)
        entities: List[Dict[str, Any]] = []
        if reference:
            entities.append({"name": "milestone_ref", "value": reference, "normalized": reference})
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="describe_milestone",
            entities=entities,
            requires_approval=False,
            risk_level="low",
            reason="Milestone description is read-only.",
        )

    if re.search(r"\b(?:mark|set|achieve)\s+milestone\b", lowered) and re.search(r"\bachieved\b|\bdone\b|\bcomplete\b", lowered):
        reference = _phase24_extract_milestone_reference(normalized)
        entities: List[Dict[str, Any]] = []
        if reference:
            entities.append({"name": "milestone_ref", "value": reference, "normalized": reference})
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="achieve_milestone",
            entities=entities,
            requires_approval=False,
            risk_level="low",
            reason="Milestone achievement updates metadata after deterministic criteria checks.",
        )

    if re.search(r"\b(?:is|show)\s+(?:this|the|current)?\s*project\s+complete\b", lowered) or "project completion status" in lowered:
        confirmed = "true" if _phase24_has_explicit_completion_confirmation(normalized) else "false"
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="project_completion_status",
            entities=[{"name": "project_completion_confirm", "value": confirmed, "normalized": confirmed}],
            requires_approval=False,
            risk_level="low",
            reason="Project completion status is advisory read-only output.",
        )

    if re.search(r"\bfinalize\s+(?:this|the|current)?\s*project\b", lowered):
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="finalize_project",
            entities=[],
            requires_approval=True,
            risk_level="high",
            reason="Project finalization requires explicit approval.",
        )

    if re.search(r"\barchive\s+(?:this|the|current)?\s*project\b", lowered):
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="archive_project",
            entities=[],
            requires_approval=True,
            risk_level="high",
            reason="Project archival moves project artifacts and requires explicit approval.",
        )

    return None


def _phase23_extract_goal_description(normalized: str) -> str:
    patterns = (
        r"\bdefine(?:\s+the)?\s+project\s+goal\s*:\s*(?P<goal>.+)$",
        r"\bdefine(?:\s+the)?\s+project\s+goal\s+(?P<goal>.+)$",
        r"\bset(?:\s+the)?\s+project\s+goal\s+to\s+(?P<goal>.+)$",
        r"\bproject\s+goal\s*:\s*(?P<goal>.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match is None:
            continue
        return _strip_wrapping_quotes(str(match.group("goal")))
    return ""


def _phase23_extract_goal_reference(normalized: str) -> str:
    goal_id = re.search(r"\b(goal-[a-z0-9-]+)\b", normalized, flags=re.IGNORECASE)
    if goal_id is not None:
        return str(goal_id.group(1))
    named = re.search(r"\bgoal\s+(?:named|called)\s+(.+)$", normalized, flags=re.IGNORECASE)
    if named is not None:
        return _strip_wrapping_quotes(str(named.group(1)))
    for_goal = re.search(r"\bfor\s+(?:this|the)\s+goal\s+(.+)$", normalized, flags=re.IGNORECASE)
    if for_goal is not None:
        return _strip_wrapping_quotes(str(for_goal.group(1)))
    return ""


def _phase23_extract_task_reference(normalized: str) -> str:
    task_id = re.search(r"\b(task-[a-z0-9-]+)\b", normalized, flags=re.IGNORECASE)
    if task_id is not None:
        return str(task_id.group(1))
    described = re.search(r"\btask\s+(?:named|called)\s+(.+)$", normalized, flags=re.IGNORECASE)
    if described is not None:
        return _strip_wrapping_quotes(str(described.group(1)))
    return ""


def _parse_phase23_intent(normalized: str) -> Envelope | None:
    if not _phase23_enabled:
        return None
    if not normalized:
        return None
    lowered = normalized.lower()

    goal_description = _phase23_extract_goal_description(normalized)
    if goal_description:
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="define_project_goal",
            entities=[{"name": "project_goal_description", "value": goal_description, "normalized": goal_description}],
            requires_approval=False,
            risk_level="low",
            reason="Project goal definition is advisory metadata with no side effects.",
        )

    if re.search(r"\b(?:list|show)\s+(?:the\s+)?goals?\b", lowered) and (
        "project" in lowered or "site" in lowered or "this goal" in lowered
    ):
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="list_project_goals",
            entities=[],
            requires_approval=False,
            risk_level="low",
            reason="Project goals listing is read-only.",
        )

    if re.search(r"\b(?:describe|show|explain)\s+(?:the\s+)?goal\b", lowered):
        goal_ref = _phase23_extract_goal_reference(normalized)
        entities: List[Dict[str, Any]] = []
        if goal_ref:
            entities.append({"name": "project_goal_id", "value": goal_ref, "normalized": goal_ref})
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="describe_project_goal",
            entities=entities,
            requires_approval=False,
            risk_level="low",
            reason="Project goal description is read-only.",
        )

    if (
        "next tasks" in lowered
        or "tasks are needed" in lowered
        or "tasks needed" in lowered
        or "propose next tasks" in lowered
    ) and ("goal" in lowered or "project" in lowered or "site" in lowered):
        goal_ref = _phase23_extract_goal_reference(normalized)
        entities: List[Dict[str, Any]] = []
        if goal_ref:
            entities.append({"name": "project_goal_id", "value": goal_ref, "normalized": goal_ref})
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="propose_next_tasks",
            entities=entities,
            requires_approval=False,
            risk_level="low",
            reason="Task decomposition is advisory-only output.",
        )

    if re.search(r"\b(?:list|show)\b.*\btasks\b", lowered):
        goal_ref = _phase23_extract_goal_reference(normalized)
        entities: List[Dict[str, Any]] = []
        if goal_ref:
            entities.append({"name": "project_goal_id", "value": goal_ref, "normalized": goal_ref})
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="list_project_tasks",
            entities=entities,
            requires_approval=False,
            risk_level="low",
            reason="Project task listing is read-only.",
        )

    if re.search(r"\b(?:task status|status of task|what is the status of task)\b", lowered):
        task_ref = _phase23_extract_task_reference(normalized)
        entities: List[Dict[str, Any]] = []
        if task_ref:
            entities.append({"name": "project_task_id", "value": task_ref, "normalized": task_ref})
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="task_status",
            entities=entities,
            requires_approval=False,
            risk_level="low",
            reason="Task status lookup is read-only.",
        )

    if re.search(r"\b(?:mark|set)\s+task\b", lowered) and re.search(r"\b(?:completed?|done)\b", lowered):
        task_ref = _phase23_extract_task_reference(normalized)
        entities: List[Dict[str, Any]] = []
        if task_ref:
            entities.append({"name": "project_task_id", "value": task_ref, "normalized": task_ref})
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="complete_task",
            entities=entities,
            requires_approval=False,
            risk_level="medium",
            reason="Task completion may require approval when side effects are expected.",
        )

    if re.search(r"\bcomplete\s+task\b", lowered):
        task_ref = _phase23_extract_task_reference(normalized)
        entities: List[Dict[str, Any]] = []
        if task_ref:
            entities.append({"name": "project_task_id", "value": task_ref, "normalized": task_ref})
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="complete_task",
            entities=entities,
            requires_approval=False,
            risk_level="medium",
            reason="Task completion may require approval when side effects are expected.",
        )

    return None


def _parse_phase22_intent(normalized: str) -> Envelope | None:
    if not _phase22_enabled:
        return None
    if not normalized:
        return None
    lowered = normalized.lower()

    if re.search(
        r"\b(?:create|start|build)\s+(?:a\s+)?(?:new\s+)?project(?:\s+(?:for|as|named|called)\b|$)",
        lowered,
    ):
        name = _phase22_extract_project_name(normalized)
        location_hint = "home"
        root_name = name or "project"
        root_path = str((Path.home() / "sandbox" / root_name).resolve())
        entities = [
            {"name": "project_name", "value": name or "project", "normalized": name or "project"},
            {"name": "project_root_path", "value": root_path, "normalized": root_path},
            {"name": "path_location_hint", "value": location_hint, "normalized": location_hint},
        ]
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="create_project",
            entities=entities,
            requires_approval=False,
            risk_level="low",
            reason="Project creation sets session-scoped metadata without filesystem side effects.",
        )

    if re.search(r"\bdelete\s+(?:this|the|current)?\s*project\b", lowered):
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="delete_project",
            entities=[],
            requires_approval=True,
            risk_level="high",
            reason="Project deletion is metadata-destructive and requires explicit approval.",
        )

    if re.search(r"\b(?:list|show)\s+(?:all\s+)?files?\s+in\s+(?:this|the|current)\s+project\b", lowered):
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="list_project_artifacts",
            entities=[],
            requires_approval=False,
            risk_level="low",
            reason="Project artifact listing is read-only introspection.",
        )

    if re.search(r"\bwhat\s+project\s+am\s+i\s+working\s+on\b", lowered) or lowered in {"current project", "this project"}:
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="list_project_artifacts",
            entities=[{"name": "project_diagnostics", "value": "true", "normalized": "true"}],
            requires_approval=False,
            risk_level="low",
            reason="Project diagnostics are advisory and read-only.",
        )

    if re.search(r"\bshow\s+next\s+steps?\s+for\s+(?:this|the|current)\s+project\b", lowered):
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="project_documentation_generate",
            entities=[{"name": "project_next_steps", "value": "true", "normalized": "true"}],
            requires_approval=False,
            risk_level="low",
            reason="Project next-step guidance is read-only advisory output.",
        )

    if re.search(r"\b(?:open|show)\b", lowered) and ("project" in lowered or "site" in lowered):
        artifact_hint = _phase22_extract_artifact_hint(normalized)
        entities: List[Dict[str, Any]] = []
        if artifact_hint:
            entities.append({"name": "project_artifact_hint", "value": artifact_hint, "normalized": artifact_hint})
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="open_project_artifact",
            entities=entities,
            requires_approval=False,
            risk_level="low",
            reason="Opening project artifact is read-only introspection.",
        )

    if re.search(r"\brefactor\s+all\b", lowered) and ("project" in lowered or "site" in lowered):
        request = _normalize(normalized)
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="project_wide_refactor",
            entities=[{"name": "phase22_request", "value": request, "normalized": request}],
            requires_approval=True,
            risk_level="medium",
            reason="Project-wide refactor composes governed multi-file writes with approval.",
        )

    if re.search(r"\b(?:generate|build)\s+(?:project\s+)?documentation\b", lowered) or (
        "table of contents" in lowered and ("project" in lowered or "site" in lowered)
    ):
        request = _normalize(normalized)
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="project_documentation_generate",
            entities=[{"name": "phase22_request", "value": request, "normalized": request}],
            requires_approval=False,
            risk_level="low",
            reason="Project documentation generation is review-only output.",
        )

    if re.search(r"\badd\b", lowered) and ("project" in lowered or "site" in lowered):
        request = _normalize(normalized)
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="update_project",
            entities=[{"name": "phase22_request", "value": request, "normalized": request}],
            requires_approval=True,
            risk_level="medium",
            reason="Project update may require governed write operations.",
        )

    return None


def _parse_phase21_intent(normalized: str) -> Envelope | None:
    if not _phase21_enabled:
        return None
    if not normalized:
        return None

    intent = _phase21_detect_intent(normalized)
    if intent is None:
        return None
    if _phase21_is_ambiguous_request(normalized, intent):
        return _phase17_clarify_envelope(
            utterance=normalized,
            message="What specific revision or transformation do you want me to apply?",
        )

    write_requested = _phase21_request_requires_write(intent, normalized)
    target_path, location_hint = _phase21_extract_write_target(normalized)
    instruction = _phase21_extract_instruction(normalized, intent)
    entities: List[Dict[str, Any]] = [
        {"name": "phase21_request", "value": instruction, "normalized": instruction},
        {"name": "phase21_write", "value": "true" if write_requested else "false", "normalized": "true" if write_requested else "false"},
    ]
    if target_path:
        entities.extend(
            [
                {"name": "path", "value": target_path, "normalized": target_path},
                {"name": "path_location_hint", "value": location_hint, "normalized": location_hint},
            ]
        )
    return _phase17_envelope_for_intent(
        utterance=normalized,
        intent=intent,
        entities=entities,
        requires_approval=write_requested,
        risk_level="medium",
        reason="Phase 21 revision/transformation request routed through governed composite handling.",
    )


def _parse_persist_note_intent(normalized: str) -> Envelope | None:
    if not _phase19_enabled:
        return None
    if not normalized:
        return None
    lowered = normalized.lower()
    has_note_word = bool(re.search(r"\bnote\b", lowered))
    has_file_word = bool(re.search(r"\bfile\b", lowered))
    working_set_reference = _phase19_working_set_reference(normalized)
    if not any(re.search(rf"\b{verb}\b", lowered) for verb in ("save", "store", "write", "create", "put")):
        return None
    if not (has_note_word or has_file_word or "sandbox" in lowered or working_set_reference):
        return None
    content_tokens_present = any(
        token in lowered
        for token in (
            "idea",
            "thought",
            "text",
            "snippet",
            "above",
            "last response",
            "this",
        )
    )
    captured_reference = bool(re.search(r"\bthat [a-z0-9_-]+\b", lowered) and has_note_word)

    if not captured_reference and not content_tokens_present and "create a note with" not in lowered:
        return None

    explicit_file_target = re.search(r"\bto file\s+(?P<target>[A-Za-z0-9._/\-]+)", lowered)
    if explicit_file_target is not None and not has_note_word:
        target_token = str(explicit_file_target.group("target"))
        if target_token not in {"a", "an", "the", "my", "in"}:
            return None

    filesystem_candidate = _parse_filesystem_intent(normalized)
    if filesystem_candidate is not None and str(filesystem_candidate.get("intent", "")) in _FILESYSTEM_INTENTS:
        return None

    inline_content = _phase19_extract_inline_content(normalized)
    filename_raw = _phase19_extract_filename(normalized)
    references_last_response = _phase19_last_response_reference(normalized)
    generation_hint = _phase19_generation_hint(normalized)
    if (
        not inline_content
        and not references_last_response
        and not generation_hint
        and not captured_reference
        and not working_set_reference
    ):
        return None

    entities: List[Dict[str, Any]] = []
    if inline_content:
        entities.append({"name": "persist_note_content", "value": inline_content, "normalized": inline_content})
    if filename_raw:
        entities.append({"name": "persist_note_filename", "value": filename_raw, "normalized": filename_raw})
    if references_last_response:
        entities.append({"name": "persist_note_reference", "value": "last_response", "normalized": "last_response"})
    if working_set_reference:
        entities.append({"name": "persist_note_reference", "value": "working_set", "normalized": "working_set"})
    if generation_hint:
        entities.append({"name": "persist_note_generate", "value": "true", "normalized": "true"})

    return _phase17_envelope_for_intent(
        utterance=normalized,
        intent=_PHASE19_PERSIST_NOTE_INTENT,
        entities=entities,
        requires_approval=True,
        risk_level="medium",
        reason="Persist-note request composes to governed write_file with explicit approval.",
    )


def _parse_filesystem_intent(normalized: str) -> Envelope | None:
    if not normalized:
        return None
    lowered = normalized.lower()

    create = re.fullmatch(
        r"create (?:a )?(?:blank |empty )?file(?: called| named| at path) (?P<path>.+?)(?: in (?P<loc>my home directory|home directory|my workspace|workspace|sandbox))?$",
        normalized,
        flags=re.IGNORECASE,
    )
    if create is not None:
        location_hint = _phase17_location_hint(create.group("loc"))
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="create_file",
            entities=[
                {"name": "path", "value": _strip_wrapping_quotes(create.group("path")), "normalized": None},
                {"name": "path_location_hint", "value": location_hint, "normalized": location_hint},
                {"name": "contents", "value": "", "normalized": ""},
            ],
            requires_approval=True,
            risk_level="medium",
            reason="Create-file request requires approval before execution.",
        )
    if re.fullmatch(
        r"create (?:a )?(?:blank |empty )?file(?: in (?:my home directory|home directory|my workspace|workspace|sandbox))?$",
        lowered,
        flags=re.IGNORECASE,
    ):
        return _phase17_clarify_envelope(
            utterance=normalized,
            message="What filename or path should I create?",
        )

    save_captured = re.fullmatch(
        r"save captured (?P<label>[a-z0-9_-]+) to file (?:named|called) (?P<path>.+?)(?: in (?P<loc>my home directory|home directory|my workspace|workspace|sandbox))?$",
        normalized,
        flags=re.IGNORECASE,
    )
    if save_captured is not None:
        location_hint = _phase17_location_hint(save_captured.group("loc"))
        label = _normalize_capture_label(save_captured.group("label"))
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="write_file",
            entities=[
                {"name": "path", "value": _strip_wrapping_quotes(save_captured.group("path")), "normalized": None},
                {"name": "path_location_hint", "value": location_hint, "normalized": location_hint},
                {"name": "captured_content_label", "value": label, "normalized": label},
            ],
            requires_approval=True,
            risk_level="medium",
            reason="Write-file request requires approval before execution.",
        )

    save_that = re.fullmatch(
        r"save that (?P<label>[a-z0-9_-]+) to (?:a )?file(?: named| called)? (?P<path>.+?)(?: in (?P<loc>my home directory|home directory|my workspace|workspace|sandbox))?$",
        normalized,
        flags=re.IGNORECASE,
    )
    if save_that is not None:
        location_hint = _phase17_location_hint(save_that.group("loc"))
        label = _normalize_capture_label(save_that.group("label"))
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="write_file",
            entities=[
                {"name": "path", "value": _strip_wrapping_quotes(save_that.group("path")), "normalized": None},
                {"name": "path_location_hint", "value": location_hint, "normalized": location_hint},
                {"name": "captured_content_label", "value": label, "normalized": label},
            ],
            requires_approval=True,
            risk_level="medium",
            reason="Write-file request requires approval before execution.",
        )

    write = re.fullmatch(
        r"write (?:text )?(?P<contents>.+?) to file (?P<path>.+?)(?: in (?P<loc>my home directory|home directory|my workspace|workspace|sandbox))?$",
        normalized,
        flags=re.IGNORECASE,
    )
    if write is not None:
        location_hint = _phase17_location_hint(write.group("loc"))
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="write_file",
            entities=[
                {"name": "path", "value": _strip_wrapping_quotes(write.group("path")), "normalized": None},
                {"name": "path_location_hint", "value": location_hint, "normalized": location_hint},
                {"name": "contents", "value": _strip_wrapping_quotes(write.group("contents")), "normalized": None},
            ],
            requires_approval=True,
            risk_level="medium",
            reason="Write-file request requires approval before execution.",
        )
    if lowered.startswith("write") and "to file" in lowered:
        return _phase17_clarify_envelope(
            utterance=normalized,
            message="Please provide both file contents and a target filename/path.",
        )

    append = re.fullmatch(
        r"append (?:text )?(?P<contents>.+?) to file (?P<path>.+?)(?: in (?P<loc>my home directory|home directory|my workspace|workspace|sandbox))?$",
        normalized,
        flags=re.IGNORECASE,
    )
    if append is not None:
        location_hint = _phase17_location_hint(append.group("loc"))
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="append_file",
            entities=[
                {"name": "path", "value": _strip_wrapping_quotes(append.group("path")), "normalized": None},
                {"name": "path_location_hint", "value": location_hint, "normalized": location_hint},
                {"name": "contents", "value": _strip_wrapping_quotes(append.group("contents")), "normalized": None},
            ],
            requires_approval=True,
            risk_level="medium",
            reason="Append-file request requires approval before execution.",
        )
    if lowered.startswith("append") and "to file" in lowered:
        return _phase17_clarify_envelope(
            utterance=normalized,
            message="Please provide both text to append and the target file path.",
        )

    read_file = re.fullmatch(
        r"read file (?P<path>.+?)(?: from (?P<loc>my home directory|home directory|my workspace|workspace|sandbox))?$",
        normalized,
        flags=re.IGNORECASE,
    )
    if read_file is not None:
        location_hint = _phase17_location_hint(read_file.group("loc"))
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="read_file",
            entities=[
                {"name": "path", "value": _strip_wrapping_quotes(read_file.group("path")), "normalized": None},
                {"name": "path_location_hint", "value": location_hint, "normalized": location_hint},
            ],
            requires_approval=False,
            risk_level="low",
            reason="Read-file request is read-only and may execute without approval.",
        )
    if lowered in {"read file", "read a file"}:
        return _phase17_clarify_envelope(
            utterance=normalized,
            message="What file path should I read?",
        )

    delete_file = re.fullmatch(
        r"delete (?:the )?file(?: at path)? (?P<path>.+?)(?: from (?P<loc>my home directory|home directory|my workspace|workspace|sandbox))?$",
        normalized,
        flags=re.IGNORECASE,
    )
    if delete_file is not None:
        location_hint = _phase17_location_hint(delete_file.group("loc"))
        return _phase17_envelope_for_intent(
            utterance=normalized,
            intent="delete_file",
            entities=[
                {"name": "path", "value": _strip_wrapping_quotes(delete_file.group("path")), "normalized": None},
                {"name": "path_location_hint", "value": location_hint, "normalized": location_hint},
            ],
            requires_approval=True,
            risk_level="high",
            reason="Delete-file request requires approval before execution.",
        )
    if lowered in {"delete file", "delete the file", "delete the file at path"}:
        return _phase17_clarify_envelope(
            utterance=normalized,
            message="What file path should I delete?",
        )
    return None


def _normalize_capture_label(raw: str) -> str:
    text = _normalize(raw).strip(" .,:;\"'()[]{}")
    text = re.sub(r"\s+", "-", text)
    return text


def _parse_capture_request(normalized: str) -> Dict[str, Any] | None:
    if not normalized:
        return None
    lowered = normalized.lower()
    if not (lowered.startswith("capture") or lowered.startswith("store") or lowered.startswith("remember")):
        return None

    simple = re.fullmatch(
        r"capture (?:this|this content|last response|the last response)(?: (?:as|with label) (.+))?",
        normalized,
        flags=re.IGNORECASE,
    )
    if simple is not None:
        raw_label = simple.group(1) or ""
        return {
            "valid": True,
            "target": "last_response",
            "label": _normalize_capture_label(raw_label),
            "reason": "",
        }

    store = re.fullmatch(
        r"store this content with label (.+)",
        normalized,
        flags=re.IGNORECASE,
    )
    if store is not None:
        return {
            "valid": True,
            "target": "last_response",
            "label": _normalize_capture_label(store.group(1)),
            "reason": "",
        }

    remember = re.fullmatch(
        r"remember (?:the )?last response as (.+)",
        normalized,
        flags=re.IGNORECASE,
    )
    if remember is not None:
        return {
            "valid": True,
            "target": "last_response",
            "label": _normalize_capture_label(remember.group(1)),
            "reason": "",
        }

    return {
        "valid": False,
        "target": "",
        "label": "",
        "reason": "Ambiguous capture request. Use explicit syntax like 'capture this' or 'remember the last response as <label>'.",
    }


def _is_capture_request(normalized: str) -> bool:
    return _parse_capture_request(normalized) is not None


def _phase16_last_response_candidate() -> Dict[str, Any] | None:
    session_key = (current_session_id() or "").strip()
    if session_key and session_key in _phase16_last_response_by_session:
        return copy.deepcopy(_phase16_last_response_by_session[session_key])
    if _phase16_last_response_global is None:
        return None
    return copy.deepcopy(_phase16_last_response_global)


def _phase16_capture_response(
    *,
    envelope: Envelope,
    normalized_utterance: str,
) -> Dict[str, Any]:
    request = _parse_capture_request(normalized_utterance)
    if request is None or not request.get("valid"):
        return {
            "type": "capture_rejected",
            "executed": False,
            "envelope": envelope,
            "message": str((request or {}).get("reason") or "Invalid capture request."),
        }

    target = _phase16_last_response_candidate()
    if target is None:
        return {
            "type": "capture_rejected",
            "executed": False,
            "envelope": envelope,
            "message": "Capture rejected: no prior assistant response is available in this session.",
        }

    captured_text = str(target.get("text", "")).strip()
    if not captured_text:
        return {
            "type": "capture_rejected",
            "executed": False,
            "envelope": envelope,
            "message": "Capture rejected: target content is empty.",
        }

    label = str(request.get("label", "")).strip()
    session_id = str(target.get("session_id", "")).strip()
    origin_turn_id = str(target.get("origin_turn_id", "")).strip()
    source = str(target.get("source", "assistant_response")).strip() or "assistant_response"

    captured = CapturedContent(
        content_id=f"cc-{uuid.uuid4()}",
        type="text",
        source=source,
        text=captured_text,
        timestamp=_utcnow().isoformat(),
        origin_turn_id=origin_turn_id,
        label=label,
        session_id=session_id,
    )
    _capture_store.append(captured)
    _emit_observability_event(
        phase="phase16",
        event_type="content_captured",
        metadata={
            "content_id": captured.content_id,
            "label": captured.label,
            "origin_turn_id": captured.origin_turn_id,
            "source": captured.source,
        },
    )
    _phase20_set_working_set(
        {
            "content_id": captured.content_id,
            "label": captured.label,
            "type": _phase20_working_set_type_from_text(captured.text),
            "source": "capture",
            "path": "",
            "text": captured.text,
            "origin_turn_id": captured.origin_turn_id,
        },
        reason="capture_success",
    )
    label_part = f" with label '{captured.label}'" if captured.label else ""
    return {
        "type": "content_captured",
        "executed": False,
        "envelope": envelope,
        "captured_content": captured.to_dict(),
        "message": f"Captured content {captured.content_id}{label_part}.",
    }


def _resolve_captured_reference(utterance: str) -> tuple[CapturedContent | None, str | None]:
    normalized = _normalize(utterance)
    if not normalized:
        return None, None

    ids = sorted(set(re.findall(r"\bcc-[a-f0-9-]{8,}\b", normalized.lower())))
    if ids:
        if len(ids) > 1:
            return None, "Capture reference rejected: multiple content IDs were provided."
        item = _capture_store.get_by_id(ids[0])
        if item is None:
            return None, f"Capture reference rejected: content ID '{ids[0]}' was not found."
        return item, None

    label_match = re.search(r"\bthat ([a-z0-9_-]+)\b", normalized, flags=re.IGNORECASE)
    if label_match is None:
        return None, None
    label = _normalize_capture_label(label_match.group(1))
    if not label:
        return None, None
    items = _capture_store.get_by_label(label)
    if len(items) > 1:
        return None, f"Capture reference rejected: label '{label}' is ambiguous."
    if len(items) == 1:
        return items[0], None
    return None, None


def _resolve_captured_label(label: str) -> tuple[CapturedContent | None, str | None]:
    normalized = _normalize_capture_label(label)
    if not normalized:
        return None, "Capture reference rejected: captured label is empty."
    items = _capture_store.get_by_label(normalized)
    if len(items) > 1:
        return None, f"Capture reference rejected: label '{normalized}' is ambiguous."
    if len(items) == 0:
        return None, f"Capture reference rejected: label '{normalized}' was not found."
    return items[0], None


def _phase17_validate_filesystem_envelope(envelope: Envelope) -> tuple[Dict[str, Any] | None, Envelope]:
    intent = str(envelope.get("intent", "")).strip()
    if intent not in _FILESYSTEM_INTENTS:
        return None, envelope

    updated = copy.deepcopy(envelope)
    entities = updated.get("entities", [])
    if not isinstance(entities, list):
        entities = []

    location_hint = "workspace"
    raw_path = ""
    has_captured_content = False
    contents_value = ""
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        entity_name = str(entity.get("name", ""))
        if entity_name == "path":
            raw_path = str(entity.get("value", ""))
        elif entity_name == "path_location_hint":
            location_hint = str(entity.get("normalized") or entity.get("value") or "workspace")
        elif entity_name == "contents":
            contents_value = str(entity.get("value") or entity.get("normalized") or "")
        elif entity_name == "captured_content":
            has_captured_content = True

    if not raw_path.strip():
        return {
            "type": "filesystem_rejected",
            "executed": False,
            "envelope": envelope,
            "message": "Filesystem request rejected: file path is required.",
        }, envelope

    if intent in {"write_file", "append_file"} and not (contents_value.strip() or has_captured_content):
        return {
            "type": "filesystem_rejected",
            "executed": False,
            "envelope": envelope,
            "message": "Filesystem request rejected: file contents are required.",
        }, envelope

    normalized_path, error = _phase17_normalize_path(raw_path, location_hint=location_hint)
    if error:
        return {
            "type": "filesystem_rejected",
            "executed": False,
            "envelope": envelope,
            "message": f"Filesystem request rejected: {error}",
        }, envelope

    normalized_entities: List[Dict[str, Any]] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        copied = copy.deepcopy(entity)
        if str(copied.get("name", "")) == "path":
            copied["normalized"] = normalized_path
            copied["value"] = raw_path
        normalized_entities.append(copied)
    updated["entities"] = normalized_entities
    return None, updated


def _phase16_apply_to_envelope(
    *,
    envelope: Envelope,
    normalized_utterance: str,
) -> tuple[Dict[str, Any] | None, Envelope]:
    if str(envelope.get("intent", "")) == "capture_content":
        return _phase16_capture_response(envelope=envelope, normalized_utterance=normalized_utterance), envelope

    if str(envelope.get("lane", "")).upper() != "PLAN":
        return None, envelope

    entities = envelope.get("entities", [])
    if isinstance(entities, list):
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            if str(entity.get("name", "")) != "captured_content_label":
                continue
            label_value = str(entity.get("normalized") or entity.get("value") or "")
            referenced, error = _resolve_captured_label(label_value)
            if error:
                return {
                    "type": "capture_reference_rejected",
                    "executed": False,
                    "envelope": envelope,
                    "message": error,
                }, envelope
            if referenced is not None:
                updated = copy.deepcopy(envelope)
                updated_entities = updated.get("entities", [])
                if not isinstance(updated_entities, list):
                    updated_entities = []
                updated_entities.append(
                    {
                        "name": "captured_content",
                        "content_id": referenced.content_id,
                        "label": referenced.label,
                        "type": referenced.type,
                        "source": referenced.source,
                        "text": referenced.text,
                        "origin_turn_id": referenced.origin_turn_id,
                    }
                )
                updated["entities"] = updated_entities
                envelope = updated
            break

    existing_entities = envelope.get("entities", [])
    if isinstance(existing_entities, list):
        for entity in existing_entities:
            if isinstance(entity, dict) and str(entity.get("name", "")) == "captured_content":
                return None, envelope

    referenced, error = _resolve_captured_reference(str(envelope.get("utterance", normalized_utterance)))
    if error:
        return {
            "type": "capture_reference_rejected",
            "executed": False,
            "envelope": envelope,
            "message": error,
        }, envelope
    if referenced is None:
        return None, envelope

    updated = copy.deepcopy(envelope)
    entities = updated.get("entities", [])
    if not isinstance(entities, list):
        entities = []
    entities.append(
        {
            "name": "captured_content",
            "content_id": referenced.content_id,
            "label": referenced.label,
            "type": referenced.type,
            "source": referenced.source,
            "text": referenced.text,
            "origin_turn_id": referenced.origin_turn_id,
        }
    )
    updated["entities"] = entities
    return None, updated


def _phase19_apply_to_envelope(
    *,
    envelope: Envelope,
    normalized_utterance: str,
) -> tuple[Dict[str, Any] | None, Envelope]:
    if not _phase19_enabled:
        return None, envelope
    if str(envelope.get("intent", "")) != _PHASE19_PERSIST_NOTE_INTENT:
        return None, envelope

    entities = envelope.get("entities", [])
    entities = entities if isinstance(entities, list) else []

    inline_content = ""
    filename_raw = ""
    generate_hint = False
    use_last_response = False
    use_working_set_reference = False
    captured_text = ""
    captured_content_id = ""
    captured_label = ""
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("name", ""))
        value = str(entity.get("normalized") or entity.get("value") or "")
        if name == "persist_note_content":
            inline_content = value
        elif name == "persist_note_filename":
            filename_raw = value
        elif name == "persist_note_generate":
            generate_hint = value.lower() == "true"
        elif name == "persist_note_reference" and value == "last_response":
            use_last_response = True
        elif name == "persist_note_reference" and value == "working_set":
            use_working_set_reference = True
        elif name == "captured_content":
            captured_text = str(entity.get("text") or "")
            captured_content_id = str(entity.get("content_id") or "").strip()
            captured_label = str(entity.get("label") or "").strip()

    content = inline_content.strip()
    source = "inline"
    resolved_content_id = ""
    resolved_label = ""
    resolved_type = ""
    if not content and captured_text.strip():
        content = captured_text.strip()
        source = "captured_content"
        resolved_content_id = captured_content_id
        resolved_label = captured_label
        resolved_type = _phase20_working_set_type_from_text(content)
    if not content and use_last_response:
        candidate = _phase16_last_response_candidate()
        if candidate is not None:
            candidate_text = str(candidate.get("text", "")).strip()
            if candidate_text:
                content = candidate_text
                source = "last_response"
    if not content and (use_working_set_reference or _phase20_implicit_reference_requested(normalized_utterance)):
        working_set = _phase20_get_working_set()
        if isinstance(working_set, dict):
            working_set_text = str(working_set.get("text", "")).strip()
            if working_set_text:
                content = working_set_text
                source = "working_set"
                resolved_content_id = str(working_set.get("content_id", "")).strip()
                resolved_label = str(working_set.get("label", "")).strip()
                resolved_type = str(working_set.get("type", "")).strip()
    if not content and (generate_hint or use_last_response):
        content = _phase19_generate_note_content(normalized_utterance).strip()
        source = "generated"
    if not content:
        return _phase19_clarify_response(
            utterance=normalized_utterance,
            message=(
                "What text should I persist in the note? "
                "You can provide inline text or refer to prior content."
            ),
        )

    filename = _phase19_normalize_filename(filename_raw) if filename_raw else _phase19_default_filename()
    if not filename:
        return _phase19_clarify_response(
            utterance=normalized_utterance,
            message="Please provide a safe filename like notes.txt.",
        )

    resolved_path = str(_phase19_notes_root() / filename)
    composed_entities = [
        {"name": "path", "value": resolved_path, "normalized": resolved_path},
        {"name": "path_location_hint", "value": "home", "normalized": "home"},
        {"name": "contents", "value": content, "normalized": content},
        {"name": "persist_note", "value": "true", "normalized": "true"},
        {"name": "persist_note_filename", "value": filename, "normalized": filename},
        {"name": "persist_note_content_source", "value": source, "normalized": source},
    ]
    if source == "captured_content" and resolved_content_id:
        composed_entities.append(
            {
                "name": "captured_content",
                "content_id": resolved_content_id,
                "label": resolved_label,
                "type": resolved_type or _phase20_working_set_type_from_text(content),
                "source": "capture",
                "text": content,
                "origin_turn_id": str(current_correlation_id() or ""),
            }
        )
    if source == "working_set" and resolved_content_id:
        composed_entities.append(
            {
                "name": "working_set_content",
                "content_id": resolved_content_id,
                "label": resolved_label,
                "type": _phase20_normalize_working_set_type(resolved_type),
                "source": "working_set",
                "path": "",
                "text": content,
                "timestamp": _phase20_now_iso(),
            }
        )
    updated = copy.deepcopy(envelope)
    updated["intent"] = "write_file"
    updated["entities"] = composed_entities
    updated["requires_approval"] = True
    policy = dict(updated.get("policy", {}))
    policy["allowed"] = True
    policy["risk_level"] = "medium"
    policy["reason"] = "Persist-note request composed to governed write_file execution."
    updated["policy"] = policy
    return None, updated


def _phase20_apply_to_envelope(
    *,
    envelope: Envelope,
    normalized_utterance: str,
) -> tuple[Dict[str, Any] | None, Envelope]:
    if not _phase20_enabled:
        return None, envelope
    if str(envelope.get("lane", "")).upper() != "PLAN":
        return None, envelope
    intent = str(envelope.get("intent", "")).strip()
    if intent not in {"write_file", "append_file"}:
        return None, envelope
    if _phase20_explicit_label_reference(normalized_utterance):
        return None, envelope
    if not _phase20_implicit_reference_requested(normalized_utterance):
        return None, envelope

    entities = envelope.get("entities", [])
    entities = entities if isinstance(entities, list) else []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        if str(entity.get("name", "")) in {"captured_content", "captured_content_label"}:
            return None, envelope

    contents_value = _entity_string(envelope, "contents")
    if contents_value.strip() and not _phase20_placeholder_contents(contents_value):
        return None, envelope

    working_set = _phase20_get_working_set()
    if not isinstance(working_set, dict):
        return _phase19_clarify_response(
            utterance=normalized_utterance,
            message="No active working set. Capture or persist content first, then refer to this/that/current/it.",
        )
    working_set_text = str(working_set.get("text", "")).strip()
    if not working_set_text:
        return _phase19_clarify_response(
            utterance=normalized_utterance,
            message="Active working set has no text content to apply here.",
        )

    updated = copy.deepcopy(envelope)
    updated_entities = updated.get("entities", [])
    updated_entities = updated_entities if isinstance(updated_entities, list) else []
    replaced = False
    for entity in updated_entities:
        if not isinstance(entity, dict):
            continue
        if str(entity.get("name", "")) == "contents":
            entity["value"] = working_set_text
            entity["normalized"] = working_set_text
            replaced = True
            break
    if not replaced:
        updated_entities.append({"name": "contents", "value": working_set_text, "normalized": working_set_text})
    updated_entities.append(
        {
            "name": "working_set_content",
            "content_id": str(working_set.get("content_id", "")),
            "label": str(working_set.get("label", "")),
            "type": str(working_set.get("type", "")),
            "source": str(working_set.get("source", "")),
            "path": str(working_set.get("path", "")),
            "text": working_set_text,
            "timestamp": str(working_set.get("timestamp", "")),
        }
    )
    updated["entities"] = updated_entities
    _emit_observability_event(
        phase="phase20",
        event_type="working_set_resolved",
        metadata={
            "intent": intent,
            "content_id": str(working_set.get("content_id", "")),
            "label": str(working_set.get("label", "")),
        },
    )
    return None, updated


def _phase21_apply_to_envelope(
    *,
    envelope: Envelope,
    normalized_utterance: str,
) -> tuple[Dict[str, Any] | None, Envelope]:
    if not _phase21_enabled:
        return None, envelope
    intent = str(envelope.get("intent", "")).strip()
    if intent not in _PHASE21_INTENTS:
        return None, envelope

    request = _entity_string(envelope, "phase21_request") or normalized_utterance
    if _phase21_is_ambiguous_request(normalized_utterance, intent):
        return _phase19_clarify_response(
            utterance=normalized_utterance,
            message="What specific revision or transformation should I apply?",
        )

    explicit_reference, explicit_error = _resolve_captured_reference(normalized_utterance)
    if explicit_error:
        return {
            "type": "capture_reference_rejected",
            "executed": False,
            "envelope": envelope,
            "message": explicit_error,
        }, envelope

    original_content = ""
    original_label = ""
    original_content_id = ""
    original_type = "other"
    original_path = ""

    if explicit_reference is not None:
        original_content = str(explicit_reference.text or "")
        original_label = str(explicit_reference.label or "")
        original_content_id = str(explicit_reference.content_id or "")
        original_type = _phase20_normalize_working_set_type(str(explicit_reference.type or "text_note"))
    else:
        working_set = _phase20_get_working_set()
        if not isinstance(working_set, dict):
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message="No active working set. Capture or generate content first, then ask to revise or transform it.",
            )
        original_label = str(working_set.get("label", "")).strip()
        original_content_id = str(working_set.get("content_id", "")).strip()
        original_type = _phase20_normalize_working_set_type(str(working_set.get("type", "other")))
        original_path = str(working_set.get("path", "")).strip()
        original_content = str(working_set.get("text", "") or "")
        if not original_content.strip() and original_path:
            original_content = _phase21_read_content_from_path(original_path)

    if not original_content.strip():
        return _phase19_clarify_response(
            utterance=normalized_utterance,
            message="I could not resolve content to revise. Please reference captured content or provide text explicitly.",
        )

    revised_content = _phase21_generate_transformed_content(
        original_content=original_content,
        request=request,
        content_type=original_type,
        intent=intent,
    ).strip()
    if not revised_content:
        return _phase19_clarify_response(
            utterance=normalized_utterance,
            message="I could not generate a revised result. Please clarify the change you want.",
        )

    captured = _phase21_capture_revision(
        revised_text=revised_content,
        original_label=original_label or original_content_id or intent,
        previous_content_id=original_content_id,
        content_type=original_type,
        source=intent,
        previous_path=original_path,
    )
    summary = _phase21_write_summary(
        intent=intent,
        captured=captured,
        original_text=original_content,
        revised_text=revised_content,
    )

    write_requested = _entity_string(envelope, "phase21_write").lower() == "true"
    explicit_path = _entity_string(envelope, "path")
    location_hint = _entity_string(envelope, "path_location_hint") or "workspace"
    if write_requested:
        target_path = explicit_path or original_path or _phase21_default_write_path(captured=captured, content_type=original_type)
        if not target_path:
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message="Please provide a file path for the revised content.",
            )
        composed = _phase17_envelope_for_intent(
            utterance=normalized_utterance,
            intent="write_file",
            entities=[
                {"name": "path", "value": target_path, "normalized": target_path},
                {"name": "path_location_hint", "value": location_hint, "normalized": location_hint},
                {"name": "contents", "value": revised_content, "normalized": revised_content},
                {"name": "phase21_composite", "value": intent, "normalized": intent},
                {"name": "phase21_summary", "value": summary, "normalized": summary},
                {
                    "name": "captured_content",
                    "content_id": captured.content_id,
                    "label": captured.label,
                    "type": captured.type,
                    "source": captured.source,
                    "text": captured.text,
                    "origin_turn_id": captured.origin_turn_id,
                },
            ],
            requires_approval=True,
            risk_level="medium",
            reason="Revision/transformation write-back requires explicit approval.",
        )
        return None, composed

    response_type = "content_revised" if intent == "revise_content" else "content_transformed"
    return {
        "type": response_type,
        "executed": False,
        "envelope": envelope,
        "capture_eligible": True,
        "captured_content": captured.to_dict(),
        "revised_content": revised_content,
        "message": revised_content,
        "summary": summary,
    }, envelope


def _phase22_location_hint_for_path(path: str) -> str:
    try:
        resolved = Path(path).resolve(strict=False)
    except Exception:
        return "workspace"
    home_root = Path.home().resolve()
    if _phase17_is_within(resolved, home_root):
        return "home"
    return "workspace"


def _phase22_list_project_artifact_paths(project: Dict[str, Any]) -> List[str]:
    artifacts = project.get("artifacts", [])
    artifacts = artifacts if isinstance(artifacts, list) else []
    paths = [str(item.get("path", "")) for item in artifacts if isinstance(item, dict)]
    return sorted([path for path in paths if path])


def _phase22_find_artifact_path(project: Dict[str, Any], hint: str) -> str:
    root = Path(str(project.get("root_path", "")))
    artifacts = _phase22_list_project_artifact_paths(project)
    lowered_hint = _normalize(hint).lower()
    if lowered_hint in {"*.css", "stylesheet"}:
        for rel in artifacts:
            if rel.lower().endswith(".css"):
                return str((root / rel).resolve())
    if lowered_hint in {"*.html", "page"}:
        for rel in artifacts:
            if rel.lower().endswith((".html", ".htm")):
                return str((root / rel).resolve())
    for rel in artifacts:
        if lowered_hint and lowered_hint in rel.lower():
            return str((root / rel).resolve())
    if hint and not any(ch in hint for ch in ("*", "?", "[")):
        candidate = (root / hint).resolve(strict=False)
        return str(candidate)
    return ""


def _phase22_resolve_refactor_targets(project: Dict[str, Any], request: str) -> List[str]:
    root = Path(str(project.get("root_path", "")))
    artifacts = _phase22_list_project_artifact_paths(project)
    lowered = request.lower()
    if "html" in lowered:
        return [str((root / rel).resolve()) for rel in artifacts if rel.lower().endswith((".html", ".htm"))]
    if "css" in lowered or "stylesheet" in lowered:
        return [str((root / rel).resolve()) for rel in artifacts if rel.lower().endswith(".css")]
    if "notes" in lowered:
        return [str((root / rel).resolve()) for rel in artifacts if rel.lower().endswith(".txt")]
    return [str((root / rel).resolve()) for rel in artifacts]


def _phase22_project_doc_text(project: Dict[str, Any]) -> str:
    name = str(project.get("name", "project"))
    root_path = str(project.get("root_path", ""))
    artifacts = _phase22_list_project_artifact_paths(project)
    lines = [f"# Project {name}", f"Root: {root_path}", "", "## Artifacts"]
    if artifacts:
        lines.extend([f"- {item}" for item in artifacts])
    else:
        lines.append("- (none)")
    lines.extend(["", "## Next Steps"])
    if artifacts:
        lines.extend(
            [
                "- Revise key pages and styles.",
                "- Generate project documentation snapshot.",
                "- Run project-wide refactor when needed.",
            ]
        )
    else:
        lines.extend(
            [
                "- Add initial pages/files.",
                "- Capture and persist project notes.",
            ]
        )
    return "\n".join(lines)


def _phase22_apply_to_envelope(
    *,
    envelope: Envelope,
    normalized_utterance: str,
) -> tuple[Dict[str, Any] | None, Envelope]:
    global _pending_plan
    if not _phase22_enabled:
        return None, envelope

    intent = str(envelope.get("intent", "")).strip()
    if intent not in _PHASE22_PROJECT_INTENTS:
        return None, envelope

    if intent == "create_project":
        name = _phase22_slug(_entity_string(envelope, "project_name") or _phase22_extract_project_name(normalized_utterance) or "project")
        root_path_raw = _entity_string(envelope, "project_root_path") or str((Path.home() / "sandbox" / name).resolve())
        location_hint = _entity_string(envelope, "path_location_hint") or _phase22_location_hint_for_path(root_path_raw)
        root_path, error = _phase22_normalize_project_root(root_path_raw, location_hint=location_hint)
        if error:
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message=f"Project root is invalid: {error}",
            )
        project = _phase22_create_project_record(name=name, root_path=str(root_path))
        return {
            "type": "project_created",
            "executed": False,
            "envelope": envelope,
            "project": copy.deepcopy(project),
            "message": f"Project '{project['name']}' created at {project['root_path']}.",
        }, envelope

    project = _phase22_resolve_project_from_utterance(normalized_utterance)
    if project is None:
        return _phase19_clarify_response(
            utterance=normalized_utterance,
            message="No active project. Create or select a project first.",
        )
    _phase22_set_project_context(project)
    if intent in {"update_project", "project_wide_refactor"} and not _phase24_project_is_writable(project):
        return _phase19_clarify_response(
            utterance=normalized_utterance,
            message=(
                f"Project '{project.get('name', '')}' is {_phase24_project_state(project)} and read-only. "
                "Reactivate or clone the project before editing."
            ),
        )

    if intent == "list_project_artifacts":
        diagnostics_only = _entity_string(envelope, "project_diagnostics").lower() == "true"
        if diagnostics_only:
            return {
                "type": "project_info",
                "executed": False,
                "envelope": envelope,
                "project": copy.deepcopy(project),
                "message": f"You are currently working on project '{project.get('name', '')}'.",
            }, envelope
        artifacts = _phase22_list_project_artifact_paths(project)
        message = "\n".join(artifacts) if artifacts else "No artifacts recorded for this project."
        return {
            "type": "project_artifacts",
            "executed": False,
            "envelope": envelope,
            "project": copy.deepcopy(project),
            "artifacts": artifacts,
            "message": message,
        }, envelope

    if intent == "open_project_artifact":
        artifact_hint = _entity_string(envelope, "project_artifact_hint") or _phase22_extract_artifact_hint(normalized_utterance)
        target_path = _phase22_find_artifact_path(project, artifact_hint)
        if not target_path:
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message="Which project artifact should I open?",
            )
        contents = _phase21_read_content_from_path(target_path)
        if not contents:
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message="That artifact could not be read from the project root.",
            )
        return {
            "type": "project_artifact_opened",
            "executed": False,
            "envelope": envelope,
            "project": copy.deepcopy(project),
            "path": target_path,
            "message": contents,
        }, envelope

    if intent == "project_documentation_generate":
        if _entity_string(envelope, "project_next_steps").lower() == "true":
            artifacts = _phase22_list_project_artifact_paths(project)
            next_steps = ["Add initial artifacts to this project."] if not artifacts else [
                "Revise key files in the project.",
                "Generate project documentation snapshot.",
                "Run project-wide refactor for consistency.",
            ]
            return {
                "type": "project_next_steps",
                "executed": False,
                "envelope": envelope,
                "project": copy.deepcopy(project),
                "next_steps": next_steps,
                "message": " ".join(next_steps),
            }, envelope
        documentation = _phase22_project_doc_text(project)
        return {
            "type": "project_documentation",
            "executed": False,
            "envelope": envelope,
            "capture_eligible": True,
            "project": copy.deepcopy(project),
            "message": documentation,
        }, envelope

    if intent == "delete_project":
        delete_envelope = _phase17_envelope_for_intent(
            utterance=normalized_utterance,
            intent="delete_project",
            entities=[
                {"name": "project_id", "value": str(project.get("project_id", "")), "normalized": str(project.get("project_id", ""))},
                {"name": "project_name", "value": str(project.get("name", "")), "normalized": str(project.get("name", ""))},
                {"name": "project_root_path", "value": str(project.get("root_path", "")), "normalized": str(project.get("root_path", ""))},
                {
                    "name": "phase22_summary",
                    "value": f"Project deletion requested for '{project.get('name', '')}'.",
                    "normalized": f"Project deletion requested for '{project.get('name', '')}'.",
                },
            ],
            requires_approval=True,
            risk_level="high",
            reason="Project deletion requires explicit approval.",
        )
        return None, delete_envelope

    if intent == "update_project":
        request = _entity_string(envelope, "phase22_request") or normalized_utterance
        page_match = re.search(r"\badd\s+(?:an?\s+)?([a-zA-Z0-9_-]+)\s+page\b", request, flags=re.IGNORECASE)
        if page_match is None:
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message="What project artifact should I add or update?",
            )
        page_name = _phase22_slug(page_match.group(1))
        target_path = str((Path(str(project.get("root_path", ""))) / f"{page_name}.html").resolve())
        generated = _phase21_generate_transformed_content(
            original_content=f"<html><body><h1>{page_name.title()}</h1></body></html>",
            request=request,
            content_type="html_page",
            intent="revise_content",
        )
        update_envelope = _phase17_envelope_for_intent(
            utterance=normalized_utterance,
            intent="write_file",
            entities=[
                {"name": "path", "value": target_path, "normalized": target_path},
                {"name": "path_location_hint", "value": _phase22_location_hint_for_path(target_path), "normalized": _phase22_location_hint_for_path(target_path)},
                {"name": "contents", "value": generated, "normalized": generated},
                {"name": "phase22_project_id", "value": str(project.get("project_id", "")), "normalized": str(project.get("project_id", ""))},
                {
                    "name": "phase22_summary",
                    "value": f"Updating project '{project.get('name', '')}' with page '{page_name}'.",
                    "normalized": f"Updating project '{project.get('name', '')}' with page '{page_name}'.",
                },
            ],
            requires_approval=True,
            risk_level="medium",
            reason="Project update writes require explicit approval.",
        )
        return None, update_envelope

    if intent == "project_wide_refactor":
        request = _entity_string(envelope, "phase22_request") or normalized_utterance
        targets = _phase22_resolve_refactor_targets(project, request)
        targets = [path for path in targets if _phase21_read_content_from_path(path)]
        if not targets:
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message="No matching project artifacts were found for project-wide refactor.",
            )

        write_contract = _resolve_tool_contract("write_file")
        if write_contract is None:
            return {
                "type": "execution_rejected",
                "executed": False,
                "message": "Execution rejected: write_file contract unavailable.",
            }, envelope

        steps: List[PlanStep] = []
        for index, target_path in enumerate(targets, start=1):
            original = _phase21_read_content_from_path(target_path)
            if not original:
                continue
            revised = _phase21_generate_transformed_content(
                original_content=original,
                request=request,
                content_type=_phase22_artifact_type_from_path(target_path),
                intent="project_wide_refactor",
            ).strip()
            if not revised:
                continue
            captured = _phase21_capture_revision(
                revised_text=revised,
                original_label=f"{project.get('name', 'project')}_{Path(target_path).stem}",
                previous_content_id="",
                content_type=_phase22_artifact_type_from_path(target_path),
                source="project_wide_refactor",
                previous_path=target_path,
            )
            relpath = _phase22_artifact_relpath(project, target_path)
            step_envelope = _phase17_envelope_for_intent(
                utterance=f"refactor {relpath}",
                intent="write_file",
                entities=[
                    {"name": "path", "value": target_path, "normalized": target_path},
                    {"name": "path_location_hint", "value": _phase22_location_hint_for_path(target_path), "normalized": _phase22_location_hint_for_path(target_path)},
                    {"name": "contents", "value": revised, "normalized": revised},
                    {"name": "phase22_project_id", "value": str(project.get("project_id", "")), "normalized": str(project.get("project_id", ""))},
                    {"name": "phase22_project_artifact", "value": relpath, "normalized": relpath},
                    {
                        "name": "captured_content",
                        "content_id": captured.content_id,
                        "label": captured.label,
                        "type": captured.type,
                        "source": captured.source,
                        "text": captured.text,
                        "origin_turn_id": captured.origin_turn_id,
                    },
                ],
                requires_approval=True,
                risk_level="medium",
                reason="Project-wide refactor step requires explicit approval.",
            )
            parameters = _tool_parameters_from_envelope(write_contract, step_envelope)
            steps.append(
                PlanStep(
                    step_id=f"step-{index}",
                    description=f"Refactor {relpath}",
                    tool_contract=write_contract,
                    parameters=parameters,
                    risk_level=write_contract.risk_level,
                    envelope_snapshot=step_envelope,
                )
            )

        if not steps:
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message="No valid refactor steps were generated for this project.",
            )

        if _phase8_enabled:
            plan = ExecutionPlan(
                plan_id=f"plan-{uuid.uuid4()}",
                intent="project_wide_refactor",
                steps=steps,
            )
            _pending_plan = _create_pending_plan(plan)
            return {
                "type": "plan_approval_required",
                "executed": False,
                "plan": _serialize_plan(plan),
                "message": _plan_approval_message(_pending_plan),
            }, envelope

        first_step = steps[0].envelope_snapshot
        return None, first_step

    return None, envelope


def _phase23_apply_to_envelope(
    *,
    envelope: Envelope,
    normalized_utterance: str,
) -> tuple[Dict[str, Any] | None, Envelope]:
    if not _phase23_enabled:
        return None, envelope

    intent = str(envelope.get("intent", "")).strip()
    if intent not in _PHASE23_GOAL_INTENTS:
        return None, envelope

    project = _phase22_resolve_project_from_utterance(normalized_utterance)
    if project is None:
        return _phase19_clarify_response(
            utterance=normalized_utterance,
            message="No active project. Create or select a project first.",
        )
    _phase22_set_project_context(project)
    project_id = str(project.get("project_id", ""))

    if intent == "define_project_goal":
        description = _normalize(_entity_string(envelope, "project_goal_description"))
        if not description:
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message="Please provide a project goal description.",
            )
        return handle_define_project_goal(project, description), envelope

    if intent == "list_project_goals":
        return handle_list_project_goals(project), envelope

    if intent == "describe_project_goal":
        goal_ref = _entity_string(envelope, "project_goal_id")
        goal, error = _phase23_resolve_goal(project_id, goal_ref or None)
        if error:
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message=error,
            )
        return handle_describe_project_goal(project, goal), envelope

    if intent == "propose_next_tasks":
        goal_ref = _entity_string(envelope, "project_goal_id")
        goal, error = _phase23_resolve_goal(project_id, goal_ref or None)
        if error:
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message=error,
            )
        return handle_propose_next_tasks(project, goal), envelope

    if intent == "list_project_tasks":
        goal_ref = _entity_string(envelope, "project_goal_id")
        if goal_ref:
            goal, error = _phase23_resolve_goal(project_id, goal_ref)
            if error:
                return _phase19_clarify_response(
                    utterance=normalized_utterance,
                    message=error,
                )
            return handle_list_project_tasks(project, goal_id=str(goal.get("goal_id", ""))), envelope
        return handle_list_project_tasks(project), envelope

    if intent == "task_status":
        task_ref = _entity_string(envelope, "project_task_id")
        if not task_ref:
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message="Specify a task_id to inspect status.",
            )
        _phase23_refresh_blocked_statuses(project_id)
        task, error = _phase23_resolve_task(project_id, task_ref)
        if error:
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message=error,
            )
        return handle_task_status(project, task), envelope

    if intent == "complete_task":
        task_ref = _entity_string(envelope, "project_task_id")
        if not task_ref:
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message="Specify which task to complete (for example: task-...).",
            )
        _phase23_refresh_blocked_statuses(project_id)
        task, error = _phase23_resolve_task(project_id, task_ref)
        if error:
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message=error,
            )
        if str(task.get("status", "")) == "COMPLETED":
            return handle_task_status(project, task), envelope
        goal = _phase23_goal_by_id(project_id, str(task.get("goal_id", ""))) or {}
        if _phase23_task_requires_approval(task):
            project_name = str(project.get("name", "project"))
            goal_description = str(goal.get("description", "unspecified goal"))
            task_description = str(task.get("description", ""))
            task_id = str(task.get("task_id", ""))
            expected_change = task_description or "Apply task updates."
            summary = (
                f"Project '{project_name}' goal '{goal_description}' task '{task_id}: {task_description}'. "
                f"Expected change: {expected_change}. "
            )
            completion_envelope = _phase17_envelope_for_intent(
                utterance=normalized_utterance,
                intent="plan.user_action_request",
                entities=[
                    {"name": "phase23_complete_task", "value": "true", "normalized": "true"},
                    {"name": "phase23_project_id", "value": project_id, "normalized": project_id},
                    {"name": "phase23_goal_id", "value": str(task.get("goal_id", "")), "normalized": str(task.get("goal_id", ""))},
                    {"name": "phase23_task_id", "value": task_id, "normalized": task_id},
                    {"name": "phase23_expected_change", "value": expected_change, "normalized": expected_change},
                    {"name": "phase23_summary", "value": summary, "normalized": summary},
                ],
                requires_approval=True,
                risk_level="medium",
                reason="Completing task with side-effect potential requires explicit approval.",
            )
            return None, completion_envelope
        return handle_complete_task(project, task), envelope

    return None, envelope


def _phase24_apply_to_envelope(
    *,
    envelope: Envelope,
    normalized_utterance: str,
) -> tuple[Dict[str, Any] | None, Envelope]:
    if not _phase24_enabled:
        return None, envelope

    intent = str(envelope.get("intent", "")).strip()
    if intent not in _PHASE24_MILESTONE_INTENTS:
        return None, envelope

    project = _phase22_resolve_project_from_utterance(normalized_utterance)
    if project is None:
        return _phase19_clarify_response(
            utterance=normalized_utterance,
            message="No active project. Create or select a project first.",
        )
    _phase22_set_project_context(project)
    project_id = str(project.get("project_id", ""))

    if intent == "define_milestone":
        title = _normalize(_entity_string(envelope, "milestone_title"))
        description = _normalize(_entity_string(envelope, "milestone_description")) or title
        raw_criteria = _entity_string(envelope, "milestone_criteria_json")
        raw_goal_ids = _entity_string(envelope, "milestone_goal_ids_json")
        if not title:
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message="Please provide a milestone title.",
            )
        criteria: List[str] = []
        goal_ids: List[str] = []
        if raw_criteria:
            try:
                parsed = json.loads(raw_criteria)
                if isinstance(parsed, list):
                    criteria = [_normalize(str(item)) for item in parsed if _normalize(str(item))]
            except Exception:
                criteria = []
        if raw_goal_ids:
            try:
                parsed = json.loads(raw_goal_ids)
                if isinstance(parsed, list):
                    goal_ids = [str(item).strip() for item in parsed if str(item).strip()]
            except Exception:
                goal_ids = []
        for goal_id in goal_ids:
            if _phase23_goal_by_id(project_id, goal_id) is None:
                return _phase19_clarify_response(
                    utterance=normalized_utterance,
                    message=f"Associated goal '{goal_id}' does not exist in this project.",
                )
        if goal_ids and not criteria:
            criteria = ["all associated goals completed"]
        return handle_define_milestone(
            project,
            title=title,
            description=description,
            associated_goals=goal_ids,
            criteria=criteria,
        ), envelope

    if intent == "list_milestones":
        return handle_list_milestones(project), envelope

    if intent == "describe_milestone":
        reference = _entity_string(envelope, "milestone_ref")
        milestone, error = _phase24_resolve_milestone(project_id, reference or None)
        if error:
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message=error,
            )
        return handle_describe_milestone(project, milestone), envelope

    if intent == "achieve_milestone":
        reference = _entity_string(envelope, "milestone_ref")
        milestone, error = _phase24_resolve_milestone(project_id, reference or None)
        if error:
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message=error,
            )
        if str(milestone.get("status", "")) == "ACHIEVED":
            return handle_describe_milestone(project, milestone), envelope
        compliant, reasons = _phase24_milestone_compliance(project_id, milestone)
        if not compliant:
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message="Milestone criteria are not satisfied: " + " ".join(reasons),
            )
        return handle_achieve_milestone(project, milestone), envelope

    if intent == "project_completion_status":
        explicit_confirmation = _entity_string(envelope, "project_completion_confirm").lower() == "true"
        return handle_project_completion_status(
            project,
            explicit_confirmation=explicit_confirmation,
        ), envelope

    if intent == "finalize_project":
        state = _phase24_project_state(project)
        if state == "finalized":
            return {
                "type": "project_finalized",
                "executed": False,
                "project": copy.deepcopy(project),
                "message": f"Project '{project.get('name', '')}' is already finalized.",
            }, envelope
        if state == "archived":
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message=f"Project '{project.get('name', '')}' is archived and cannot be finalized again.",
            )
        completion = _phase24_project_completion_snapshot(project, explicit_confirmation=True)
        if not completion["all_milestones_achieved"] or not completion["no_pending_tasks"]:
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message="Project is not ready to finalize. " + " ".join(completion.get("next_steps", [])),
            )
        summary = _phase24_project_summary_text(project)
        finalize_envelope = _phase17_envelope_for_intent(
            utterance=normalized_utterance,
            intent="finalize_project",
            entities=[
                {"name": "project_id", "value": project_id, "normalized": project_id},
                {"name": "project_name", "value": str(project.get("name", "")), "normalized": str(project.get("name", ""))},
                {"name": "phase24_summary", "value": f"Finalize project '{project.get('name', '')}'.", "normalized": f"Finalize project '{project.get('name', '')}'."},
                {"name": "phase24_project_summary", "value": summary, "normalized": summary},
            ],
            requires_approval=True,
            risk_level="high",
            reason="Project finalization requires explicit approval.",
        )
        return None, finalize_envelope

    if intent == "archive_project":
        state = _phase24_project_state(project)
        if state == "archived":
            return {
                "type": "project_archived",
                "executed": False,
                "project": copy.deepcopy(project),
                "message": f"Project '{project.get('name', '')}' is already archived.",
            }, envelope
        archive_root = _phase24_archive_root(project)
        archive_envelope = _phase17_envelope_for_intent(
            utterance=normalized_utterance,
            intent="archive_project",
            entities=[
                {"name": "project_id", "value": project_id, "normalized": project_id},
                {"name": "project_name", "value": str(project.get("name", "")), "normalized": str(project.get("name", ""))},
                {"name": "project_root_path", "value": str(project.get("root_path", "")), "normalized": str(project.get("root_path", ""))},
                {"name": "archive_root_path", "value": archive_root, "normalized": archive_root},
                {"name": "phase24_summary", "value": f"Archive project '{project.get('name', '')}' to {archive_root}.", "normalized": f"Archive project '{project.get('name', '')}' to {archive_root}."},
            ],
            requires_approval=True,
            risk_level="high",
            reason="Project archival requires explicit approval.",
        )
        return None, archive_envelope

    return None, envelope


def _phase26_workflow_project(normalized_utterance: str) -> Dict[str, Any] | None:
    project = _phase22_resolve_project_from_utterance(normalized_utterance)
    if isinstance(project, dict):
        _phase22_set_project_context(project)
        return project
    diagnostics = get_project_context_diagnostics()
    maybe = diagnostics.get("project")
    return maybe if isinstance(maybe, dict) else None


def _phase26_step_envelope_for_execution(run: Dict[str, Any], step: Dict[str, Any]) -> Envelope:
    run_id = str(run.get("run_id", "")).strip()
    step_id = _normalize(str(step.get("step_id", "")))
    intent = _normalize(str(step.get("intent", "")))
    parameters = step.get("parameters", {})
    parameters = parameters if isinstance(parameters, dict) else {}
    base_entities = [
        {"name": "phase26_run_id", "value": run_id, "normalized": run_id},
        {"name": "phase26_step_id", "value": step_id, "normalized": step_id},
        {"name": "phase26_step_intent", "value": intent, "normalized": intent},
    ]

    if intent in _FILESYSTEM_INTENTS:
        location_hint = _normalize(str(parameters.get("location", ""))).lower() or "workspace"
        raw_path = _normalize(str(parameters.get("path", "")))
        normalized_path, path_error = _phase17_normalize_path(raw_path, location_hint=location_hint)
        if path_error:
            raise ValueError(path_error)
        entities = list(base_entities)
        entities.append({"name": "path", "value": normalized_path, "normalized": normalized_path})
        entities.append({"name": "path_location_hint", "value": location_hint, "normalized": location_hint})
        if intent in {"create_file", "write_file", "append_file"}:
            contents = str(parameters.get("contents", ""))
            entities.append({"name": "contents", "value": contents, "normalized": contents})
        envelope = _phase17_envelope_for_intent(
            utterance=f"workflow step {step_id}",
            intent=intent,
            entities=entities,
            requires_approval=intent in _FILESYSTEM_WRITE_INTENTS,
            risk_level="high" if intent == "delete_file" else ("medium" if intent in _FILESYSTEM_WRITE_INTENTS else "low"),
            reason="Workflow step execution through governed filesystem contract.",
        )
        validation, validated_envelope = _phase17_validate_filesystem_envelope(envelope)
        if validation is not None:
            raise ValueError(str(validation.get("message", "Filesystem validation failed.")))
        return validated_envelope

    if intent == "delegate_to_agent":
        agent_type = _normalize(str(parameters.get("agent_type", ""))).upper() or "CODING"
        task = _normalize(str(parameters.get("task", ""))) or "workflow delegated task"
        base = _phase17_envelope_for_intent(
            utterance=f"delegate {task} to {agent_type.lower()} agent",
            intent="delegate_to_agent",
            entities=base_entities
            + [
                {"name": "delegation_agent_type", "value": agent_type, "normalized": agent_type},
                {"name": "delegation_task", "value": task, "normalized": task},
            ],
            requires_approval=True,
            risk_level="medium",
            reason="Workflow delegated step requires explicit approval.",
        )
        phase25_result, composed = _phase25_apply_to_envelope(
            envelope=base,
            normalized_utterance=f"delegate {task} to {agent_type.lower()} agent",
        )
        if phase25_result is not None:
            raise ValueError(str(phase25_result.get("message", "Delegated step validation failed.")))
        entities = composed.get("entities", [])
        entities = entities if isinstance(entities, list) else []
        composed["entities"] = entities + base_entities
        return composed

    if intent == "plan.user_action_request":
        summary = _normalize(str(parameters.get("summary", ""))) or f"Workflow step {step_id}"
        return _phase17_envelope_for_intent(
            utterance=f"workflow step {step_id}",
            intent="plan.user_action_request",
            entities=base_entities
            + [
                {"name": "phase26_summary", "value": summary, "normalized": summary},
            ],
            requires_approval=True,
            risk_level="medium",
            reason="Workflow generic step requires explicit approval.",
        )

    raise ValueError(f"Unsupported workflow step intent '{intent}'.")


def _phase26_execute_next_step(run: Dict[str, Any]) -> Dict[str, Any]:
    run_id = str(run.get("run_id", "")).strip()
    workflow_name = str(run.get("workflow_name", "workflow"))
    steps = run.get("steps_ordered", [])
    steps = steps if isinstance(steps, list) else []
    index = int(run.get("current_step_index", 0) or 0)
    if index >= len(steps):
        run["status"] = "COMPLETED"
        run["finished_at"] = _utcnow().isoformat()
        _phase26_active_run_by_session.pop(_phase26_session_key(), None)
        return {
            "type": "workflow_completed",
            "executed": False,
            "workflow_run": copy.deepcopy(run),
            "message": _phase26_status_message(run),
        }

    step = steps[index]
    step_id = _normalize(str(step.get("step_id", "")))
    try:
        envelope = _phase26_step_envelope_for_execution(run, step)
        execution = _execute_envelope_once(envelope)
    except Exception as exc:
        run["status"] = "FAILED"
        run["failure"] = str(exc)
        run["finished_at"] = _utcnow().isoformat()
        _phase26_active_run_by_session.pop(_phase26_session_key(), None)
        return {
            "type": "execution_rejected",
            "executed": False,
            "workflow_run": copy.deepcopy(run),
            "message": f"Workflow '{workflow_name}' failed at step '{step_id}': {exc}",
        }

    updated = _phase26_find_run(run_id) or run
    next_step_id = _phase26_next_step_id(updated)
    message = (
        _phase26_status_message(updated)
        if str(updated.get("status", "")) == "COMPLETED"
        else (
            f"Workflow '{workflow_name}' executed step '{step_id}'. "
            + (
                f"Reply exactly: approve to continue with step '{next_step_id}'."
                if next_step_id
                else "No remaining steps."
            )
        )
    )
    payload = {
        "type": "workflow_step_executed",
        "executed": True,
        "workflow_run": copy.deepcopy(updated),
        "execution_event": execution.get("execution_event"),
        "message": message,
    }
    if isinstance(execution.get("execution_event"), dict):
        payload.update(_phase25_execution_response_fields(execution["execution_event"]))
        payload.update(_phase26_execution_response_fields(execution["execution_event"]))
    return payload


def _phase26_active_run_progress_response(utterance: str) -> Dict[str, Any] | None:
    if not _phase26_enabled:
        return None
    if _pending_action is not None or _pending_plan is not None:
        return None
    run = _phase26_active_run()
    if not isinstance(run, dict):
        return None
    lowered = _normalize(utterance).lower()
    if re.search(r"\b(?:cancel\s+(?:the\s+)?(?:current\s+)?workflow|workflow\s+cancel)\b", lowered):
        return None
    if re.search(r"\bworkflow\s+status\b", lowered) or lowered in {"status workflow", "workflow status"}:
        return _phase26_status_payload(run)
    if not _is_valid_approval_phrase(utterance):
        next_step_id = _phase26_next_step_id(run)
        return {
            "type": "workflow_waiting_approval",
            "executed": False,
            "workflow_run": copy.deepcopy(run),
            "message": (
                f"Workflow '{run.get('workflow_name', 'workflow')}' is waiting for approval"
                + (f" on step '{next_step_id}'." if next_step_id else ".")
                + " Reply exactly: approve, or ask for workflow status."
            ),
        }
    return _phase26_execute_next_step(run)


def _phase26_apply_to_envelope(
    *,
    envelope: Envelope,
    normalized_utterance: str,
) -> tuple[Dict[str, Any] | None, Envelope]:
    if not _phase26_enabled:
        return None, envelope
    intent = str(envelope.get("intent", "")).strip()
    if intent not in _PHASE26_WORKFLOW_INTENTS:
        return None, envelope

    session_key = _phase26_session_key()

    if intent == "workflow_status":
        run = _phase26_active_run() or _phase26_find_run(_phase26_last_run_by_session.get(session_key, ""))
        if isinstance(run, dict):
            return _phase26_status_payload(run), envelope
        return _phase19_clarify_response(
            utterance=normalized_utterance,
            message="No workflow run is active in this session.",
        )

    if intent == "workflow_cancel":
        run = _phase26_active_run()
        if not isinstance(run, dict):
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message="No active workflow to cancel.",
            )
        run_id = str(run.get("run_id", ""))
        summary = f"Cancel workflow '{run.get('workflow_name', '')}' ({run_id})."
        composed = _phase17_envelope_for_intent(
            utterance=normalized_utterance,
            intent="plan.user_action_request",
            entities=[
                {"name": "phase26_cancel", "value": "true", "normalized": "true"},
                {"name": "phase26_run_id", "value": run_id, "normalized": run_id},
                {"name": "phase26_summary", "value": summary, "normalized": summary},
            ],
            requires_approval=True,
            risk_level="medium",
            reason="Workflow cancellation requires explicit approval.",
        )
        return None, composed

    project = _phase26_workflow_project(normalized_utterance)
    if not isinstance(project, dict):
        return _phase19_clarify_response(
            utterance=normalized_utterance,
            message="No active project. Create or select a project first.",
        )
    project_id = str(project.get("project_id", "")).strip()
    workflows = _phase26_workflows_for_project(project_id)

    if intent == "list_workflows":
        listed = [copy.deepcopy(item) for item in workflows if isinstance(item, dict)]
        names = [str(item.get("name", "")) for item in listed]
        return {
            "type": "workflows_list",
            "executed": False,
            "project": copy.deepcopy(project),
            "workflows": listed,
            "message": "\n".join(names) if names else "No workflows defined for this project.",
        }, envelope

    workflow_name = _entity_string(envelope, "workflow_name")
    if not workflow_name:
        workflow_name = _phase26_extract_workflow_name(
            normalized_utterance,
            verbs=["describe", "preview", "run", "status"],
        )

    if intent == "define_workflow":
        name = _normalize(workflow_name).lower()
        if not name:
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message="Provide a workflow name (for example: define workflow named site_build).",
            )
        description = _entity_string(envelope, "workflow_description") or f"Workflow {name}"
        schema_json = _entity_string(envelope, "workflow_schema_json")
        steps_json = _entity_string(envelope, "workflow_steps_json")

        schema_payload = _phase26_parse_json_payload(schema_json) if schema_json else {}
        if schema_payload is None:
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message="Workflow schema must be valid JSON.",
            )
        schema = schema_payload if isinstance(schema_payload, dict) else {}
        schema_error = _phase26_validate_schema(schema)
        if schema_error:
            return _phase19_clarify_response(utterance=normalized_utterance, message=schema_error)

        steps_payload = _phase26_parse_json_payload(steps_json) if steps_json else None
        if steps_payload is None:
            steps = [
                {
                    "step_id": "step1",
                    "description": "Delegate stylesheet draft",
                    "intent": "delegate_to_agent",
                    "parameters": {"agent_type": "CODING", "task": "creating the stylesheet"},
                    "depends_on": [],
                },
                {
                    "step_id": "step2",
                    "description": "Write workflow marker file",
                    "intent": "write_file",
                    "parameters": {"path": "sandbox/phase26_workflow_output.txt", "contents": "phase26 workflow output"},
                    "depends_on": ["step1"],
                },
            ]
        elif not isinstance(steps_payload, list):
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message="Workflow steps must be a JSON array.",
            )
        else:
            steps = [item for item in steps_payload if isinstance(item, dict)]

        step_error = _phase26_validate_steps(steps=steps, schema=schema)
        if step_error:
            return _phase19_clarify_response(utterance=normalized_utterance, message=step_error)

        now = _utcnow().isoformat()
        workflow = {
            "workflow_id": f"wf-{uuid.uuid4()}",
            "project_id": project_id,
            "name": name,
            "description": description or f"Workflow {name}",
            "parameters_schema": copy.deepcopy(schema),
            "steps": copy.deepcopy(steps),
            "created_at": now,
            "updated_at": now,
        }
        replaced = False
        for index, existing in enumerate(workflows):
            if not isinstance(existing, dict):
                continue
            if _normalize(str(existing.get("name", ""))).lower() == name:
                workflow["workflow_id"] = str(existing.get("workflow_id", workflow["workflow_id"]))
                workflow["created_at"] = str(existing.get("created_at", now))
                workflows[index] = copy.deepcopy(workflow)
                replaced = True
                break
        if not replaced:
            workflows.append(copy.deepcopy(workflow))
        _phase22_update_project_timestamp(project_id)
        return {
            "type": "workflow_defined",
            "executed": False,
            "project": copy.deepcopy(project),
            "workflow": copy.deepcopy(workflow),
            "message": (
                f"Workflow '{name}' {'updated' if replaced else 'defined'} with {len(steps)} steps."
            ),
        }, envelope

    workflow = _phase26_workflow_by_name(project_id, workflow_name)
    if not isinstance(workflow, dict):
        return _phase19_clarify_response(
            utterance=normalized_utterance,
            message=f"Unknown workflow '{workflow_name or 'requested'}'.",
        )

    if intent == "describe_workflow":
        return {
            "type": "workflow_description",
            "executed": False,
            "project": copy.deepcopy(project),
            "workflow": copy.deepcopy(workflow),
            "message": _phase26_workflow_message(workflow),
        }, envelope

    parameters_json = _entity_string(envelope, "workflow_parameters_json")
    parameter_bindings: Dict[str, str] = {}
    if parameters_json:
        parsed_params = _phase26_parse_json_payload(parameters_json)
        if isinstance(parsed_params, dict):
            parameter_bindings = {str(key).strip().lower(): str(value) for key, value in parsed_params.items()}

    schema = workflow.get("parameters_schema", {})
    schema = schema if isinstance(schema, dict) else {}
    missing_error = _phase26_required_parameter_error(schema, parameter_bindings)
    if missing_error:
        return _phase19_clarify_response(
            utterance=normalized_utterance,
            message=missing_error,
        )

    raw_steps = workflow.get("steps", [])
    raw_steps = raw_steps if isinstance(raw_steps, list) else []
    ordered = _phase26_order_steps(raw_steps)
    resolved_steps: List[Dict[str, Any]] = []
    for item in ordered:
        if not isinstance(item, dict):
            continue
        resolved = copy.deepcopy(item)
        resolved["parameters"] = _phase26_bind_parameter_value(resolved.get("parameters", {}), parameter_bindings)
        resolved["depends_on"] = [
            _normalize(str(dep))
            for dep in (resolved.get("depends_on", []) if isinstance(resolved.get("depends_on", []), list) else [])
            if _normalize(str(dep))
        ]
        resolved_steps.append(resolved)
    side_effects = _phase26_estimated_side_effects(resolved_steps)

    if intent == "preview_workflow":
        lines = [f"Workflow preview: {workflow.get('name', '')}"]
        for index, step in enumerate(resolved_steps, start=1):
            lines.append(
                f"{index}. {step.get('step_id', '')} -> {step.get('intent', '')} params={json.dumps(step.get('parameters', {}), ensure_ascii=True)}"
            )
        if side_effects:
            lines.append("Estimated side effects:")
            lines.extend([f"- {item}" for item in side_effects])
        return {
            "type": "workflow_preview",
            "executed": False,
            "project": copy.deepcopy(project),
            "workflow": copy.deepcopy(workflow),
            "preview": {"steps": resolved_steps, "side_effects": side_effects, "parameters": parameter_bindings},
            "message": "\n".join(lines),
        }, envelope

    run_id = f"wfr-{uuid.uuid4()}"
    now = _utcnow().isoformat()
    run = {
        "run_id": run_id,
        "workflow_id": str(workflow.get("workflow_id", "")),
        "workflow_name": str(workflow.get("name", "")),
        "project_id": project_id,
        "status": "PENDING_APPROVAL",
        "current_step_index": 0,
        "current_step_id": _normalize(str(resolved_steps[0].get("step_id", ""))) if resolved_steps else "",
        "completed_steps": [],
        "pending_steps": [_normalize(str(item.get("step_id", ""))) for item in resolved_steps if _normalize(str(item.get("step_id", "")))],
        "steps_ordered": copy.deepcopy(resolved_steps),
        "parameter_bindings": copy.deepcopy(parameter_bindings),
        "execution_event_ids": [],
        "side_effects": side_effects,
        "failure": "",
        "created_at": now,
        "updated_at": now,
        "started_at": "",
        "finished_at": "",
        "session_id": session_key,
    }
    _phase26_runs_by_id[run_id] = copy.deepcopy(run)
    _phase26_last_run_by_session[session_key] = run_id

    summary = (
        f"Run workflow '{workflow.get('name', '')}' "
        f"({len(resolved_steps)} steps, side_effects={len(side_effects)})."
    )
    composed = _phase17_envelope_for_intent(
        utterance=normalized_utterance,
        intent="plan.user_action_request",
        entities=[
            {"name": "phase26_run_start", "value": "true", "normalized": "true"},
            {"name": "phase26_run_id", "value": run_id, "normalized": run_id},
            {"name": "phase26_workflow_id", "value": str(workflow.get("workflow_id", "")), "normalized": str(workflow.get("workflow_id", ""))},
            {"name": "phase26_workflow_name", "value": str(workflow.get("name", "")), "normalized": str(workflow.get("name", ""))},
            {"name": "phase22_project_id", "value": project_id, "normalized": project_id},
            {"name": "phase26_summary", "value": summary, "normalized": summary},
        ],
        requires_approval=True,
        risk_level="medium",
        reason="Workflow run requires explicit approval before execution.",
    )
    return None, composed


def _invoke_delegated_agent(contract: Dict[str, Any]) -> Dict[str, Any]:
    agent_type = _normalize(str(contract.get("agent_type", ""))).upper()
    task = _normalize(str(contract.get("task_description", "")))
    requested_tool = _normalize(str(contract.get("requested_tool", "")))
    lowered = task.lower()

    if "stylesheet" in lowered or " css" in lowered or lowered.endswith("css"):
        result_text = "/* delegated stylesheet draft */\nbody { margin: 0; font-family: sans-serif; }\n"
    elif "navigation" in lowered or "nav" in lowered:
        result_text = "<nav><a href=\"/\">Home</a> <a href=\"/about\">About</a></nav>\n"
    elif requested_tool == "transform_content":
        result_text = f"Transformed delegation output for task: {task}"
    elif requested_tool == "revise_content":
        result_text = f"Revised delegation output for task: {task}"
    elif requested_tool == "content_generation":
        result_text = f"{agent_type} draft:\n{task}"
    else:
        result_text = f"# Delegated {agent_type} output\n{task}\n"

    summary = f"Prepared delegated {agent_type} output for '{task}'."
    return {
        "result_text": result_text,
        "result_summary": summary,
    }


def _phase25_apply_to_envelope(
    *,
    envelope: Envelope,
    normalized_utterance: str,
) -> tuple[Dict[str, Any] | None, Envelope]:
    if not _phase25_enabled:
        return None, envelope
    intent = str(envelope.get("intent", "")).strip()
    if intent not in _PHASE25_DELEGATION_INTENTS:
        return None, envelope

    if intent == "list_delegation_capabilities":
        capabilities = _phase25_capabilities_list()
        lines = [
            f"{item.get('agent_type', '')}: {item.get('description', '')} "
            f"(allowed_tools={', '.join(item.get('allowed_tools', []))})"
            for item in capabilities
        ]
        return {
            "type": "delegation_capabilities",
            "executed": False,
            "capabilities": capabilities,
            "message": "\n".join(lines) if lines else "No delegation capabilities are registered.",
        }, envelope

    if intent == "describe_delegation_result":
        record = _phase25_last_delegation()
        if not isinstance(record, dict):
            return _phase19_clarify_response(
                utterance=normalized_utterance,
                message="No delegation result is available in this session yet.",
            )
        return {
            "type": "delegation_result",
            "executed": False,
            "delegation": copy.deepcopy(record),
            "message": _phase25_result_message(record),
        }, envelope

    agent_type = _entity_string(envelope, "delegation_agent_type") or _phase25_extract_agent_type(normalized_utterance)
    if not agent_type:
        return _phase19_clarify_response(
            utterance=normalized_utterance,
            message="Specify which specialist agent type to use (for example: coding agent).",
        )
    capability = _phase25_capability_registry().get(agent_type.upper())
    if not isinstance(capability, dict):
        return _phase19_clarify_response(
            utterance=normalized_utterance,
            message=f"Unknown delegation agent type '{agent_type}'.",
        )

    task_description = _entity_string(envelope, "delegation_task") or _phase25_extract_task(normalized_utterance)
    if not task_description:
        return _phase19_clarify_response(
            utterance=normalized_utterance,
            message="Describe the task to delegate.",
        )
    requested_tool = _phase25_requested_tool(task_description)
    allowed_tools = capability.get("allowed_tools", [])
    allowed_tools = allowed_tools if isinstance(allowed_tools, list) else []
    if requested_tool not in allowed_tools:
        return _phase19_clarify_response(
            utterance=normalized_utterance,
            message=(
                f"Delegation rejected: {agent_type.upper()} does not allow '{requested_tool}'. "
                "Choose a compatible agent or revise the task scope."
            ),
        )

    project = _phase22_resolve_project_from_utterance(normalized_utterance)
    project_id = str(project.get("project_id", "")) if isinstance(project, dict) else ""
    project_name = str(project.get("name", "")) if isinstance(project, dict) else ""
    delegation_id = f"dlg-{uuid.uuid4()}"
    contract = DelegationContract(
        delegation_id=delegation_id,
        agent_type=agent_type.upper(),
        task_description=task_description,
        allowed_tools=list(allowed_tools),
        requested_tool=requested_tool,
        project_id=project_id,
        project_name=project_name,
        created_at=_utcnow().isoformat(),
    )
    contract_dict = _phase25_contract_to_dict(contract)
    _phase25_contracts_by_id[delegation_id] = copy.deepcopy(contract_dict)
    summary = (
        f"Delegation {delegation_id}: agent_type: {contract.agent_type}; "
        f"requested_tool: {contract.requested_tool}; task: {contract.task_description}."
    )
    entities: List[Dict[str, Any]] = [
        {"name": "phase25_delegation", "value": "true", "normalized": "true"},
        {"name": "phase25_delegation_id", "value": delegation_id, "normalized": delegation_id},
        {"name": "phase25_agent_type", "value": contract.agent_type, "normalized": contract.agent_type},
        {"name": "phase25_task", "value": contract.task_description, "normalized": contract.task_description},
        {"name": "phase25_requested_tool", "value": contract.requested_tool, "normalized": contract.requested_tool},
        {"name": "phase25_contract_json", "value": json.dumps(contract_dict, ensure_ascii=True), "normalized": json.dumps(contract_dict, ensure_ascii=True)},
        {"name": "phase25_summary", "value": summary, "normalized": summary},
    ]
    if project_id:
        entities.append({"name": "phase22_project_id", "value": project_id, "normalized": project_id})
    composed = _phase17_envelope_for_intent(
        utterance=normalized_utterance,
        intent="plan.user_action_request",
        entities=entities,
        requires_approval=True,
        risk_level="medium",
        reason="Delegation execution requires explicit human approval.",
    )
    return None, composed


def _interpret_phase1(utterance: str) -> Envelope:
    """Frozen Phase 1 deterministic interpreter behavior."""
    normalized = _normalize(utterance)
    lowered = normalized.lower()

    # Fixture-aligned deterministic outputs (Phase 0 golden contract).
    if lowered == "what is a cool thing to drink?":
        return _envelope(
            utterance=normalized,
            lane="CHAT",
            intent="chat.recommend_drink",
            confidence=0.96,
            requires_approval=False,
            risk_level="low",
            allowed=True,
            reason="Benign conversational recommendation request.",
            next_prompt="",
        )

    if lowered == "where are you?":
        return _envelope(
            utterance=normalized,
            lane="CHAT",
            intent="chat.identity_location_question",
            confidence=0.93,
            requires_approval=False,
            risk_level="low",
            allowed=True,
            reason="Identity/context question; must not trigger service inspection or execution paths.",
            next_prompt="",
        )

    if lowered == "/engineer":
        return _envelope(
            utterance=normalized,
            lane="ENGINEER",
            intent="engineer.enter_mode",
            confidence=0.99,
            requires_approval=False,
            risk_level="low",
            allowed=True,
            reason="Explicit engineering-mode intent without execution side effects.",
            next_prompt="What engineering problem should be analyzed?",
        )

    if lowered == "create an empty text file in your home directory":
        return _envelope(
            utterance=normalized,
            lane="PLAN",
            intent="plan.create_empty_file",
            entities=[
                {
                    "name": "target_location",
                    "value": "home directory",
                    "normalized": "$HOME",
                },
                {
                    "name": "file_state",
                    "value": "empty",
                },
            ],
            confidence=0.95,
            requires_approval=True,
            risk_level="medium",
            allowed=True,
            reason="State-changing request requires explicit approval before any execution path.",
            next_prompt="What filename should be used in the home directory?",
        )

    if lowered == "qzv blorp":
        return _envelope(
            utterance=normalized,
            lane="CLARIFY",
            intent="clarify.request_context",
            confidence=0.22,
            requires_approval=False,
            risk_level="low",
            allowed=True,
            reason="Ambiguous input requires clarification before any route selection.",
            next_prompt="Can you clarify what outcome you want?",
        )

    phase26_envelope = _parse_phase26_intent(normalized)
    if phase26_envelope is not None:
        return phase26_envelope

    phase25_envelope = _parse_phase25_intent(normalized)
    if phase25_envelope is not None:
        return phase25_envelope

    phase24_envelope = _parse_phase24_intent(normalized)
    if phase24_envelope is not None:
        return phase24_envelope

    phase23_envelope = _parse_phase23_intent(normalized)
    if phase23_envelope is not None:
        return phase23_envelope

    phase22_envelope = _parse_phase22_intent(normalized)
    if phase22_envelope is not None:
        return phase22_envelope

    phase21_envelope = _parse_phase21_intent(normalized)
    if phase21_envelope is not None:
        return phase21_envelope

    persist_note_envelope = _parse_persist_note_intent(normalized)
    if persist_note_envelope is not None:
        return persist_note_envelope

    filesystem_envelope = _parse_filesystem_intent(normalized)
    if filesystem_envelope is not None:
        return filesystem_envelope

    capture_request = _parse_capture_request(normalized)
    if capture_request is not None:
        valid = bool(capture_request.get("valid"))
        return _envelope(
            utterance=normalized,
            lane="HELP",
            intent="capture_content",
            confidence=0.94 if valid else 0.50,
            requires_approval=False,
            risk_level="low",
            allowed=True,
            reason=(
                "Explicit content-capture request routed through governed interpreter."
                if valid
                else str(capture_request.get("reason") or "Capture request requires clarification.")
            ),
            next_prompt="",
        )

    content_generation_route = _content_generation_route(normalized)
    if content_generation_route == "content_generation":
        return _envelope(
            utterance=normalized,
            lane="CONTENT_GENERATION",
            intent="content_generation.draft",
            confidence=0.90,
            requires_approval=False,
            risk_level="low",
            allowed=True,
            reason="Text generation request routed to content-generation mode for review-only output.",
            next_prompt="",
        )
    if content_generation_route == "clarify":
        return _envelope(
            utterance=normalized,
            lane="CLARIFY",
            intent="clarify.request_context",
            confidence=0.32,
            requires_approval=False,
            risk_level="low",
            allowed=True,
            reason="Generation request is underspecified and requires clarification before drafting content.",
            next_prompt="What content should I draft for review?",
        )

    # General deterministic fallback rules.
    if lowered.startswith("/"):
        return _envelope(
            utterance=normalized,
            lane="HELP",
            intent="help.slash_command",
            confidence=0.85,
            requires_approval=False,
            risk_level="low",
            allowed=True,
            reason="Slash command recognized as explicit control-style input requiring guidance.",
            next_prompt="Use an explicit supported command or describe your goal in plain text.",
        )

    if _is_action_like(normalized):
        return _envelope(
            utterance=normalized,
            lane="PLAN",
            intent="plan.user_action_request",
            confidence=0.82,
            requires_approval=True,
            risk_level="medium",
            allowed=True,
            reason="Action-like request interpreted as planning intent pending explicit approval.",
            next_prompt="Please provide concrete parameters so a safe plan can be drafted.",
        )

    if _looks_ambiguous(normalized):
        return _envelope(
            utterance=normalized,
            lane="CLARIFY",
            intent="clarify.request_context",
            confidence=0.30,
            requires_approval=False,
            risk_level="low",
            allowed=True,
            reason="Input is underspecified and needs clarification before planning or engineering lanes.",
            next_prompt="Can you clarify what you want me to help with?",
        )

    if _is_conversational(normalized):
        return _envelope(
            utterance=normalized,
            lane="CHAT",
            intent="chat.general",
            confidence=0.80,
            requires_approval=False,
            risk_level="low",
            allowed=True,
            reason="Benign conversational input.",
            next_prompt="",
        )

    return _envelope(
        utterance=normalized,
        lane="CLARIFY",
        intent="clarify.request_context",
        confidence=0.35,
        requires_approval=False,
        risk_level="low",
        allowed=True,
        reason="Input could not be mapped confidently; clarification required.",
        next_prompt="Please clarify the outcome you want.",
    )


class SemanticLaneRouter(Protocol):
    """Swappable semantic lane router abstraction."""

    def route_lane(self, utterance: str) -> tuple[Lane, float]:
        ...


@dataclass(frozen=True)
class _LaneProfile:
    lane: Lane
    tokens: tuple[str, ...]
    phrases: tuple[str, ...]


class KeywordSemanticLaneRouter:
    """Deterministic semantic lane scoring using token/phrase overlap."""

    def __init__(self, profiles: List[_LaneProfile] | None = None) -> None:
        self._profiles = profiles or [
            _LaneProfile(
                lane="HELP",
                tokens=("help", "how", "guide", "explain", "usage", "learn"),
                phrases=("how do i", "how can i", "help me", "show me how"),
            ),
            _LaneProfile(
                lane="PLAN",
                tokens=(
                    "create",
                    "write",
                    "delete",
                    "remove",
                    "update",
                    "modify",
                    "rename",
                    "move",
                    "copy",
                    "file",
                ),
                phrases=("create a", "build a", "make a", "update the"),
            ),
            _LaneProfile(
                lane="CHAT",
                tokens=("what", "who", "where", "when", "why", "talk", "chat"),
                phrases=("what is", "who are", "where are", "tell me"),
            ),
            _LaneProfile(
                lane="CLARIFY",
                tokens=("unknown", "unclear", "ambiguous"),
                phrases=(),
            ),
        ]

    def route_lane(self, utterance: str) -> tuple[Lane, float]:
        normalized = _normalize(utterance).lower()
        tokens = set(re.findall(r"[a-z0-9]+", normalized))
        if not tokens:
            return "CLARIFY", 0.0

        best_lane = "CLARIFY"
        best_score = 0.0
        for profile in self._profiles:
            score = self._score_profile(normalized, tokens, profile)
            if score > best_score:
                best_score = score
                best_lane = profile.lane

        return best_lane, round(best_score, 2)

    @staticmethod
    def _score_profile(normalized: str, tokens: set[str], profile: _LaneProfile) -> float:
        profile_tokens = set(profile.tokens)
        token_overlap = len(tokens & profile_tokens) / max(1, len(profile_tokens))
        phrase_hit = any(phrase in normalized for phrase in profile.phrases)
        score = token_overlap + (0.60 if phrase_hit else 0.0)
        return min(1.0, score)


_semantic_lane_router: SemanticLaneRouter = KeywordSemanticLaneRouter()


def set_semantic_lane_router(router: SemanticLaneRouter) -> None:
    """Swap semantic lane router implementation without touching interpreter logic."""
    global _semantic_lane_router
    _semantic_lane_router = router


def _coarse_intent_for_lane(lane: Lane) -> str:
    return {
        "CHAT": "chat.general",
        "PLAN": "plan.user_action_request",
        "HELP": "help.guidance",
        "CLARIFY": "clarify.request_context",
        "CONTENT_GENERATION": "content_generation.draft",
    }.get(lane, "clarify.request_context")


def _apply_semantic_lane(base: Envelope, lane: Lane, confidence: float) -> Envelope:
    updated = dict(base)
    updated["lane"] = lane
    updated["intent"] = _coarse_intent_for_lane(lane)
    updated["confidence"] = confidence
    updated["requires_approval"] = lane == "PLAN"

    policy = dict(base.get("policy", {}))
    policy["allowed"] = True
    if lane == "PLAN":
        policy["risk_level"] = "medium"
        policy["reason"] = "Semantic lane routing identified action/planning intent."
    elif lane == "HELP":
        policy["risk_level"] = "low"
        policy["reason"] = "Semantic lane routing identified guidance/help intent."
    elif lane == "CHAT":
        policy["risk_level"] = "low"
        policy["reason"] = "Semantic lane routing identified conversational intent."
    elif lane == "CONTENT_GENERATION":
        policy["risk_level"] = "low"
        policy["reason"] = "Semantic lane routing identified content generation intent."
    else:
        policy["risk_level"] = "low"
        policy["reason"] = "Semantic lane routing requested clarification."
    updated["policy"] = policy

    if lane == "CLARIFY" and not str(updated.get("next_prompt", "")).strip():
        updated["next_prompt"] = "Please clarify the outcome you want."
    return updated


def _interpret_phase2(utterance: str) -> Envelope:
    """Phase 2 semantic lane routing with deterministic fallback."""
    phase1_envelope = _interpret_phase1(utterance)
    normalized = _normalize(utterance)

    # Keep explicit slash-command handling under frozen deterministic behavior.
    if normalized.startswith("/"):
        return phase1_envelope

    # Preserve explicit filesystem clarification prompts (missing required params).
    filesystem_candidate = _parse_filesystem_intent(normalized)
    if filesystem_candidate is not None and str(filesystem_candidate.get("lane", "")).upper() == "CLARIFY":
        return phase1_envelope

    lane, semantic_confidence = _semantic_lane_router.route_lane(normalized)

    # Mandatory deterministic fallback when confidence is low.
    if semantic_confidence < _SEMANTIC_CONFIDENCE_THRESHOLD:
        return phase1_envelope

    # Keep frozen envelope unchanged when semantic router agrees on lane.
    if lane == phase1_envelope.get("lane"):
        return phase1_envelope

    return _apply_semantic_lane(phase1_envelope, lane=lane, confidence=semantic_confidence)


def set_phase3_enabled(enabled: bool) -> None:
    """Enable or disable Phase 3 extraction without changing Phase 1/2 behavior."""
    global _phase3_enabled
    _phase3_enabled = bool(enabled)


@lru_cache(maxsize=1)
def _intent_envelope_schema() -> dict:
    schema_path = Path(__file__).resolve().parents[2] / "schemas" / "intent_envelope.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _load_model_config() -> dict:
    config_path = Path(__file__).resolve().parents[1] / "config.yaml"
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        model_cfg = data.get("model", {})
        return model_cfg if isinstance(model_cfg, dict) else {}
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _phase4_policy_rules() -> dict[str, dict[str, Any]]:
    rules_path = Path(__file__).resolve().parents[1] / "contracts" / "intent_policy_rules.yaml"
    try:
        payload = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}
    except Exception:
        payload = {}

    raw_rules = payload.get("rules", {})
    if not isinstance(raw_rules, dict):
        return {}

    rules: dict[str, dict[str, Any]] = {}
    for key, value in raw_rules.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        rule = {
            "allowed": bool(value.get("allowed", False)),
            "risk_level": str(value.get("risk_level", "critical")),
            "requires_approval": bool(value.get("requires_approval", True)),
            "reason": str(value.get("reason", "Policy rule matched.")),
        }
        rules[key] = rule
    return rules


@lru_cache(maxsize=1)
def _phase6_tool_contract_registry() -> dict[str, ToolContract]:
    registry_path = Path(__file__).resolve().parents[1] / "contracts" / "intent_tool_contracts.yaml"
    try:
        payload = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    except Exception:
        payload = {}

    raw_contracts = payload.get("contracts", [])
    if not isinstance(raw_contracts, list):
        return {}

    registry: dict[str, ToolContract] = {}
    for item in raw_contracts:
        if not isinstance(item, dict):
            continue
        try:
            contract = ToolContract(
                tool_name=str(item["tool_name"]),
                intent=str(item["intent"]),
                description=str(item["description"]),
                input_schema=dict(item["input_schema"]),
                output_schema=dict(item["output_schema"]),
                risk_level=str(item["risk_level"]),
                side_effects=bool(item["side_effects"]),
            )
        except Exception:
            continue

        if contract.intent in registry:
            continue
        registry[contract.intent] = contract
    return registry


def get_tool_contract_registry() -> Dict[str, ToolContract]:
    return dict(_phase6_tool_contract_registry())


def _resolve_tool_contract(intent: str) -> ToolContract | None:
    if not isinstance(intent, str) or not intent.strip():
        return None
    return _phase6_tool_contract_registry().get(intent.strip())


def _call_llm_for_intent_json(utterance: str, envelope: Envelope) -> str | None:
    """Isolated LLM call for Phase 3 extraction."""
    model_config = _load_model_config()
    if not model_config:
        return None

    prompt_payload = {
        "utterance": utterance,
        "current_envelope": envelope,
        "instructions": {
            "return_json_only": True,
            "allowed_fields": ["intent", "entities", "confidence"],
            "forbidden_fields": ["lane", "policy", "requires_approval", "utterance", "next_prompt"],
        },
    }
    messages = [
        {
            "role": "system",
            "content": (
                "Return JSON only. Output a single object with keys intent, entities, confidence. "
                "Do not include markdown, comments, or extra keys."
            ),
        },
        {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=True)},
    ]
    try:
        return llm_api.get_completion(messages, model_config)
    except Exception:
        return None


def _parse_llm_extraction(raw: str | None) -> dict | None:
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _merge_extraction_fields(base: Envelope, extracted: dict) -> Envelope | None:
    intent = extracted.get("intent")
    entities = extracted.get("entities")
    confidence = extracted.get("confidence")
    if not isinstance(intent, str) or not intent.strip():
        return None
    if not isinstance(entities, list):
        return None
    if not isinstance(confidence, (int, float)):
        return None

    candidate = dict(base)
    candidate["intent"] = intent
    candidate["entities"] = entities
    candidate["confidence"] = float(confidence)
    return candidate


def _is_valid_envelope(envelope: Envelope) -> bool:
    schema = _intent_envelope_schema()
    try:
        jsonschema.validate(envelope, schema)
    except jsonschema.ValidationError:
        return False
    return True


def _extract_intent_with_llm(utterance: str, phase2_envelope: Envelope) -> Envelope | None:
    for _attempt in range(_PHASE3_MAX_RETRIES):
        raw = _call_llm_for_intent_json(utterance, phase2_envelope)
        parsed = _parse_llm_extraction(raw)
        if parsed is None:
            continue

        merged = _merge_extraction_fields(phase2_envelope, parsed)
        if merged is None:
            continue

        # Lane/policy/requires_approval remain Phase 2 authoritative.
        merged["lane"] = phase2_envelope["lane"]
        merged["policy"] = dict(phase2_envelope["policy"])
        merged["requires_approval"] = phase2_envelope["requires_approval"]

        if _is_valid_envelope(merged):
            return merged

    return None


def _interpret_phase3(utterance: str) -> Envelope:
    phase2_envelope = _interpret_phase2(utterance)
    if not _phase3_enabled:
        return phase2_envelope

    extracted = _extract_intent_with_llm(utterance, phase2_envelope)
    if extracted is None:
        return phase2_envelope
    return extracted


def set_phase4_enabled(enabled: bool) -> None:
    global _phase4_enabled
    _phase4_enabled = bool(enabled)


def set_phase4_explanation_enabled(enabled: bool) -> None:
    global _phase4_explanation_enabled
    _phase4_explanation_enabled = bool(enabled)


def _resolve_policy_rule(lane: str, intent: str) -> dict[str, Any]:
    rules = _phase4_policy_rules()
    direct_key = f"{lane}::{intent}"
    lane_key = f"{lane}::*"
    if direct_key in rules:
        return dict(rules[direct_key])
    if lane_key in rules:
        return dict(rules[lane_key])
    return dict(_PHASE4_DEFAULT_POLICY)


def _apply_phase4_policy_deterministic(envelope: Envelope) -> Envelope:
    lane = str(envelope.get("lane", "CLARIFY"))
    intent = str(envelope.get("intent", "clarify.request_context"))
    rule = _resolve_policy_rule(lane, intent)

    updated = dict(envelope)
    policy = dict(updated.get("policy", {}))
    policy["allowed"] = bool(rule["allowed"])
    policy["risk_level"] = str(rule["risk_level"])
    policy["reason"] = str(rule["reason"])
    updated["policy"] = policy
    updated["requires_approval"] = bool(rule["requires_approval"])
    return updated


def _call_llm_for_policy_reason(envelope: Envelope, policy_result: Envelope) -> str | None:
    model_config = _load_model_config()
    if not model_config:
        return None

    prompt_payload = {
        "envelope": envelope,
        "deterministic_policy": {
            "allowed": policy_result["policy"]["allowed"],
            "risk_level": policy_result["policy"]["risk_level"],
            "requires_approval": policy_result["requires_approval"],
        },
        "instructions": {
            "task": "Provide a concise human-readable explanation for policy.reason only.",
            "must_not_change_decision": True,
            "output_format": {"reason": "string"},
        },
    }
    messages = [
        {
            "role": "system",
            "content": "Return JSON only with key: reason. Do not include any other keys.",
        },
        {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=True)},
    ]
    try:
        return llm_api.get_completion(messages, model_config)
    except Exception:
        return None


def _apply_phase4_explanation(envelope: Envelope, deterministic_result: Envelope) -> Envelope:
    raw = _call_llm_for_policy_reason(envelope, deterministic_result)
    if not isinstance(raw, str):
        return deterministic_result
    try:
        parsed = json.loads(raw.strip())
    except json.JSONDecodeError:
        return deterministic_result
    if not isinstance(parsed, dict):
        return deterministic_result
    reason = parsed.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return deterministic_result

    updated = dict(deterministic_result)
    policy = dict(updated.get("policy", {}))
    policy["reason"] = reason.strip()
    updated["policy"] = policy
    return updated


def _interpret_phase4(phase3_envelope: Envelope) -> Envelope:
    if not _phase4_enabled:
        return phase3_envelope

    deterministic_result = _apply_phase4_policy_deterministic(phase3_envelope)
    if not _phase4_explanation_enabled:
        return deterministic_result
    return _apply_phase4_explanation(phase3_envelope, deterministic_result)


def interpret_utterance(utterance: str) -> Envelope:
    """Interpret raw user text into a canonical, auditable intent envelope."""
    phase3_envelope = _interpret_phase3(utterance)
    return _interpret_phase4(phase3_envelope)


def set_phase5_enabled(enabled: bool) -> None:
    global _phase5_enabled
    _phase5_enabled = bool(enabled)


def set_phase8_enabled(enabled: bool) -> None:
    global _phase8_enabled
    _phase8_enabled = bool(enabled)


def set_phase19_enabled(enabled: bool) -> None:
    global _phase19_enabled
    _phase19_enabled = bool(enabled)


def set_phase20_enabled(enabled: bool) -> None:
    global _phase20_enabled
    _phase20_enabled = bool(enabled)


def set_phase21_enabled(enabled: bool) -> None:
    global _phase21_enabled
    _phase21_enabled = bool(enabled)


def set_phase22_enabled(enabled: bool) -> None:
    global _phase22_enabled
    _phase22_enabled = bool(enabled)


def set_phase23_enabled(enabled: bool) -> None:
    global _phase23_enabled
    _phase23_enabled = bool(enabled)


def set_phase24_enabled(enabled: bool) -> None:
    global _phase24_enabled
    _phase24_enabled = bool(enabled)


def set_phase25_enabled(enabled: bool) -> None:
    global _phase25_enabled
    _phase25_enabled = bool(enabled)


def set_phase26_enabled(enabled: bool) -> None:
    global _phase26_enabled
    _phase26_enabled = bool(enabled)


def set_current_working_set(
    label: str,
    content_id: str,
    working_type: str,
    *,
    source: str = "user_supplied",
    text: str = "",
    path: str = "",
) -> None:
    _phase20_set_working_set(
        {
            "label": _normalize(label),
            "content_id": _normalize(content_id),
            "type": _phase20_normalize_working_set_type(working_type),
            "source": _normalize(source),
            "path": _normalize(path),
            "text": str(text),
            "origin_turn_id": str(current_correlation_id() or ""),
        },
        reason="manual_set",
    )


def reset_current_working_set(session_id: str | None = None) -> bool:
    return _phase20_clear_working_set(reason="manual_reset", session_id=session_id)


def get_current_working_set(session_id: str | None = None) -> Dict[str, Any] | None:
    return _phase20_get_working_set(session_id)


def set_phase8_approval_mode(mode: str) -> None:
    global _phase8_approval_mode
    normalized = _normalize(mode).lower()
    if normalized not in {"step", "plan"}:
        raise ValueError(f"Unsupported Phase 8 approval mode: {mode}")
    _phase8_approval_mode = normalized


def set_tool_invoker(invoker: ToolInvoker) -> None:
    global _tool_invoker
    _tool_invoker = invoker


def configure_memory_store(mode: str, *, path: str | None = None) -> None:
    """Configure append-only memory store backend.

    Supported modes:
    - in_memory
    - file (requires path)
    """
    global _memory_store
    normalized = _normalize(mode).lower()
    if normalized == "in_memory":
        _memory_store = InMemoryMemoryStore()
        return
    if normalized == "file":
        if not path or not str(path).strip():
            raise ValueError("File-backed memory mode requires a non-empty path.")
        _memory_store = FileBackedMemoryStore(path)
        return
    raise ValueError(f"Unsupported memory store mode: {mode}")


def set_memory_store(store: MemoryStore) -> None:
    global _memory_store
    _memory_store = store


def configure_capture_store(mode: str, *, path: str | None = None) -> None:
    """Configure captured-content store backend.

    Supported modes:
    - in_memory
    - file (requires path)
    """
    global _capture_store
    normalized = _normalize(mode).lower()
    if normalized == "in_memory":
        _capture_store = InMemoryContentCaptureStore()
        return
    if normalized == "file":
        if not path or not str(path).strip():
            raise ValueError("File-backed capture mode requires a non-empty path.")
        _capture_store = FileBackedContentCaptureStore(path)
        return
    raise ValueError(f"Unsupported capture store mode: {mode}")


def set_capture_store(store: ContentCaptureStore) -> None:
    global _capture_store
    _capture_store = store


def get_captured_content_last(count: int) -> List[Dict[str, Any]]:
    return [item.to_dict() for item in _capture_store.get_last(count)]


def get_captured_content_by_id(content_id: str) -> Dict[str, Any] | None:
    item = _capture_store.get_by_id(content_id)
    return item.to_dict() if item is not None else None


def get_captured_content_by_label(label: str) -> List[Dict[str, Any]]:
    return [item.to_dict() for item in _capture_store.get_by_label(label)]


def get_memory_events_last(count: int) -> List[Dict[str, Any]]:
    return [event.to_dict() for event in _memory_store.get_last(count)]


def get_memory_events_by_intent(intent: str) -> List[Dict[str, Any]]:
    return [event.to_dict() for event in _memory_store.get_by_intent(intent)]


def get_memory_events_by_tool(tool_name: str) -> List[Dict[str, Any]]:
    return [event.to_dict() for event in _memory_store.get_by_tool(tool_name)]


def get_observability_trace(session_id: str) -> TraceReport:
    from v2.core.observability import get_session_events

    return build_trace_report(session_id=session_id, events=get_session_events(session_id))


def get_observability_metrics() -> MetricsSummary:
    return get_metrics_summary()


def reset_observability_state() -> None:
    reset_telemetry_events()
    reset_metrics()


def _memory_events_filtered(
    *,
    limit: int = 50,
    intent: str | None = None,
    tool_name: str | None = None,
) -> List[Dict[str, Any]]:
    if intent and tool_name:
        by_intent = _memory_store.get_by_intent(intent)
        by_tool = _memory_store.get_by_tool(tool_name)
        by_tool_tuples = {
            (event.timestamp, event.intent, event.tool_name, event.success) for event in by_tool
        }
        filtered = [
            event
            for event in by_intent
            if (event.timestamp, event.intent, event.tool_name, event.success) in by_tool_tuples
        ]
    elif intent:
        filtered = _memory_store.get_by_intent(intent)
    elif tool_name:
        filtered = _memory_store.get_by_tool(tool_name)
    else:
        filtered = _memory_store.get_last(limit if limit > 0 else 0)

    serialized = [event.to_dict() for event in filtered]
    if limit > 0:
        return serialized[-limit:]
    return serialized


def get_memory_advisory_summary(
    *,
    limit: int = 50,
    intent: str | None = None,
    tool_name: str | None = None,
) -> Dict[str, Any]:
    events = _memory_events_filtered(limit=limit, intent=intent, tool_name=tool_name)
    success_count = sum(1 for event in events if bool(event.get("success")))
    failure_count = len(events) - success_count
    success_rate = round((success_count / len(events)), 2) if events else 0.0

    by_intent: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"intent": "", "count": 0, "success_count": 0, "failure_count": 0}
    )
    by_tool: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"tool_name": "", "count": 0, "success_count": 0, "failure_count": 0}
    )

    for event in events:
        event_intent = str(event.get("intent", "unknown.intent"))
        event_tool = str(event.get("tool_name", "unknown.tool"))
        event_success = bool(event.get("success"))

        intent_bucket = by_intent[event_intent]
        intent_bucket["intent"] = event_intent
        intent_bucket["count"] += 1
        if event_success:
            intent_bucket["success_count"] += 1
        else:
            intent_bucket["failure_count"] += 1

        tool_bucket = by_tool[event_tool]
        tool_bucket["tool_name"] = event_tool
        tool_bucket["count"] += 1
        if event_success:
            tool_bucket["success_count"] += 1
        else:
            tool_bucket["failure_count"] += 1

    if not events:
        suggestions = ["Suggestion: No execution history found yet; collect more approved runs before drawing conclusions."]
    elif failure_count > 0:
        suggestions = [
            "Suggestion: Review failing intents/tools before approving similar actions.",
            "Suggestion: Keep approval gating explicit; advisory insights never replace approval.",
        ]
    else:
        suggestions = [
            "Suggestion: Recent runs are successful; continue using explicit approvals for repeatable safety.",
        ]

    return {
        "type": "memory_advisory_summary",
        "advisory_only": True,
        "filters": {
            "limit": limit,
            "intent": intent,
            "tool_name": tool_name,
        },
        "events_considered": len(events),
        "outcomes": {
            "success_count": success_count,
            "failure_count": failure_count,
            "success_rate": success_rate,
        },
        "by_intent": sorted(by_intent.values(), key=lambda item: str(item["intent"])),
        "by_tool": sorted(by_tool.values(), key=lambda item: str(item["tool_name"])),
        "recent_events": events[-5:],
        "suggestions": suggestions,
        "safety_note": "Advisory only: this summary does not change policy, approval, or execution behavior.",
    }


def get_memory_pattern_insights(*, limit: int = 50) -> Dict[str, Any]:
    events = _memory_events_filtered(limit=limit)
    patterns: List[Dict[str, Any]] = []

    if not events:
        patterns.append(
            {
                "pattern": "No historical execution events.",
                "suggestion": "Suggestion: Run approved actions first to build advisory context.",
            }
        )
    else:
        recent_intents = [str(event.get("intent", "unknown.intent")) for event in events[-3:]]
        if len(recent_intents) == 3 and len(set(recent_intents)) == 1:
            patterns.append(
                {
                    "pattern": f"Last three executions used intent `{recent_intents[0]}`.",
                    "suggestion": "Suggestion: If repeating this action, verify parameters before approving again.",
                }
            )

        failures = [event for event in events if not bool(event.get("success"))]
        if failures:
            latest_failure = failures[-1]
            patterns.append(
                {
                    "pattern": (
                        f"Recent failure observed for intent `{latest_failure.get('intent', 'unknown.intent')}` "
                        f"with tool `{latest_failure.get('tool_name', 'unknown.tool')}`."
                    ),
                    "suggestion": "Suggestion: Inspect failure details and adjust inputs before the next approval.",
                }
            )

        if not patterns:
            patterns.append(
                {
                    "pattern": "No high-risk trend detected in recent history.",
                    "suggestion": "Suggestion: Continue explicit approvals and monitor outcomes over time.",
                }
            )

    return {
        "type": "memory_pattern_insights",
        "advisory_only": True,
        "events_considered": len(events),
        "patterns": patterns,
        "safety_note": "Advisory only: pattern insights cannot trigger or authorize any action.",
    }


def _call_llm_for_memory_advisory_json(summary: Dict[str, Any], patterns: Dict[str, Any]) -> Dict[str, Any] | None:
    model_config = _load_model_config()
    if llm_api is None or not model_config:
        return None

    prompt_payload = {
        "summary": summary,
        "patterns": patterns,
        "instructions": {
            "task": "Provide a concise advisory explanation of historical patterns.",
            "must_not_suggest_automatic_actions": True,
            "output_format": {
                "explanation": "string",
                "suggestions": ["string"],
            },
        },
    }
    messages = [
        {
            "role": "system",
            "content": (
                "Return JSON only with keys: explanation, suggestions. "
                "Suggestions must be advisory and must not imply automatic execution."
            ),
        },
        {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=True)},
    ]
    try:
        raw = llm_api.get_completion(messages, model_config)
    except Exception:
        return None
    if not isinstance(raw, str):
        return None
    try:
        payload = json.loads(raw.strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _normalize_llm_advisory_payload(payload: Any) -> Dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    explanation = payload.get("explanation")
    suggestions = payload.get("suggestions")
    if not isinstance(explanation, str) or not explanation.strip():
        return None
    if not isinstance(suggestions, list):
        return None
    normalized_suggestions: List[str] = []
    for item in suggestions:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text:
            continue
        if not text.lower().startswith("suggestion:"):
            text = f"Suggestion: {text}"
        normalized_suggestions.append(text)
    return {
        "explanation": explanation.strip(),
        "suggestions": normalized_suggestions,
    }


def get_memory_advisory_report(
    *,
    limit: int = 50,
    intent: str | None = None,
    tool_name: str | None = None,
    llm_explainer: Callable[[Dict[str, Any], Dict[str, Any]], Any] | None = None,
) -> Dict[str, Any]:
    summary = get_memory_advisory_summary(limit=limit, intent=intent, tool_name=tool_name)
    patterns = get_memory_pattern_insights(limit=limit)
    llm_payload: Dict[str, Any] | None = None

    if llm_explainer is not None:
        try:
            llm_payload = _normalize_llm_advisory_payload(llm_explainer(summary, patterns))
        except Exception:
            llm_payload = None
    else:
        llm_payload = _normalize_llm_advisory_payload(_call_llm_for_memory_advisory_json(summary, patterns))

    if llm_payload is None:
        llm_payload = {
            "explanation": (
                "Historical execution data is advisory context only; approvals and policy gates remain unchanged."
            ),
            "suggestions": [
                "Suggestion: Use these insights to guide human approvals, not to skip approval steps.",
            ],
        }

    return {
        "type": "memory_advisory_report",
        "advisory_only": True,
        "summary": summary,
        "patterns": patterns,
        "llm_context": llm_payload,
        "safety_note": (
            "Advisory only: this report cannot modify interpreter routing, policy decisions, or execution authority."
        ),
    }


def reset_phase7_memory() -> None:
    _memory_store.clear()


def get_tool_invocations() -> List[Dict[str, Any]]:
    if isinstance(_tool_invoker, StubToolInvoker):
        return _tool_invoker.get_invocations()
    return []


def reset_phase8_state() -> None:
    global _pending_plan
    _pending_plan = None


def _serialize_plan_step(step: PlanStep) -> Dict[str, Any]:
    return {
        "step_id": step.step_id,
        "description": step.description,
        "tool_contract": {
            "tool_name": step.tool_contract.tool_name,
            "intent": step.tool_contract.intent,
            "description": step.tool_contract.description,
            "risk_level": step.tool_contract.risk_level,
            "side_effects": step.tool_contract.side_effects,
        },
        "parameters": copy.deepcopy(step.parameters),
        "risk_level": step.risk_level,
    }


def _serialize_plan(plan: ExecutionPlan) -> Dict[str, Any]:
    return {
        "plan_id": plan.plan_id,
        "intent": plan.intent,
        "steps": [_serialize_plan_step(step) for step in plan.steps],
    }


def get_pending_plan() -> Dict[str, Any] | None:
    if _pending_plan is None:
        return None
    return {
        "plan": _serialize_plan(_pending_plan.plan),
        "created_at": _pending_plan.created_at,
        "expires_at": _pending_plan.expires_at,
        "awaiting_next_user_turn": _pending_plan.awaiting_next_user_turn,
        "next_step_index": _pending_plan.next_step_index,
    }


def _serialize_autonomy_scope(scope: AutonomyScope) -> Dict[str, Any]:
    return {
        "allowed_lanes": list(scope.allowed_lanes),
        "allowed_intents": list(scope.allowed_intents),
    }


def _serialize_autonomy_constraints(constraints: AutonomyConstraints) -> Dict[str, Any]:
    return {
        "mode": constraints.mode,
        "max_risk_level": constraints.max_risk_level,
        "allowed_tools": list(constraints.allowed_tools),
        "blocked_tools": list(constraints.blocked_tools),
        "max_actions": constraints.max_actions,
    }


def _serialize_autonomy_session(session: AutonomySession, *, include_events: bool) -> Dict[str, Any]:
    payload = {
        "session_id": session.session_id,
        "scope": _serialize_autonomy_scope(session.scope),
        "constraints": _serialize_autonomy_constraints(session.constraints),
        "origin": session.origin,
        "enabled_at": session.enabled_at,
        "expires_at": session.expires_at,
        "active": session.active,
        "stop_reason": session.stop_reason,
        "revoked_at": session.revoked_at,
        "ended_at": session.ended_at,
        "actions_executed": session.actions_executed,
        "event_count": len(session.events),
    }
    if include_events:
        payload["events"] = copy.deepcopy(session.events)
    return payload


def _autonomy_event(
    session: AutonomySession,
    *,
    event_type: str,
    metadata: Dict[str, Any] | None = None,
) -> None:
    correlation = current_correlation_id() or f"corr-{uuid.uuid4()}"
    event = {
        "event_id": f"autoevt-{uuid.uuid4()}",
        "timestamp": _utcnow().isoformat(),
        "event_type": str(event_type),
        "correlation_id": correlation,
        "metadata": copy.deepcopy(metadata or {}),
    }
    session.events.append(event)


def _normalize_autonomy_scope(scope: AutonomyScope) -> AutonomyScope:
    allowed_lanes: List[str] = []
    for lane in scope.allowed_lanes:
        normalized_lane = str(lane).strip().upper()
        if not normalized_lane:
            continue
        allowed_lanes.append(normalized_lane)
    allowed_intents: List[str] = []
    for intent in scope.allowed_intents:
        normalized_intent = str(intent).strip()
        if not normalized_intent:
            continue
        allowed_intents.append(normalized_intent)
    return AutonomyScope(
        allowed_lanes=sorted(set(allowed_lanes)),
        allowed_intents=sorted(set(allowed_intents)),
    )


def _normalize_autonomy_constraints(constraints: AutonomyConstraints) -> AutonomyConstraints:
    mode = str(constraints.mode).strip().lower()
    if mode not in _PHASE15_CONSTRAINT_MODES:
        raise ValueError(f"Unsupported autonomy constraint mode: {constraints.mode}")
    max_risk = str(constraints.max_risk_level).strip().lower()
    if max_risk not in _PHASE8_RISK_ORDER:
        raise ValueError(f"Unsupported autonomy max_risk_level: {constraints.max_risk_level}")
    max_actions = int(constraints.max_actions)
    if max_actions <= 0:
        raise ValueError("Autonomy constraints require max_actions > 0.")
    allowed_tools = sorted({str(name).strip() for name in constraints.allowed_tools if str(name).strip()})
    blocked_tools = sorted({str(name).strip() for name in constraints.blocked_tools if str(name).strip()})
    return AutonomyConstraints(
        mode=mode,
        max_risk_level=max_risk,
        allowed_tools=allowed_tools,
        blocked_tools=blocked_tools,
        max_actions=max_actions,
    )


def _autonomy_session_expired(session: AutonomySession) -> bool:
    return _utcnow() > _parse_iso(session.expires_at)


def _close_autonomy_session(
    session: AutonomySession,
    *,
    reason: str,
    event_type: str,
    metadata: Dict[str, Any] | None = None,
) -> None:
    global _active_autonomy_session_id
    if not session.active:
        return
    session.active = False
    session.stop_reason = reason
    session.ended_at = _utcnow().isoformat()
    _autonomy_event(session, event_type=event_type, metadata=metadata)
    _emit_observability_event(
        phase="phase15",
        event_type=event_type,
        metadata={
            "autonomy_session_id": session.session_id,
            "reason": reason,
            "actions_executed": session.actions_executed,
        },
    )
    if _active_autonomy_session_id == session.session_id:
        _active_autonomy_session_id = None


def _get_active_autonomy_session() -> AutonomySession | None:
    session_id = _active_autonomy_session_id
    if session_id is None:
        return None
    session = _autonomy_sessions.get(session_id)
    if session is None:
        return None
    if not session.active:
        return None
    if _autonomy_session_expired(session):
        _close_autonomy_session(
            session,
            reason="expired",
            event_type="autonomy_expired",
            metadata={"autonomy_session_id": session.session_id},
        )
        return None
    return session


def enable_autonomy(
    scope: AutonomyScope,
    duration: timedelta,
    constraints: AutonomyConstraints,
    *,
    origin: str = "human.explicit",
) -> Dict[str, Any]:
    global _active_autonomy_session_id
    if not isinstance(scope, AutonomyScope):
        raise ValueError("scope must be an AutonomyScope instance.")
    if not isinstance(duration, timedelta):
        raise ValueError("duration must be a timedelta.")
    if duration.total_seconds() <= 0:
        raise ValueError("duration must be greater than zero.")
    if not isinstance(constraints, AutonomyConstraints):
        raise ValueError("constraints must be an AutonomyConstraints instance.")

    normalized_scope = _normalize_autonomy_scope(scope)
    normalized_constraints = _normalize_autonomy_constraints(constraints)
    if not normalized_scope.allowed_intents:
        raise ValueError("Autonomy scope must include at least one allowed intent.")
    if not normalized_scope.allowed_lanes:
        raise ValueError("Autonomy scope must include at least one allowed lane.")

    active = _get_active_autonomy_session()
    if active is not None:
        _close_autonomy_session(
            active,
            reason="superseded",
            event_type="autonomy_superseded",
            metadata={"autonomy_session_id": active.session_id},
        )

    now = _utcnow()
    session = AutonomySession(
        session_id=f"autosess-{uuid.uuid4()}",
        scope=normalized_scope,
        constraints=normalized_constraints,
        origin=str(origin).strip() or "human.explicit",
        enabled_at=now.isoformat(),
        expires_at=(now + duration).isoformat(),
        active=True,
        stop_reason=None,
        revoked_at=None,
        ended_at=None,
        actions_executed=0,
        events=[],
    )
    _autonomy_sessions[session.session_id] = session
    _autonomy_session_order.append(session.session_id)
    _active_autonomy_session_id = session.session_id
    _autonomy_event(
        session,
        event_type="autonomy_enabled",
        metadata={
            "scope": _serialize_autonomy_scope(session.scope),
            "constraints": _serialize_autonomy_constraints(session.constraints),
            "origin": session.origin,
        },
    )
    _emit_observability_event(
        phase="phase15",
        event_type="autonomy_enabled",
        metadata={
            "autonomy_session_id": session.session_id,
            "origin": session.origin,
            "scope": _serialize_autonomy_scope(session.scope),
            "constraints": _serialize_autonomy_constraints(session.constraints),
        },
    )
    return _serialize_autonomy_session(session, include_events=False)


def revoke_autonomy() -> Dict[str, Any]:
    session = _get_active_autonomy_session()
    if session is None:
        return {
            "revoked": False,
            "message": "No active autonomy session to revoke.",
        }
    session.revoked_at = _utcnow().isoformat()
    _close_autonomy_session(
        session,
        reason="manual_revoke",
        event_type="autonomy_revoked",
        metadata={"autonomy_session_id": session.session_id},
    )
    return {
        "revoked": True,
        "session_id": session.session_id,
        "actions_executed": session.actions_executed,
    }


def list_autonomy_sessions() -> List[Dict[str, Any]]:
    sessions: List[Dict[str, Any]] = []
    for session_id in _autonomy_session_order:
        session = _autonomy_sessions.get(session_id)
        if session is None:
            continue
        sessions.append(_serialize_autonomy_session(session, include_events=False))
    return sessions


def get_autonomy_session_report(session_id: str) -> Dict[str, Any]:
    key = str(session_id).strip()
    if not key:
        raise ValueError("session_id is required.")
    session = _autonomy_sessions.get(key)
    if session is None:
        raise ValueError(f"Autonomy session not found: {session_id}")
    events = sorted(session.events, key=lambda event: str(event.get("timestamp", "")))
    report = _serialize_autonomy_session(session, include_events=False)
    report["events"] = copy.deepcopy(events)
    return report


def reset_phase15_state() -> None:
    global _active_autonomy_session_id, _autonomy_sessions, _autonomy_session_order
    _active_autonomy_session_id = None
    _autonomy_sessions = {}
    _autonomy_session_order = []


def reset_phase16_state() -> None:
    global _phase16_last_response_by_session, _phase16_last_response_global
    _phase16_last_response_by_session = {}
    _phase16_last_response_global = None
    _capture_store.clear()


def reset_phase20_state() -> None:
    global _phase20_working_set_by_session
    _phase20_working_set_by_session = {}


def reset_phase22_state() -> None:
    global _phase22_projects_by_id, _phase22_project_context_by_session
    _phase22_projects_by_id = {}
    _phase22_project_context_by_session = {}


def reset_phase23_state() -> None:
    global _phase23_goals_by_project_id, _phase23_tasks_by_project_id
    _phase23_goals_by_project_id = {}
    _phase23_tasks_by_project_id = {}


def reset_phase24_state() -> None:
    global _phase24_milestones_by_project_id
    _phase24_milestones_by_project_id = {}


def reset_phase25_state() -> None:
    global _phase25_contracts_by_id, _phase25_last_delegation_by_session, _phase25_last_delegation_global
    _phase25_contracts_by_id = {}
    _phase25_last_delegation_by_session = {}
    _phase25_last_delegation_global = None
    _phase25_capability_registry.cache_clear()


def reset_phase26_state() -> None:
    global _phase26_workflows_by_project_id, _phase26_runs_by_id, _phase26_active_run_by_session, _phase26_last_run_by_session
    _phase26_workflows_by_project_id = {}
    _phase26_runs_by_id = {}
    _phase26_active_run_by_session = {}
    _phase26_last_run_by_session = {}


def reset_phase5_state() -> None:
    global _pending_action, _execution_events
    _pending_action = None
    reset_phase8_state()
    reset_phase15_state()
    reset_phase16_state()
    reset_phase20_state()
    reset_phase22_state()
    reset_phase23_state()
    reset_phase24_state()
    reset_phase25_state()
    reset_phase26_state()
    _execution_events = []
    reset_phase7_memory()
    reset_observability_state()
    if isinstance(_tool_invoker, StubToolInvoker):
        _tool_invoker.reset()


def get_pending_action() -> PendingAction | None:
    if _pending_action is None:
        return None
    return copy.deepcopy(_pending_action)


def get_execution_events() -> List[Dict[str, Any]]:
    return copy.deepcopy(_execution_events)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _is_valid_approval_phrase(text: str) -> bool:
    return _normalize(text).lower() in _PHASE5_APPROVAL_PHRASES


def _pending_is_expired(pending: PendingAction) -> bool:
    return _utcnow() > _parse_iso(pending.expires_at)


def _is_actionable_envelope(envelope: Envelope) -> bool:
    lane = str(envelope.get("lane", ""))
    policy = envelope.get("policy", {}) if isinstance(envelope.get("policy"), dict) else {}
    allowed = bool(policy.get("allowed", False))
    requires_approval = bool(envelope.get("requires_approval", False))
    return lane == "PLAN" and (allowed or requires_approval)


def _is_content_generation_envelope(envelope: Envelope) -> bool:
    return str(envelope.get("lane", "")).upper() == "CONTENT_GENERATION"


def _content_generation_result(envelope: Envelope) -> Dict[str, Any]:
    return {
        "type": "content_generation",
        "executed": False,
        "envelope": copy.deepcopy(envelope),
        "capture_eligible": True,
        "message": "",
    }


def _requires_explicit_approval(envelope: Envelope) -> bool:
    return bool(envelope.get("requires_approval", False))


def _is_auto_executable(envelope: Envelope) -> bool:
    if str(envelope.get("lane", "")).upper() != "PLAN":
        return False
    policy = envelope.get("policy", {}) if isinstance(envelope.get("policy"), dict) else {}
    allowed = bool(policy.get("allowed", False))
    return allowed and not _requires_explicit_approval(envelope)


def _execute_envelope_once(envelope: Envelope) -> Dict[str, Any]:
    global _pending_action
    _pending_action = _create_pending_action(envelope)
    action_id = _pending_action.action_id
    try:
        event = execute_pending_action(action_id)
    finally:
        _pending_action = None
    payload = {
        "type": "executed",
        "executed": True,
        "action_id": action_id,
        "execution_event": event,
        "message": _execution_confirmation_message(event),
    }
    payload.update(_phase25_execution_response_fields(event))
    payload.update(_phase26_execution_response_fields(event))
    return payload


def _split_plan_clauses(utterance: str) -> List[str]:
    normalized = _normalize(utterance)
    if not normalized:
        return []
    parts = re.split(r"\b(?:and then|then|and)\b", normalized, flags=re.IGNORECASE)
    clauses = [_normalize(part.strip(" ,.;")) for part in parts if _normalize(part.strip(" ,.;"))]
    return clauses or [normalized]


def _resolve_plan_step_intent(clause: str) -> str | None:
    lowered = clause.lower()
    if "empty text file" in lowered or ("empty" in lowered and "file" in lowered):
        return "plan.create_empty_file"
    parsed_phase26 = _parse_phase26_intent(clause)
    if parsed_phase26 is not None:
        parsed_intent = str(parsed_phase26.get("intent", "")).strip()
        if parsed_intent in {"run_workflow", "workflow_cancel"}:
            return "plan.user_action_request"
    parsed_phase25 = _parse_phase25_intent(clause)
    if parsed_phase25 is not None:
        parsed_intent = str(parsed_phase25.get("intent", "")).strip()
        if parsed_intent in _PHASE25_DELEGATION_INTENTS:
            return "plan.user_action_request"
    parsed_phase24 = _parse_phase24_intent(clause)
    if parsed_phase24 is not None:
        parsed_intent = str(parsed_phase24.get("intent", "")).strip()
        if parsed_intent in _PHASE24_MILESTONE_INTENTS:
            return parsed_intent
    parsed_phase22 = _parse_phase22_intent(clause)
    if parsed_phase22 is not None:
        parsed_intent = str(parsed_phase22.get("intent", "")).strip()
        if parsed_intent in _PHASE22_PROJECT_INTENTS:
            return parsed_intent
    parsed_filesystem = _parse_filesystem_intent(clause)
    if parsed_filesystem is not None:
        parsed_intent = str(parsed_filesystem.get("intent", "")).strip()
        if parsed_intent:
            return parsed_intent
    if _is_action_like(clause):
        return "plan.user_action_request"
    return None


def _plan_risk_summary(plan: ExecutionPlan) -> str:
    worst = "low"
    for step in plan.steps:
        if _PHASE8_RISK_ORDER.get(step.risk_level, 0) > _PHASE8_RISK_ORDER.get(worst, 0):
            worst = step.risk_level
    return worst


def build_execution_plan(envelope: Envelope) -> ExecutionPlan:
    increment_metric("plan_building_calls")
    started = time.perf_counter()
    if not _is_actionable_envelope(envelope):
        record_latency_ms("plan_building_latency_ms", (time.perf_counter() - started) * 1000.0)
        raise ValueError("Envelope is not actionable for planning.")

    utterance = str(envelope.get("utterance", ""))
    fallback_intent = str(envelope.get("intent", ""))
    clauses = _split_plan_clauses(utterance)
    if not clauses:
        record_latency_ms("plan_building_latency_ms", (time.perf_counter() - started) * 1000.0)
        raise ValueError("No actionable plan steps found in utterance.")

    steps: List[PlanStep] = []
    for index, clause in enumerate(clauses, start=1):
        step_intent = _resolve_plan_step_intent(clause)
        if step_intent is None and len(clauses) == 1 and fallback_intent and _resolve_tool_contract(fallback_intent):
            step_intent = fallback_intent
        if step_intent is None:
            record_latency_ms("plan_building_latency_ms", (time.perf_counter() - started) * 1000.0)
            raise ValueError(f"Unmappable plan step: {clause}")
        contract = _resolve_tool_contract(step_intent)
        if contract is None:
            record_latency_ms("plan_building_latency_ms", (time.perf_counter() - started) * 1000.0)
            raise ValueError(f"No tool contract found for step intent: {step_intent}")

        step_envelope = copy.deepcopy(envelope)
        step_envelope["utterance"] = clause
        step_envelope["intent"] = step_intent
        step_envelope["lane"] = "PLAN"
        step_envelope["requires_approval"] = True

        parameters = _tool_parameters_from_envelope(contract, step_envelope)
        steps.append(
            PlanStep(
                step_id=f"step-{index}",
                description=clause,
                tool_contract=contract,
                parameters=parameters,
                risk_level=contract.risk_level,
                envelope_snapshot=step_envelope,
            )
        )

    plan = ExecutionPlan(
        plan_id=f"plan-{uuid.uuid4()}",
        intent=fallback_intent or "plan.user_action_request",
        steps=steps,
    )
    record_latency_ms("plan_building_latency_ms", (time.perf_counter() - started) * 1000.0)
    _emit_observability_event(
        phase="phase8",
        event_type="plan_constructed",
        metadata={
            "step_count": len(plan.steps),
            "step_ids": [step.step_id for step in plan.steps],
            "step_intents": [step.tool_contract.intent for step in plan.steps],
        },
    )
    return plan


def _create_pending_plan(plan: ExecutionPlan) -> PendingPlan:
    now = _utcnow()
    return PendingPlan(
        plan=plan,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=_PHASE8_PENDING_TTL_SECONDS)).isoformat(),
        awaiting_next_user_turn=True,
        next_step_index=0,
    )


def _pending_plan_is_expired(pending: PendingPlan) -> bool:
    return _utcnow() > _parse_iso(pending.expires_at)


def _plan_approval_message(pending: PendingPlan) -> str:
    plan = pending.plan
    risk_summary = _plan_risk_summary(plan)
    if _phase8_approval_mode == "plan":
        return (
            f"Proposed plan {plan.plan_id}: {len(plan.steps)} steps, risk={risk_summary}. "
            "To approve full-plan execution, reply exactly: approve"
        )
    next_step = plan.steps[pending.next_step_index]
    return (
        f"Proposed plan {plan.plan_id}: {len(plan.steps)} steps, risk={risk_summary}. "
        f"Next step is {next_step.step_id}: {next_step.description}. "
        "To approve this step, reply exactly: approve"
    )


def _create_pending_action(envelope: Envelope) -> PendingAction:
    now = _utcnow()
    action_id = f"act-{uuid.uuid4()}"
    resolved_tool_contract = _resolve_tool_contract(str(envelope.get("intent", "")))
    return PendingAction(
        action_id=action_id,
        envelope_snapshot=copy.deepcopy(envelope),
        resolved_tool_contract=resolved_tool_contract,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=_PHASE5_PENDING_TTL_SECONDS)).isoformat(),
        consumed=False,
        awaiting_next_user_turn=True,
    )


def _approval_request_message(pending: PendingAction) -> str:
    envelope = pending.envelope_snapshot
    intent = envelope.get("intent", "unknown.intent")
    risk_level = envelope.get("policy", {}).get("risk_level", "critical")
    message = (
        f"Pending action {pending.action_id}: intent={intent}, risk={risk_level}. "
        "To approve, reply exactly: approve"
    )
    summary = (
        _entity_string(envelope, "phase21_summary")
        or _entity_string(envelope, "phase23_summary")
        or _entity_string(envelope, "phase24_summary")
        or _entity_string(envelope, "phase26_summary")
        or _entity_string(envelope, "phase25_summary")
    )
    if summary.strip():
        message = f"{summary} {message}"
    return message


def _entity_string(envelope: Envelope, name: str) -> str:
    entities = envelope.get("entities", [])
    if not isinstance(entities, list):
        return ""
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        if str(entity.get("name", "")) != name:
            continue
        normalized = entity.get("normalized")
        value = normalized if isinstance(normalized, str) and normalized.strip() else entity.get("value")
        if isinstance(value, str):
            return value
    return ""


def _captured_text_from_envelope(envelope: Envelope) -> str:
    entities = envelope.get("entities", [])
    if not isinstance(entities, list):
        return ""
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        if str(entity.get("name", "")) != "captured_content":
            continue
        text = entity.get("text")
        if isinstance(text, str) and text.strip():
            return text
    return ""


def _phase20_captured_content_id_from_envelope(envelope: Envelope) -> str:
    entities = envelope.get("entities", [])
    if not isinstance(entities, list):
        return ""
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        if str(entity.get("name", "")) != "captured_content":
            continue
        content_id = str(entity.get("content_id", "")).strip()
        if content_id:
            return content_id
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        if str(entity.get("name", "")) != "working_set_content":
            continue
        content_id = str(entity.get("content_id", "")).strip()
        if content_id:
            return content_id
    return ""


def _phase20_set_working_set_from_execution_event(event: Dict[str, Any]) -> None:
    if not _phase20_enabled:
        return
    if not isinstance(event, dict):
        return
    tool_contract = event.get("tool_contract", {})
    tool_contract = tool_contract if isinstance(tool_contract, dict) else {}
    intent = str(tool_contract.get("intent", "")).strip()
    if intent not in {"create_file", "write_file", "append_file"}:
        return

    envelope = event.get("envelope", {})
    envelope = envelope if isinstance(envelope, dict) else {}
    path = _entity_string(envelope, "path")
    contents = _entity_string(envelope, "contents") or _captured_text_from_envelope(envelope)
    if not path and isinstance(event.get("tool_result"), dict):
        path = str(event.get("tool_result", {}).get("path", "")).strip()
    label = Path(path).name if path else ""
    content_id = _phase20_captured_content_id_from_envelope(envelope) or f"ws-{uuid.uuid4()}"
    _phase20_set_working_set(
        {
            "content_id": content_id,
            "label": label,
            "type": _phase20_working_set_type_from_path(path) if path else _phase20_working_set_type_from_text(contents),
            "source": "filesystem",
            "path": path,
            "text": contents,
            "origin_turn_id": str(current_correlation_id() or ""),
        },
        reason=f"execution_{intent}",
    )


def _phase22_update_projects_from_execution_event(event: Dict[str, Any]) -> None:
    if not _phase22_enabled:
        return
    if not isinstance(event, dict):
        return
    tool_contract = event.get("tool_contract", {})
    tool_contract = tool_contract if isinstance(tool_contract, dict) else {}
    intent = str(tool_contract.get("intent", "")).strip()
    envelope = event.get("envelope", {})
    envelope = envelope if isinstance(envelope, dict) else {}

    if intent == "delete_project":
        project_id = _entity_string(envelope, "project_id")
        if project_id:
            _phase22_projects_by_id.pop(project_id, None)
            _phase23_goals_by_project_id.pop(project_id, None)
            _phase23_tasks_by_project_id.pop(project_id, None)
            _phase24_milestones_by_project_id.pop(project_id, None)
            stale_sessions = [
                session_id
                for session_id, context in _phase22_project_context_by_session.items()
                if isinstance(context, dict) and str(context.get("project_id", "")) == project_id
            ]
            for session_id in stale_sessions:
                _phase22_project_context_by_session.pop(session_id, None)
            _emit_observability_event(
                phase="phase22",
                event_type="project_deleted",
                metadata={"project_id": project_id},
            )
        return

    if intent not in _FILESYSTEM_INTENTS:
        return

    path = _entity_string(envelope, "path")
    if not path and isinstance(event.get("tool_result"), dict):
        path = str(event.get("tool_result", {}).get("path", "")).strip()
    if not path:
        return

    explicit_project_id = _entity_string(envelope, "phase22_project_id")
    project: Dict[str, Any] | None = None
    if explicit_project_id:
        candidate = _phase22_projects_by_id.get(explicit_project_id)
        if isinstance(candidate, dict):
            project = candidate
    if project is None:
        project = _phase22_project_for_path(path)
    if project is None:
        return

    if intent == "delete_file":
        _phase22_remove_artifact(project, path)
    elif intent in {"create_file", "write_file", "append_file"}:
        _phase22_add_or_update_artifact(project, path)
    _phase22_update_project_timestamp(str(project.get("project_id", "")))


def _phase23_update_tasks_from_execution_event(event: Dict[str, Any]) -> None:
    if not _phase23_enabled:
        return
    if not isinstance(event, dict):
        return
    envelope = event.get("envelope", {})
    envelope = envelope if isinstance(envelope, dict) else {}
    if _entity_string(envelope, "phase23_complete_task").lower() != "true":
        return

    project_id = _entity_string(envelope, "phase23_project_id")
    task_id = _entity_string(envelope, "phase23_task_id")
    if not project_id or not task_id:
        return

    project = _phase22_projects_by_id.get(project_id)
    if not isinstance(project, dict):
        return
    task = _phase23_task_by_id(project_id, task_id)
    if not isinstance(task, dict):
        return
    if str(task.get("status", "")) == "COMPLETED":
        return

    handle_complete_task(project, task)
    _emit_observability_event(
        phase="phase23",
        event_type="task_completed",
        metadata={
            "project_id": project_id,
            "task_id": task_id,
            "goal_id": _entity_string(envelope, "phase23_goal_id"),
        },
    )


def _phase24_update_projects_from_execution_event(event: Dict[str, Any]) -> None:
    if not _phase24_enabled:
        return
    if not isinstance(event, dict):
        return
    tool_contract = event.get("tool_contract", {})
    tool_contract = tool_contract if isinstance(tool_contract, dict) else {}
    intent = str(tool_contract.get("intent", "")).strip()
    if intent not in {"finalize_project", "archive_project"}:
        return
    envelope = event.get("envelope", {})
    envelope = envelope if isinstance(envelope, dict) else {}
    project_id = _entity_string(envelope, "project_id")
    if not project_id:
        return
    project = _phase22_projects_by_id.get(project_id)
    if not isinstance(project, dict):
        return
    now = _utcnow().isoformat()

    if intent == "finalize_project":
        project["state"] = "finalized"
        project["finalized_at"] = now
        project["completion_confirmed"] = True
        summary = _entity_string(envelope, "phase24_project_summary") or _phase24_project_summary_text(project)
        captured = CapturedContent(
            content_id=f"cc-{uuid.uuid4()}",
            type="text_note",
            source="phase24_finalize",
            text=summary,
            timestamp=now,
            origin_turn_id=str(current_correlation_id() or ""),
            label=f"{_phase22_slug(str(project.get('name', 'project')))}_final_summary",
            session_id=str(current_session_id() or ""),
        )
        _capture_store.append(captured)
        metadata = project.get("metadata", {})
        metadata = metadata if isinstance(metadata, dict) else {}
        metadata["final_summary_content_id"] = captured.content_id
        project["metadata"] = metadata
        project["updated_at"] = now
        event_result = event.get("tool_result", {})
        if isinstance(event_result, dict):
            event_result["project_state"] = "finalized"
            event_result["final_summary_content_id"] = captured.content_id
        _emit_observability_event(
            phase="phase24",
            event_type="project_finalized",
            metadata={"project_id": project_id, "summary_content_id": captured.content_id},
        )
        return

    archive_root = _entity_string(envelope, "archive_root_path") or _phase24_archive_root(project)
    root_path = str(project.get("root_path", ""))
    root = Path(root_path).resolve(strict=False)
    archive_dir = Path(archive_root).resolve(strict=False)
    moved: List[str] = []
    artifacts = project.get("artifacts", [])
    artifacts = artifacts if isinstance(artifacts, list) else []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        rel = str(artifact.get("path", "")).strip()
        if not rel:
            continue
        source = (root / rel).resolve(strict=False)
        if not source.exists() or not source.is_file():
            continue
        destination = (archive_dir / rel).resolve(strict=False)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(source), str(destination))
        except Exception:
            continue
        moved.append(rel)
    project["state"] = "archived"
    project["archived_at"] = now
    project["archive_path"] = str(archive_dir)
    project["completion_confirmed"] = True
    project["artifacts"] = _phase22_scan_artifacts(root_path)
    metadata = project.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    metadata["archived_artifacts"] = list(moved)
    project["metadata"] = metadata
    project["updated_at"] = now
    event_result = event.get("tool_result", {})
    if isinstance(event_result, dict):
        event_result["project_state"] = "archived"
        event_result["archive_path"] = str(archive_dir)
        event_result["moved_files"] = list(moved)
        event_result["moved_count"] = len(moved)
    _emit_observability_event(
        phase="phase24",
        event_type="project_archived",
        metadata={"project_id": project_id, "archive_path": str(archive_dir), "moved_count": len(moved)},
    )


def _phase25_update_from_execution_event(event: Dict[str, Any]) -> None:
    global _phase25_last_delegation_global
    if not _phase25_enabled:
        return
    if not isinstance(event, dict):
        return

    envelope = event.get("envelope", {})
    envelope = envelope if isinstance(envelope, dict) else {}
    if _entity_string(envelope, "phase25_delegation").lower() != "true":
        return

    delegation_id = _entity_string(envelope, "phase25_delegation_id")
    contract = _phase25_parse_contract_json(_entity_string(envelope, "phase25_contract_json"))
    if contract is None and delegation_id:
        cached = _phase25_contracts_by_id.get(delegation_id)
        if isinstance(cached, dict):
            contract = copy.deepcopy(cached)
    if contract is None:
        contract = {
            "delegation_id": delegation_id or f"dlg-{uuid.uuid4()}",
            "agent_type": _entity_string(envelope, "phase25_agent_type") or "UNKNOWN",
            "task_description": _entity_string(envelope, "phase25_task") or str(envelope.get("utterance", "")),
            "requested_tool": _entity_string(envelope, "phase25_requested_tool") or "content_generation",
            "allowed_tools": [],
            "project_id": _entity_string(envelope, "phase22_project_id"),
            "project_name": "",
            "created_at": _utcnow().isoformat(),
        }

    contract.setdefault("delegation_id", delegation_id or f"dlg-{uuid.uuid4()}")
    contract.setdefault("agent_type", "UNKNOWN")
    contract.setdefault("task_description", str(envelope.get("utterance", "")))
    contract.setdefault("requested_tool", "content_generation")
    contract.setdefault("project_id", _entity_string(envelope, "phase22_project_id"))
    contract.setdefault("project_name", "")
    contract.setdefault("created_at", _utcnow().isoformat())

    delegation_output = _invoke_delegated_agent(contract)
    result_text = str(delegation_output.get("result_text", "")).strip()
    if not result_text:
        result_text = str(contract.get("task_description", "")).strip() or "Delegated output."
    result_summary = _normalize(str(delegation_output.get("result_summary", ""))) or (
        f"Delegated result prepared for {contract.get('agent_type', 'UNKNOWN')}."
    )

    now_iso = _utcnow().isoformat()
    delegation_id_text = str(contract.get("delegation_id", "")).strip() or f"dlg-{uuid.uuid4()}"
    delegation_token = delegation_id_text.split("-")[-1][:8] or "result"
    base_label = _phase22_slug(
        f"{contract.get('agent_type', 'agent')}_{str(contract.get('task_description', '')).strip()[:48]}"
    )
    captured_label = f"{base_label}_{delegation_token}"
    captured = CapturedContent(
        content_id=f"cc-{uuid.uuid4()}",
        type=_phase20_working_set_type_from_text(result_text),
        source="phase25_delegation",
        text=result_text,
        timestamp=now_iso,
        origin_turn_id=str(current_correlation_id() or ""),
        label=captured_label,
        session_id=str(current_session_id() or ""),
    )
    _capture_store.append(captured)

    _phase20_set_working_set(
        {
            "content_id": captured.content_id,
            "label": captured.label,
            "type": _phase20_working_set_type_from_text(captured.text),
            "source": "phase25_delegation",
            "path": "",
            "text": captured.text,
            "origin_turn_id": captured.origin_turn_id,
        },
        reason="phase25_delegation",
    )

    record = {
        "delegation_id": delegation_id_text,
        "agent_type": str(contract.get("agent_type", "")).upper(),
        "task_description": str(contract.get("task_description", "")),
        "requested_tool": str(contract.get("requested_tool", "")),
        "project_id": str(contract.get("project_id", "")),
        "project_name": str(contract.get("project_name", "")),
        "result_text": result_text,
        "result_summary": result_summary,
        "captured_content_id": captured.content_id,
        "captured_label": captured.label,
        "timestamp": now_iso,
    }
    session_key = _phase25_session_key()
    if session_key:
        _phase25_last_delegation_by_session[session_key] = copy.deepcopy(record)
    _phase25_last_delegation_global = copy.deepcopy(record)

    tool_result = event.get("tool_result", {})
    if isinstance(tool_result, dict):
        tool_result["delegation_id"] = delegation_id_text
        tool_result["delegation_result_summary"] = result_summary
        tool_result["captured_content_id"] = captured.content_id
        tool_result["captured_label"] = captured.label
    event["delegation"] = copy.deepcopy(record)

    project_id = str(contract.get("project_id", "")).strip()
    if project_id:
        _phase22_update_project_timestamp(project_id)

    _emit_observability_event(
        phase="phase25",
        event_type="delegation_executed",
        metadata={
            "delegation_id": delegation_id_text,
            "agent_type": record["agent_type"],
            "project_id": record["project_id"],
            "captured_content_id": captured.content_id,
        },
    )


def _phase26_update_from_execution_event(event: Dict[str, Any]) -> None:
    if not _phase26_enabled:
        return
    if not isinstance(event, dict):
        return
    envelope = event.get("envelope", {})
    envelope = envelope if isinstance(envelope, dict) else {}
    run_id = _entity_string(envelope, "phase26_run_id")
    if not run_id:
        return
    run = _phase26_find_run(run_id)
    if not isinstance(run, dict):
        return
    now = _utcnow().isoformat()
    session_id = str(run.get("session_id", "")).strip() or _phase26_session_key()

    if _entity_string(envelope, "phase26_run_start").lower() == "true":
        run["status"] = "RUNNING"
        run["started_at"] = run.get("started_at") or now
        run["updated_at"] = now
        run["current_step_index"] = 0
        run["completed_steps"] = []
        steps = run.get("steps_ordered", [])
        steps = steps if isinstance(steps, list) else []
        run["pending_steps"] = [
            _normalize(str(item.get("step_id", "")))
            for item in steps
            if isinstance(item, dict) and _normalize(str(item.get("step_id", "")))
        ]
        run["current_step_id"] = run["pending_steps"][0] if run["pending_steps"] else ""
        _phase26_active_run_by_session[session_id] = run_id
        _phase26_last_run_by_session[session_id] = run_id
        event_result = event.get("tool_result", {})
        if isinstance(event_result, dict):
            event_result["workflow_status"] = "RUNNING"
            event_result["workflow_run_id"] = run_id
        _emit_observability_event(
            phase="phase26",
            event_type="workflow_run_started",
            metadata={
                "run_id": run_id,
                "workflow_id": str(run.get("workflow_id", "")),
                "project_id": str(run.get("project_id", "")),
            },
        )
        return

    if _entity_string(envelope, "phase26_cancel").lower() == "true":
        run["status"] = "CANCELED"
        run["updated_at"] = now
        run["finished_at"] = now
        _phase26_active_run_by_session.pop(session_id, None)
        _phase26_last_run_by_session[session_id] = run_id
        event_result = event.get("tool_result", {})
        if isinstance(event_result, dict):
            event_result["workflow_status"] = "CANCELED"
            event_result["workflow_run_id"] = run_id
        _emit_observability_event(
            phase="phase26",
            event_type="workflow_run_canceled",
            metadata={
                "run_id": run_id,
                "workflow_id": str(run.get("workflow_id", "")),
                "project_id": str(run.get("project_id", "")),
            },
        )
        return

    if str(run.get("status", "")).strip().upper() not in {"RUNNING", "PENDING_APPROVAL"}:
        return
    step_id = _entity_string(envelope, "phase26_step_id")
    if not step_id:
        return
    completed = run.get("completed_steps", [])
    completed = completed if isinstance(completed, list) else []
    if step_id not in completed:
        completed.append(step_id)
    run["completed_steps"] = completed
    run["updated_at"] = now
    execution_ids = run.get("execution_event_ids", [])
    execution_ids = execution_ids if isinstance(execution_ids, list) else []
    event_id = str(event.get("event_id", "")).strip()
    if event_id:
        execution_ids.append(event_id)
    run["execution_event_ids"] = execution_ids

    steps = run.get("steps_ordered", [])
    steps = steps if isinstance(steps, list) else []
    step_order = [_normalize(str(item.get("step_id", ""))) for item in steps if isinstance(item, dict)]
    next_index = max(0, int(run.get("current_step_index", 0) or 0))
    if step_id in step_order:
        next_index = step_order.index(step_id) + 1
    run["current_step_index"] = next_index
    pending = [item for item in step_order[next_index:] if item]
    run["pending_steps"] = pending
    run["current_step_id"] = pending[0] if pending else ""
    if not pending:
        run["status"] = "COMPLETED"
        run["finished_at"] = now
        _phase26_active_run_by_session.pop(session_id, None)
        _phase26_last_run_by_session[session_id] = run_id
    else:
        run["status"] = "RUNNING"
        _phase26_active_run_by_session[session_id] = run_id

    event_result = event.get("tool_result", {})
    if isinstance(event_result, dict):
        event_result["workflow_status"] = str(run.get("status", ""))
        event_result["workflow_run_id"] = run_id
        event_result["workflow_step_id"] = step_id
    _emit_observability_event(
        phase="phase26",
        event_type="workflow_step_executed",
        metadata={
            "run_id": run_id,
            "workflow_id": str(run.get("workflow_id", "")),
            "project_id": str(run.get("project_id", "")),
            "step_id": step_id,
            "status": str(run.get("status", "")),
        },
    )


def _phase19_persist_note_confirmation(event: Dict[str, Any]) -> str | None:
    envelope = event.get("envelope", {})
    if not isinstance(envelope, dict):
        return None
    entities = envelope.get("entities", [])
    if not isinstance(entities, list):
        return None
    if not any(isinstance(entity, dict) and str(entity.get("name", "")) == "persist_note" for entity in entities):
        return None

    tool_result = event.get("tool_result", {})
    if isinstance(tool_result, dict):
        resolved_path = str(tool_result.get("path", "")).strip()
        if resolved_path:
            return f"Note persisted to {resolved_path}."
    resolved_path = _entity_string(envelope, "path")
    if resolved_path:
        return f"Note persisted to {resolved_path}."
    return "Note persisted."


def _phase25_delegation_confirmation(event: Dict[str, Any]) -> str | None:
    if not isinstance(event, dict):
        return None
    tool_result = event.get("tool_result", {})
    if not isinstance(tool_result, dict):
        return None
    delegation_id = str(tool_result.get("delegation_id", "")).strip()
    summary = _normalize(str(tool_result.get("delegation_result_summary", "")))
    if not delegation_id and not summary:
        return None
    if delegation_id and summary:
        return f"Delegation {delegation_id} completed. {summary}"
    if delegation_id:
        return f"Delegation {delegation_id} completed."
    return summary


def _phase26_workflow_confirmation(event: Dict[str, Any]) -> str | None:
    if not isinstance(event, dict):
        return None
    tool_result = event.get("tool_result", {})
    if not isinstance(tool_result, dict):
        return None
    status = _normalize(str(tool_result.get("workflow_status", ""))).upper()
    run_id = _normalize(str(tool_result.get("workflow_run_id", "")))
    step_id = _normalize(str(tool_result.get("workflow_step_id", "")))
    if not status and not run_id:
        return None
    if status == "RUNNING":
        return f"Workflow {run_id} started. Reply exactly: approve to run the next step."
    if status == "CANCELED":
        return f"Workflow {run_id} canceled."
    if status == "COMPLETED":
        return f"Workflow {run_id} completed."
    if step_id:
        return f"Workflow {run_id} executed step {step_id}."
    return f"Workflow {run_id} status: {status or 'UPDATED'}."


def _phase25_execution_response_fields(event: Dict[str, Any]) -> Dict[str, Any]:
    tool_result = event.get("tool_result", {})
    if not isinstance(tool_result, dict):
        return {}
    payload: Dict[str, Any] = {}
    for source_key, target_key in (
        ("delegation_id", "delegation_id"),
        ("captured_label", "captured_label"),
        ("captured_content_id", "captured_content_id"),
    ):
        value = tool_result.get(source_key)
        if isinstance(value, str) and value.strip():
            payload[target_key] = value
    return payload


def _phase26_execution_response_fields(event: Dict[str, Any]) -> Dict[str, Any]:
    tool_result = event.get("tool_result", {})
    if not isinstance(tool_result, dict):
        return {}
    payload: Dict[str, Any] = {}
    for source_key, target_key in (
        ("workflow_run_id", "workflow_run_id"),
        ("workflow_status", "workflow_status"),
        ("workflow_step_id", "workflow_step_id"),
    ):
        value = tool_result.get(source_key)
        if isinstance(value, str) and value.strip():
            payload[target_key] = value
    return payload


def _execution_confirmation_message(event: Dict[str, Any]) -> str:
    return (
        _phase19_persist_note_confirmation(event)
        or _phase26_workflow_confirmation(event)
        or _phase25_delegation_confirmation(event)
        or "Execution accepted and completed once."
    )


def _tool_parameters_from_envelope(contract: ToolContract, envelope: Envelope) -> Dict[str, Any]:
    if contract.intent == "plan.create_empty_file":
        target_dir = "$HOME"
        for entity in envelope.get("entities", []):
            if not isinstance(entity, dict):
                continue
            if entity.get("name") != "target_location":
                continue
            normalized = entity.get("normalized")
            value = normalized if isinstance(normalized, str) else entity.get("value")
            if isinstance(value, str) and value.strip():
                target_dir = value.strip()
                break
        return {"path": f"{target_dir.rstrip('/')}/untitled.txt"}

    if contract.intent in _FILESYSTEM_INTENTS:
        path = _entity_string(envelope, "path")
        contents = _entity_string(envelope, "contents") or _captured_text_from_envelope(envelope)
        if contract.intent == "create_file":
            payload: Dict[str, Any] = {"path": path}
            if contents:
                payload["contents"] = contents
            return payload
        if contract.intent == "write_file":
            return {"path": path, "contents": contents}
        if contract.intent == "append_file":
            return {"path": path, "contents": contents}
        if contract.intent == "read_file":
            return {"path": path}
        if contract.intent == "delete_file":
            return {"path": path}

    return {
        "utterance": str(envelope.get("utterance", "")),
        "entities": copy.deepcopy(envelope.get("entities", [])),
    }


def _record_memory_event(
    *,
    envelope: Envelope | None,
    contract: ToolContract | None,
    parameters: Dict[str, Any],
    execution_result: Dict[str, Any],
    success: bool,
) -> None:
    intent = str((envelope or {}).get("intent", "unknown.intent"))
    tool_name = contract.tool_name if contract is not None else "unresolved.tool"
    event = MemoryEvent(
        timestamp=_utcnow().isoformat(),
        intent=intent,
        tool_name=tool_name,
        parameters=copy.deepcopy(parameters),
        execution_result=copy.deepcopy(execution_result),
        success=bool(success),
    )
    try:
        _memory_store.append(event)
        _emit_observability_event(
            phase="phase7",
            event_type="memory_recorded",
            metadata={
                "intent": intent,
                "tool_name": tool_name,
                "success": bool(success),
            },
        )
    except Exception:
        _emit_observability_event(
            phase="phase7",
            event_type="memory_record_failed",
            metadata={
                "intent": intent,
                "tool_name": tool_name,
                "success": bool(success),
            },
        )
        # Memory recording must never change execution behavior.
        return


def execute_pending_action(action_id: str) -> Dict[str, Any]:
    global _pending_action, _execution_events
    increment_metric("execution_attempts")
    started = time.perf_counter()
    snapshot = copy.deepcopy(_pending_action.envelope_snapshot) if _pending_action else None
    contract = _pending_action.resolved_tool_contract if _pending_action else None
    parameters: Dict[str, Any] = {}
    if snapshot is not None and contract is not None:
        parameters = _tool_parameters_from_envelope(contract, snapshot)

    try:
        if _pending_action is None:
            raise ValueError("No pending action available.")
        if _pending_action.action_id != action_id:
            raise ValueError("Pending action id mismatch.")
        if _pending_action.consumed:
            raise ValueError("Pending action already consumed.")
        if _pending_is_expired(_pending_action):
            raise ValueError("Pending action expired.")
        contract = _pending_action.resolved_tool_contract
        if contract is None:
            raise ValueError("No tool contract resolved for pending action.")

        parameters = _tool_parameters_from_envelope(contract, _pending_action.envelope_snapshot)
        _emit_observability_event(
            phase="phase6",
            event_type="tool_invocation_attempt",
            metadata={
                "intent": contract.intent,
                "tool_name": contract.tool_name,
                "parameter_keys": sorted(parameters.keys()),
            },
        )
        result = _tool_invoker.invoke(contract, parameters)

        event = {
            "event_id": f"exec-{uuid.uuid4()}",
            "action_id": _pending_action.action_id,
            "executed_at": _utcnow().isoformat(),
            "status": "executed_stub",
            "envelope": copy.deepcopy(_pending_action.envelope_snapshot),
            "tool_contract": {
                "tool_name": contract.tool_name,
                "intent": contract.intent,
                "description": contract.description,
                "risk_level": contract.risk_level,
                "side_effects": contract.side_effects,
            },
            "tool_result": copy.deepcopy(result),
        }
        _pending_action.consumed = True
        _execution_events.append(event)
        _phase20_set_working_set_from_execution_event(event)
        _phase22_update_projects_from_execution_event(event)
        _phase23_update_tasks_from_execution_event(event)
        _phase24_update_projects_from_execution_event(event)
        _phase25_update_from_execution_event(event)
        _phase26_update_from_execution_event(event)
        _record_memory_event(
            envelope=_pending_action.envelope_snapshot,
            contract=contract,
            parameters=parameters,
            execution_result=result,
            success=True,
        )
        _emit_observability_event(
            phase="phase6",
            event_type="tool_invocation_result",
            metadata={
                "intent": contract.intent,
                "tool_name": contract.tool_name,
                "status": str(result.get("status", "unknown")),
                "success": True,
            },
        )
        record_latency_ms("execution_attempt_latency_ms", (time.perf_counter() - started) * 1000.0)
        return copy.deepcopy(event)
    except Exception as exc:
        _record_memory_event(
            envelope=snapshot,
            contract=contract,
            parameters=parameters,
            execution_result={"error": str(exc)},
            success=False,
        )
        _emit_observability_event(
            phase="phase6",
            event_type="tool_invocation_result",
            metadata={
                "intent": contract.intent if contract is not None else "unknown.intent",
                "tool_name": contract.tool_name if contract is not None else "unknown.tool",
                "success": False,
                "error": str(exc),
            },
        )
        record_latency_ms("execution_attempt_latency_ms", (time.perf_counter() - started) * 1000.0)
        raise


def _execute_plan_step(step: PlanStep, *, plan_id: str, step_index: int) -> Dict[str, Any]:
    global _pending_action
    if _pending_action is not None:
        raise ValueError("Cannot execute plan step while another pending action exists.")

    pending = _create_pending_action(step.envelope_snapshot)
    pending.resolved_tool_contract = step.tool_contract
    _pending_action = pending
    try:
        event = execute_pending_action(pending.action_id)
    finally:
        _pending_action = None

    plan_metadata = {
        "plan_id": plan_id,
        "step_id": step.step_id,
        "step_index": step_index,
    }
    event["plan_step"] = copy.deepcopy(plan_metadata)
    if _execution_events:
        _execution_events[-1]["plan_step"] = copy.deepcopy(plan_metadata)
    return event


def _execute_plan_steps_from_pending() -> Dict[str, Any]:
    global _pending_plan
    if _pending_plan is None:
        raise ValueError("No pending plan available.")

    events: List[Dict[str, Any]] = []
    while _pending_plan.next_step_index < len(_pending_plan.plan.steps):
        index = _pending_plan.next_step_index
        step = _pending_plan.plan.steps[index]
        event = _execute_plan_step(step, plan_id=_pending_plan.plan.plan_id, step_index=index)
        events.append(event)
        _pending_plan.next_step_index += 1
        if _phase8_approval_mode == "step":
            break
    return {
        "plan_id": _pending_plan.plan.plan_id,
        "events": events,
    }


def _scope_allows_envelope(scope: AutonomyScope, envelope: Envelope) -> tuple[bool, str]:
    lane = str(envelope.get("lane", "")).upper()
    intent = str(envelope.get("intent", ""))
    if scope.allowed_lanes and lane not in set(scope.allowed_lanes):
        return False, f"scope_violation: lane {lane} is not permitted"
    if not scope.allowed_intents:
        return False, "scope_violation: no allowed intents configured"
    if "*" in scope.allowed_intents:
        return True, ""
    for allowed_intent in scope.allowed_intents:
        if allowed_intent == intent:
            return True, ""
        if allowed_intent.endswith(".*") and intent.startswith(allowed_intent[:-1]):
            return True, ""
    return False, f"scope_violation: intent {intent} is not permitted"


def _constraints_allow_step(
    session: AutonomySession,
    step: PlanStep,
) -> tuple[bool, str]:
    constraints = session.constraints
    tool_name = step.tool_contract.tool_name

    if constraints.allowed_tools and tool_name not in set(constraints.allowed_tools):
        return False, f"constraint_violation: tool {tool_name} is not in allowed_tools"
    if constraints.blocked_tools and tool_name in set(constraints.blocked_tools):
        return False, f"constraint_violation: tool {tool_name} is blocked"

    if constraints.mode == "read_only" and bool(step.tool_contract.side_effects):
        return False, f"constraint_violation: mode read_only forbids side-effect tool {tool_name}"

    max_risk = _PHASE8_RISK_ORDER.get(constraints.max_risk_level, 0)
    step_risk = _PHASE8_RISK_ORDER.get(step.risk_level, 0)
    if step_risk > max_risk:
        return (
            False,
            f"constraint_violation: risk {step.risk_level} exceeds max_risk_level {constraints.max_risk_level}",
        )

    if session.actions_executed >= constraints.max_actions:
        return (
            False,
            f"constraint_violation: max_actions exhausted ({constraints.max_actions})",
        )
    return True, ""


def _autonomy_terminated_response(
    *,
    session: AutonomySession,
    message: str,
    envelope: Envelope | None = None,
    events: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    payload = {
        "type": "autonomy_terminated",
        "executed": bool(events),
        "session_id": session.session_id,
        "actions_executed": session.actions_executed,
        "message": message,
    }
    if envelope is not None:
        payload["envelope"] = envelope
    if events is not None:
        payload["execution_events"] = copy.deepcopy(events)
    return payload


def _process_user_message_phase15(utterance: str) -> Dict[str, Any] | None:
    session = _get_active_autonomy_session()
    if session is None:
        return None
    if _pending_action is not None or _pending_plan is not None:
        return None

    normalized = _normalize(utterance)
    routed_utterance = _phase9_normalize_utterance(normalized)
    if _is_valid_approval_phrase(normalized):
        return None
    if _is_deprecated_engineer_mode_input(normalized) and routed_utterance == normalized:
        return None

    envelope = interpret_utterance(routed_utterance)
    increment_metric("policy_decisions")
    _emit_observability_event(
        phase="phase1-4",
        event_type="utterance_interpreted",
        metadata=_envelope_pointer(envelope),
    )
    _emit_observability_event(
        phase="phase4",
        event_type="policy_evaluated",
        metadata=_envelope_pointer(envelope),
    )
    phase16_result, envelope = _phase16_apply_to_envelope(
        envelope=envelope,
        normalized_utterance=routed_utterance,
    )
    if phase16_result is not None:
        return phase16_result
    phase19_result, envelope = _phase19_apply_to_envelope(
        envelope=envelope,
        normalized_utterance=routed_utterance,
    )
    if phase19_result is not None:
        return phase19_result
    phase20_result, envelope = _phase20_apply_to_envelope(
        envelope=envelope,
        normalized_utterance=routed_utterance,
    )
    if phase20_result is not None:
        return phase20_result
    phase21_result, envelope = _phase21_apply_to_envelope(
        envelope=envelope,
        normalized_utterance=routed_utterance,
    )
    if phase21_result is not None:
        return phase21_result
    phase22_result, envelope = _phase22_apply_to_envelope(
        envelope=envelope,
        normalized_utterance=routed_utterance,
    )
    if phase22_result is not None:
        return phase22_result
    phase23_result, envelope = _phase23_apply_to_envelope(
        envelope=envelope,
        normalized_utterance=routed_utterance,
    )
    if phase23_result is not None:
        return phase23_result
    phase24_result, envelope = _phase24_apply_to_envelope(
        envelope=envelope,
        normalized_utterance=routed_utterance,
    )
    if phase24_result is not None:
        return phase24_result
    phase26_result, envelope = _phase26_apply_to_envelope(
        envelope=envelope,
        normalized_utterance=routed_utterance,
    )
    if phase26_result is not None:
        return phase26_result
    phase25_result, envelope = _phase25_apply_to_envelope(
        envelope=envelope,
        normalized_utterance=routed_utterance,
    )
    if phase25_result is not None:
        return phase25_result
    phase24_guard_result, envelope = _phase24_apply_write_guard(
        envelope=envelope,
        normalized_utterance=routed_utterance,
    )
    if phase24_guard_result is not None:
        return phase24_guard_result
    phase17_result, envelope = _phase17_validate_filesystem_envelope(envelope)
    if phase17_result is not None:
        return phase17_result

    if not _is_actionable_envelope(envelope):
        return {
            "type": "no_action",
            "executed": False,
            "envelope": envelope,
            "message": "",
        }

    allowed_scope, scope_reason = _scope_allows_envelope(session.scope, envelope)
    if not allowed_scope:
        _close_autonomy_session(
            session,
            reason="scope_violation",
            event_type="autonomy_scope_violation",
            metadata={
                "autonomy_session_id": session.session_id,
                "intent": str(envelope.get("intent", "")),
                "lane": str(envelope.get("lane", "")),
                "reason": scope_reason,
            },
        )
        return _autonomy_terminated_response(
            session=session,
            envelope=envelope,
            message=f"Autonomy terminated: {scope_reason}.",
            events=[],
        )

    try:
        plan = build_execution_plan(envelope)
    except Exception as exc:
        _autonomy_event(
            session,
            event_type="autonomy_plan_rejected",
            metadata={
                "autonomy_session_id": session.session_id,
                "error": str(exc),
            },
        )
        _emit_observability_event(
            phase="phase15",
            event_type="autonomy_plan_rejected",
            metadata={
                "autonomy_session_id": session.session_id,
                "error": str(exc),
            },
        )
        return {
            "type": "plan_rejected",
            "executed": False,
            "envelope": envelope,
            "message": f"Plan rejected: {exc}",
        }

    events: List[Dict[str, Any]] = []
    _autonomy_event(
        session,
        event_type="autonomy_plan_started",
        metadata={
            "autonomy_session_id": session.session_id,
            "plan_id": plan.plan_id,
            "step_count": len(plan.steps),
            "intent": str(envelope.get("intent", "")),
        },
    )
    _emit_observability_event(
        phase="phase15",
        event_type="autonomy_plan_started",
        metadata={
            "autonomy_session_id": session.session_id,
            "plan_id": plan.plan_id,
            "step_count": len(plan.steps),
        },
    )

    for step_index, step in enumerate(plan.steps):
        if session is not _get_active_autonomy_session():
            return _autonomy_terminated_response(
                session=session,
                envelope=envelope,
                message="Autonomy terminated: session is no longer active.",
                events=events,
            )

        allowed_step, violation_reason = _constraints_allow_step(session, step)
        if not allowed_step:
            _close_autonomy_session(
                session,
                reason="constraint_violation",
                event_type="autonomy_constraint_violation",
                metadata={
                    "autonomy_session_id": session.session_id,
                    "plan_id": plan.plan_id,
                    "step_id": step.step_id,
                    "tool_name": step.tool_contract.tool_name,
                    "reason": violation_reason,
                },
            )
            return _autonomy_terminated_response(
                session=session,
                envelope=envelope,
                message=f"Autonomy terminated: {violation_reason}.",
                events=events,
            )

        _autonomy_event(
            session,
            event_type="autonomy_step_executing",
            metadata={
                "autonomy_session_id": session.session_id,
                "plan_id": plan.plan_id,
                "step_id": step.step_id,
                "tool_name": step.tool_contract.tool_name,
            },
        )
        _emit_observability_event(
            phase="phase15",
            event_type="autonomy_step_executing",
            metadata={
                "autonomy_session_id": session.session_id,
                "plan_id": plan.plan_id,
                "step_id": step.step_id,
                "tool_name": step.tool_contract.tool_name,
            },
        )
        event = _execute_plan_step(step, plan_id=plan.plan_id, step_index=step_index)
        session.actions_executed += 1
        events.append(event)
        _autonomy_event(
            session,
            event_type="autonomy_step_executed",
            metadata={
                "autonomy_session_id": session.session_id,
                "plan_id": plan.plan_id,
                "step_id": step.step_id,
                "tool_name": step.tool_contract.tool_name,
            },
        )
        _emit_observability_event(
            phase="phase15",
            event_type="autonomy_step_executed",
            metadata={
                "autonomy_session_id": session.session_id,
                "plan_id": plan.plan_id,
                "step_id": step.step_id,
                "tool_name": step.tool_contract.tool_name,
            },
        )

    _autonomy_event(
        session,
        event_type="autonomy_plan_completed",
        metadata={
            "autonomy_session_id": session.session_id,
            "plan_id": plan.plan_id,
            "executed_steps": len(events),
        },
    )
    _emit_observability_event(
        phase="phase15",
        event_type="autonomy_plan_completed",
        metadata={
            "autonomy_session_id": session.session_id,
            "plan_id": plan.plan_id,
            "executed_steps": len(events),
        },
    )
    return {
        "type": "autonomy_executed",
        "executed": bool(events),
        "session_id": session.session_id,
        "plan": _serialize_plan(plan),
        "execution_events": events,
        "message": "Autonomy execution completed within active scope and constraints.",
    }


def _process_user_message_phase8(utterance: str) -> Dict[str, Any]:
    global _pending_plan
    normalized = _normalize(utterance)

    if not _phase5_enabled:
        return {
            "type": "phase5_disabled",
            "executed": False,
            "envelope": interpret_utterance(utterance),
            "message": "",
        }

    if _pending_plan is None:
        routed_utterance = _phase9_normalize_utterance(normalized)
        if _is_deprecated_engineer_mode_input(normalized) and routed_utterance == normalized:
            return _phase9_engineer_mode_info_response(normalized)

        if _is_valid_approval_phrase(normalized):
            return {
                "type": "approval_rejected",
                "executed": False,
                "message": "Approval rejected: no pending plan to approve.",
            }

        envelope = interpret_utterance(routed_utterance)
        increment_metric("policy_decisions")
        _emit_observability_event(
            phase="phase1-4",
            event_type="utterance_interpreted",
            metadata=_envelope_pointer(envelope),
        )
        _emit_observability_event(
            phase="phase4",
            event_type="policy_evaluated",
            metadata=_envelope_pointer(envelope),
        )
        phase16_result, envelope = _phase16_apply_to_envelope(
            envelope=envelope,
            normalized_utterance=routed_utterance,
        )
        if phase16_result is not None:
            return phase16_result
        phase19_result, envelope = _phase19_apply_to_envelope(
            envelope=envelope,
            normalized_utterance=routed_utterance,
        )
        if phase19_result is not None:
            return phase19_result
        phase20_result, envelope = _phase20_apply_to_envelope(
            envelope=envelope,
            normalized_utterance=routed_utterance,
        )
        if phase20_result is not None:
            return phase20_result
        phase21_result, envelope = _phase21_apply_to_envelope(
            envelope=envelope,
            normalized_utterance=routed_utterance,
        )
        if phase21_result is not None:
            return phase21_result
        phase22_result, envelope = _phase22_apply_to_envelope(
            envelope=envelope,
            normalized_utterance=routed_utterance,
        )
        if phase22_result is not None:
            return phase22_result
        phase23_result, envelope = _phase23_apply_to_envelope(
            envelope=envelope,
            normalized_utterance=routed_utterance,
        )
        if phase23_result is not None:
            return phase23_result
        phase24_result, envelope = _phase24_apply_to_envelope(
            envelope=envelope,
            normalized_utterance=routed_utterance,
        )
        if phase24_result is not None:
            return phase24_result
        phase26_result, envelope = _phase26_apply_to_envelope(
            envelope=envelope,
            normalized_utterance=routed_utterance,
        )
        if phase26_result is not None:
            return phase26_result
        phase25_result, envelope = _phase25_apply_to_envelope(
            envelope=envelope,
            normalized_utterance=routed_utterance,
        )
        if phase25_result is not None:
            return phase25_result
        phase24_guard_result, envelope = _phase24_apply_write_guard(
            envelope=envelope,
            normalized_utterance=routed_utterance,
        )
        if phase24_guard_result is not None:
            return phase24_guard_result
        phase17_result, envelope = _phase17_validate_filesystem_envelope(envelope)
        if phase17_result is not None:
            return phase17_result
        if not _is_actionable_envelope(envelope):
            if _is_content_generation_envelope(envelope):
                return _content_generation_result(envelope)
            return {
                "type": "no_action",
                "executed": False,
                "envelope": envelope,
                "message": "",
            }
        if _is_auto_executable(envelope):
            _emit_observability_event(
                phase="phase5",
                event_type="approval_not_required",
                metadata={
                    "intent": str(envelope.get("intent", "unknown.intent")),
                    "reason": "policy_allows_auto_execute",
                },
            )
            try:
                return _execute_envelope_once(envelope)
            except Exception as exc:
                return {
                    "type": "execution_rejected",
                    "executed": False,
                    "message": f"Execution rejected: {exc}",
                }

        try:
            plan = build_execution_plan(envelope)
        except Exception as exc:
            return {
                "type": "plan_rejected",
                "executed": False,
                "envelope": envelope,
                "message": f"Plan rejected: {exc}",
            }

        _pending_plan = _create_pending_plan(plan)
        _emit_observability_event(
            phase="phase5",
            event_type="approval_requested",
            metadata={
                "approval_scope": "plan" if _phase8_approval_mode == "plan" else "step",
                "plan_id": plan.plan_id,
                "step_count": len(plan.steps),
            },
        )
        return {
            "type": "plan_approval_required",
            "executed": False,
            "plan": _serialize_plan(plan),
            "message": _plan_approval_message(_pending_plan),
        }

    if _pending_plan_is_expired(_pending_plan):
        _emit_observability_event(
            phase="phase5",
            event_type="approval_response",
            metadata={
                "accepted": False,
                "approval_scope": "plan" if _phase8_approval_mode == "plan" else "step",
                "reason": "pending_plan_expired",
            },
        )
        _pending_plan = None
        return {
            "type": "approval_expired",
            "executed": False,
            "message": "Approval rejected: pending plan expired. Re-submit the action request.",
        }

    if not _pending_plan.awaiting_next_user_turn:
        _emit_observability_event(
            phase="phase5",
            event_type="approval_response",
            metadata={
                "accepted": False,
                "approval_scope": "plan" if _phase8_approval_mode == "plan" else "step",
                "reason": "approval_window_closed",
            },
        )
        return {
            "type": "approval_rejected",
            "executed": False,
            "message": "Approval rejected: approval window closed. Re-submit the action request.",
        }

    _pending_plan.awaiting_next_user_turn = False
    if not _is_valid_approval_phrase(normalized):
        _emit_observability_event(
            phase="phase5",
            event_type="approval_response",
            metadata={
                "accepted": False,
                "approval_scope": "plan" if _phase8_approval_mode == "plan" else "step",
                "reason": "explicit_phrase_required",
            },
        )
        _pending_plan = None
        return {
            "type": "approval_rejected",
            "executed": False,
            "message": "Approval rejected: explicit phrase required. Re-submit the action request.",
        }

    _emit_observability_event(
        phase="phase5",
        event_type="approval_response",
        metadata={
            "accepted": True,
            "approval_scope": "plan" if _phase8_approval_mode == "plan" else "step",
        },
    )
    try:
        result = _execute_plan_steps_from_pending()
    except Exception as exc:
        _pending_plan = None
        return {
            "type": "execution_rejected",
            "executed": False,
            "message": f"Execution rejected: {exc}",
        }

    if _pending_plan is None:
        return {
            "type": "execution_rejected",
            "executed": False,
            "message": "Execution rejected: pending plan state unavailable.",
        }

    events = result["events"]
    persist_message = ""
    if len(events) == 1:
        persist_message = _execution_confirmation_message(events[0])
    if _pending_plan.next_step_index >= len(_pending_plan.plan.steps):
        plan_id = _pending_plan.plan.plan_id
        _pending_plan = None
        return {
            "type": "plan_executed",
            "executed": True,
            "plan_id": plan_id,
            "execution_events": events,
            "message": persist_message or "Plan execution completed.",
        }

    _pending_plan.awaiting_next_user_turn = True
    return {
        "type": "step_executed",
        "executed": True,
        "plan_id": _pending_plan.plan.plan_id,
        "execution_events": events,
        "remaining_steps": len(_pending_plan.plan.steps) - _pending_plan.next_step_index,
        "message": persist_message or _plan_approval_message(_pending_plan),
    }


def process_user_message(utterance: str) -> Dict[str, Any]:
    """Phase 5 conversational approval gate.

    This function keeps Phases 1-4 authoritative for interpretation and policy.
    It only adds explicit conversational approval and single-use execution gating.
    """
    with ensure_observability_context():
        increment_metric("interpreter_calls")
        started = time.perf_counter()
        normalized = _normalize(utterance)
        _emit_observability_event(
            phase="phase1-4",
            event_type="utterance_received",
            metadata={"utterance": normalized},
        )
        try:
            if not _phase5_enabled:
                envelope = interpret_utterance(utterance)
                increment_metric("policy_decisions")
                _emit_observability_event(
                    phase="phase1-4",
                    event_type="utterance_interpreted",
                    metadata=_envelope_pointer(envelope),
                )
                _emit_observability_event(
                    phase="phase4",
                    event_type="policy_evaluated",
                    metadata=_envelope_pointer(envelope),
                )
                return {
                    "type": "phase5_disabled",
                    "executed": False,
                    "envelope": envelope,
                    "message": "",
                }

            if _phase20_enabled:
                working_set_control = _phase20_control_response(normalized)
                if working_set_control is not None:
                    return working_set_control
            if _phase22_enabled:
                project_control = _phase22_control_response(normalized)
                if project_control is not None:
                    return project_control
            if _phase26_enabled:
                workflow_progress = _phase26_active_run_progress_response(normalized)
                if workflow_progress is not None:
                    return workflow_progress

            autonomy_result = _process_user_message_phase15(utterance)
            if autonomy_result is not None:
                return autonomy_result

            if _phase8_enabled:
                return _process_user_message_phase8(utterance)

            global _pending_action

            if _pending_action is None:
                routed_utterance = _phase9_normalize_utterance(normalized)
                if _is_deprecated_engineer_mode_input(normalized) and routed_utterance == normalized:
                    return _phase9_engineer_mode_info_response(normalized)

                if _is_valid_approval_phrase(normalized):
                    _emit_observability_event(
                        phase="phase5",
                        event_type="approval_response",
                        metadata={
                            "accepted": False,
                            "reason": "no_pending_action",
                        },
                    )
                    return {
                        "type": "approval_rejected",
                        "executed": False,
                        "message": "Approval rejected: no pending action to approve.",
                    }

                envelope = interpret_utterance(routed_utterance)
                increment_metric("policy_decisions")
                _emit_observability_event(
                    phase="phase1-4",
                    event_type="utterance_interpreted",
                    metadata=_envelope_pointer(envelope),
                )
                _emit_observability_event(
                    phase="phase4",
                    event_type="policy_evaluated",
                    metadata=_envelope_pointer(envelope),
                )
                phase16_result, envelope = _phase16_apply_to_envelope(
                    envelope=envelope,
                    normalized_utterance=routed_utterance,
                )
                if phase16_result is not None:
                    return phase16_result
                phase19_result, envelope = _phase19_apply_to_envelope(
                    envelope=envelope,
                    normalized_utterance=routed_utterance,
                )
                if phase19_result is not None:
                    return phase19_result
                phase20_result, envelope = _phase20_apply_to_envelope(
                    envelope=envelope,
                    normalized_utterance=routed_utterance,
                )
                if phase20_result is not None:
                    return phase20_result
                phase21_result, envelope = _phase21_apply_to_envelope(
                    envelope=envelope,
                    normalized_utterance=routed_utterance,
                )
                if phase21_result is not None:
                    return phase21_result
                phase22_result, envelope = _phase22_apply_to_envelope(
                    envelope=envelope,
                    normalized_utterance=routed_utterance,
                )
                if phase22_result is not None:
                    return phase22_result
                phase23_result, envelope = _phase23_apply_to_envelope(
                    envelope=envelope,
                    normalized_utterance=routed_utterance,
                )
                if phase23_result is not None:
                    return phase23_result
                phase24_result, envelope = _phase24_apply_to_envelope(
                    envelope=envelope,
                    normalized_utterance=routed_utterance,
                )
                if phase24_result is not None:
                    return phase24_result
                phase26_result, envelope = _phase26_apply_to_envelope(
                    envelope=envelope,
                    normalized_utterance=routed_utterance,
                )
                if phase26_result is not None:
                    return phase26_result
                phase25_result, envelope = _phase25_apply_to_envelope(
                    envelope=envelope,
                    normalized_utterance=routed_utterance,
                )
                if phase25_result is not None:
                    return phase25_result
                phase24_guard_result, envelope = _phase24_apply_write_guard(
                    envelope=envelope,
                    normalized_utterance=routed_utterance,
                )
                if phase24_guard_result is not None:
                    return phase24_guard_result
                phase17_result, envelope = _phase17_validate_filesystem_envelope(envelope)
                if phase17_result is not None:
                    return phase17_result
                if not _is_actionable_envelope(envelope):
                    if _is_content_generation_envelope(envelope):
                        return _content_generation_result(envelope)
                    return {
                        "type": "no_action",
                        "executed": False,
                        "envelope": envelope,
                        "message": "",
                    }

                if _is_auto_executable(envelope):
                    _emit_observability_event(
                        phase="phase5",
                        event_type="approval_not_required",
                        metadata={
                            "intent": str(envelope.get("intent", "unknown.intent")),
                            "reason": "policy_allows_auto_execute",
                        },
                    )
                    try:
                        return _execute_envelope_once(envelope)
                    except Exception as exc:
                        return {
                            "type": "execution_rejected",
                            "executed": False,
                            "message": f"Execution rejected: {exc}",
                        }

                _pending_action = _create_pending_action(envelope)
                _emit_observability_event(
                    phase="phase5",
                    event_type="approval_requested",
                    metadata={
                        "approval_scope": "single_action",
                        "intent": str(envelope.get("intent", "unknown.intent")),
                    },
                )
                return {
                    "type": "approval_required",
                    "executed": False,
                    "action_id": _pending_action.action_id,
                    "envelope": copy.deepcopy(envelope),
                    "message": _approval_request_message(_pending_action),
                }

            # There is a pending action: this is the approval turn.
            if _pending_is_expired(_pending_action):
                _emit_observability_event(
                    phase="phase5",
                    event_type="approval_response",
                    metadata={
                        "accepted": False,
                        "reason": "pending_action_expired",
                    },
                )
                _pending_action = None
                return {
                    "type": "approval_expired",
                    "executed": False,
                    "message": "Approval rejected: pending action expired. Re-submit the action request.",
                }

            if not _pending_action.awaiting_next_user_turn:
                _emit_observability_event(
                    phase="phase5",
                    event_type="approval_response",
                    metadata={
                        "accepted": False,
                        "reason": "approval_window_closed",
                    },
                )
                return {
                    "type": "approval_rejected",
                    "executed": False,
                    "message": "Approval rejected: approval window closed. Re-submit the action request.",
                }

            if _phase26_enabled and _entity_string(_pending_action.envelope_snapshot, "phase26_run_start").lower() == "true":
                status_probe = _parse_phase26_intent(normalized)
                if isinstance(status_probe, dict) and str(status_probe.get("intent", "")) == "workflow_status":
                    run_id = _entity_string(_pending_action.envelope_snapshot, "phase26_run_id")
                    run = _phase26_find_run(run_id)
                    if isinstance(run, dict):
                        return _phase26_status_payload(run)

            _pending_action.awaiting_next_user_turn = False
            if not _is_valid_approval_phrase(normalized):
                _emit_observability_event(
                    phase="phase5",
                    event_type="approval_response",
                    metadata={
                        "accepted": False,
                        "reason": "explicit_phrase_required",
                    },
                )
                _pending_action = None
                return {
                    "type": "approval_rejected",
                    "executed": False,
                    "message": "Approval rejected: explicit phrase required. Re-submit the action request.",
                }

            _emit_observability_event(
                phase="phase5",
                event_type="approval_response",
                metadata={"accepted": True, "approval_scope": "single_action"},
            )
            action_id = _pending_action.action_id
            try:
                event = execute_pending_action(action_id)
            except Exception as exc:
                _pending_action = None
                return {
                    "type": "execution_rejected",
                    "executed": False,
                    "action_id": action_id,
                    "message": f"Execution rejected: {exc}",
                }

            _pending_action = None
            payload = {
                "type": "executed",
                "executed": True,
                "action_id": action_id,
                "execution_event": event,
                "message": _execution_confirmation_message(event),
            }
            payload.update(_phase25_execution_response_fields(event))
            payload.update(_phase26_execution_response_fields(event))
            return payload
        finally:
            record_latency_ms("interpreter_call_latency_ms", (time.perf_counter() - started) * 1000.0)


def _phase10_default_freeform_response(utterance: str, _envelope: Envelope) -> str:
    normalized = _normalize(utterance)
    model_config = _load_model_config()
    if llm_api is not None and model_config:
        messages = [
            {
                "role": "system",
                "content": "Respond conversationally to the user. Do not emit tool calls or policy decisions.",
            },
            {"role": "user", "content": normalized},
        ]
        try:
            answer = llm_api.get_completion(messages, model_config)
            if isinstance(answer, str) and answer.strip():
                return answer.strip()
        except Exception:
            pass
    if normalized.lower().startswith("tell me a joke"):
        return "Why do programmers confuse Halloween and Christmas? Because OCT 31 == DEC 25."
    return "I can help with that."


def _phase10_response_text(
    utterance: str,
    governed_result: Dict[str, Any],
    llm_responder: Callable[[str, Envelope], str] | None = None,
) -> str:
    result_type = str(governed_result.get("type", ""))
    envelope = governed_result.get("envelope", {})
    envelope = envelope if isinstance(envelope, dict) else {}
    lane = str(envelope.get("lane", ""))

    if result_type in {"approval_required", "plan_approval_required", "mode_info"}:
        return str(governed_result.get("message", ""))

    if result_type in {"executed", "step_executed", "plan_executed"}:
        return str(governed_result.get("message", ""))

    if result_type in {"approval_rejected", "approval_expired", "execution_rejected", "plan_rejected"}:
        return str(governed_result.get("message", ""))

    if result_type == "content_generation":
        responder = llm_responder or _phase10_default_freeform_response
        text = responder(utterance, envelope)
        return str(text) if text is not None else ""

    if result_type in {"no_action", "phase5_disabled"}:
        if lane in {"CHAT", "HELP", "CONTENT_GENERATION"}:
            responder = llm_responder or _phase10_default_freeform_response
            text = responder(utterance, envelope)
            return str(text) if text is not None else ""
        if lane == "CLARIFY":
            next_prompt = envelope.get("next_prompt", "")
            if isinstance(next_prompt, str) and next_prompt.strip():
                return next_prompt
            return "Can you clarify what outcome you want?"
        return str(governed_result.get("message", ""))

    return str(governed_result.get("message", ""))


def _phase16_response_source(governed_result: Dict[str, Any]) -> str:
    result_type = str(governed_result.get("type", ""))
    envelope = governed_result.get("envelope", {})
    envelope = envelope if isinstance(envelope, dict) else {}
    lane = str(envelope.get("lane", ""))
    if result_type == "content_generation":
        return "llm"
    if result_type in {"no_action", "phase5_disabled"} and lane in {"CHAT", "HELP", "CONTENT_GENERATION"}:
        return "llm"
    if result_type in {"executed", "step_executed", "plan_executed", "autonomy_executed"}:
        return "tool_result"
    if result_type in {"content_revised", "content_transformed"}:
        return "llm"
    return "assistant_response"


def _phase16_record_last_response(
    *,
    session_id: str,
    correlation_id: str,
    response_text: str,
    governed_result: Dict[str, Any],
) -> None:
    global _phase16_last_response_global
    record = {
        "session_id": session_id,
        "origin_turn_id": correlation_id,
        "text": str(response_text),
        "source": _phase16_response_source(governed_result),
        "timestamp": _utcnow().isoformat(),
    }
    _phase16_last_response_by_session[session_id] = copy.deepcopy(record)
    _phase16_last_response_global = copy.deepcopy(record)


def process_conversational_turn(
    utterance: str,
    *,
    session_id: str | None = None,
    llm_responder: Callable[[str, Envelope], str] | None = None,
) -> Dict[str, Any]:
    """Phase 10 conversational entrypoint.

    Every turn is governed by process_user_message(...). Freeform text generation
    is a subroutine that cannot capture conversational control state.
    """
    with observability_turn(session_id=session_id) as (resolved_session_id, resolved_correlation_id):
        _emit_observability_event(
            phase="phase10",
            event_type="conversational_turn_started",
            metadata={"utterance": utterance},
        )
        governed_result = process_user_message(utterance)
        response_text = _phase10_response_text(
            utterance=utterance,
            governed_result=governed_result,
            llm_responder=llm_responder,
        )
        _phase16_record_last_response(
            session_id=resolved_session_id,
            correlation_id=resolved_correlation_id,
            response_text=response_text,
            governed_result=governed_result,
        )
        _emit_observability_event(
            phase="phase10",
            event_type="conversational_turn_completed",
            metadata={
                "result_type": str(governed_result.get("type", "")),
                "response": response_text,
            },
        )
        return {
            "response": response_text,
            "next_state": "ready_for_input",
            "governed_result": governed_result,
            "session_id": resolved_session_id,
            "correlation_id": resolved_correlation_id,
        }
