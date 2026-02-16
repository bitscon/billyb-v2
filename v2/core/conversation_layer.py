"""Phase 27 conversational front-end and interpreter gate.

This layer separates natural conversation from governed execution intent.
It never executes actions directly. It only decides whether to:
1) return a conversational reply, or
2) escalate a structured intent envelope to the governed interpreter.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict

from v2.core import command_interpreter


_ESCALATION_KEYWORDS = (
    "save",
    "write",
    "create",
    "run",
    "execute",
    "delete",
    "refactor",
    "delegate",
    "workflow",
    "project",
)
_ESCALATION_PHRASES = (
    "make file",
    "put in sandbox",
)
_CASUAL_EXACT = {
    "hi",
    "hello",
    "hey",
    "thanks",
    "thank you",
    "thats cool",
    "that's cool",
}
_CASUAL_PREFIXES = (
    "tell me",
    "what do you think",
    "explain",
    "what is",
    "who is",
    "how do",
    "how does",
)
_AMBIGUOUS_ACTION_PHRASES = (
    "i want something done",
    "do something",
    "handle this",
    "take care of this",
)
_READ_ONLY_VERB_PREFIXES = (
    "read ",
    "show ",
    "view ",
    "inspect ",
)
_STRUCTURED_READ_FILE_PATTERN = re.compile(
    r"read file (?P<path>.+?)(?: from (?P<loc>my home directory|home directory|my workspace|workspace|sandbox))?$"
)


def _normalize_utterance(utterance: str) -> str:
    return re.sub(r"\s+", " ", str(utterance or "").strip())


def _compact_text(utterance: str) -> str:
    compact = re.sub(r"[^a-z0-9\s]", " ", utterance.lower())
    return re.sub(r"\s+", " ", compact).strip()


def _has_escalation_trigger(utterance: str) -> bool:
    lowered = _compact_text(utterance)
    if not lowered:
        return False
    if any(phrase in lowered for phrase in _ESCALATION_PHRASES):
        return True
    return any(re.search(rf"\b{re.escape(keyword)}\b", lowered) for keyword in _ESCALATION_KEYWORDS)


def _is_casual_chat(utterance: str) -> bool:
    lowered = _compact_text(utterance)
    if not lowered:
        return True
    if lowered in _CASUAL_EXACT:
        return True
    if lowered.startswith("thanks ") or lowered.startswith("thank you "):
        return True
    return any(lowered.startswith(prefix + " ") or lowered == prefix for prefix in _CASUAL_PREFIXES)


def _is_ambiguous_action_request(utterance: str) -> bool:
    lowered = _compact_text(utterance)
    if not lowered:
        return False
    if any(phrase in lowered for phrase in _AMBIGUOUS_ACTION_PHRASES):
        return True
    return bool(
        re.fullmatch(
            r"(?:i (?:want|need)|can you|please)\s+(?:something|anything)\s*(?:done|handled)?",
            lowered,
        )
    )


def _is_non_authoritative_read_language(utterance: str) -> bool:
    lowered = _compact_text(utterance)
    if not lowered:
        return False
    return any(lowered.startswith(prefix) for prefix in _READ_ONLY_VERB_PREFIXES)


def _is_explicit_structured_read_file_request(utterance: str) -> bool:
    lowered = _compact_text(utterance)
    if not lowered:
        return False
    matched = _STRUCTURED_READ_FILE_PATTERN.fullmatch(lowered)
    if matched is None:
        return False
    path_value = str(matched.group("path") or "").strip()
    return path_value not in {"", "this", "that", "it", "current", "current file", "file"}


def _chat_response(utterance: str) -> str:
    lowered = _compact_text(utterance)
    if "joke" in lowered:
        return "Here is a joke: Why do programmers confuse Halloween and Christmas? Because OCT 31 == DEC 25."
    if lowered.startswith("thanks") or lowered.startswith("thank you"):
        return "You're welcome."
    if lowered in {"hi", "hello", "hey"} or lowered.startswith("hi ") or lowered.startswith("hello ") or lowered.startswith("hey "):
        return "Hi. Tell me what you want to discuss, or ask for an action when you want execution."
    if lowered.startswith("explain "):
        topic = utterance.strip()[len("explain ") :].strip()
        if topic:
            return f"Sure. I can explain {topic}."
    return "I can help with that."


def process_conversational_turn(utterance: str) -> Dict[str, Any]:
    """Classify one conversational turn into chat or governed escalation."""
    normalized = _normalize_utterance(utterance)
    if not normalized:
        return {
            "escalate": False,
            "chat_response": "I can help with that.",
        }

    envelope = command_interpreter.interpret_utterance(normalized)
    lane = str(envelope.get("lane", "")).upper()

    has_trigger = _has_escalation_trigger(normalized)
    casual = _is_casual_chat(normalized)
    ambiguous_action = _is_ambiguous_action_request(normalized)
    read_only_language = _is_non_authoritative_read_language(normalized)
    structured_read_request = _is_explicit_structured_read_file_request(normalized)

    if casual and not has_trigger:
        return {
            "escalate": False,
            "chat_response": _chat_response(normalized),
        }

    if read_only_language and not has_trigger and not ambiguous_action and not structured_read_request:
        return {
            "escalate": False,
            "chat_response": _chat_response(normalized),
        }

    escalate = has_trigger or lane == "PLAN" or ambiguous_action
    if lane == "CLARIFY" and not casual:
        # Keep ambiguous non-casual requests in governed CLARIFY handling.
        escalate = True

    if escalate:
        intent_envelope = copy.deepcopy(envelope)
        intent_envelope["escalate"] = True
        return {
            "escalate": True,
            "intent_envelope": intent_envelope,
        }

    return {
        "escalate": False,
        "chat_response": _chat_response(normalized),
    }


def _governed_response_text(governed_result: Dict[str, Any], fallback_envelope: Dict[str, Any]) -> str:
    result_type = str(governed_result.get("type", ""))
    message = str(governed_result.get("message", "") or "").strip()
    envelope = governed_result.get("envelope")
    if not isinstance(envelope, dict):
        envelope = fallback_envelope
    lane = str(envelope.get("lane", "")).upper()
    next_prompt = str(envelope.get("next_prompt", "") or "").strip()

    if message:
        return message
    if lane == "CLARIFY":
        return next_prompt or "Can you clarify what outcome you want?"
    if lane in {"CHAT", "HELP", "CONTENT_GENERATION"}:
        return _chat_response(str(envelope.get("utterance", "")))
    if result_type in {"approval_required", "plan_approval_required"}:
        return "Approval required before execution."
    return "Request routed through governed interpreter."


def run_governed_interpreter(intent_envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Forward an escalated envelope into Billy's governed interpreter."""
    envelope = dict(intent_envelope or {})
    utterance = _normalize_utterance(str(envelope.get("utterance", "")))
    if not utterance:
        return {
            "intent": str(envelope.get("intent", "")),
            "governed_result": {
                "type": "execution_rejected",
                "executed": False,
                "message": "Execution rejected: missing utterance in intent envelope.",
                "envelope": envelope,
            },
            "response": "Execution rejected: missing utterance in intent envelope.",
        }

    governed_result = command_interpreter.process_user_message(utterance)
    resolved_envelope = governed_result.get("envelope")
    if not isinstance(resolved_envelope, dict):
        resolved_envelope = copy.deepcopy(envelope)

    return {
        "intent": str(resolved_envelope.get("intent", envelope.get("intent", ""))),
        "governed_result": governed_result,
        "response": _governed_response_text(governed_result, resolved_envelope),
    }
