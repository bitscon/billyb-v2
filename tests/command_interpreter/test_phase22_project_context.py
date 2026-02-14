from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import v2.core.command_interpreter as interpreter


@dataclass
class LocalFilesystemInvoker:
    invocations: List[Dict[str, Any]] = field(default_factory=list)
    created_paths: List[Path] = field(default_factory=list)

    def invoke(self, contract, parameters: Dict[str, Any]) -> Dict[str, Any]:
        intent = str(contract.intent)
        if intent in {"write_file", "append_file", "create_file"}:
            path = Path(str(parameters.get("path", "")))
            contents = str(parameters.get("contents", ""))
            path.parent.mkdir(parents=True, exist_ok=True)
            if intent == "append_file" and path.exists():
                path.write_text(path.read_text(encoding="utf-8") + contents, encoding="utf-8")
            elif intent == "create_file" and path.exists():
                pass
            else:
                path.write_text(contents, encoding="utf-8")
            self.created_paths.append(path)
            self.invocations.append({"intent": intent, "parameters": dict(parameters)})
            return {"status": "stubbed", "operation": intent, "path": str(path)}
        if intent == "delete_file":
            path = Path(str(parameters.get("path", "")))
            if path.exists() and path.is_file():
                path.unlink()
            self.invocations.append({"intent": intent, "parameters": dict(parameters)})
            return {"status": "stubbed", "operation": intent, "path": str(path)}
        if intent == "read_file":
            path = Path(str(parameters.get("path", "")))
            contents = path.read_text(encoding="utf-8") if path.exists() else ""
            self.invocations.append({"intent": intent, "parameters": dict(parameters)})
            return {"status": "stubbed", "operation": intent, "path": str(path), "contents": contents}
        self.invocations.append({"intent": intent, "parameters": dict(parameters)})
        return {"status": "stubbed", "accepted": True}

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
    interpreter.set_phase22_enabled(True)


def _teardown(invoker: LocalFilesystemInvoker | None = None) -> None:
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


def _approve_once(session_id: str) -> Dict[str, Any]:
    return interpreter.process_conversational_turn("approve", session_id=session_id)


def _project_root(session_id: str) -> Path:
    diagnostics = interpreter.get_project_context_diagnostics(session_id)
    assert diagnostics["has_project_context"] is True
    project = diagnostics["project"]
    assert isinstance(project, dict)
    return Path(str(project["root_path"]))


def test_project_creation_sets_context_and_name():
    invoker = LocalFilesystemInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase22-create"
    try:
        parsed = interpreter.interpret_utterance("Create a new project for personal website")
        assert parsed["intent"] == "create_project"

        turn = interpreter.process_conversational_turn("Create a new project for personal website", session_id=session_id)
        governed = turn["governed_result"]
        assert governed["type"] == "project_created"
        project = governed["project"]
        assert project["name"] == "personal_website"
        assert str(project["root_path"]).startswith(str(Path.home()))
        diagnostics = interpreter.get_project_context_diagnostics(session_id)
        assert diagnostics["has_project_context"] is True
        assert diagnostics["project"]["name"] == "personal_website"
        assert invoker.invocations == []
    finally:
        _teardown(invoker)


def test_artifact_tracking_updates_after_project_file_write():
    invoker = LocalFilesystemInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase22-artifacts"
    before_artifacts = _artifact_snapshot()
    try:
        interpreter.process_conversational_turn("Create a new project for docs site", session_id=session_id)
        root = _project_root(session_id)
        target = root / "index.html"
        request = interpreter.process_conversational_turn(
            f'write text "<html><body>Hello</body></html>" to file {target}',
            session_id=session_id,
        )
        assert request["governed_result"]["type"] == "approval_required"
        assert _entity_value(request["governed_result"]["envelope"], "path").startswith(str(root))
        assert invoker.invocations == []

        approved = _approve_once(session_id)
        assert approved["governed_result"]["type"] == "executed"
        assert target.exists()
        diagnostics = interpreter.get_project_context_diagnostics(session_id)
        artifact_paths = [str(item.get("path", "")) for item in diagnostics["project"]["artifacts"]]
        assert "index.html" in artifact_paths
        ws = interpreter.get_working_set_diagnostics(session_id)
        assert ws["has_working_set"] is True
        assert str(ws["working_set"]["path"]).endswith("index.html")
    finally:
        _teardown(invoker)
    assert _artifact_snapshot() == before_artifacts


