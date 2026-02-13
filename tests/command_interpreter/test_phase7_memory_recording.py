import v2.core.command_interpreter as interpreter


def _set_flags(*, phase3: bool, phase4: bool, phase4_explain: bool, phase5: bool) -> None:
    interpreter.set_phase3_enabled(phase3)
    interpreter.set_phase4_enabled(phase4)
    interpreter.set_phase4_explanation_enabled(phase4_explain)
    interpreter.set_phase5_enabled(phase5)


def _action_request() -> str:
    return "create an empty text file in your home directory"


def _teardown() -> None:
    _set_flags(phase3=False, phase4=False, phase4_explain=False, phase5=False)
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()


def test_memory_event_recorded_on_successful_execution():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True)
    try:
        interpreter.process_user_message(_action_request())
        response = interpreter.process_user_message("approve")
        assert response["type"] == "executed"
        events = interpreter.get_memory_events_last(1)
        assert len(events) == 1
        assert events[0]["success"] is True
        assert events[0]["intent"] == "plan.create_empty_file"
        assert events[0]["tool_name"] == "stub.filesystem.create_empty_file"
    finally:
        _teardown()


def test_memory_event_recorded_on_failed_execution_attempt(monkeypatch):
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True)
    try:
        monkeypatch.setattr(interpreter, "_resolve_tool_contract", lambda _intent: None)
        interpreter.process_user_message(_action_request())
        response = interpreter.process_user_message("approve")
        assert response["type"] == "execution_rejected"
        events = interpreter.get_memory_events_last(1)
        assert len(events) == 1
        assert events[0]["success"] is False
        assert events[0]["intent"] == "plan.create_empty_file"
        assert "No tool contract resolved" in events[0]["execution_result"]["error"]
    finally:
        _teardown()


def test_memory_is_append_only_and_recall_apis_work():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True)
    try:
        interpreter.process_user_message(_action_request())
        interpreter.process_user_message("approve")

        interpreter.process_user_message("create a project note")
        interpreter.process_user_message("approve")

        latest = interpreter.get_memory_events_last(2)
        assert len(latest) == 2
        assert latest[0]["intent"] == "plan.create_empty_file"
        assert latest[1]["intent"] == "plan.user_action_request"

        by_intent = interpreter.get_memory_events_by_intent("plan.user_action_request")
        assert len(by_intent) == 1
        assert by_intent[0]["tool_name"] == "stub.actions.generic_plan_request"

        by_tool = interpreter.get_memory_events_by_tool("stub.filesystem.create_empty_file")
        assert len(by_tool) == 1
        assert by_tool[0]["intent"] == "plan.create_empty_file"

        # Returned data is detached from store state.
        latest[0]["intent"] = "tampered.intent"
        again = interpreter.get_memory_events_last(2)
        assert again[0]["intent"] == "plan.create_empty_file"
    finally:
        _teardown()


def test_file_backed_memory_store_records_events(tmp_path):
    memory_path = tmp_path / "phase7-memory.jsonl"
    interpreter.configure_memory_store("file", path=str(memory_path))
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True)
    try:
        interpreter.process_user_message(_action_request())
        interpreter.process_user_message("approve")

        events = interpreter.get_memory_events_last(1)
        assert len(events) == 1
        assert events[0]["success"] is True
        assert memory_path.exists()
        assert memory_path.read_text(encoding="utf-8").strip()
    finally:
        _teardown()


def test_memory_failure_does_not_affect_execution():
    class BrokenMemoryStore:
        def append(self, _event):
            raise RuntimeError("memory down")

        def get_last(self, _count):
            return []

        def get_by_intent(self, _intent):
            return []

        def get_by_tool(self, _tool_name):
            return []

        def clear(self):
            return None

    interpreter.set_memory_store(BrokenMemoryStore())
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True)
    try:
        interpreter.process_user_message(_action_request())
        response = interpreter.process_user_message("approve")
        assert response["type"] == "executed"
        assert response["executed"] is True
        assert interpreter.get_memory_events_last(10) == []
    finally:
        _teardown()
