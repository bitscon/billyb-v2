from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import v2.core.command_interpreter as interpreter
from v2.core.observability import observability_turn


@dataclass
class LocalInvoker:
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
    interpreter.set_phase23_enabled(True)
    interpreter.set_phase24_enabled(True)


def _teardown(invoker: LocalInvoker | None = None) -> None:
    if invoker is not None:
        invoker.cleanup()
    _set_flags(phase3=False, phase4=False, phase4_explain=False, phase5=False, phase8=False)
    interpreter.set_tool_invoker(interpreter.StubToolInvoker())
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()


def _send(session_id: str, utterance: str) -> Dict[str, Any]:
    with observability_turn(session_id=session_id):
        return interpreter.process_user_message(utterance)


def _approve(session_id: str) -> Dict[str, Any]:
    return _send(session_id, "approve")


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


def _project_root(session_id: str) -> Path:
    diagnostics = interpreter.get_project_context_diagnostics(session_id)
    assert diagnostics["has_project_context"] is True
    project = diagnostics["project"]
    assert isinstance(project, dict)
    return Path(str(project["root_path"]))


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


def _setup_project(session_id: str) -> None:
    created = _send(session_id, "Create a new project for milestone site")
    assert created["type"] == "project_created"


def _define_goal_and_tasks(session_id: str, monkeypatch) -> tuple[str, List[str]]:
    goal_resp = _send(session_id, "Define project goal: launch homepage")
    assert goal_resp["type"] == "project_goal_defined"
    goal_id = str(goal_resp["goal"]["goal_id"])
    monkeypatch.setattr(
        interpreter,
        "_phase23_llm_task_descriptions",
        lambda _project, _goal: ["Review homepage copy", "Review launch checklist"],
    )
    tasks_resp = _send(session_id, "What are the next tasks for this goal?")
    assert tasks_resp["type"] == "project_tasks_proposed"
    task_ids = [str(task["task_id"]) for task in tasks_resp["tasks"]]
    return goal_id, task_ids


def test_define_list_and_describe_milestones():
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase24-define"
    try:
        _setup_project(session_id)
        defined = _send(
            session_id,
            "Define a milestone: Prepare homepage and about page with criteria no pending tasks",
        )
        assert defined["type"] == "project_milestone_defined"
        milestone_id = str(defined["milestone"]["milestone_id"])

        listed = _send(session_id, "List milestones for this project")
        assert listed["type"] == "project_milestones"
        assert any(str(item.get("milestone_id", "")) == milestone_id for item in listed["milestones"])

        described = _send(session_id, f"Describe milestone {milestone_id}")
        assert described["type"] == "project_milestone"
        assert str(described["milestone"]["milestone_id"]) == milestone_id
        assert invoker.invocations == []
    finally:
        _teardown(invoker)


def test_milestone_achievement_checks_goal_and_task_criteria(monkeypatch):
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase24-achieve"
    try:
        _setup_project(session_id)
        goal_id, task_ids = _define_goal_and_tasks(session_id, monkeypatch)
        milestone = _send(
            session_id,
            f"Define a milestone: Launch readiness for {goal_id} with criteria all associated goals completed and no pending tasks",
        )
        milestone_id = str(milestone["milestone"]["milestone_id"])

        premature = _send(session_id, f"Mark milestone {milestone_id} as achieved")
        assert premature["type"] == "no_action"
        assert premature["envelope"]["lane"] == "CLARIFY"
        assert "criteria" in premature["envelope"]["next_prompt"].lower()

        for task_id in task_ids:
            done = _send(session_id, f"Mark task {task_id} as completed")
            assert done["type"] == "task_completed"

        achieved = _send(session_id, f"Mark milestone {milestone_id} as achieved")
        assert achieved["type"] == "project_milestone_achieved"
        assert achieved["milestone"]["status"] == "ACHIEVED"
        assert invoker.invocations == []
    finally:
        _teardown(invoker)


def test_project_completion_status_mixed_then_complete(monkeypatch):
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase24-completion"
    try:
        _setup_project(session_id)
        goal_id, task_ids = _define_goal_and_tasks(session_id, monkeypatch)
        milestone = _send(
            session_id,
            f"Define a milestone: Launch readiness for {goal_id} with criteria all associated goals completed and no pending tasks",
        )
        milestone_id = str(milestone["milestone"]["milestone_id"])

        mixed = _send(session_id, "Is this project complete?")
        assert mixed["type"] == "project_completion_status"
        assert mixed["completion"]["is_complete"] is False
        assert mixed["completion"]["milestones_achieved"] == 0

        for task_id in task_ids:
            assert _send(session_id, f"Mark task {task_id} as completed")["type"] == "task_completed"
        assert _send(session_id, f"Mark milestone {milestone_id} as achieved")["type"] == "project_milestone_achieved"

        still_unconfirmed = _send(session_id, "Is this project complete?")
        assert still_unconfirmed["completion"]["is_complete"] is False
        assert still_unconfirmed["completion"]["confirmation_received"] is False

        confirmed = _send(session_id, "Is this project complete? I confirm")
        assert confirmed["type"] == "project_completion_status"
        assert confirmed["completion"]["is_complete"] is True
    finally:
        _teardown(invoker)


