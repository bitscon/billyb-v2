from datetime import timedelta

import v2.core.command_interpreter as interpreter


class _RevokingInvoker:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, contract, parameters):
        self.calls += 1
        if self.calls == 1:
            interpreter.revoke_autonomy()
        if contract.intent == "plan.create_empty_file":
            return {
                "status": "stubbed",
                "created": True,
                "path": str(parameters.get("path", "$HOME/untitled.txt")),
            }
        return {
            "status": "stubbed",
            "accepted": True,
        }


def _set_flags(*, phase3: bool, phase4: bool, phase4_explain: bool, phase5: bool, phase8: bool) -> None:
    interpreter.set_phase3_enabled(phase3)
    interpreter.set_phase4_enabled(phase4)
    interpreter.set_phase4_explanation_enabled(phase4_explain)
    interpreter.set_phase5_enabled(phase5)
    interpreter.set_phase8_enabled(phase8)
    interpreter.set_phase8_approval_mode("step")


def _scope() -> interpreter.AutonomyScope:
    return interpreter.AutonomyScope(
        allowed_lanes=["PLAN"],
        allowed_intents=["plan.*"],
    )


def _constraints(*, allowed_tools=None, blocked_tools=None, max_risk_level="medium") -> interpreter.AutonomyConstraints:
    return interpreter.AutonomyConstraints(
        mode="bounded_write",
        max_risk_level=max_risk_level,
        allowed_tools=list(allowed_tools or []),
        blocked_tools=list(blocked_tools or []),
        max_actions=10,
    )


def _multi_step_request() -> str:
    return "create an empty text file in your home directory and create a project note"


def _teardown() -> None:
    _set_flags(phase3=False, phase4=False, phase4_explain=False, phase5=False, phase8=False)
    interpreter.set_tool_invoker(interpreter.StubToolInvoker())
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()


def test_scoped_autonomy_activation_records_constraints_and_duration():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        # Without explicit activation, normal approval gating still applies.
        baseline = interpreter.process_user_message("create an empty text file in your home directory")
        assert baseline["type"] == "approval_required"
        interpreter.reset_phase5_state()

        enabled = interpreter.enable_autonomy(
            _scope(),
            timedelta(minutes=5),
            _constraints(
                allowed_tools=[
                    "stub.filesystem.create_empty_file",
                    "stub.actions.generic_plan_request",
                ]
            ),
            origin="human.test",
        )

        assert enabled["active"] is True
        assert enabled["origin"] == "human.test"
        assert enabled["scope"]["allowed_lanes"] == ["PLAN"]
        assert enabled["constraints"]["max_risk_level"] == "medium"
        assert enabled["expires_at"] > enabled["enabled_at"]

        sessions = interpreter.list_autonomy_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == enabled["session_id"]
        assert sessions[0]["event_count"] >= 1
    finally:
        _teardown()


def test_autonomy_executes_plan_within_constraints_without_per_step_approval():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        enabled = interpreter.enable_autonomy(
            _scope(),
            timedelta(minutes=5),
            _constraints(
                allowed_tools=[
                    "stub.filesystem.create_empty_file",
                    "stub.actions.generic_plan_request",
                ]
            ),
            origin="human.test",
        )

        response = interpreter.process_user_message(_multi_step_request())
        assert response["type"] == "autonomy_executed"
        assert response["executed"] is True
        assert response["session_id"] == enabled["session_id"]
        assert len(response["execution_events"]) == 2
        assert [event["tool_contract"]["intent"] for event in response["execution_events"]] == [
            "plan.create_empty_file",
            "plan.user_action_request",
        ]

        report = interpreter.get_autonomy_session_report(enabled["session_id"])
        assert report["actions_executed"] == 2
        assert report["active"] is True
        assert interpreter.get_pending_action() is None
        assert interpreter.get_pending_plan() is None
    finally:
        _teardown()


def test_autonomy_stops_immediately_on_forbidden_tool_constraint_violation():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        enabled = interpreter.enable_autonomy(
            _scope(),
            timedelta(minutes=5),
            _constraints(allowed_tools=["stub.filesystem.create_empty_file"]),
            origin="human.test",
        )

        response = interpreter.process_user_message(_multi_step_request())
        assert response["type"] == "autonomy_terminated"
        assert response["executed"] is True
        assert response["session_id"] == enabled["session_id"]
        assert len(response["execution_events"]) == 1
        assert response["execution_events"][0]["tool_contract"]["tool_name"] == "stub.filesystem.create_empty_file"

        report = interpreter.get_autonomy_session_report(enabled["session_id"])
        assert report["active"] is False
        assert report["stop_reason"] == "constraint_violation"
        event_types = [event["event_type"] for event in report["events"]]
        assert "autonomy_constraint_violation" in event_types
    finally:
        _teardown()


def test_manual_revocation_stops_autonomy_mid_session():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        revoking_invoker = _RevokingInvoker()
        interpreter.set_tool_invoker(revoking_invoker)

        enabled = interpreter.enable_autonomy(
            _scope(),
            timedelta(minutes=5),
            _constraints(
                allowed_tools=[
                    "stub.filesystem.create_empty_file",
                    "stub.actions.generic_plan_request",
                ]
            ),
            origin="human.test",
        )

        response = interpreter.process_user_message(_multi_step_request())
        assert response["type"] == "autonomy_terminated"
        assert response["executed"] is True
        assert len(response["execution_events"]) == 1

        report = interpreter.get_autonomy_session_report(enabled["session_id"])
        assert report["active"] is False
        assert report["stop_reason"] == "manual_revoke"
        assert report["revoked_at"] is not None
        assert "autonomy_revoked" in [event["event_type"] for event in report["events"]]

        # After revocation, requests return to governed approval flow.
        follow_up = interpreter.process_user_message("create a project note")
        assert follow_up["type"] == "approval_required"
    finally:
        _teardown()


def test_autonomy_session_report_is_ordered_and_auditable():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        enabled = interpreter.enable_autonomy(
            _scope(),
            timedelta(minutes=5),
            _constraints(
                allowed_tools=[
                    "stub.filesystem.create_empty_file",
                    "stub.actions.generic_plan_request",
                ]
            ),
            origin="human.test",
        )

        run = interpreter.process_user_message("create an empty text file in your home directory")
        assert run["type"] == "autonomy_executed"

        revoked = interpreter.revoke_autonomy()
        assert revoked["revoked"] is True

        sessions = interpreter.list_autonomy_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == enabled["session_id"]

        report = interpreter.get_autonomy_session_report(enabled["session_id"])
        timestamps = [event["timestamp"] for event in report["events"]]
        assert timestamps == sorted(timestamps)
        assert all(event["correlation_id"] for event in report["events"])

        event_types = [event["event_type"] for event in report["events"]]
        assert "autonomy_enabled" in event_types
        assert "autonomy_step_executed" in event_types
        assert "autonomy_revoked" in event_types
    finally:
        _teardown()
