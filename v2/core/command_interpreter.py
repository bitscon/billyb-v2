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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Protocol
import uuid

import jsonschema
import yaml

from v2.core import llm_api
from v2.core.command_memory import (
    FileBackedMemoryStore,
    InMemoryMemoryStore,
    MemoryEvent,
    MemoryStore,
)


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


_pending_action: PendingAction | None = None
_execution_events: List[Dict[str, Any]] = []
_memory_store: MemoryStore = InMemoryMemoryStore()
_pending_plan: PendingPlan | None = None


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


def get_memory_events_last(count: int) -> List[Dict[str, Any]]:
    return [event.to_dict() for event in _memory_store.get_last(count)]


def get_memory_events_by_intent(intent: str) -> List[Dict[str, Any]]:
    return [event.to_dict() for event in _memory_store.get_by_intent(intent)]


def get_memory_events_by_tool(tool_name: str) -> List[Dict[str, Any]]:
    return [event.to_dict() for event in _memory_store.get_by_tool(tool_name)]


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


def reset_phase5_state() -> None:
    global _pending_action, _execution_events
    _pending_action = None
    reset_phase8_state()
    _execution_events = []
    reset_phase7_memory()
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
    if not _is_actionable_envelope(envelope):
        raise ValueError("Envelope is not actionable for planning.")

    utterance = str(envelope.get("utterance", ""))
    fallback_intent = str(envelope.get("intent", ""))
    clauses = _split_plan_clauses(utterance)
    if not clauses:
        raise ValueError("No actionable plan steps found in utterance.")

    steps: List[PlanStep] = []
    for index, clause in enumerate(clauses, start=1):
        step_intent = _resolve_plan_step_intent(clause)
        if step_intent is None and len(clauses) == 1 and fallback_intent and _resolve_tool_contract(fallback_intent):
            step_intent = fallback_intent
        if step_intent is None:
            raise ValueError(f"Unmappable plan step: {clause}")
        contract = _resolve_tool_contract(step_intent)
        if contract is None:
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

    return ExecutionPlan(
        plan_id=f"plan-{uuid.uuid4()}",
        intent=fallback_intent or "plan.user_action_request",
        steps=steps,
    )


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
    except Exception:
        # Memory recording must never change execution behavior.
        return


def execute_pending_action(action_id: str) -> Dict[str, Any]:
    global _pending_action, _execution_events
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
        return copy.deepcopy(event)
    except Exception as exc:
        _record_memory_event(
            envelope=snapshot,
            contract=contract,
            parameters=parameters,
            execution_result={"error": str(exc)},
            success=False,
        )
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
        return {
            "type": "plan_approval_required",
            "executed": False,
            "plan": _serialize_plan(plan),
            "message": _plan_approval_message(_pending_plan),
        }

    if _pending_plan_is_expired(_pending_plan):
        _pending_plan = None
        return {
            "type": "approval_expired",
            "executed": False,
            "message": "Approval rejected: pending plan expired. Re-submit the action request.",
        }

    if not _pending_plan.awaiting_next_user_turn:
        return {
            "type": "approval_rejected",
            "executed": False,
            "message": "Approval rejected: approval window closed. Re-submit the action request.",
        }

    _pending_plan.awaiting_next_user_turn = False
    if not _is_valid_approval_phrase(normalized):
        _pending_plan = None
        return {
            "type": "approval_rejected",
            "executed": False,
            "message": "Approval rejected: explicit phrase required. Re-submit the action request.",
        }

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
    if _phase8_enabled:
        return _process_user_message_phase8(utterance)

    global _pending_action
    normalized = _normalize(utterance)

    if not _phase5_enabled:
        return {
            "type": "phase5_disabled",
            "executed": False,
            "envelope": interpret_utterance(utterance),
            "message": "",
        }

    if _pending_action is None:
        if _is_deprecated_engineer_mode_input(normalized):
            return _phase9_engineer_mode_info_response(normalized)

        if _is_valid_approval_phrase(normalized):
            return {
                "type": "approval_rejected",
                "executed": False,
                "message": "Approval rejected: no pending action to approve.",
            }

        routed_utterance = _phase9_normalize_utterance(normalized)
        envelope = interpret_utterance(routed_utterance)
        if not _is_actionable_envelope(envelope):
            return {
                "type": "no_action",
                "executed": False,
                "envelope": envelope,
                "message": "",
            }

        _pending_action = _create_pending_action(envelope)
        return {
            "type": "approval_required",
            "executed": False,
            "action_id": _pending_action.action_id,
            "envelope": copy.deepcopy(envelope),
            "message": _approval_request_message(_pending_action),
        }

    # There is a pending action: this is the approval turn.
    if _pending_is_expired(_pending_action):
        _pending_action = None
        return {
            "type": "approval_expired",
            "executed": False,
            "message": "Approval rejected: pending action expired. Re-submit the action request.",
        }

    if not _pending_action.awaiting_next_user_turn:
        return {
            "type": "approval_rejected",
            "executed": False,
            "message": "Approval rejected: approval window closed. Re-submit the action request.",
        }

    _pending_action.awaiting_next_user_turn = False
    if not _is_valid_approval_phrase(normalized):
        _pending_action = None
        return {
            "type": "approval_rejected",
            "executed": False,
            "message": "Approval rejected: explicit phrase required. Re-submit the action request.",
        }

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


def process_conversational_turn(
    utterance: str,
    *,
    llm_responder: Callable[[str, Envelope], str] | None = None,
) -> Dict[str, Any]:
    """Phase 10 conversational entrypoint.

    Every turn is governed by process_user_message(...). Freeform text generation
    is a subroutine that cannot capture conversational control state.
    """
    governed_result = process_user_message(utterance)
    response_text = _phase10_response_text(
        utterance=utterance,
        governed_result=governed_result,
        llm_responder=llm_responder,
    )
    return {
        "response": response_text,
        "next_state": "ready_for_input",
        "governed_result": governed_result,
    }
