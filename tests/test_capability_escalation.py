from v2.core.capability_escalation import (
    CapabilityEscalation,
    explain_selection,
    select_pattern,
)


def test_content_generation_task_routes_to_inert():
    task = {
        "description": "Draft a short onboarding email",
        "deterministic": True,
        "has_predefined_workflow": False,
        "requires_tools": False,
        "requires_iteration": False,
        "mutates_state": False,
    }
    assert select_pattern(task) == CapabilityEscalation.INERT_LLM_CONTENT_GENERATION


def test_fixed_predefined_workflow_routes_to_structured_workflow():
    task = {
        "description": "Run standard release checklist",
        "deterministic": True,
        "has_predefined_workflow": True,
        "requires_tools": False,
        "requires_iteration": True,
        "mutates_state": False,
    }
    assert select_pattern(task) == CapabilityEscalation.STRUCTURED_WORKFLOWS


def test_task_requiring_tools_routes_to_tool_augmented_reasoning():
    task = {
        "description": "Collect metrics from monitoring API",
        "deterministic": False,
        "requires_tools": True,
        "tool_count": 1,
        "dynamic_environment": False,
        "requires_iteration": False,
        "mutates_state": False,
    }
    assert select_pattern(task) == CapabilityEscalation.TOOL_AUGMENTED_REASONING


def test_legitimate_agent_loop_routes_to_guarded_agentic_loops():
    task = {
        "description": "Iteratively diagnose flaky integration tests",
        "deterministic": False,
        "requires_tools": True,
        "tool_count": 2,
        "dynamic_environment": True,
        "requires_iteration": True,
        "mutates_state": False,
    }
    assert select_pattern(task) == CapabilityEscalation.GUARDED_AGENTIC_LOOPS

    trace = explain_selection(task)
    assert "visible" in trace.rationale.lower() or "guarded" in trace.rationale.lower()


def test_mutating_or_high_impact_request_routes_to_authorized_execution():
    task = {
        "description": "Delete temp files and restart service",
        "deterministic": True,
        "requires_tools": True,
        "mutates_state": True,
        "requires_authorized_execution": True,
    }
    assert select_pattern(task) == CapabilityEscalation.AUTHORIZED_EXECUTION

