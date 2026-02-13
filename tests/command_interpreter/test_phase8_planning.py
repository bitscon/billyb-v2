import pytest

import v2.core.command_interpreter as interpreter


def _set_flags(
    *,
    phase3: bool,
    phase4: bool,
    phase4_explain: bool,
    phase5: bool,
    phase8: bool,
    approval_mode: str = "step",
) -> None:
    interpreter.set_phase3_enabled(phase3)
    interpreter.set_phase4_enabled(phase4)
    interpreter.set_phase4_explanation_enabled(phase4_explain)
    interpreter.set_phase5_enabled(phase5)
    interpreter.set_phase8_enabled(phase8)
    interpreter.set_phase8_approval_mode(approval_mode)


def _multi_step_request() -> str:
    return "create an empty text file in your home directory and create a project note"


def _teardown() -> None:
    _set_flags(
        phase3=False,
        phase4=False,
        phase4_explain=False,
        phase5=False,
        phase8=False,
        approval_mode="step",
    )
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()


def test_plan_construction_correctness():
    _set_flags(
        phase3=False,
        phase4=True,
        phase4_explain=False,
        phase5=True,
        phase8=True,
        approval_mode="step",
    )
    try:
        envelope = interpreter.interpret_utterance(_multi_step_request())
        plan = interpreter.build_execution_plan(envelope)

        assert plan.intent.startswith("plan.")
        assert len(plan.steps) == 2
        assert [step.step_id for step in plan.steps] == ["step-1", "step-2"]
        assert [step.tool_contract.intent for step in plan.steps] == [
            "plan.create_empty_file",
            "plan.user_action_request",
        ]
    finally:
        _teardown()


def test_plan_builder_fails_for_unmappable_step():
    _set_flags(
        phase3=False,
        phase4=True,
        phase4_explain=False,
        phase5=True,
        phase8=True,
        approval_mode="step",
    )
    try:
        envelope = interpreter.interpret_utterance("create an empty text file in your home directory")
        custom = dict(envelope)
        custom["utterance"] = "create an empty text file in your home directory and frobnicate quantum state"
        with pytest.raises(ValueError, match="Unmappable plan step"):
            interpreter.build_execution_plan(custom)
    finally:
        _teardown()


def test_no_execution_without_plan_approval():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(
        phase3=False,
        phase4=True,
        phase4_explain=False,
        phase5=True,
        phase8=True,
        approval_mode="step",
    )
    try:
        response = interpreter.process_user_message(_multi_step_request())
        assert response["type"] == "plan_approval_required"
        assert response["executed"] is False
        assert interpreter.get_execution_events() == []
        assert interpreter.get_memory_events_last(10) == []
    finally:
        _teardown()


def test_approved_plan_executes_steps_in_order():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(
        phase3=False,
        phase4=True,
        phase4_explain=False,
        phase5=True,
        phase8=True,
        approval_mode="step",
    )
    try:
        first = interpreter.process_user_message(_multi_step_request())
        assert first["type"] == "plan_approval_required"

        step_one = interpreter.process_user_message("approve")
        assert step_one["type"] == "step_executed"
        assert step_one["executed"] is True
        assert step_one["remaining_steps"] == 1

        finished = interpreter.process_user_message("approve")
        assert finished["type"] == "plan_executed"
        assert finished["executed"] is True

        events = interpreter.get_execution_events()
        assert len(events) == 2
        assert events[0]["plan_step"]["step_id"] == "step-1"
        assert events[1]["plan_step"]["step_id"] == "step-2"
        assert events[0]["tool_contract"]["intent"] == "plan.create_empty_file"
        assert events[1]["tool_contract"]["intent"] == "plan.user_action_request"
    finally:
        _teardown()


def test_memory_records_each_step_execution():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(
        phase3=False,
        phase4=True,
        phase4_explain=False,
        phase5=True,
        phase8=True,
        approval_mode="step",
    )
    try:
        interpreter.process_user_message(_multi_step_request())
        interpreter.process_user_message("approve")
        interpreter.process_user_message("approve")

        memory_events = interpreter.get_memory_events_last(10)
        assert len(memory_events) == 2
        assert [event["intent"] for event in memory_events] == [
            "plan.create_empty_file",
            "plan.user_action_request",
        ]
        assert all(event["success"] is True for event in memory_events)
    finally:
        _teardown()


def test_plan_approval_mode_plan_executes_all_steps_after_single_approval():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(
        phase3=False,
        phase4=True,
        phase4_explain=False,
        phase5=True,
        phase8=True,
        approval_mode="plan",
    )
    try:
        first = interpreter.process_user_message(_multi_step_request())
        assert first["type"] == "plan_approval_required"
        approved = interpreter.process_user_message("approve")
        assert approved["type"] == "plan_executed"
        assert approved["executed"] is True
        assert len(interpreter.get_execution_events()) == 2
    finally:
        _teardown()
