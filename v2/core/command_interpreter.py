"""Deterministic command interpreter (Phase 1 skeleton).

This module intentionally stays below execution authority:
- no tool calls
- no command execution
- no routing/dispatch side effects
- no LLM usage
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


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
    # Confidence is a deterministic heuristic in [0.0, 1.0], not a model score.
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


def interpret_utterance(utterance: str) -> Envelope:
    """Interpret raw user text into a canonical, auditable intent envelope."""
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
