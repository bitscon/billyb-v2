import v2.core.command_interpreter as interpreter


def _set_flags(*, phase3: bool, phase4: bool, phase4_explain: bool, phase5: bool, phase8: bool) -> None:
    interpreter.set_phase3_enabled(phase3)
    interpreter.set_phase4_enabled(phase4)
    interpreter.set_phase4_explanation_enabled(phase4_explain)
    interpreter.set_phase5_enabled(phase5)
    interpreter.set_phase8_enabled(phase8)
    interpreter.set_phase8_approval_mode("step")


def _teardown() -> None:
    _set_flags(phase3=False, phase4=False, phase4_explain=False, phase5=False, phase8=False)
    interpreter.set_tool_invoker(interpreter.StubToolInvoker())
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()


def test_filesystem_contract_mapping_is_explicit():
    registry = interpreter.get_tool_contract_registry()
    assert registry["create_file"].tool_name == "filesystem.create_file"
    assert registry["write_file"].tool_name == "filesystem.write_file"
    assert registry["append_file"].tool_name == "filesystem.append_file"
    assert registry["read_file"].tool_name == "filesystem.read_file"
    assert registry["delete_file"].tool_name == "filesystem.delete_file"


def test_create_write_append_delete_within_allowed_directories_require_approval():
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        create = interpreter.process_user_message("create a blank file called notes.txt in my home directory")
        assert create["type"] == "approval_required"
        assert create["envelope"]["intent"] == "create_file"
        assert create["envelope"]["requires_approval"] is True
        created = interpreter.process_user_message("approve")
        assert created["type"] == "executed"
        assert created["execution_event"]["tool_contract"]["intent"] == "create_file"

        write = interpreter.process_user_message('write text "hello" to file notes.txt in my workspace')
        assert write["type"] == "approval_required"
        assert write["envelope"]["intent"] == "write_file"
        wrote = interpreter.process_user_message("approve")
        assert wrote["type"] == "executed"
        assert wrote["execution_event"]["tool_contract"]["intent"] == "write_file"

        append = interpreter.process_user_message('append text "world" to file notes.txt in my workspace')
        assert append["type"] == "approval_required"
        assert append["envelope"]["intent"] == "append_file"
        appended = interpreter.process_user_message("approve")
        assert appended["type"] == "executed"
        assert appended["execution_event"]["tool_contract"]["intent"] == "append_file"

        delete = interpreter.process_user_message("delete the file at path notes.txt from my workspace")
        assert delete["type"] == "approval_required"
        assert delete["envelope"]["intent"] == "delete_file"
        deleted = interpreter.process_user_message("approve")
        assert deleted["type"] == "executed"
        assert deleted["execution_event"]["tool_contract"]["intent"] == "delete_file"
    finally:
        _teardown()


def test_read_file_executes_without_approval():
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        response = interpreter.process_user_message("read file notes.txt from my workspace")
        assert response["type"] == "executed"
        assert response["executed"] is True
        assert response["execution_event"]["tool_contract"]["intent"] == "read_file"
        invocations = interpreter.get_tool_invocations()
        assert len(invocations) == 1
        assert invocations[0]["intent"] == "read_file"
    finally:
        _teardown()


def test_missing_required_parameters_route_to_clarify():
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        response = interpreter.process_user_message("create a blank file in my home directory")
        assert response["type"] == "no_action"
        assert response["envelope"]["lane"] == "CLARIFY"
        assert "filename" in response["envelope"]["next_prompt"].lower() or "path" in response["envelope"]["next_prompt"].lower()
    finally:
        _teardown()


def test_paths_outside_allowed_scope_are_rejected():
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        response = interpreter.process_user_message("delete the file at path /etc/passwd")
        assert response["type"] == "filesystem_rejected"
        assert "outside allowed scope" in response["message"].lower()
        assert interpreter.get_pending_action() is None
    finally:
        _teardown()


def test_capture_plus_save_flow_uses_captured_content():
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase17-capture-save"
    try:
        turn = interpreter.process_conversational_turn(
            "tell me a fun fact about Rome",
            session_id=session_id,
            llm_responder=lambda _u, _e: "Rome has more than 900 churches.",
        )
        assert turn["response"] == "Rome has more than 900 churches."

        capture = interpreter.process_conversational_turn(
            "remember the last response as rome_fact",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        assert capture["governed_result"]["type"] == "content_captured"

        save = interpreter.process_user_message("save captured rome_fact to file named fact.txt in my workspace")
        assert save["type"] == "approval_required"
        assert save["envelope"]["intent"] == "write_file"
        approved = interpreter.process_user_message("approve")
        assert approved["type"] == "executed"
        invocations = interpreter.get_tool_invocations()
        assert invocations[-1]["intent"] == "write_file"
        assert invocations[-1]["parameters"]["contents"] == "Rome has more than 900 churches."
    finally:
        _teardown()
