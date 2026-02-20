"""Deterministic ACI intent routing and phase gatekeeping.

This module is intentionally side-effect free:
- no execution
- no planning
- no artifact creation
- no state mutation
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Sequence


class INTENT_CLASS(str, Enum):
    CONVERSATIONAL = "CONVERSATIONAL"
    INSPECT = "INSPECT"
    PLAN = "PLAN"
    GOVERNANCE_ISSUANCE = "GOVERNANCE_ISSUANCE"
    EXECUTION_SEEKING = "EXECUTION_SEEKING"
    AMBIGUOUS = "AMBIGUOUS"
    FORBIDDEN = "FORBIDDEN"


INTENT_CONFIDENCE_THRESHOLD = 0.68
ACI_MIN_PHASE = 27
ACI_MAX_PHASE = 69


@dataclass(frozen=True)
class IntentRoutingResult:
    intent_class: INTENT_CLASS
    confidence: float
    rationale: str


@dataclass(frozen=True)
class PhaseTransition:
    next_phase: int
    artifact_type: str
    allowed_intents: tuple[INTENT_CLASS, ...]


@dataclass(frozen=True)
class LadderState:
    current_phase: int
    min_phase: int = ACI_MIN_PHASE
    max_phase: int = ACI_MAX_PHASE


@dataclass(frozen=True)
class PhaseGatekeeperResult:
    admissible: bool
    allowed_next_artifact: str | None
    deterministic_reason_code: str
    allowed_alternatives: List[str]


_PHASE_CONTRACTS: Dict[int, str] = {
    27: "conversational_frontend_gate.v1",
    28: "inspection_capabilities_gate.v1",
    29: "inspection_result_binding.v1",
    30: "delegation_envelope.v1",
    31: "synthesis_output.v1",
    32: "action_plan_envelope.v1",
    33: "human_approval.v1",
    34: "approval_audit_record.v1",
    35: "revocation_record.v1",
    36: "lineage_record.v1",
    37: "execution_eligibility_record.v1",
    38: "execution_readiness_envelope.v1",
    39: "execution_authorization_record.v1",
    40: "execution_commitment_envelope.v1",
    41: "execution_invocation_envelope.v1",
    42: "execution_runtime_interface.v1",
    43: "execution_enablement_switch.v1",
    44: "execution_capability.v1",
    45: "execution_decision.v1",
    46: "execution_intent_seal.v1",
    47: "pre_execution_validation.v1",
    48: "execution_arming.v1",
    49: "execution_attempt.v1",
    50: "executor_interface.v1",
    51: "external_executor_trust.v1",
    52: "executor_result.v1",
    53: "human_execution_review.v1",
    54: "human_replanning_intent.v1",
    55: "planning_context.v1",
    56: "planning_output.v1",
    57: "planning_session.v1",
    58: "plan_acceptance.v1",
    59: "plan_approval.v1",
    60: "plan_authorization.v1",
    61: "execution_scope_binding.v1",
    62: "execution_preconditions.v1",
    63: "execution_readiness.v1",
    64: "readiness_attestation.v1",
    65: "execution_arming_authorization.v1",
    66: "execution_arming_state.v1",
    67: "execution_eligibility.v1",
    68: "execution_attempt.v1",
    69: "execution_handoff.v1",
}

_FORBIDDEN_PATTERNS = (
    r"\byou decide\b",
    r"\byou choose\b",
    r"\bdecide for me\b",
    r"\bdo whatever you think\b",
    r"\bwithout approval\b",
    r"\bskip approval\b",
    r"\bbypass\b",
    r"\bignore (?:the )?(?:gate|gates|governance|protocol)\b",
    r"\bassume (?:permission|authority)\b",
    r"\bact autonomously\b",
)

_EXECUTION_SEEKING_PATTERNS = (
    r"\bexecute\b",
    r"\brun\b",
    r"\bdeploy\b",
    r"\binvoke\b",
    r"\bstart\b",
    r"\bstop\b",
    r"\brestart\b",
    r"\bapply now\b",
    r"\bship it\b",
)

_INSPECT_PATTERNS = (
    r"\binspect\b",
    r"\bread\b",
    r"\bshow\b",
    r"\bview\b",
    r"\blocate\b",
    r"\bstatus\b",
    r"\bwhere is\b",
    r"\bfind\b",
)

_PLAN_PATTERNS = (
    r"\bplan\b",
    r"\bdraft\b",
    r"\bpropose\b",
    r"\boutline\b",
    r"\bdesign\b",
)

_GOVERNANCE_PATTERNS = (
    r"\bapprove\b",
    r"\bauthorize\b",
    r"\battest\b",
    r"\bissue\b",
    r"\bissuance\b",
    r"\bconfirm issuance\b",
    r"\brevoke\b",
    r"\bsupersede\b",
    r"\bbind\b",
    r"\bseal\b",
    r"\bhandoff\b",
)

_CONVERSATIONAL_PATTERNS = (
    r"^\s*(hi|hello|hey)\b",
    r"\bwhat\b",
    r"\bwho\b",
    r"\bwhy\b",
    r"\bhow\b",
    r"\bthanks?\b",
    r"\bexplain\b",
    r"\btell me\b",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _count_matches(patterns: Sequence[str], normalized_text: str) -> int:
    return sum(1 for pattern in patterns if re.search(pattern, normalized_text))


def _is_forbidden(normalized_text: str) -> str | None:
    for pattern in _FORBIDDEN_PATTERNS:
        if re.search(pattern, normalized_text):
            return pattern
    return None


def _allowed_intents_for_next_phase(next_phase: int) -> tuple[INTENT_CLASS, ...]:
    if 28 <= next_phase <= 31:
        return (INTENT_CLASS.INSPECT, INTENT_CLASS.PLAN, INTENT_CLASS.GOVERNANCE_ISSUANCE)
    if 32 <= next_phase <= 38:
        return (INTENT_CLASS.PLAN, INTENT_CLASS.GOVERNANCE_ISSUANCE)
    if 39 <= next_phase <= 69:
        return (INTENT_CLASS.GOVERNANCE_ISSUANCE,)
    return tuple()


def derive_admissible_phase_transitions(ladder_state: LadderState) -> List[PhaseTransition]:
    current = ladder_state.current_phase
    if current < ladder_state.min_phase or current > ladder_state.max_phase:
        return []

    next_phase = current + 1
    if next_phase > ladder_state.max_phase:
        return []

    artifact = _PHASE_CONTRACTS.get(next_phase)
    if artifact is None:
        return []

    return [
        PhaseTransition(
            next_phase=next_phase,
            artifact_type=artifact,
            allowed_intents=_allowed_intents_for_next_phase(next_phase),
        )
    ]


def route_intent(
    raw_utterance: str,
    current_phase: int,
    admissible_phase_transitions: Sequence[str],
    confidence_threshold: float = INTENT_CONFIDENCE_THRESHOLD,
) -> IntentRoutingResult:
    normalized = _normalize(raw_utterance)
    if not normalized:
        return IntentRoutingResult(
            intent_class=INTENT_CLASS.AMBIGUOUS,
            confidence=0.0,
            rationale="Empty utterance cannot be deterministically classified.",
        )

    forbidden_match = _is_forbidden(normalized)
    if forbidden_match is not None:
        return IntentRoutingResult(
            intent_class=INTENT_CLASS.FORBIDDEN,
            confidence=0.99,
            rationale=f"Detected forbidden authority leakage pattern `{forbidden_match}`.",
        )

    scores: Dict[INTENT_CLASS, int] = {
        INTENT_CLASS.EXECUTION_SEEKING: _count_matches(_EXECUTION_SEEKING_PATTERNS, normalized),
        INTENT_CLASS.INSPECT: _count_matches(_INSPECT_PATTERNS, normalized),
        INTENT_CLASS.PLAN: _count_matches(_PLAN_PATTERNS, normalized),
        INTENT_CLASS.GOVERNANCE_ISSUANCE: _count_matches(_GOVERNANCE_PATTERNS, normalized),
        INTENT_CLASS.CONVERSATIONAL: _count_matches(_CONVERSATIONAL_PATTERNS, normalized),
    }

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_class, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0

    if best_score <= 0:
        return IntentRoutingResult(
            intent_class=INTENT_CLASS.AMBIGUOUS,
            confidence=0.45,
            rationale="No deterministic intent signals detected; defaulting to AMBIGUOUS.",
        )

    if best_score == second_score and best_score > 0:
        return IntentRoutingResult(
            intent_class=INTENT_CLASS.AMBIGUOUS,
            confidence=0.55,
            rationale="Competing intent signals with equal score; deterministic tie-break defaults to AMBIGUOUS.",
        )

    base_confidence = {
        INTENT_CLASS.EXECUTION_SEEKING: 0.94,
        INTENT_CLASS.GOVERNANCE_ISSUANCE: 0.84,
        INTENT_CLASS.PLAN: 0.82,
        INTENT_CLASS.INSPECT: 0.80,
        INTENT_CLASS.CONVERSATIONAL: 0.74,
    }[best_class]
    confidence = min(1.0, base_confidence + (0.03 * max(0, best_score - 1)))

    if best_class in (INTENT_CLASS.INSPECT, INTENT_CLASS.PLAN, INTENT_CLASS.GOVERNANCE_ISSUANCE):
        if not admissible_phase_transitions:
            confidence = max(0.0, confidence - 0.15)
            rationale = (
                "Intent signal detected, but no admissible phase transitions are available from ladder state."
            )
        else:
            rationale = (
                f"Detected `{best_class.value}` intent from deterministic phrase match set "
                f"at phase {current_phase} with {len(admissible_phase_transitions)} admissible transition(s)."
            )
    else:
        rationale = f"Detected `{best_class.value}` intent from deterministic phrase match set."

    if confidence < confidence_threshold:
        return IntentRoutingResult(
            intent_class=INTENT_CLASS.AMBIGUOUS,
            confidence=round(confidence, 2),
            rationale=(
                f"Confidence {confidence:.2f} below threshold {confidence_threshold:.2f}; "
                "defaulting to AMBIGUOUS."
            ),
        )

    return IntentRoutingResult(
        intent_class=best_class,
        confidence=round(confidence, 2),
        rationale=rationale,
    )


def phase_gatekeeper(
    intent_class: INTENT_CLASS,
    current_phase: int,
    ladder_state: LadderState,
) -> PhaseGatekeeperResult:
    transitions = derive_admissible_phase_transitions(ladder_state)
    transition = transitions[0] if transitions else None
    alternatives = [t.artifact_type for t in transitions]

    if intent_class is INTENT_CLASS.FORBIDDEN:
        return PhaseGatekeeperResult(
            admissible=False,
            allowed_next_artifact=None,
            deterministic_reason_code="FORBIDDEN_INTENT_AUTHORITY_LEAKAGE",
            allowed_alternatives=alternatives,
        )

    if intent_class is INTENT_CLASS.AMBIGUOUS:
        return PhaseGatekeeperResult(
            admissible=False,
            allowed_next_artifact=None,
            deterministic_reason_code="AMBIGUOUS_INTENT",
            allowed_alternatives=alternatives,
        )

    if intent_class is INTENT_CLASS.EXECUTION_SEEKING:
        return PhaseGatekeeperResult(
            admissible=False,
            allowed_next_artifact=None,
            deterministic_reason_code="EXECUTION_SEEKING_FORBIDDEN",
            allowed_alternatives=alternatives,
        )

    if intent_class is INTENT_CLASS.CONVERSATIONAL:
        return PhaseGatekeeperResult(
            admissible=False,
            allowed_next_artifact=None,
            deterministic_reason_code="CONVERSATIONAL_NO_GOVERNANCE_ACTION",
            allowed_alternatives=alternatives,
        )

    if transition is None:
        return PhaseGatekeeperResult(
            admissible=False,
            allowed_next_artifact=None,
            deterministic_reason_code="NO_ADMISSIBLE_PHASE_TRANSITION",
            allowed_alternatives=[],
        )

    if intent_class not in transition.allowed_intents:
        return PhaseGatekeeperResult(
            admissible=False,
            allowed_next_artifact=None,
            deterministic_reason_code="INTENT_NOT_ADMISSIBLE_AT_CURRENT_PHASE",
            allowed_alternatives=alternatives,
        )

    return PhaseGatekeeperResult(
        admissible=True,
        allowed_next_artifact=transition.artifact_type,
        deterministic_reason_code="ADMISSIBLE_NEXT_ARTIFACT_AVAILABLE",
        allowed_alternatives=[],
    )


def build_response_envelope(
    routing: IntentRoutingResult,
    gate: PhaseGatekeeperResult,
    *,
    current_phase: int,
) -> Dict[str, Any]:
    if routing.intent_class is INTENT_CLASS.AMBIGUOUS:
        return {
            "type": "clarification",
            "ambiguity": routing.rationale,
            "options": [
                "State whether you want inspection, planning, or governance issuance.",
                f"Current phase is {current_phase}; specify a single protocol goal.",
            ],
        }

    if gate.admissible and gate.allowed_next_artifact is not None:
        return {
            "type": "proposal",
            "next_artifact": gate.allowed_next_artifact,
            "reason": (
                f"Intent `{routing.intent_class.value}` is admissible at phase {current_phase}; "
                f"next artifact is `{gate.allowed_next_artifact}`."
            ),
            "question": "Shall I prepare this?",
        }

    if gate.deterministic_reason_code == "AMBIGUOUS_INTENT":
        return {
            "type": "clarification",
            "ambiguity": "Intent is ambiguous for deterministic phase gating.",
            "options": [
                "Request inspection intent explicitly.",
                "Request planning intent explicitly.",
                "Request governance issuance intent explicitly.",
            ],
        }

    return {
        "type": "refusal",
        "reason_code": gate.deterministic_reason_code,
        "explanation": (
            f"Intent `{routing.intent_class.value}` is not admissible at phase {current_phase}. "
            f"{routing.rationale}"
        ),
        "allowed_alternatives": gate.allowed_alternatives,
    }
