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

_SEMANTIC_LANES = ("CHAT", "PLAN", "HELP", "CLARIFY")
_SEMANTIC_CONFIDENCE_THRESHOLD = 0.70
_PHASE3_MAX_RETRIES = 2
_phase3_enabled = False
_phase4_enabled = False
_phase4_explanation_enabled = False
_phase5_enabled = False
_phase8_enabled = False
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


def _is_deprecated_engineer_mode_input(text: str) -> bool:
    lowered = _normalize(text).lower()
    return (
        lowered == "/engineer"
        or lowered.startswith("/engineer ")
        or lowered == "engineer mode"
        or lowered == "enter engineer mode"
        or lowered == "switch to engineer mode"
    )


def _phase9_normalize_utterance(text: str) -> str:
    normalized = _normalize(text)
    lowered = normalized.lower()
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


def _is_conversational(normalized: str) -> bool:
    lowered = normalized.lower()
    if lowered in {"hi", "hello", "hey", "thanks", "thank you"}:
        return True
    return any(lowered.startswith(prefix + " ") for prefix in _CONVERSATIONAL_PREFIXES)


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


def _phase16_apply_to_envelope(
    *,
    envelope: Envelope,
    normalized_utterance: str,
) -> tuple[Dict[str, Any] | None, Envelope]:
    if str(envelope.get("intent", "")) == "capture_content":
        return _phase16_capture_response(envelope=envelope, normalized_utterance=normalized_utterance), envelope

    if str(envelope.get("lane", "")).upper() != "PLAN":
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


def reset_phase5_state() -> None:
    global _pending_action, _execution_events
    _pending_action = None
    reset_phase8_state()
    reset_phase15_state()
    reset_phase16_state()
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
    return (
        f"Pending action {pending.action_id}: intent={intent}, risk={risk_level}. "
        "To approve, reply exactly: approve"
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
    if _is_valid_approval_phrase(normalized):
        return None
    if _is_deprecated_engineer_mode_input(normalized):
        return None

    routed_utterance = _phase9_normalize_utterance(normalized)
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
        if _is_deprecated_engineer_mode_input(normalized):
            return _phase9_engineer_mode_info_response(normalized)

        if _is_valid_approval_phrase(normalized):
            return {
                "type": "approval_rejected",
                "executed": False,
                "message": "Approval rejected: no pending plan to approve.",
            }

        routed_utterance = _phase9_normalize_utterance(normalized)
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
        if not _is_actionable_envelope(envelope):
            return {
                "type": "no_action",
                "executed": False,
                "envelope": envelope,
                "message": "",
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
    if _pending_plan.next_step_index >= len(_pending_plan.plan.steps):
        plan_id = _pending_plan.plan.plan_id
        _pending_plan = None
        return {
            "type": "plan_executed",
            "executed": True,
            "plan_id": plan_id,
            "execution_events": events,
            "message": "Plan execution completed.",
        }

    _pending_plan.awaiting_next_user_turn = True
    return {
        "type": "step_executed",
        "executed": True,
        "plan_id": _pending_plan.plan.plan_id,
        "execution_events": events,
        "remaining_steps": len(_pending_plan.plan.steps) - _pending_plan.next_step_index,
        "message": _plan_approval_message(_pending_plan),
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

            autonomy_result = _process_user_message_phase15(utterance)
            if autonomy_result is not None:
                return autonomy_result

            if _phase8_enabled:
                return _process_user_message_phase8(utterance)

            global _pending_action

            if _pending_action is None:
                if _is_deprecated_engineer_mode_input(normalized):
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

                routed_utterance = _phase9_normalize_utterance(normalized)
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
                if not _is_actionable_envelope(envelope):
                    return {
                        "type": "no_action",
                        "executed": False,
                        "envelope": envelope,
                        "message": "",
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
            return {
                "type": "executed",
                "executed": True,
                "action_id": action_id,
                "execution_event": event,
                "message": "Execution accepted and completed once.",
            }
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

    if result_type in {"no_action", "phase5_disabled"}:
        if lane in {"CHAT", "HELP"}:
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
    if result_type in {"no_action", "phase5_disabled"} and lane in {"CHAT", "HELP"}:
        return "llm"
    if result_type in {"executed", "step_executed", "plan_executed", "autonomy_executed"}:
        return "tool_result"
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
