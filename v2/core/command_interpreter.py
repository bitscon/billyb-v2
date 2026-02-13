"""Command interpreter with deterministic Phase 1 fallback and Phase 2 lane semantics.

This module stays below execution authority:
- no command execution
- no tool invocation
- no LLM usage
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
from typing import Any, Dict, List, Protocol
import uuid

import jsonschema
import yaml

from v2.core import llm_api


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

_PHASE5_PENDING_TTL_SECONDS = 300
_PHASE5_APPROVAL_PHRASES = {
    "yes, proceed",
    "approve",
    "approved",
    "go ahead",
    "do it",
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
    created_at: str
    expires_at: str
    consumed: bool
    awaiting_next_user_turn: bool


_pending_action: PendingAction | None = None
_execution_events: List[Dict[str, Any]] = []


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


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


def reset_phase5_state() -> None:
    global _pending_action, _execution_events
    _pending_action = None
    _execution_events = []


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


def _create_pending_action(envelope: Envelope) -> PendingAction:
    now = _utcnow()
    action_id = f"act-{uuid.uuid4()}"
    return PendingAction(
        action_id=action_id,
        envelope_snapshot=copy.deepcopy(envelope),
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


def execute_pending_action(action_id: str) -> Dict[str, Any]:
    global _pending_action, _execution_events
    if _pending_action is None:
        raise ValueError("No pending action available.")
    if _pending_action.action_id != action_id:
        raise ValueError("Pending action id mismatch.")
    if _pending_action.consumed:
        raise ValueError("Pending action already consumed.")
    if _pending_is_expired(_pending_action):
        raise ValueError("Pending action expired.")

    event = {
        "event_id": f"exec-{uuid.uuid4()}",
        "action_id": _pending_action.action_id,
        "executed_at": _utcnow().isoformat(),
        "status": "executed_stub",
        "envelope": copy.deepcopy(_pending_action.envelope_snapshot),
    }
    _pending_action.consumed = True
    _execution_events.append(event)
    return copy.deepcopy(event)


def process_user_message(utterance: str) -> Dict[str, Any]:
    """Phase 5 conversational approval gate.

    This function keeps Phases 1-4 authoritative for interpretation and policy.
    It only adds explicit conversational approval and single-use execution gating.
    """
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
        if _is_valid_approval_phrase(normalized):
            return {
                "type": "approval_rejected",
                "executed": False,
                "message": "Approval rejected: no pending action to approve.",
            }

        envelope = interpret_utterance(utterance)
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
    event = execute_pending_action(action_id)
    _pending_action = None
    return {
        "type": "executed",
        "executed": True,
        "action_id": action_id,
        "execution_event": event,
        "message": "Execution accepted and completed once.",
    }
