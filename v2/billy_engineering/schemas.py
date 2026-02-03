from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

PLAN_REQUIRED_PHRASES = [
    "problem statement",
    "constraints",
    "non-goals",
    "proposed approach",
]

VERIFY_REQUIRED_PHRASES = [
    "what was verified",
    "how it was verified",
    "what was not verified",
    "pass",
    "fail",
]

FORBIDDEN_ARTIFACT_TOKENS = [
    "TODO",
    "TBD",
    "PLACEHOLDER",
    "<<",
    ">>",
]


@dataclass
class ValidationResult:
    ok: bool
    errors: List[str]


def _require_phrases(text: str, phrases: List[str]) -> List[str]:
    lower = text.lower()
    missing = [p for p in phrases if p not in lower]
    return missing


def validate_plan(text: str) -> ValidationResult:
    errors: List[str] = []
    if not text.strip():
        errors.append("Plan is empty.")
    missing = _require_phrases(text, PLAN_REQUIRED_PHRASES)
    if missing:
        errors.append(f"Plan missing required sections: {', '.join(missing)}")
    return ValidationResult(ok=not errors, errors=errors)


def validate_verify(text: str) -> ValidationResult:
    errors: List[str] = []
    if not text.strip():
        errors.append("Verification is empty.")
    missing = _require_phrases(text, VERIFY_REQUIRED_PHRASES)
    if missing:
        errors.append(f"Verification missing required sections: {', '.join(missing)}")
    return ValidationResult(ok=not errors, errors=errors)


def validate_artifact(text: str) -> ValidationResult:
    errors: List[str] = []
    if not text.strip():
        errors.append("Artifact is empty.")
    for token in FORBIDDEN_ARTIFACT_TOKENS:
        if token in text:
            errors.append(f"Artifact contains forbidden token: {token}")
    return ValidationResult(ok=not errors, errors=errors)
