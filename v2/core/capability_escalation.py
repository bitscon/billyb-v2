"""Capability escalation selection for Billy task routing.

This module encodes a conservative strategy:
- prefer deterministic workflows over agentic loops
- avoid autonomy unless feedback-driven iteration is necessary
- require explicit authorized execution for mutating side effects
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class CapabilityEscalation(str, Enum):
    INERT_LLM_CONTENT_GENERATION = "inert_llm_content_generation"
    STRUCTURED_WORKFLOWS = "structured_workflows"
    TOOL_AUGMENTED_REASONING = "tool_augmented_reasoning"
    GUARDED_AGENTIC_LOOPS = "guarded_agentic_loops"
    AUTHORIZED_EXECUTION = "authorized_execution"


@dataclass(frozen=True)
class TaskProfile:
    description: str
    deterministic: bool = True
    has_predefined_workflow: bool = False
    requires_tools: bool = False
    tool_count: int = 0
    dynamic_environment: bool = False
    requires_iteration: bool = False
    mutates_state: bool = False
    requires_authorized_execution: bool = False


@dataclass(frozen=True)
class SelectionTrace:
    selected: CapabilityEscalation
    rationale: str


def _as_profile(task: TaskProfile | Mapping[str, Any]) -> TaskProfile:
    if isinstance(task, TaskProfile):
        return task
    return TaskProfile(
        description=str(task.get("description", "")),
        deterministic=bool(task.get("deterministic", True)),
        has_predefined_workflow=bool(task.get("has_predefined_workflow", False)),
        requires_tools=bool(task.get("requires_tools", False)),
        tool_count=int(task.get("tool_count", 0) or 0),
        dynamic_environment=bool(task.get("dynamic_environment", False)),
        requires_iteration=bool(task.get("requires_iteration", False)),
        mutates_state=bool(task.get("mutates_state", False)),
        requires_authorized_execution=bool(task.get("requires_authorized_execution", False)),
    )


def explain_selection(task: TaskProfile | Mapping[str, Any]) -> SelectionTrace:
    """Return pattern selection and rationale for auditability."""
    profile = _as_profile(task)

    needs_tools = profile.requires_tools or profile.tool_count > 0
    needs_authorized_execution = profile.requires_authorized_execution or profile.mutates_state

    if needs_authorized_execution:
        return SelectionTrace(
            selected=CapabilityEscalation.AUTHORIZED_EXECUTION,
            rationale=(
                "Task mutates state or explicitly requests execution authority; "
                "route through governed approval and authorized execution only."
            ),
        )

    if needs_tools and profile.dynamic_environment and profile.requires_iteration:
        return SelectionTrace(
            selected=CapabilityEscalation.GUARDED_AGENTIC_LOOPS,
            rationale=(
                "Task requires tools plus feedback-driven iteration in a dynamic environment; "
                "use guarded agentic loops with visible planning and strict limits."
            ),
        )

    if needs_tools:
        return SelectionTrace(
            selected=CapabilityEscalation.TOOL_AUGMENTED_REASONING,
            rationale=(
                "Task needs external tools but not autonomous loops; "
                "use bounded tool-augmented reasoning with minimal tool scope."
            ),
        )

    if profile.has_predefined_workflow:
        return SelectionTrace(
            selected=CapabilityEscalation.STRUCTURED_WORKFLOWS,
            rationale=(
                "Task matches a fixed sequence; "
                "use deterministic workflow execution instead of agent autonomy."
            ),
        )

    if profile.deterministic and profile.requires_iteration:
        return SelectionTrace(
            selected=CapabilityEscalation.STRUCTURED_WORKFLOWS,
            rationale=(
                "Task is repeatable and deterministic; "
                "use prompt chaining/orchestrator-worker workflows rather than agent loops."
            ),
        )

    return SelectionTrace(
        selected=CapabilityEscalation.INERT_LLM_CONTENT_GENERATION,
        rationale=(
            "Task is content-only with no required tools or side effects; "
            "keep execution inert."
        ),
    )


def select_pattern(task: TaskProfile | Mapping[str, Any]) -> CapabilityEscalation:
    """Select the minimal viable capability pattern for a task."""
    return explain_selection(task).selected