def test_implicit_current_project_reference_for_update_project():
    invoker = LocalFilesystemInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase22-update"
    try:
        interpreter.process_conversational_turn("Create a new project for support site", session_id=session_id)
        root = _project_root(session_id)
        parsed = interpreter.interpret_utterance("Add an about page to the current project")
        assert parsed["intent"] == "update_project"

        request = interpreter.process_conversational_turn(
            "Add an about page to the current project",
            session_id=session_id,
        )
        governed = request["governed_result"]
        assert governed["type"] == "approval_required"
        path = _entity_value(governed["envelope"], "path")
        assert path.startswith(str(root))
        assert path.endswith("about.html")
        assert invoker.invocations == []

        approved = _approve_once(session_id)
        assert approved["governed_result"]["type"] == "executed"
        assert Path(path).exists()
        diagnostics = interpreter.get_project_context_diagnostics(session_id)
        artifact_paths = [str(item.get("path", "")) for item in diagnostics["project"]["artifacts"]]
        assert "about.html" in artifact_paths
    finally:
        _teardown(invoker)


def test_listing_project_artifacts_and_project_info_queries():
    invoker = LocalFilesystemInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase22-list"
    try:
        interpreter.process_conversational_turn("Create a new project for listing site", session_id=session_id)
        root = _project_root(session_id)
        req = interpreter.process_conversational_turn(
            f'write text "<html>home</html>" to file {root / "index.html"}',
            session_id=session_id,
        )
        assert req["governed_result"]["type"] == "approval_required"
        _approve_once(session_id)

        info = interpreter.process_conversational_turn("What project am I working on?", session_id=session_id)
        assert info["governed_result"]["type"] == "project_info"
        assert "listing_site" in info["response"]

        listing = interpreter.process_conversational_turn("List all files in the project", session_id=session_id)
        governed = listing["governed_result"]
        assert governed["type"] == "project_artifacts"
        assert "index.html" in governed["artifacts"]
        assert len(invoker.invocations) == 1
    finally:
        _teardown(invoker)


def test_project_scoped_revision_transform_uses_project_file_path(monkeypatch):
    invoker = LocalFilesystemInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase22-revise"
    monkeypatch.setattr(
        interpreter,
        "_phase21_generate_transformed_content",
        lambda **_kwargs: "<html><body><h1>Home</h1><footer>Footer</footer></body></html>",
    )
    try:
        interpreter.process_conversational_turn("Create a new project for revise site", session_id=session_id)
        root = _project_root(session_id)
        write = interpreter.process_conversational_turn(
            f'write text "<html><body><h1>Home</h1></body></html>" to file {root / "index.html"}',
            session_id=session_id,
        )
        assert write["governed_result"]["type"] == "approval_required"
        _approve_once(session_id)

        revise = interpreter.process_conversational_turn(
            "Revise the current page to add a footer.",
            session_id=session_id,
        )
        governed = revise["governed_result"]
        assert governed["type"] == "approval_required"
        assert governed["envelope"]["intent"] == "write_file"
        assert _entity_value(governed["envelope"], "path").endswith("index.html")
        assert "Footer" in _entity_value(governed["envelope"], "contents")
        assert len(invoker.invocations) == 1
        _approve_once(session_id)
        assert len(invoker.invocations) == 2
    finally:
        _teardown(invoker)


