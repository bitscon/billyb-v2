"""Phase 27 conversational front-end and interpreter gate.

This layer separates natural conversation from governed execution intent.
It never executes actions directly. It only decides whether to:
1) return a conversational reply, or
2) escalate a structured intent envelope to the governed interpreter.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List

from v2.core import command_interpreter
from v2.core.proposal_governance import (
    approve_proposal as approve_governed_proposal,
    create_proposal,
    enforce_proposal_expiration as enforce_governed_proposal_expiration,
    expire_proposal as expire_governed_proposal,
    get_proposal,
    get_proposal_ledger,
    reject_proposal as reject_governed_proposal,
    reset_proposal_ledger,
    submit_proposal as submit_governed_proposal,
)

# Canonical, immutable intent taxonomy.
class IntentClass(str, Enum):
    INFORMATIONAL_QUERY = "informational_query"
    GENERATIVE_CONTENT_REQUEST = "generative_content_request"
    ADVISORY_REQUEST = "advisory_request"
    PLANNING_REQUEST = "planning_request"
    GOVERNED_ACTION_PROPOSAL = "governed_action_proposal"
    EXECUTION_ATTEMPT = "execution_attempt"
    POLICY_BOUNDARY_CHALLENGE = "policy_boundary_challenge"
    META_GOVERNANCE_INQUIRY = "meta_governance_inquiry"
    AMBIGUOUS_INTENT = "ambiguous_intent"


NON_ESCALATING_INTENTS = frozenset(
    {
        IntentClass.INFORMATIONAL_QUERY,
        IntentClass.GENERATIVE_CONTENT_REQUEST,
        IntentClass.ADVISORY_REQUEST,
        IntentClass.PLANNING_REQUEST,
        IntentClass.POLICY_BOUNDARY_CHALLENGE,
        IntentClass.META_GOVERNANCE_INQUIRY,
        IntentClass.AMBIGUOUS_INTENT,
    }
)
ESCALATING_INTENTS = frozenset(
    {
        IntentClass.GOVERNED_ACTION_PROPOSAL,
        IntentClass.EXECUTION_ATTEMPT,
    }
)

_POLICY_BOUNDARY_CHALLENGE_PHRASES = (
    "bypass policy",
    "bypass governance",
    "ignore policy",
    "ignore governance",
    "override policy",
    "override governance",
    "skip approval",
    "without approval",
    "circumvent guardrails",
    "disable guardrails",
    "bypass rules",
    "ignore safeguards",
    "you decide and bypass approval",
)
_META_GOVERNANCE_TOKENS = (
    "governance",
    "policy",
    "authority",
    "boundary",
    "boundaries",
    "escalation",
    "refusal",
    "approval",
)
_META_GOVERNANCE_PREFIXES = (
    "what is",
    "what are",
    "how does",
    "how do",
    "why does",
    "why do",
    "explain",
    "describe",
)
_EXECUTION_COMMAND_PREFIXES = (
    "approve:",
    "apply:",
    "run tool:",
    "confirm run tool:",
    "run workflow:",
    "/exec ",
)
_EXECUTION_ATTEMPT_PHRASES = (
    "execute now",
    "run now",
    "run it now",
    "do it now",
    "do this now",
    "just do it",
    "execute immediately",
    "run immediately",
    "deploy now",
    "apply now",
    "right now",
    "immediately",
)
_EXECUTION_VERBS = (
    "execute",
    "run",
    "deploy",
    "apply",
    "restart",
    "start",
    "stop",
)
_GOVERNED_ACTION_PATTERNS = (
    re.compile(
        r"\b(save|write|create|delete|remove|refactor|edit|modify)\b.*\b("
        r"file|folder|directory|repo|repository|project|workflow|note|document|"
        r"sandbox|workspace|service|script|tool"
        r")\b"
    ),
    re.compile(r"\b(delegate|workflow|project)\b"),
    re.compile(r"\bmake file\b"),
    re.compile(r"\bput in sandbox\b"),
    re.compile(r"\bsave\b.*\b(this|that|it)\b"),
    re.compile(r"\bread file .+\b"),
)
_PLANNING_TOKENS = (
    "plan",
    "roadmap",
    "next steps",
    "milestone",
    "task list",
    "strategy",
    "outline",
)
_GENERATION_TOKENS = (
    "draft",
    "generate",
    "compose",
    "template",
    "poem",
    "story",
    "email",
    "blog",
    "homepage",
    "write me",
    "propose",
)
_ADVISORY_PREFIXES = (
    "should i",
    "what should",
    "how should",
    "can you advise",
    "advice",
    "recommend",
    "best way",
)
_INFORMATIONAL_PREFIXES = (
    "what",
    "who",
    "when",
    "where",
    "why",
    "how",
    "tell me",
)
_SOCIAL_CHITCHAT_PREFIXES = (
    "hi",
    "hello",
    "hey",
    "thanks",
    "thank you",
)
_AMBIGUOUS_ACTION_PHRASES = (
    "i want something done",
    "do something",
    "handle this",
    "take care of this",
    "help me with this",
)
_STRUCTURED_READ_FILE_PATTERN = re.compile(
    r"read file (?P<path>.+?)(?: from (?P<loc>my home directory|home directory|my workspace|workspace|sandbox))?$"
)
_EXECUTION_REFUSAL_CITATION = "v2/docs/charter/08_TOOLS_WORKERS_EXECUTION.md"
_INTENT_ROUTING_AUDIT_LOG: List[Dict[str, Any]] = []


@dataclass(frozen=True)
class _ClassificationDecision:
    intent_class: IntentClass
    escalate: bool
    reason: str


def _normalize_utterance(utterance: str) -> str:
    return re.sub(r"\s+", " ", str(utterance or "").strip())


def _compact_text(utterance: str) -> str:
    compact = re.sub(r"[^a-z0-9\s]", " ", utterance.lower())
    return re.sub(r"\s+", " ", compact).strip()


def _is_policy_boundary_challenge(lowered: str) -> bool:
    if not lowered:
        return False
    return any(phrase in lowered for phrase in _POLICY_BOUNDARY_CHALLENGE_PHRASES)


def _is_meta_governance_inquiry(lowered: str) -> bool:
    if not lowered:
        return False
    if not any(token in lowered for token in _META_GOVERNANCE_TOKENS):
        return False
    return any(lowered.startswith(prefix + " ") or lowered == prefix for prefix in _META_GOVERNANCE_PREFIXES)


def _is_execution_attempt(utterance: str, lowered: str) -> bool:
    normalized = utterance.strip().lower()
    if any(normalized.startswith(prefix) for prefix in _EXECUTION_COMMAND_PREFIXES):
        return True
    if any(phrase in lowered for phrase in _EXECUTION_ATTEMPT_PHRASES):
        return True
    if not lowered:
        return False
    return any(
        lowered.startswith(verb + " ") and ("now" in lowered or "immediately" in lowered)
        for verb in _EXECUTION_VERBS
    )


def _is_governed_action_proposal(lowered: str) -> bool:
    if not lowered:
        return False
    return any(pattern.search(lowered) is not None for pattern in _GOVERNED_ACTION_PATTERNS)


def _is_planning_request(lowered: str) -> bool:
    if not lowered:
        return False
    return any(token in lowered for token in _PLANNING_TOKENS)


def _is_generative_content_request(lowered: str) -> bool:
    if not lowered:
        return False
    return any(token in lowered for token in _GENERATION_TOKENS)


def _is_advisory_request(lowered: str) -> bool:
    if not lowered:
        return False
    return any(lowered.startswith(prefix) for prefix in _ADVISORY_PREFIXES)


def _is_informational_query(utterance: str, lowered: str) -> bool:
    if not lowered:
        return False
    if utterance.strip().endswith("?"):
        return True
    return any(lowered.startswith(prefix + " ") or lowered == prefix for prefix in _INFORMATIONAL_PREFIXES)


def _is_social_chitchat(lowered: str) -> bool:
    if not lowered:
        return False
    return any(lowered == prefix or lowered.startswith(prefix + " ") for prefix in _SOCIAL_CHITCHAT_PREFIXES)


def _is_ambiguous_intent(lowered: str) -> bool:
    if not lowered:
        return True
    if any(phrase in lowered for phrase in _AMBIGUOUS_ACTION_PHRASES):
        return True
    return bool(
        re.fullmatch(
            r"(?:i (?:want|need)|can you|please)\s+(?:something|anything)\s*(?:done|handled)?",
            lowered,
        )
    )


def _is_explicit_structured_read_file_request(lowered: str) -> bool:
    matched = _STRUCTURED_READ_FILE_PATTERN.fullmatch(lowered)
    if matched is None:
        return False
    path_value = str(matched.group("path") or "").strip()
    return path_value not in {"", "this", "that", "it", "current", "current file", "file"}


def _build_routing_contract(utterance: str, decision: _ClassificationDecision) -> Dict[str, Any]:
    if decision.intent_class is IntentClass.EXECUTION_ATTEMPT:
        route_target = "execution_boundary"
    elif decision.intent_class is IntentClass.GOVERNED_ACTION_PROPOSAL:
        route_target = "governed_interpreter"
    else:
        route_target = "chat_response"
    fingerprint_source = {
        "utterance": utterance,
        "intent_class": decision.intent_class.value,
        "escalate": decision.escalate,
        "reason": decision.reason,
        "route_target": route_target,
    }
    canonical = json.dumps(fingerprint_source, sort_keys=True, separators=(",", ":"))
    decision_fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "contract_version": "phase27.intent_router.v1",
        "intent_class": decision.intent_class.value,
        "escalate": decision.escalate,
        "reason": decision.reason,
        "route_target": route_target,
        "decision_fingerprint": decision_fingerprint,
        "immutable": True,
    }


def _record_routing_contract(contract: Dict[str, Any]) -> None:
    _INTENT_ROUTING_AUDIT_LOG.append(copy.deepcopy(contract))


def get_intent_routing_audit_log() -> List[Dict[str, Any]]:
    return copy.deepcopy(_INTENT_ROUTING_AUDIT_LOG)


def reset_intent_routing_audit_log() -> None:
    _INTENT_ROUTING_AUDIT_LOG.clear()


def classify_turn_intent(utterance: str) -> Dict[str, Any]:
    normalized = _normalize_utterance(utterance)
    lowered = _compact_text(normalized)

    if not normalized:
        decision = _ClassificationDecision(
            intent_class=IntentClass.AMBIGUOUS_INTENT,
            escalate=False,
            reason="Input is empty after normalization.",
        )
    elif _is_policy_boundary_challenge(lowered):
        decision = _ClassificationDecision(
            intent_class=IntentClass.POLICY_BOUNDARY_CHALLENGE,
            escalate=False,
            reason="Request challenges governance boundaries and is handled in chat-only mode.",
        )
    elif _is_meta_governance_inquiry(lowered):
        decision = _ClassificationDecision(
            intent_class=IntentClass.META_GOVERNANCE_INQUIRY,
            escalate=False,
            reason="Request asks about governance policy or authority and stays chat-only.",
        )
    elif _is_execution_attempt(normalized, lowered):
        decision = _ClassificationDecision(
            intent_class=IntentClass.EXECUTION_ATTEMPT,
            escalate=True,
            reason="Request asks for direct execution and routes to the execution boundary.",
        )
    elif _is_explicit_structured_read_file_request(lowered):
        decision = _ClassificationDecision(
            intent_class=IntentClass.GOVERNED_ACTION_PROPOSAL,
            escalate=True,
            reason="Request is an explicit structured file action proposal and requires governed routing.",
        )
    elif _is_governed_action_proposal(lowered):
        decision = _ClassificationDecision(
            intent_class=IntentClass.GOVERNED_ACTION_PROPOSAL,
            escalate=True,
            reason="Request proposes a governed action and requires approval-gated proposal routing.",
        )
    elif _is_planning_request(lowered):
        decision = _ClassificationDecision(
            intent_class=IntentClass.PLANNING_REQUEST,
            escalate=False,
            reason="Request asks for planning guidance and stays in chat-only mode.",
        )
    elif _is_generative_content_request(lowered):
        decision = _ClassificationDecision(
            intent_class=IntentClass.GENERATIVE_CONTENT_REQUEST,
            escalate=False,
            reason="Request asks for generated content and stays in chat-only mode.",
        )
    elif _is_advisory_request(lowered):
        decision = _ClassificationDecision(
            intent_class=IntentClass.ADVISORY_REQUEST,
            escalate=False,
            reason="Request asks for advice and stays in chat-only mode.",
        )
    elif _is_social_chitchat(lowered):
        decision = _ClassificationDecision(
            intent_class=IntentClass.INFORMATIONAL_QUERY,
            escalate=False,
            reason="Conversational prompt is handled in chat-only informational mode.",
        )
    elif _is_informational_query(normalized, lowered):
        decision = _ClassificationDecision(
            intent_class=IntentClass.INFORMATIONAL_QUERY,
            escalate=False,
            reason="Request asks for information and stays in chat-only mode.",
        )
    elif _is_ambiguous_intent(lowered):
        decision = _ClassificationDecision(
            intent_class=IntentClass.AMBIGUOUS_INTENT,
            escalate=False,
            reason="Request is ambiguous and cannot be escalated without explicit intent.",
        )
    else:
        decision = _ClassificationDecision(
            intent_class=IntentClass.AMBIGUOUS_INTENT,
            escalate=False,
            reason="Request does not match a governed trigger and defaults to ambiguous intent.",
        )

    if decision.intent_class in ESCALATING_INTENTS:
        decision = _ClassificationDecision(
            intent_class=decision.intent_class,
            escalate=True,
            reason=decision.reason,
        )
    elif decision.intent_class in NON_ESCALATING_INTENTS:
        decision = _ClassificationDecision(
            intent_class=decision.intent_class,
            escalate=False,
            reason=decision.reason,
        )

    routing_contract = _build_routing_contract(normalized, decision)
    _record_routing_contract(routing_contract)
    return {
        "intent_class": decision.intent_class.value,
        "escalate": decision.escalate,
        "reason": decision.reason,
        "routing_contract": routing_contract,
        "utterance": normalized,
    }


def _chat_response(utterance: str, intent_class: str) -> str:
    lowered = _compact_text(utterance)
    if intent_class == IntentClass.POLICY_BOUNDARY_CHALLENGE.value:
        return "I can explain policy boundaries, but I cannot bypass governance controls."
    if intent_class == IntentClass.META_GOVERNANCE_INQUIRY.value:
        return "Governance is explicit: intent is classified first, escalation is structured, and execution authority is separate."
    if intent_class == IntentClass.AMBIGUOUS_INTENT.value:
        return "I need a more explicit request. Clarify whether you want information, advice, planning, or a governed action proposal."
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
    return "Share your exact goal and constraints, and I will give concrete steps or options."


def process_conversational_turn(utterance: str) -> Dict[str, Any]:
    """Classify one turn deterministically and choose exactly one immutable route."""
    classification = classify_turn_intent(utterance)
    intent_class = str(classification["intent_class"])
    escalate = bool(classification["escalate"])
    reason = str(classification["reason"])
    normalized = str(classification["utterance"])
    routing_contract = copy.deepcopy(classification["routing_contract"])

    response: Dict[str, Any] = {
        "intent_class": intent_class,
        "escalate": escalate,
        "reason": reason,
        "routing_contract": routing_contract,
    }
    if not escalate:
        response["chat_response"] = _chat_response(normalized, intent_class)
        return response

    response["intent_envelope"] = {
        "utterance": normalized,
        "intent_class": intent_class,
        "escalate": True,
        "reason": reason,
        "originating_turn_id": str(routing_contract.get("decision_fingerprint", "")),
        "routing_contract": routing_contract,
    }
    return response


def run_governed_interpreter(intent_envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Route escalated intents into governed proposal or deterministic refusal boundaries."""
    envelope = dict(intent_envelope or {})
    utterance = _normalize_utterance(str(envelope.get("utterance", "")))
    intent_class = str(envelope.get("intent_class", IntentClass.AMBIGUOUS_INTENT.value))
    if not utterance:
        return {
            "intent": str(envelope.get("intent", "")) or intent_class,
            "governed_result": {
                "type": "execution_rejected",
                "executed": False,
                "message": "Execution rejected: missing utterance in intent envelope.",
                "envelope": envelope,
            },
            "response": "Execution rejected: missing utterance in intent envelope.",
        }

    if intent_class == IntentClass.EXECUTION_ATTEMPT.value:
        refusal_reason = (
            "Execution attempts are deterministically refused at this phase because execution authority is not granted."
        )
        response_text = f"Execution refused: {refusal_reason} Governance citation: {_EXECUTION_REFUSAL_CITATION}."
        governed_result = {
            "type": "execution_rejected",
            "executed": False,
            "message": response_text,
            "refusal_reason": refusal_reason,
            "governance_citation": _EXECUTION_REFUSAL_CITATION,
            "envelope": copy.deepcopy(envelope),
        }
        return {
            "intent": IntentClass.EXECUTION_ATTEMPT.value,
            "governed_result": governed_result,
            "response": response_text,
        }

    if intent_class != IntentClass.GOVERNED_ACTION_PROPOSAL.value:
        response_text = "Routing rejected: non-escalating intent cannot enter governed interpreter."
        return {
            "intent": intent_class,
            "governed_result": {
                "type": "routing_rejected",
                "executed": False,
                "message": response_text,
                "envelope": copy.deepcopy(envelope),
            },
            "response": response_text,
        }

    interpreted = command_interpreter.interpret_utterance(utterance)
    interpreted = interpreted if isinstance(interpreted, dict) else {}
    resolved_intent = str(interpreted.get("intent", "clarify.request_context"))
    resolved_lane = str(interpreted.get("lane", "")).upper()
    originating_turn_id = str(envelope.get("originating_turn_id", "") or "").strip()
    if not originating_turn_id:
        routing_contract = envelope.get("routing_contract", {})
        if isinstance(routing_contract, dict):
            originating_turn_id = str(routing_contract.get("decision_fingerprint", "")).strip()
    if not originating_turn_id:
        originating_turn_id = _build_routing_contract(
            utterance,
            _ClassificationDecision(
                intent_class=IntentClass.GOVERNED_ACTION_PROPOSAL,
                escalate=True,
                reason="Fallback originating turn id derivation.",
            ),
        )["decision_fingerprint"]

    creation = create_proposal(
        intent_class=IntentClass.GOVERNED_ACTION_PROPOSAL.value,
        originating_turn_id=originating_turn_id,
        governance_context={
            "utterance": utterance,
            "resolved_intent": resolved_intent,
            "resolved_lane": resolved_lane,
            "routing_contract": copy.deepcopy(envelope.get("routing_contract", {})),
        },
        expiration_time=None,
    )
    if not creation.ok or creation.proposal is None:
        refusal_text = (
            "Proposal refused: replay or governance validation blocked this proposal. "
            f"Reason: {creation.reason_code}."
        )
        governed_result = {
            "type": "proposal_rejected",
            "executed": False,
            "approved": False,
            "message": refusal_text,
            "reason_code": creation.reason_code,
            "envelope": interpreted if interpreted else copy.deepcopy(envelope),
        }
        return {
            "intent": resolved_intent,
            "governed_result": governed_result,
            "response": refusal_text,
        }

    proposal_artifact = copy.deepcopy(creation.proposal)
    proposal_envelope = {
        "type": "proposal",
        "intent": resolved_intent,
        "lane": resolved_lane,
        "utterance": utterance,
        "requires_approval": True,
        "approved": False,
        "executed": False,
        "routing_contract": copy.deepcopy(envelope.get("routing_contract", {})),
        "proposal_id": str(proposal_artifact.get("proposal_id", "")),
        "state": str(proposal_artifact.get("state", "drafted")),
    }
    response_text = (
        "Governed proposal drafted. Explicit submission and external approval reference are required. "
        "Execution remains disabled."
    )
    governed_result = {
        "type": "proposal",
        "executed": False,
        "approved": False,
        "message": response_text,
        "proposal_state": str(proposal_artifact.get("state", "drafted")),
        "proposal_artifact": proposal_artifact,
        "proposal_reason_code": creation.reason_code,
        "proposal_envelope": proposal_envelope,
        "envelope": interpreted if interpreted else copy.deepcopy(envelope),
    }

    return {
        "intent": resolved_intent,
        "governed_result": governed_result,
        "response": response_text,
    }


