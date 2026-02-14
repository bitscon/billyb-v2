from pathlib import Path

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


def _artifact_snapshot() -> set[str]:
    workspace_root = Path(__file__).resolve().parents[2] / "v2" / "billy_engineering" / "workspace"
    if not workspace_root.exists():
        return set()
    names = {"PLAN.md", "ARTIFACT.md", "VERIFY.md"}
    return {
        str(path.relative_to(workspace_root))
        for path in workspace_root.rglob("*")
        if path.is_file() and path.name in names
    }


def test_write_file_routes_exclusively_through_governed_filesystem_execution():
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        routed = interpreter.process_user_message('/engineer write text "hello" to file notes17_2.txt in my workspace')
        assert routed["type"] == "approval_required"
        assert routed["envelope"]["intent"] == "write_file"

        executed = interpreter.process_user_message("approve")
        assert executed["type"] == "executed"
        assert executed["execution_event"]["tool_contract"]["intent"] == "write_file"
        assert executed["execution_event"]["tool_contract"]["tool_name"] == "filesystem.write_file"

        invocations = interpreter.get_tool_invocations()
        assert len(invocations) == 1
        assert invocations[0]["intent"] == "write_file"
    finally:
        _teardown()


def test_filesystem_intent_does_not_generate_engineering_artifacts():
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    before = _artifact_snapshot()
    try:
        routed = interpreter.process_user_message('/engineer write text "hello" to file notes17_2_artifacts.txt in my workspace')
        assert routed["type"] == "approval_required"
        assert routed["envelope"]["intent"] == "write_file"
        interpreter.process_user_message("approve")
    finally:
        _teardown()
    after = _artifact_snapshot()
    assert after == before


def test_legacy_engineer_mode_path_is_not_used_for_matched_filesystem_intents(monkeypatch):
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)

    def _fail_mode_info(_utterance: str):
        raise AssertionError("Filesystem intents must not route through legacy engineer-mode handling.")

    monkeypatch.setattr(interpreter, "_phase9_engineer_mode_info_response", _fail_mode_info)
    try:
        routed = interpreter.process_user_message("/engineer delete the file at path notes17_2_delete.txt from my workspace")
        assert routed["type"] == "approval_required"
        assert routed["envelope"]["intent"] == "delete_file"
    finally:
        _teardown()