def test_project_wide_refactor_multi_file_with_phase8_plan(monkeypatch):
    invoker = LocalFilesystemInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase22-refactor"
    before_artifacts = _artifact_snapshot()

    def _inject_header(**kwargs: Any) -> str:
        original = str(kwargs["original_content"])
        if "<body>" in original:
            return original.replace("<body>", "<body><header>Common</header>")
        return "<header>Common</header>\n" + original

    monkeypatch.setattr(interpreter, "_phase21_generate_transformed_content", _inject_header)
    try:
        interpreter.process_conversational_turn("Create a new project for refactor site", session_id=session_id)
        root = _project_root(session_id)
        for name in ("index.html", "about.html"):
            req = interpreter.process_conversational_turn(
                f'write text "<html><body>{name}</body></html>" to file {root / name}',
                session_id=session_id,
            )
            assert req["governed_result"]["type"] == "approval_required"
            _approve_once(session_id)

        interpreter.set_phase8_enabled(True)
        response = interpreter.process_conversational_turn(
            "Refactor all HTML files in this project to include a common header",
            session_id=session_id,
        )
        governed = response["governed_result"]
        assert governed["type"] == "plan_approval_required"
        assert len(governed["plan"]["steps"]) >= 2
        before_exec = len(invoker.invocations)

        while True:
            approval = _approve_once(session_id)
            result_type = approval["governed_result"]["type"]
            if result_type == "plan_executed":
                break
            assert result_type == "step_executed"

        assert len(invoker.invocations) >= before_exec + 2
        assert "Common" in (root / "index.html").read_text(encoding="utf-8")
        assert "Common" in (root / "about.html").read_text(encoding="utf-8")
    finally:
        _teardown(invoker)
    assert _artifact_snapshot() == before_artifacts


def test_project_wide_refactor_requires_approval_before_any_writes(monkeypatch):
    invoker = LocalFilesystemInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=True)
    session_id = "sess-phase22-refactor-approval"
    monkeypatch.setattr(interpreter, "_phase21_generate_transformed_content", lambda **kwargs: str(kwargs["original_content"]) + "\n<!--refactor-->")
    try:
        interpreter.process_conversational_turn("Create a new project for approval site", session_id=session_id)
        root = _project_root(session_id)
        req = interpreter.process_conversational_turn(
            f'write text "<html><body>base</body></html>" to file {root / "index.html"}',
            session_id=session_id,
        )
        assert req["governed_result"]["type"] == "plan_approval_required"
        _approve_once(session_id)

        refactor = interpreter.process_conversational_turn(
            "Refactor all HTML files in this project to include a common header",
            session_id=session_id,
        )
        assert refactor["governed_result"]["type"] == "plan_approval_required"
        before = len(invoker.invocations)
        non_approval = interpreter.process_conversational_turn("tell me a fact", session_id=session_id)
        assert non_approval["governed_result"]["type"] == "approval_rejected"
        assert len(invoker.invocations) == before
    finally:
        _teardown(invoker)


def test_clarify_when_no_active_project():
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        response = interpreter.process_user_message("List all files in the project")
        assert response["type"] == "no_action"
        assert response["envelope"]["lane"] == "CLARIFY"
        assert "no active project" in response["envelope"]["next_prompt"].lower()
    finally:
        _teardown()


def test_project_deletion_is_approval_gated():
    interpreter.set_tool_invoker(interpreter.StubToolInvoker())
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase22-delete"
    try:
        interpreter.process_conversational_turn("Create a new project for delete site", session_id=session_id)
        before = interpreter.get_project_context_diagnostics(session_id)
        assert before["has_project_context"] is True

        request = interpreter.process_conversational_turn("Delete this project", session_id=session_id)
        governed = request["governed_result"]
        assert governed["type"] == "approval_required"
        assert governed["envelope"]["intent"] == "delete_project"

        approved = interpreter.process_conversational_turn("approve", session_id=session_id)
        assert approved["governed_result"]["type"] == "executed"
        after = interpreter.get_project_context_diagnostics(session_id)
        assert after["has_project_context"] is False
    finally:
        _teardown()
