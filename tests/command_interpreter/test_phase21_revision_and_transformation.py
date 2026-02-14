from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import v2.core.command_interpreter as interpreter


@dataclass
class LocalFilesystemWriteInvoker:
    invocations: List[Dict[str, Any]] = field(default_factory=list)
    created_paths: List[Path] = field(default_factory=list)

    def invoke(self, contract, parameters: Dict[str, Any]) -> Dict[str, Any]:
        if str(contract.intent) != "write_file":
            raise AssertionError(f"Unexpected contract intent for phase21 test: {contract.intent}")
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
        return {"status": "stubbed", "operation": "write_file", "path": str(path)}

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
    interpreter.set_phase21_enabled(True)


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


def test_simple_text_revision_captures_and_updates_working_set(monkeypatch):
    invoker = LocalFilesystemWriteInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase21-simple-revise"
    try:
        interpreter.process_conversational_turn(
            "tell me a long sentence",
            session_id=session_id,
            llm_responder=lambda _u, _e: "This sentence is very long and repetitive.",
        )
        captured = interpreter.process_conversational_turn(
            "capture this as draft_note",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        original_id = captured["governed_result"]["captured_content"]["content_id"]
        monkeypatch.setattr(
            interpreter,
            "_phase21_generate_transformed_content",
            lambda **_kwargs: "Concise revised note.",
        )

        turn = interpreter.process_conversational_turn(
            "Revise this to be concise.",
            session_id=session_id,
        )
        governed = turn["governed_result"]
        assert governed["type"] == "content_revised"
        assert governed["revised_content"] == "Concise revised note."
        assert governed["captured_content"]["label"].startswith("draft_note_rev")
        assert governed["captured_content"]["content_id"] != original_id
        diagnostics = interpreter.get_working_set_diagnostics(session_id)
        assert diagnostics["has_working_set"] is True
        assert diagnostics["working_set"]["content_id"] == governed["captured_content"]["content_id"]
        assert diagnostics["working_set"]["previous_content_id"] == original_id
        assert invoker.invocations == []
    finally:
        _teardown(invoker)


def test_html_revision_resolves_current_page_and_requests_write_approval(monkeypatch):
    invoker = LocalFilesystemWriteInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase21-html-write"
    before_artifacts = _artifact_snapshot()
    try:
        interpreter.process_conversational_turn(
            "tell me a tiny html page",
            session_id=session_id,
            llm_responder=lambda _u, _e: "<html><body><h1>Home</h1></body></html>",
        )
        interpreter.process_conversational_turn(
            "capture this as home_page",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        request = interpreter.process_conversational_turn(
            "save that home_page to file named home.html in my workspace",
            session_id=session_id,
        )
        assert request["governed_result"]["type"] == "approval_required"
        interpreter.process_conversational_turn("approve", session_id=session_id)

        monkeypatch.setattr(
            interpreter,
            "_phase21_generate_transformed_content",
            lambda **_kwargs: "<html><body><h1>Home</h1><footer>Copyright 2026</footer></body></html>",
        )
        revise = interpreter.process_conversational_turn(
            "Revise the current page to add a footer with copyright notice.",
            session_id=session_id,
        )
        governed = revise["governed_result"]
        assert governed["type"] == "approval_required"
        assert governed["envelope"]["intent"] == "write_file"
        assert "Copyright 2026" in _entity_value(governed["envelope"], "contents")
        assert len(invoker.invocations) == 1

        captured_entities = [
            entity
            for entity in governed["envelope"]["entities"]
            if isinstance(entity, dict) and str(entity.get("name", "")) == "captured_content"
        ]
        assert len(captured_entities) == 1
        revised_id = captured_entities[0]["content_id"]

        approved = interpreter.process_conversational_turn("approve", session_id=session_id)
        assert approved["governed_result"]["type"] == "executed"
        assert approved["next_state"] == "ready_for_input"
        assert len(invoker.invocations) == 2
        path = _entity_value(approved["governed_result"]["execution_event"]["envelope"], "path")
        assert Path(path).read_text(encoding="utf-8").find("Copyright 2026") != -1
        diagnostics = interpreter.get_working_set_diagnostics(session_id)
        assert diagnostics["working_set"]["content_id"] == revised_id
    finally:
        _teardown(invoker)
    assert _artifact_snapshot() == before_artifacts


def test_implicit_working_set_resolution_for_transform_to_uppercase():
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase21-implicit-transform"
    try:
        interpreter.process_conversational_turn(
            "tell me mixed case text",
            session_id=session_id,
            llm_responder=lambda _u, _e: "MiXeD CaSe",
        )
        interpreter.process_conversational_turn(
            "capture this as mixed_text",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        transformed = interpreter.process_conversational_turn(
            "Transform this note to uppercase.",
            session_id=session_id,
        )
        governed = transformed["governed_result"]
        assert governed["type"] == "content_transformed"
        assert governed["revised_content"] == "MIXED CASE"
        assert interpreter.get_tool_invocations() == []
    finally:
        _teardown()


def test_explicit_label_transformation_overrides_current_working_set():
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase21-explicit-label"
    try:
        interpreter.process_conversational_turn(
            "tell me target text",
            session_id=session_id,
            llm_responder=lambda _u, _e: "keep me",
        )
        interpreter.process_conversational_turn(
            "capture this as target_label",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        interpreter.process_conversational_turn(
            "tell me another text",
            session_id=session_id,
            llm_responder=lambda _u, _e: "ignore me",
        )
        interpreter.process_conversational_turn(
            "capture this as current_label",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )

        transformed = interpreter.process_conversational_turn(
            "Transform that target_label to uppercase.",
            session_id=session_id,
        )
        governed = transformed["governed_result"]
        assert governed["type"] == "content_transformed"
        assert governed["revised_content"] == "KEEP ME"
    finally:
        _teardown()


def test_filename_specified_rewrite_and_approval_gate(monkeypatch):
    invoker = LocalFilesystemWriteInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase21-filename"
    before_artifacts = _artifact_snapshot()
    monkeypatch.setattr(
        interpreter,
        "_phase21_generate_transformed_content",
        lambda **_kwargs: "def greet(name):\n    if not name:\n        return 'unknown'\n    return f'hi {name}'\n",
    )
    try:
        interpreter.process_conversational_turn(
            "tell me code",
            session_id=session_id,
            llm_responder=lambda _u, _e: "def greet(name): return f'hi {name}'",
        )
        interpreter.process_conversational_turn(
            "capture this as greet_code",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )

        request = interpreter.process_conversational_turn(
            "Refactor this file to add error handling into file safer.py in my workspace",
            session_id=session_id,
        )
        governed = request["governed_result"]
        assert governed["type"] == "approval_required"
        assert governed["envelope"]["intent"] == "write_file"
        assert _entity_value(governed["envelope"], "path").endswith("safer.py")
        assert invoker.invocations == []

        approved = interpreter.process_conversational_turn("approve", session_id=session_id)
        assert approved["governed_result"]["type"] == "executed"
        path = _entity_value(approved["governed_result"]["execution_event"]["envelope"], "path")
        assert Path(path).exists()
        assert "if not name" in Path(path).read_text(encoding="utf-8")
        assert len(invoker.invocations) == 1
    finally:
        _teardown(invoker)
    assert _artifact_snapshot() == before_artifacts


def test_no_write_without_approval_for_non_write_revision(monkeypatch):
    invoker = LocalFilesystemWriteInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase21-no-write"
    monkeypatch.setattr(interpreter, "_phase21_generate_transformed_content", lambda **_kwargs: "Updated text only.")
    try:
        interpreter.process_conversational_turn(
            "tell me base text",
            session_id=session_id,
            llm_responder=lambda _u, _e: "Base text",
        )
        interpreter.process_conversational_turn(
            "capture this as base_note",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        response = interpreter.process_conversational_turn(
            "Make this more concise",
            session_id=session_id,
        )
        assert response["governed_result"]["type"] == "content_revised"
        assert interpreter.get_pending_action() is None
        assert invoker.invocations == []
    finally:
        _teardown(invoker)


def test_refactor_action_routes_from_current_file_intent(monkeypatch):
    invoker = LocalFilesystemWriteInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase21-refactor-intent"
    monkeypatch.setattr(interpreter, "_phase21_generate_transformed_content", lambda **_kwargs: "print('safe')\n")
    try:
        parsed = interpreter.interpret_utterance("Refactor the current file to add error handling")
        assert parsed["intent"] == "refactor_file"

        interpreter.process_conversational_turn(
            "tell me file text",
            session_id=session_id,
            llm_responder=lambda _u, _e: "print('x')",
        )
        interpreter.process_conversational_turn(
            "capture this as script_code",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        planned = interpreter.process_conversational_turn(
            "Refactor the current file to add error handling",
            session_id=session_id,
        )
        governed = planned["governed_result"]
        assert governed["type"] == "approval_required"
        assert governed["envelope"]["intent"] == "write_file"
        assert invoker.invocations == []
    finally:
        _teardown(invoker)


def test_ambiguous_revision_request_falls_back_to_clarify():
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        response = interpreter.process_user_message("revise this")
        assert response["type"] == "no_action"
        assert response["envelope"]["lane"] == "CLARIFY"
        assert "specific revision" in response["envelope"]["next_prompt"].lower()
    finally:
        _teardown()