def submit_governed_proposal_state(proposal_id: str) -> Dict[str, Any]:
    result = submit_governed_proposal(str(proposal_id))
    return {
        "ok": result.ok,
        "reason_code": result.reason_code,
        "proposal": copy.deepcopy(result.proposal),
    }


def approve_governed_proposal_state(proposal_id: str, approval_reference: str) -> Dict[str, Any]:
    result = approve_governed_proposal(str(proposal_id), approval_reference=str(approval_reference))
    return {
        "ok": result.ok,
        "reason_code": result.reason_code,
        "proposal": copy.deepcopy(result.proposal),
    }


def reject_governed_proposal_state(proposal_id: str, rejection_reason: str | None = None) -> Dict[str, Any]:
    result = reject_governed_proposal(str(proposal_id), rejection_reason=rejection_reason)
    return {
        "ok": result.ok,
        "reason_code": result.reason_code,
        "proposal": copy.deepcopy(result.proposal),
    }


def expire_governed_proposal_state(proposal_id: str, trigger: str = "governance") -> Dict[str, Any]:
    result = expire_governed_proposal(str(proposal_id), trigger=str(trigger))
    return {
        "ok": result.ok,
        "reason_code": result.reason_code,
        "proposal": copy.deepcopy(result.proposal),
    }


def enforce_governed_proposal_expiration_state(proposal_id: str, now_iso: str | None = None) -> Dict[str, Any]:
    result = enforce_governed_proposal_expiration(str(proposal_id), now_iso=now_iso)
    return {
        "ok": result.ok,
        "reason_code": result.reason_code,
        "proposal": copy.deepcopy(result.proposal),
    }


def get_governed_proposal_state(proposal_id: str) -> Dict[str, Any] | None:
    proposal = get_proposal(str(proposal_id))
    if proposal is None:
        return None
    return copy.deepcopy(proposal)


def get_governed_proposal_ledger() -> List[Dict[str, Any]]:
    return copy.deepcopy(get_proposal_ledger())


def reset_governed_proposal_ledger() -> None:
    reset_proposal_ledger()
