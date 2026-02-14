from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import v2.core.command_interpreter as interpreter


@dataclass
class LocalFilesystemWriteInvoker:
    invocations: List[Dict[str, Any]] = field(default_factory=list)
    created_paths: List[Path] = field(default_factory=list)

    def invoke(self, contract, parameters: Dict[str, Any]) -> Dict[str, Any]:
        if str(contract.intent) != "write_file":
            raise AssertionError(f"Unexpected contract intent for working-set test: {contract.intent}")
        path = Path(str(parameters.get("path", "")))
        contents = str(parameters.get("contents", ""))
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
    interpreter.set_phase19_enabled(True)
    interpreter.set_phase20_enabled(True)


def _teardown(invoker: LocalFilesystemWriteInvoker | None = None) -> None:
    if invoker is not None:
        invoker.cleanup()
    _set_flags(phase3=False, phase4=False, phase4_explain=False, phase5=False, phase8=False)
    interpreter.set_tool_invoker(interpreter.StubToolInvoker())
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()


def _entity_value(envelope: Dict[str, Any], name: str) -> str:
    entities = envelope.get("entities", [])
    if not isinstance(entities, list):
        return ""
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        if str(entity.get("name", "")) != name:
            continue
        normalized = entity.get("normalized")
        if isinstance(normalized, str) and normalized.strip():
            return normalized
        value = entity.get("value")
        if isinstance(value, str):
            return value
    return ""


