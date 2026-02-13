from datetime import timedelta

import v2.core.command_interpreter as interpreter


def _set_flags(*, phase3: bool, phase4: bool, phase4_explain: bool, phase5: bool) -> None:
    interpreter.set_phase3_enabled(phase3)
    interpreter.set_phase4_enabled(phase4)
    interpreter.set_phase4_explanation_enabled(phase4_explain)
    interpreter.set_phase5_enabled(phase5)


def _action_request() -> str:
    return "create an empty text file in your home directory"


def test_no_execution_without_approval():
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True)
    try:
        response = interpreter.process_user_message(_action_request())
        assert response["type"] == "approval_required"
        assert response["executed"] is False
        assert interpreter.get_pending_action() is not None
        assert interpreter.get_execution_events() == []
    finally:
        _set_flags(phase3=False, phase4=False, phase4_explain=False, phase5=False)
        interpreter.reset_phase5_state()


def test_ambiguous_approval_does_not_execute():
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True)
    try:
        interpreter.process_user_message(_action_request())
        response = interpreter.process_user_message("sure")
        assert response["type"] == "approval_rejected"
        assert response["executed"] is False
        assert interpreter.get_execution_events() == []
        assert interpreter.get_pending_action() is None
    finally:
        _set_flags(phase3=False, phase4=False, phase4_explain=False, phase5=False)
        interpreter.reset_phase5_state()


def test_valid_approval_executes_exactly_once():
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True)
    try:
        interpreter.process_user_message(_action_request())
        response = interpreter.process_user_message("approve")
        assert response["type"] == "executed"
        assert response["executed"] is True
        events = interpreter.get_execution_events()
        assert len(events) == 1
        assert events[0]["status"] == "executed_stub"
        assert interpreter.get_pending_action() is None
    finally:
        _set_flags(phase3=False, phase4=False, phase4_explain=False, phase5=False)
        interpreter.reset_phase5_state()


def test_repeated_approval_is_rejected():
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True)
    try:
        interpreter.process_user_message(_action_request())
        interpreter.process_user_message("approve")
        second = interpreter.process_user_message("approve")
        assert second["type"] == "approval_rejected"
        assert second["executed"] is False
        assert len(interpreter.get_execution_events()) == 1
    finally:
        _set_flags(phase3=False, phase4=False, phase4_explain=False, phase5=False)
        interpreter.reset_phase5_state()


def test_expired_pending_action_cannot_be_approved(monkeypatch):
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True)
    try:
        interpreter.process_user_message(_action_request())
        pending = interpreter.get_pending_action()
        assert pending is not None
        expired_now = interpreter._parse_iso(pending.expires_at) + timedelta(seconds=1)
        monkeypatch.setattr(interpreter, "_utcnow", lambda: expired_now)

        response = interpreter.process_user_message("approve")
        assert response["type"] == "approval_expired"
        assert response["executed"] is False
        assert interpreter.get_execution_events() == []
        assert interpreter.get_pending_action() is None
    finally:
        _set_flags(phase3=False, phase4=False, phase4_explain=False, phase5=False)
        interpreter.reset_phase5_state()
