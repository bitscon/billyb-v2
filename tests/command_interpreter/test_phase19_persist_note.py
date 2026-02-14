from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import v2.core.command_interpreter as interpreter


@dataclass
class LocalFilesystemWriteInvoker:
    invocations: List[Dict[str, Any]] = field(default_factory=list)
    created_paths: List[Path] = field(default_factory=list)

    def invoke(self, contract, parameters: Dict[str, Any]) -> Dict[str, Any]:
        if str(contract.intent) != "write_file":
            raise AssertionError(f"Unexpected contract intent for persist_note test: {contract.intent}")
        path = Path(str(parameters.get("path", "")))
        contents = str(parameters.get("contents", ""))
        if not path:
            raise AssertionError("Expected non-empty path.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        self.created_paths.append(path)
        self.invocations.append(
            {
                "intent": str(contract.intent),
                "tool_name": str(contract.tool_name),
                "parameters": dict(parameters),
            }
        )
        return {
            "status": "stubbed",
            "operation": "write_file",
            "path": str(path),
        }

    def cleanup(self) -> None:
        for path in self.created_paths:
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass


def _set_flags(*, phase3: bool, phase4: bool, phase4_explain: bool, phase5: bool, phase8: bool) -> None:
    interpreter.set_phase3_enabled(phase3)
    interpreter.set_phase4_enabled(phase4)
    interpreter.set_phase4_explanation_enabled(phase4_explain)
    interpreter.set_phase5_enabled(phase5)
    interpreter.set_phase8_enabled(phase8)
    interpreter.set_phase8_approval_mode("step")


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


def _entity_value(envelope: Dict[str, Any], name: str) -> str:
    entities = envelope.get("entities", [])
    if not isinstance(entities, list):
        return ""
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        if str(entity.get("name", "")) != name:
            continue
        value = entity.get("normalized")
        if isinstance(value, str) and value.strip():
            return value
        raw = entity.get("value")
        if isinstance(raw, str):
            return raw
    return ""


def _teardown(invoker: LocalFilesystemWriteInvoker | None) -> None:
    if invoker is not None:
        invoker.cleanup()
    _set_flags(phase3=False, phase4=False, phase4_explain=False, phase5=False, phase8=False)
    interpreter.set_tool_invoker(interpreter.StubToolInvoker())
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()


def test_persist_inline_text_given_in_same_message():
    invoker = LocalFilesystemWriteInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    before_artifacts = _artifact_snapshot()
    try:
        turn = interpreter.process_conversational_turn(
            'create a note with "Rotate API keys weekly"',
            session_id="sess-phase19-inline",
        )
        governed = turn["governed_result"]
        assert governed["type"] == "approval_required"
        assert governed["envelope"]["intent"] == "write_file"
        path = _entity_value(governed["envelope"], "path")
        assert path
        assert not Path(path).exists()
        assert invoker.invocations == []
        assert turn["next_state"] == "ready_for_input"

        approved = interpreter.process_conversational_turn("approve", session_id="sess-phase19-inline")
        assert approved["governed_result"]["type"] == "executed"
        assert approved["next_state"] == "ready_for_input"
        assert Path(path).exists()
        assert Path(path).read_text(encoding="utf-8") == "Rotate API keys weekly"
        assert "note persisted to" in approved["response"].lower()
        assert len(invoker.invocations) == 1
        assert invoker.invocations[0]["intent"] == "write_file"
        assert interpreter.get_pending_action() is None
    finally:
        _teardown(invoker)
    assert _artifact_snapshot() == before_artifacts


def test_persist_referenced_captured_content_from_phase16():
    invoker = LocalFilesystemWriteInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    before_artifacts = _artifact_snapshot()
    try:
        interpreter.process_conversational_turn(
            "tell me a short line",
            session_id="sess-phase19-captured",
            llm_responder=lambda _u, _e: "Captured source line.",
        )
        captured = interpreter.process_conversational_turn(
            "remember the last response as source_note",
            session_id="sess-phase19-captured",
            llm_responder=lambda _u, _e: "unused",
        )
        assert captured["governed_result"]["type"] == "content_captured"

        request = interpreter.process_conversational_turn(
            "save that source_note as a note named captured-note.txt",
            session_id="sess-phase19-captured",
        )
        governed = request["governed_result"]
        assert governed["type"] == "approval_required"
        path = _entity_value(governed["envelope"], "path")
        assert path.endswith("captured-note.txt")
        assert not Path(path).exists()
        assert invoker.invocations == []

        approved = interpreter.process_conversational_turn("approve", session_id="sess-phase19-captured")
        assert approved["governed_result"]["type"] == "executed"
        assert Path(path).read_text(encoding="utf-8") == "Captured source line."
        assert approved["next_state"] == "ready_for_input"
    finally:
        _teardown(invoker)
    assert _artifact_snapshot() == before_artifacts


def test_autogeneration_of_content_when_needed(monkeypatch):
    invoker = LocalFilesystemWriteInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    calls = {"count": 0}

    def _fake_generate(_utterance: str) -> str:
        calls["count"] += 1
        return "Generated minimal note content."

    monkeypatch.setattr(interpreter, "_phase19_generate_note_content", _fake_generate)
    try:
        response = interpreter.process_user_message("save this idea as a note")
        assert response["type"] == "approval_required"
        assert _entity_value(response["envelope"], "contents") == "Generated minimal note content."
        path = _entity_value(response["envelope"], "path")
        assert path
        assert not Path(path).exists()
        assert calls["count"] == 1
        assert invoker.invocations == []

        approved = interpreter.process_user_message("approve")
        assert approved["type"] == "executed"
        assert Path(path).read_text(encoding="utf-8") == "Generated minimal note content."
        assert len(invoker.invocations) == 1
    finally:
        _teardown(invoker)


def test_autogenerated_filename_when_not_provided(monkeypatch):
    invoker = LocalFilesystemWriteInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    monkeypatch.setattr(interpreter, "_phase19_generate_note_content", lambda _u: "Generated content.")
    monkeypatch.setattr(
        interpreter,
        "_utcnow",
        lambda: datetime(2026, 2, 14, 20, 30, tzinfo=timezone.utc),
    )
    try:
        response = interpreter.process_user_message("save this thought as a note")
        assert response["type"] == "approval_required"
        path = Path(_entity_value(response["envelope"], "path"))
        assert path.name == "note-20260214-2030.txt"
        assert path.parent == (Path.home() / "sandbox" / "notes")
        assert not path.exists()
        assert invoker.invocations == []
    finally:
        _teardown(invoker)


def test_explicit_filename_resolution_when_provided(monkeypatch):
    invoker = LocalFilesystemWriteInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    monkeypatch.setattr(interpreter, "_phase19_generate_note_content", lambda _u: "Generated content.")
    try:
        response = interpreter.process_user_message("store this text as a note named sprint-plan.txt")
        assert response["type"] == "approval_required"
        path = Path(_entity_value(response["envelope"], "path"))
        assert path.name == "sprint-plan.txt"
        assert path.parent == (Path.home() / "sandbox" / "notes")
        assert not path.exists()
        assert invoker.invocations == []
    finally:
        _teardown(invoker)


def test_path_normalization_and_scope_enforcement_rejects_unsafe_filename(monkeypatch):
    invoker = LocalFilesystemWriteInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    monkeypatch.setattr(interpreter, "_phase19_generate_note_content", lambda _u: "Generated content.")
    try:
        response = interpreter.process_user_message("save this idea as a note named ../escape.txt")
        assert response["type"] == "no_action"
        assert response["envelope"]["lane"] == "CLARIFY"
        assert "safe filename" in response["envelope"]["next_prompt"].lower()
        assert interpreter.get_pending_action() is None
        assert invoker.invocations == []
    finally:
        _teardown(invoker)


def test_ambiguous_persist_request_falls_back_to_clarify():
    invoker = LocalFilesystemWriteInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        response = interpreter.process_user_message("save this as a note")
        assert response["type"] == "no_action"
        assert response["envelope"]["lane"] == "CLARIFY"
        assert interpreter.get_pending_action() is None
        assert invoker.invocations == []
    finally:
        _teardown(invoker)


def test_approval_gating_triggers_exactly_once(monkeypatch):
    invoker = LocalFilesystemWriteInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    monkeypatch.setattr(interpreter, "_phase19_generate_note_content", lambda _u: "Generated content.")
    try:
        first = interpreter.process_user_message("save this idea as a note")
        assert first["type"] == "approval_required"
        assert invoker.invocations == []
        assert interpreter.get_pending_action() is not None

        second = interpreter.process_user_message("approve")
        assert second["type"] == "executed"
        assert len(invoker.invocations) == 1
        assert interpreter.get_pending_action() is None

        third = interpreter.process_user_message("approve")
        assert third["type"] == "approval_rejected"
        assert len(invoker.invocations) == 1
    finally:
        _teardown(invoker)


def test_successful_write_uses_governed_filesystem_and_returns_ready_state(monkeypatch):
    invoker = LocalFilesystemWriteInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    monkeypatch.setattr(interpreter, "_phase19_generate_note_content", lambda _u: "Generated content.")
    before_artifacts = _artifact_snapshot()
    try:
        turn = interpreter.process_conversational_turn("save this idea as a note", session_id="sess-phase19-state")
        assert turn["next_state"] == "ready_for_input"
        assert turn["governed_result"]["type"] == "approval_required"
        path = Path(_entity_value(turn["governed_result"]["envelope"], "path"))
        assert not path.exists()

        approved = interpreter.process_conversational_turn("approve", session_id="sess-phase19-state")
        governed = approved["governed_result"]
        assert approved["next_state"] == "ready_for_input"
        assert governed["type"] == "executed"
        assert governed["execution_event"]["tool_contract"]["intent"] == "write_file"
        assert len(invoker.invocations) == 1
        assert path.exists()
        assert path.read_text(encoding="utf-8") == "Generated content."
        assert str(path).startswith(str(Path.home() / "sandbox" / "notes"))
    finally:
        _teardown(invoker)
    assert _artifact_snapshot() == before_artifacts