def test_finalize_project_requires_approval_and_freezes_writes(monkeypatch):
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase24-finalize"
    before_artifacts = _artifact_snapshot()
    try:
        _setup_project(session_id)
        root = _project_root(session_id)
        write = _send(session_id, f'write text "<html>home</html>" to file {root / "index.html"}')
        assert write["type"] == "approval_required"
        _approve(session_id)

        goal_id, task_ids = _define_goal_and_tasks(session_id, monkeypatch)
        milestone = _send(
            session_id,
            f"Define a milestone: Launch readiness for {goal_id} with criteria all associated goals completed and no pending tasks",
        )
        milestone_id = str(milestone["milestone"]["milestone_id"])
        for task_id in task_ids:
            assert _send(session_id, f"Mark task {task_id} as completed")["type"] == "task_completed"
        assert _send(session_id, f"Mark milestone {milestone_id} as achieved")["type"] == "project_milestone_achieved"

        finalize_req = _send(session_id, "Finalize the project")
        assert finalize_req["type"] == "approval_required"
        assert finalize_req["envelope"]["intent"] == "finalize_project"
        assert "Finalize project" in finalize_req["message"]
        baseline_invocations = len(invoker.invocations)

        finalized = _approve(session_id)
        assert finalized["type"] == "executed"
        diagnostics = interpreter.get_project_context_diagnostics(session_id)
        assert diagnostics["project"]["state"] == "finalized"
        assert diagnostics["project"]["completion_confirmed"] is True

        blocked_write = _send(session_id, f'write text "after" to file {root / "after.txt"}')
        assert blocked_write["type"] == "no_action"
        assert blocked_write["envelope"]["lane"] == "CLARIFY"
        assert "read-only" in blocked_write["envelope"]["next_prompt"].lower()
        assert len(invoker.invocations) == baseline_invocations + 1
    finally:
        _teardown(invoker)
    assert _artifact_snapshot() == before_artifacts


def test_archive_project_requires_approval_moves_files_and_blocks_edits():
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase24-archive"
    before_artifacts = _artifact_snapshot()
    try:
        _setup_project(session_id)
        root = _project_root(session_id)
        for name in ("index.html", "about.html"):
            req = _send(session_id, f'write text "{name}" to file {root / name}')
            assert req["type"] == "approval_required"
            _approve(session_id)
            assert (root / name).exists()

        archive_req = _send(session_id, "Archive the project")
        assert archive_req["type"] == "approval_required"
        assert archive_req["envelope"]["intent"] == "archive_project"

        archived = _approve(session_id)
        assert archived["type"] == "executed"
        tool_result = archived["execution_event"]["tool_result"]
        archive_path = Path(str(tool_result["archive_path"]))
        assert int(tool_result["moved_count"]) >= 2
        assert (archive_path / "index.html").exists()
        assert (archive_path / "about.html").exists()
        assert not (root / "index.html").exists()
        assert not (root / "about.html").exists()

        diagnostics = interpreter.get_project_context_diagnostics(session_id)
        assert diagnostics["project"]["state"] == "archived"
        assert str(diagnostics["project"]["archive_path"]) == str(archive_path)

        blocked = _send(session_id, f'write text "new" to file {root / "new.txt"}')
        assert blocked["type"] == "no_action"
        assert blocked["envelope"]["lane"] == "CLARIFY"
        assert "read-only" in blocked["envelope"]["next_prompt"].lower()
    finally:
        _teardown(invoker)
    assert _artifact_snapshot() == before_artifacts


def test_archive_project_uses_phase8_plan_when_enabled():
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=True)
    session_id = "sess-phase24-archive-phase8"
    try:
        _setup_project(session_id)
        archive_req = _send(session_id, "Archive this project")
        assert archive_req["type"] == "plan_approval_required"
        assert len(invoker.invocations) == 0

        rejected = _send(session_id, "nope")
        assert rejected["type"] == "approval_rejected"
        assert len(invoker.invocations) == 0

        archive_req = _send(session_id, "Archive this project")
        assert archive_req["type"] == "plan_approval_required"
        approved = _approve(session_id)
        assert approved["type"] in {"step_executed", "plan_executed"}
        if approved["type"] == "step_executed":
            approved = _approve(session_id)
            assert approved["type"] == "plan_executed"
        diagnostics = interpreter.get_project_context_diagnostics(session_id)
        assert diagnostics["project"]["state"] == "archived"
    finally:
        _teardown(invoker)


def test_clarify_fallback_for_ambiguous_milestone_and_missing_project_context():
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase24-clarify"
    try:
        missing_project = _send("sess-phase24-none", "Is this project complete?")
        assert missing_project["type"] == "no_action"
        assert missing_project["envelope"]["lane"] == "CLARIFY"
        assert "no active project" in missing_project["envelope"]["next_prompt"].lower()

        _setup_project(session_id)
        first = _send(session_id, "Define a milestone: first milestone")
        second = _send(session_id, "Define a milestone: second milestone")
        assert first["type"] == "project_milestone_defined"
        assert second["type"] == "project_milestone_defined"

        ambiguous = _send(session_id, "Describe milestone")
        assert ambiguous["type"] == "no_action"
        assert ambiguous["envelope"]["lane"] == "CLARIFY"
        assert "multiple milestones" in ambiguous["envelope"]["next_prompt"].lower()
    finally:
        _teardown(invoker)
