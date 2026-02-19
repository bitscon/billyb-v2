"""Phase 32 advisory/planning capability (non-executing)."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List

ADVISORY_INTENT = "advisory_request"
PLANNING_INTENT = "planning_request"
EXECUTION_INTENT = "execution_attempt"
_ALLOWED_INTENTS = {ADVISORY_INTENT, PLANNING_INTENT}

_EXECUTION_TERMS = ("execute", "run", "deploy", "apply", "immediately", "right now", "/exec ")
_IMPLICIT_ACTION_TERMS = (
    "create",
    "write",
    "delete",
    "remove",
    "restart",
    "start",
    "stop",
    "modify",
    "refactor",
)
_PLANNING_TERMS = ("plan", "steps", "strategy", "advice", "recommend", "how should")
_EXPLICIT_ESCALATION_TERMS = (
    "escalate",
    "request approval",
    "create proposal",
    "submit proposal",
    "route to governance",
)
_SERVICE_HINTS = ("nginx", "postgres", "redis", "n8n", "apache", "mysql")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _extract_service_name(normalized: str) -> str:
    match = re.search(r"\bservice\s+([a-z0-9_.-]+)\b", normalized)
    if match is not None:
        return str(match.group(1))
    for name in _SERVICE_HINTS:
        if re.search(rf"\b{re.escape(name)}\b", normalized):
            return name
    return "target-service"


def _infer_escalation_requested(normalized: str, explicit_override: bool | None) -> bool:
    if explicit_override is True:
        return True
    if explicit_override is False:
        return False
    return _contains_any(normalized, _EXPLICIT_ESCALATION_TERMS)


def _is_execution_attempt(intent_class: str, normalized: str) -> bool:
    return str(intent_class) == EXECUTION_INTENT or _contains_any(normalized, _EXECUTION_TERMS)


def _is_implicit_action_request(intent_class: str, normalized: str) -> bool:
    if str(intent_class) in _ALLOWED_INTENTS:
        return False
    if _contains_any(normalized, _PLANNING_TERMS):
        return False
    return _contains_any(normalized, _IMPLICIT_ACTION_TERMS)


def _planning_steps(normalized: str) -> List[str]:
    if "service" in normalized or any(name in normalized for name in _SERVICE_HINTS):
        service = _extract_service_name(normalized)
        return [
            f"Define the target state and success criteria for `{service}`.",
            f"Inspect current `{service}` state manually before any change.",
            f"Apply the smallest reversible change first and verify impact.",
            f"Document observed outcomes and decide whether to proceed.",
        ]
    if "git" in normalized or "repo" in normalized or "repository" in normalized:
        return [
            "Define the exact repository objective and acceptance criteria.",
            "Inspect current branch, status, and pending diffs manually.",
            "Prepare minimal changes in a reversible sequence.",
            "Verify diffs and tests manually before any governed action request.",
        ]
    if "file" in normalized or "directory" in normalized or "folder" in normalized:
        return [
            "Define exact file-system scope and intended final state.",
            "Inspect current files and create a manual backup plan.",
            "Draft minimal, reversible edits in explicit order.",
            "Verify results manually and capture rollback checkpoints.",
        ]
    return [
        "Define objective, constraints, and success criteria.",
        "Inspect current state and identify reversible first moves.",
        "Plan a minimal-step sequence with checkpoints.",
        "Verify outcomes after each step and stop on unexpected drift.",
    ]


def _suggested_commands(normalized: str) -> List[str]:
    if "service" in normalized or any(name in normalized for name in _SERVICE_HINTS):
        service = _extract_service_name(normalized)
        return [
            f"systemctl status {service}",
            f"journalctl -u {service} --no-pager -n 100",
            f"systemctl cat {service}",
        ]
    if "git" in normalized or "repo" in normalized or "repository" in normalized:
        return [
            "git status --short",
            "git branch --show-current",
            "git diff --stat",
        ]
    if "file" in normalized or "directory" in normalized or "folder" in normalized:
        return [
            "ls -la <target_path>",
            "cp -a <target_path> <target_path>.bak",
            "diff -ruN <target_path>.bak <target_path>",
        ]
    return [
        "echo \"define target and constraints before applying changes\"",
        "printf '%s\\n' \"checkpoint: inspected current state\"",
        "printf '%s\\n' \"checkpoint: verified expected outcome\"",
    ]


def _risk_notes(normalized: str) -> List[str]:
    notes = [
        "State drift risk: current environment may differ from assumptions.",
        "Reversibility risk: large or batched changes are harder to unwind.",
    ]
    if "service" in normalized:
        notes.append("Availability risk: service changes may cause user-visible downtime.")
    if "git" in normalized or "repo" in normalized:
        notes.append("History risk: incorrect branch or push target can propagate bad changes.")
    if "file" in normalized or "directory" in normalized:
        notes.append("Data risk: file modifications without backups can cause irreversible loss.")
    return notes


def _assumptions(normalized: str, intent_class: str) -> List[str]:
    assumptions = [
        "You will manually review each step before acting.",
        "Commands are examples and require your environment-specific edits.",
    ]
    if intent_class == PLANNING_INTENT:
        assumptions.append("You requested structured planning guidance rather than direct execution.")
    if intent_class == ADVISORY_INTENT:
        assumptions.append("You requested decision support and tradeoff analysis.")
    if "service" in normalized:
        assumptions.append("Target service identity is correct and accessible from your shell session.")
    return assumptions


def _rollback_guidance(normalized: str) -> List[str]:
    guidance = [
        "Capture a before-state snapshot before any manual action.",
        "Use one-change-at-a-time sequencing with verification checkpoints.",
        "Stop immediately if observed state differs from expected state.",
    ]
    if "git" in normalized or "repo" in normalized:
        guidance.append("Keep rollback options explicit (revert or branch reset) before sharing changes.")
    if "file" in normalized or "directory" in normalized:
        guidance.append("Retain a backup copy until post-change verification completes.")
    return guidance


def _tradeoff_options(normalized: str, intent_class: str) -> List[Dict[str, str]]:
    if "service" in normalized or any(name in normalized for name in _SERVICE_HINTS):
        return [
            {
                "title": "Conservative rollout",
                "benefits": "Minimizes disruption by validating each checkpoint before moving forward.",
                "risks": "Can take longer and may delay non-critical improvements.",
                "effort": "medium",
                "alignment": "Fits reliability-first goals and strict operational constraints.",
            },
            {
                "title": "Balanced rollout",
                "benefits": "Balances speed and safety with reversible increments.",
                "risks": "Still depends on accurate checkpoint criteria and operator discipline.",
                "effort": "medium",
                "alignment": "Fits mixed goals where uptime and delivery speed both matter.",
            },
            {
                "title": "Fast-track rollout",
                "benefits": "Delivers changes quickly when urgency is high.",
                "risks": "Higher blast radius and rollback pressure if assumptions are wrong.",
                "effort": "low",
                "alignment": "Fits urgent goals only when risk tolerance is explicitly high.",
            },
        ]

    if "git" in normalized or "repo" in normalized or "repository" in normalized:
        return [
            {
                "title": "Small PR sequence",
                "benefits": "Improves review quality and rollback clarity.",
                "risks": "More coordination overhead across multiple changesets.",
                "effort": "medium",
                "alignment": "Fits quality-focused goals and conservative change constraints.",
            },
            {
                "title": "Single focused PR",
                "benefits": "Keeps momentum while preserving a clear review boundary.",
                "risks": "Can become harder to reason about if scope expands mid-flight.",
                "effort": "low",
                "alignment": "Fits balanced goals for speed with manageable risk.",
            },
            {
                "title": "Bulk refactor pass",
                "benefits": "Can quickly reduce widespread technical debt.",
                "risks": "High review burden and elevated regression risk.",
                "effort": "high",
                "alignment": "Fits debt-reduction goals only when delivery pressure is low.",
            },
        ]

    if "file" in normalized or "directory" in normalized or "folder" in normalized:
        return [
            {
                "title": "Backup-first edit",
                "benefits": "Maximizes reversibility and reduces data-loss risk.",
                "risks": "Adds setup overhead before making progress.",
                "effort": "medium",
                "alignment": "Fits safety and recoverability constraints.",
            },
            {
                "title": "Targeted minimal edit",
                "benefits": "Fast path for a narrow objective with minimal scope drift.",
                "risks": "Can miss adjacent issues if context is too narrow.",
                "effort": "low",
                "alignment": "Fits speed-oriented goals with bounded scope.",
            },
            {
                "title": "Broader cleanup pass",
                "benefits": "Improves long-term maintainability in one pass.",
                "risks": "Introduces more change surface and verification cost.",
                "effort": "high",
                "alignment": "Fits maintainability goals when change budget is available.",
            },
        ]

    default_alignment = (
        "Fits advisory decision support."
        if intent_class == ADVISORY_INTENT
        else "Fits planning conversations with explicit constraints."
    )
    return [
        {
            "title": "Low-risk baseline",
            "benefits": "Prioritizes predictability and reduces downside exposure.",
            "risks": "May underperform on speed or ambition.",
            "effort": "medium",
            "alignment": f"{default_alignment} Best for conservative execution posture.",
        },
        {
            "title": "Balanced path",
            "benefits": "Balances progress velocity with explicit checkpoints.",
            "risks": "Tradeoffs require active judgment at each checkpoint.",
            "effort": "medium",
            "alignment": f"{default_alignment} Best for mixed objectives.",
        },
        {
            "title": "Aggressive push",
            "benefits": "Maximizes short-term momentum.",
            "risks": "Higher chance of rework, drift, or rollback complexity.",
            "effort": "low",
            "alignment": f"{default_alignment} Best when speed clearly outweighs stability.",
        },
    ]


def _base_response(intent_class: str) -> Dict[str, Any]:
    return {
        "mode": "advisory",
        "execution_enabled": False,
        "advisory_only": True,
        "intent_class": str(intent_class),
        "commands_not_executed": True,
    }


def _attach_fingerprint(payload: Dict[str, Any], normalized_utterance: str, escalation_requested: bool) -> Dict[str, Any]:
    framed = dict(payload)
    framed["framing_fingerprint"] = _digest(
        {
            "intent_class": framed.get("intent_class"),
            "normalized_utterance": normalized_utterance,
            "status": framed.get("status"),
            "plan_steps": framed.get("plan_steps", []),
            "suggested_commands": framed.get("suggested_commands", []),
            "risk_notes": framed.get("risk_notes", []),
            "assumptions": framed.get("assumptions", []),
            "rollback_guidance": framed.get("rollback_guidance", []),
            "options": framed.get("options", []),
            "escalation": framed.get("escalation", {}),
            "explicit_escalation_requested": bool(escalation_requested),
        }
    )
    return framed


def build_advisory_plan(
    *,
    utterance: str,
    intent_class: str,
    explicit_escalation_requested: bool | None = None,
) -> Dict[str, Any]:
    """Generate deterministic, human-facing advisory/planning output.

    Non-negotiable guarantees:
    - no execution
    - no tool invocation
    - no proposal auto-creation
    - no hidden escalation
    """

    normalized = _normalize(utterance)
    escalation_requested = _infer_escalation_requested(normalized, explicit_escalation_requested)
    response = _base_response(intent_class)

    if _is_execution_attempt(intent_class, normalized):
        response.update(
            {
                "status": "refused",
                "message": (
                    "Execution attempts are out of scope in advisory mode. "
                    "No commands were run; request governed escalation explicitly if needed."
                ),
                "plan_steps": [],
                "suggested_commands": [],
                "risk_notes": ["Execution is disabled in advisory mode."],
                "assumptions": ["No execution authority is granted in this phase."],
                "rollback_guidance": ["No rollback needed because nothing was executed."],
                "options": [],
                "escalation": {
                    "explicitly_requested": bool(escalation_requested),
                    "escalation_prepared": bool(escalation_requested),
                    "next_step": "request_governed_proposal" if escalation_requested else "none",
                },
            }
        )
        return _attach_fingerprint(response, normalized, escalation_requested)

    if _is_implicit_action_request(intent_class, normalized):
        response.update(
            {
                "status": "clarification_required",
                "message": (
                    "Request implies action. I can provide advisory planning now, "
                    "or you can explicitly request governed escalation."
                ),
                "plan_steps": [],
                "suggested_commands": [],
                "risk_notes": ["Implicit action requests are fail-closed in advisory mode."],
                "assumptions": ["No side effects occur without explicit governed routing."],
                "rollback_guidance": ["No rollback needed because nothing was executed."],
                "options": [],
                "escalation": {
                    "explicitly_requested": bool(escalation_requested),
                    "escalation_prepared": bool(escalation_requested),
                    "next_step": "request_governed_proposal" if escalation_requested else "none",
                },
            }
        )
        return _attach_fingerprint(response, normalized, escalation_requested)

    if str(intent_class) not in _ALLOWED_INTENTS:
        response.update(
            {
                "status": "clarification_required",
                "message": (
                    "Advisory mode accepts `advisory_request` or `planning_request`. "
                    "Please restate your request in one of those forms."
                ),
                "plan_steps": [],
                "suggested_commands": [],
                "risk_notes": ["Unsupported advisory intent classification."],
                "assumptions": ["No escalation occurs unless explicitly requested."],
                "rollback_guidance": ["No rollback needed because nothing was executed."],
                "options": [],
                "escalation": {
                    "explicitly_requested": bool(escalation_requested),
                    "escalation_prepared": False,
                    "next_step": "none",
                },
            }
        )
        return _attach_fingerprint(response, normalized, escalation_requested)

    commands = [f"NOT EXECUTED: {item}" for item in _suggested_commands(normalized)]
    response.update(
        {
            "status": "advisory_ready",
            "message": (
                "Advisory plan prepared. Commands are suggestions only and were NOT EXECUTED."
            ),
            "plan_steps": _planning_steps(normalized),
            "suggested_commands": commands,
            "risk_notes": _risk_notes(normalized),
            "assumptions": _assumptions(normalized, str(intent_class)),
            "rollback_guidance": _rollback_guidance(normalized),
            "options": _tradeoff_options(normalized, str(intent_class)),
            "escalation": {
                "explicitly_requested": bool(escalation_requested),
                "escalation_prepared": bool(escalation_requested),
                "next_step": "request_governed_proposal" if escalation_requested else "none",
            },
        }
    )
    return _attach_fingerprint(response, normalized, escalation_requested)