def test_working_set_updates_after_capture_and_filesystem_write():
    invoker = LocalFilesystemWriteInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase20-capture-write"
    try:
        interpreter.process_conversational_turn(
            "tell me a one-line note",
            session_id=session_id,
            llm_responder=lambda _u, _e: "Captured working-set text.",
        )
        captured = interpreter.process_conversational_turn(
            "remember the last response as ws_note",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        captured_id = captured["governed_result"]["captured_content"]["content_id"]
        diag_after_capture = interpreter.get_working_set_diagnostics(session_id)
        assert diag_after_capture["has_working_set"] is True
        assert diag_after_capture["working_set"]["content_id"] == captured_id
        assert diag_after_capture["working_set"]["type"] in {"text_note", "html_page", "code_file", "other"}
        assert isinstance(diag_after_capture["working_set"]["timestamp"], str)

        request = interpreter.process_conversational_turn(
            "save that ws_note to file named phase20_ws.txt in my workspace",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        governed = request["governed_result"]
        assert governed["type"] == "approval_required"
        assert governed["envelope"]["intent"] == "write_file"
        assert request["next_state"] == "ready_for_input"
        assert invoker.invocations == []
        assert governed["type"] != "mode_info"

        approved = interpreter.process_conversational_turn("approve", session_id=session_id)
        assert approved["governed_result"]["type"] == "executed"
        assert approved["next_state"] == "ready_for_input"
        path = _entity_value(approved["governed_result"]["execution_event"]["envelope"], "path")
        assert Path(path).exists()

        diag_after_write = interpreter.get_working_set_diagnostics(session_id)
        assert diag_after_write["has_working_set"] is True
        assert diag_after_write["working_set"]["content_id"] == captured_id
        assert diag_after_write["working_set"]["path"] == path
        assert diag_after_write["working_set"]["type"] in {"text_note", "html_page", "code_file", "other"}
    finally:
        _teardown(invoker)


def test_implicit_reference_resolution_for_this_that_current_it():
    invoker = LocalFilesystemWriteInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase20-implicit"
    try:
        interpreter.process_conversational_turn(
            "tell me a source sentence",
            session_id=session_id,
            llm_responder=lambda _u, _e: "Implicit source sentence.",
        )
        captured = interpreter.process_conversational_turn(
            "capture this as implicit_source",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        expected_content_id = captured["governed_result"]["captured_content"]["content_id"]

        for pronoun, suffix in [
            ("this", "this.txt"),
            ("that", "that.txt"),
            ("current", "current.txt"),
            ("it", "it.txt"),
            ("current note", "current-note.txt"),
            ("that note", "that-note.txt"),
            ("current file", "current-file.txt"),
        ]:
            before_count = len(invoker.invocations)
            request = interpreter.process_conversational_turn(
                f"write text {pronoun} to file {suffix} in my workspace",
                session_id=session_id,
            )
            governed = request["governed_result"]
            assert governed["type"] == "approval_required"
            assert governed["envelope"]["intent"] == "write_file"
            assert _entity_value(governed["envelope"], "contents") == "Implicit source sentence."
            assert len(invoker.invocations) == before_count
            approved = interpreter.process_conversational_turn("approve", session_id=session_id)
            assert approved["governed_result"]["type"] == "executed"
            assert approved["next_state"] == "ready_for_input"
            write_path = _entity_value(approved["governed_result"]["execution_event"]["envelope"], "path")
            assert Path(write_path).read_text(encoding="utf-8") == "Implicit source sentence."
            diagnostics = interpreter.get_working_set_diagnostics(session_id)
            assert diagnostics["working_set"]["content_id"] == expected_content_id
    finally:
        _teardown(invoker)


def test_shorthand_save_this_uses_working_set_with_single_approval():
    invoker = LocalFilesystemWriteInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase20-save-this"
    try:
        interpreter.process_conversational_turn(
            "tell me a concise idea",
            session_id=session_id,
            llm_responder=lambda _u, _e: "Working-set shorthand content.",
        )
        capture = interpreter.process_conversational_turn(
            "capture this as shorthand_source",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        expected_id = capture["governed_result"]["captured_content"]["content_id"]

        request = interpreter.process_conversational_turn("save this", session_id=session_id)
        governed = request["governed_result"]
        assert governed["type"] == "approval_required"
        assert governed["envelope"]["intent"] == "write_file"
        assert _entity_value(governed["envelope"], "contents") == "Working-set shorthand content."
        assert invoker.invocations == []

        approved = interpreter.process_conversational_turn("approve", session_id=session_id)
        assert approved["governed_result"]["type"] == "executed"
        assert approved["next_state"] == "ready_for_input"
        assert len(invoker.invocations) == 1
        diagnostics = interpreter.get_working_set_diagnostics(session_id)
        assert diagnostics["working_set"]["content_id"] == expected_id
        assert diagnostics["working_set"]["source"] == "filesystem"
    finally:
        _teardown(invoker)


def test_multiple_working_set_replacements_in_session():
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase20-replace"
    try:
        interpreter.process_conversational_turn(
            "tell me text one",
            session_id=session_id,
            llm_responder=lambda _u, _e: "First working-set text.",
        )
        first = interpreter.process_conversational_turn(
            "capture this as first_set",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        first_id = first["governed_result"]["captured_content"]["content_id"]
        diag_first = interpreter.get_working_set_diagnostics(session_id)
        assert diag_first["working_set"]["content_id"] == first_id

        interpreter.process_conversational_turn(
            "tell me text two",
            session_id=session_id,
            llm_responder=lambda _u, _e: "Second working-set text.",
        )
        second = interpreter.process_conversational_turn(
            "capture this as second_set",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        second_id = second["governed_result"]["captured_content"]["content_id"]
        diag_second = interpreter.get_working_set_diagnostics(session_id)
        assert second_id != first_id
        assert diag_second["working_set"]["content_id"] == second_id
    finally:
        _teardown()


def test_working_set_reset_on_explicit_command():
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase20-reset"
    try:
        interpreter.process_conversational_turn(
            "tell me reset text",
            session_id=session_id,
            llm_responder=lambda _u, _e: "Resettable text.",
        )
        interpreter.process_conversational_turn(
            "capture this as reset_item",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        assert interpreter.get_working_set_diagnostics(session_id)["has_working_set"] is True

        reset = interpreter.process_conversational_turn("reset current working set", session_id=session_id)
        assert reset["governed_result"]["type"] == "working_set_reset"
        assert "cleared" in reset["response"].lower()
        assert interpreter.get_working_set_diagnostics(session_id)["has_working_set"] is False
    finally:
        _teardown()


def test_working_set_reset_on_task_completion_phrase():
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase20-task-complete"
    try:
        interpreter.process_conversational_turn(
            "tell me completion text",
            session_id=session_id,
            llm_responder=lambda _u, _e: "Task completion reset text.",
        )
        interpreter.process_conversational_turn(
            "capture this as completion_item",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        assert interpreter.get_working_set_diagnostics(session_id)["has_working_set"] is True

        done = interpreter.process_conversational_turn("I'm done with this page", session_id=session_id)
        assert done["governed_result"]["type"] == "working_set_reset"
        assert "reset" in done["response"].lower()
        assert interpreter.get_working_set_diagnostics(session_id)["has_working_set"] is False
    finally:
        _teardown()


def test_working_set_invalidation_on_session_boundary():
    invoker = LocalFilesystemWriteInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_a = "sess-phase20-boundary-a"
    session_b = "sess-phase20-boundary-b"
    try:
        interpreter.process_conversational_turn(
            "tell me boundary text",
            session_id=session_a,
            llm_responder=lambda _u, _e: "Boundary text.",
        )
        interpreter.process_conversational_turn(
            "capture this as boundary_item",
            session_id=session_a,
            llm_responder=lambda _u, _e: "unused",
        )
        assert interpreter.get_working_set_diagnostics(session_a)["has_working_set"] is True
        assert interpreter.get_working_set_diagnostics(session_b)["has_working_set"] is False

        response = interpreter.process_conversational_turn(
            "write text this to file boundary.txt in my workspace",
            session_id=session_b,
        )
        governed = response["governed_result"]
        assert governed["type"] == "no_action"
        assert governed["envelope"]["lane"] == "CLARIFY"
        assert "working set" in governed["envelope"]["next_prompt"].lower()
        assert invoker.invocations == []
    finally:
        _teardown(invoker)


def test_working_set_expires_after_session_ttl(monkeypatch):
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase20-expiry"
    base = datetime(2026, 2, 14, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(interpreter, "_utcnow", lambda: base)
    try:
        interpreter.process_conversational_turn(
            "tell me expiry text",
            session_id=session_id,
            llm_responder=lambda _u, _e: "Expiring working-set text.",
        )
        interpreter.process_conversational_turn(
            "capture this as expiry_item",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        before = interpreter.get_working_set_diagnostics(session_id)
        assert before["has_working_set"] is True

        future = base + timedelta(seconds=interpreter._PHASE20_WORKING_SET_TTL_SECONDS + 1)
        monkeypatch.setattr(interpreter, "_utcnow", lambda: future)
        after = interpreter.get_working_set_diagnostics(session_id)
        assert after["has_working_set"] is False
    finally:
        _teardown()


def test_clarify_fallback_when_working_set_missing():
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        response = interpreter.process_user_message("write text this to file missing.txt in my workspace")
        assert response["type"] == "no_action"
        assert response["envelope"]["lane"] == "CLARIFY"
        assert "working set" in response["envelope"]["next_prompt"].lower()
        assert response["type"] != "mode_info"
    finally:
        _teardown()


def test_working_set_diagnostics_message_exposes_active_label():
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase20-diagnostics"
    try:
        interpreter.process_conversational_turn(
            "tell me diagnostic text",
            session_id=session_id,
            llm_responder=lambda _u, _e: "Diagnostic working-set text.",
        )
        interpreter.process_conversational_turn(
            "capture this as diag_item",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )

        diagnostics = interpreter.process_conversational_turn("what am i working on", session_id=session_id)
        assert diagnostics["governed_result"]["type"] == "working_set_info"
        assert "diag_item" in diagnostics["response"]
        assert diagnostics["next_state"] == "ready_for_input"
    finally:
        _teardown()


def test_working_set_does_not_override_explicit_label_reference():
    invoker = LocalFilesystemWriteInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase20-explicit-override"
    try:
        interpreter.process_conversational_turn(
            "tell me explicit content",
            session_id=session_id,
            llm_responder=lambda _u, _e: "Explicit label text.",
        )
        explicit_capture = interpreter.process_conversational_turn(
            "capture this as explicit_label",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        explicit_id = explicit_capture["governed_result"]["captured_content"]["content_id"]

        request = interpreter.process_conversational_turn(
            'write text "Working-set replacement text." to file replace_ws.txt in my workspace',
            session_id=session_id,
        )
        assert request["governed_result"]["type"] == "approval_required"
        interpreter.process_conversational_turn("approve", session_id=session_id)

        explicit_write = interpreter.process_conversational_turn(
            "save that explicit_label to file named explicit-target.txt in my workspace",
            session_id=session_id,
        )
        governed = explicit_write["governed_result"]
        assert governed["type"] == "approval_required"
        captured_entities = [
            entity
            for entity in governed["envelope"]["entities"]
            if isinstance(entity, dict) and str(entity.get("name", "")) == "captured_content"
        ]
        assert len(captured_entities) == 1
        assert captured_entities[0]["content_id"] == explicit_id
        assert captured_entities[0]["text"] == "Explicit label text."
        assert invoker.invocations[-1]["parameters"]["contents"] != "Explicit label text."
    finally:
        _teardown(invoker)


def test_unrelated_conversation_has_no_implicit_writes_or_working_set_mutation():
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase20-no-side-effects"
    try:
        interpreter.process_conversational_turn(
            "tell me baseline text",
            session_id=session_id,
            llm_responder=lambda _u, _e: "Baseline working-set text.",
        )
        capture = interpreter.process_conversational_turn(
            "capture this as baseline_ctx",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        baseline_id = capture["governed_result"]["captured_content"]["content_id"]

        unrelated = interpreter.process_conversational_turn(
            "tell me a fun fact about bees",
            session_id=session_id,
            llm_responder=lambda _u, _e: "Bees can recognize human faces.",
        )
        assert unrelated["governed_result"]["type"] == "no_action"
        assert interpreter.get_tool_invocations() == []
        diagnostics = interpreter.get_working_set_diagnostics(session_id)
        assert diagnostics["has_working_set"] is True
        assert diagnostics["working_set"]["content_id"] == baseline_id
        assert unrelated["governed_result"]["type"] != "mode_info"
    finally:
        _teardown()


def test_reads_and_clarifications_do_not_mutate_working_set():
    interpreter.set_tool_invoker(interpreter.StubToolInvoker())
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase20-read-clarify"
    try:
        interpreter.process_conversational_turn(
            "tell me stable text",
            session_id=session_id,
            llm_responder=lambda _u, _e: "Stable working-set text.",
        )
        captured = interpreter.process_conversational_turn(
            "capture this as stable_item",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        expected_id = captured["governed_result"]["captured_content"]["content_id"]

        read_turn = interpreter.process_conversational_turn(
            "read file stable.txt from my workspace",
            session_id=session_id,
        )
        assert read_turn["governed_result"]["type"] == "executed"
        assert read_turn["governed_result"]["type"] != "mode_info"

        clarify_turn = interpreter.process_conversational_turn(
            "write to file",
            session_id=session_id,
        )
        assert clarify_turn["governed_result"]["type"] == "no_action"
        assert clarify_turn["governed_result"]["envelope"]["lane"] == "CLARIFY"

        diagnostics = interpreter.get_working_set_diagnostics(session_id)
        assert diagnostics["has_working_set"] is True
        assert diagnostics["working_set"]["content_id"] == expected_id
    finally:
        _teardown()
