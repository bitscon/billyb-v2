from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import v2.core.command_interpreter as interpreter


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


def _teardown(invoker: LocalInvoker | None = None) -> None:
    if invoker is not None:
        invoker.cleanup()
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


def _project_name(session_id: str) -> str:
    diagnostics = interpreter.get_project_context_diagnostics(session_id)
    assert diagnostics["has_project_context"] is True
    project = diagnostics["project"]
    assert isinstance(project, dict)
    return str(project.get("name", ""))


def _create_project(session_id: str, request: str = "Create a new project for goal site") -> None:
    turn = interpreter.process_conversational_turn(request, session_id=session_id)
    governed = turn["governed_result"]
    assert governed["type"] == "project_created"


def _define_goal(session_id: str, description: str) -> Dict[str, Any]:
    turn = interpreter.process_conversational_turn(
        f"Define project goal: {description}",
        session_id=session_id,
    )
    governed = turn["governed_result"]
    assert governed["type"] == "project_goal_defined"
    return governed["goal"]


def _propose_tasks(session_id: str) -> List[Dict[str, Any]]:
    turn = interpreter.process_conversational_turn(
        "What are the next tasks for this goal?",
        session_id=session_id,
    )
    governed = turn["governed_result"]
    assert governed["type"] == "project_tasks_proposed"
    tasks = governed["tasks"]
    assert isinstance(tasks, list)
    return tasks


def test_goal_definition_listing_and_description():
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase23-goals"
    try:
        parsed = interpreter.interpret_utterance("Define project goal: launch homepage")
        assert parsed["intent"] == "define_project_goal"

        _create_project(session_id)
        defined = _define_goal(session_id, "launch homepage")
        goal_id = str(defined["goal_id"])

        listed = interpreter.process_conversational_turn("List the goals for this project", session_id=session_id)
        governed_list = listed["governed_result"]
        assert governed_list["type"] == "project_goals"
        assert len(governed_list["goals"]) == 1
        assert governed_list["goals"][0]["goal_id"] == goal_id

        described = interpreter.process_conversational_turn(
            f"Describe goal {goal_id}",
            session_id=session_id,
        )
        governed_desc = described["governed_result"]
        assert governed_desc["type"] == "project_goal"
        assert governed_desc["goal"]["goal_id"] == goal_id
        assert invoker.invocations == []
    finally:
        _teardown(invoker)


def test_propose_next_tasks_returns_structured_advisory_tasks(monkeypatch):
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase23-propose"
    monkeypatch.setattr(
        interpreter,
        "_phase23_llm_task_descriptions",
        lambda _project, _goal: [
            "Draft homepage structure",
            "Write updated index.html content",
            "Review links and navigation",
        ],
    )
    try:
        _create_project(session_id)
        _define_goal(session_id, "launch homepage")
        tasks = _propose_tasks(session_id)

        assert len(tasks) == 3
        assert all(str(task.get("task_id", "")).startswith("task-") for task in tasks)
        assert all(task.get("status") in {"PENDING", "BLOCKED", "COMPLETED"} for task in tasks)
        assert str(tasks[0]["status"]) == "PENDING"
        assert str(tasks[1]["status"]) == "BLOCKED"
        assert str(tasks[1]["dependencies"][0]) == str(tasks[0]["task_id"])
        assert invoker.invocations == []
    finally:
        _teardown(invoker)


def test_list_tasks_and_status_do_not_change_until_complete_request(monkeypatch):
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase23-status"
    monkeypatch.setattr(
        interpreter,
        "_phase23_llm_task_descriptions",
        lambda _project, _goal: ["Review homepage copy", "Publish final homepage copy"],
    )
    try:
        _create_project(session_id)
        _define_goal(session_id, "launch homepage")
        proposed = _propose_tasks(session_id)
        task_id = str(proposed[0]["task_id"])

        listed = interpreter.process_conversational_turn("List project tasks", session_id=session_id)
        governed_listed = listed["governed_result"]
        assert governed_listed["type"] == "project_tasks"
        first = governed_listed["tasks"][0]
        assert first["task_id"] == task_id
        assert first["status"] == "PENDING"

        status = interpreter.process_conversational_turn(f"Task status {task_id}", session_id=session_id)
        governed_status = status["governed_result"]
        assert governed_status["type"] == "task_status"
        assert governed_status["task"]["task_id"] == task_id
        assert governed_status["task"]["status"] == "PENDING"
        assert invoker.invocations == []
    finally:
        _teardown(invoker)


def test_dependency_blocking_unblocks_after_advisory_completion(monkeypatch):
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase23-dependencies"
    monkeypatch.setattr(
        interpreter,
        "_phase23_llm_task_descriptions",
        lambda _project, _goal: ["Review requirements", "Document launch checklist"],
    )
    try:
        _create_project(session_id)
        _define_goal(session_id, "launch homepage")
        proposed = _propose_tasks(session_id)
        first_id = str(proposed[0]["task_id"])
        second_id = str(proposed[1]["task_id"])

        before = interpreter.process_conversational_turn("List tasks", session_id=session_id)
        before_tasks = before["governed_result"]["tasks"]
        second_before = [task for task in before_tasks if str(task["task_id"]) == second_id][0]
        assert second_before["status"] == "BLOCKED"

        completed = interpreter.process_conversational_turn(
            f"Mark task {first_id} as completed",
            session_id=session_id,
        )
        governed_completed = completed["governed_result"]
        assert governed_completed["type"] == "task_completed"
        assert governed_completed["task"]["task_id"] == first_id

        after = interpreter.process_conversational_turn("List tasks", session_id=session_id)
        after_tasks = after["governed_result"]["tasks"]
        second_after = [task for task in after_tasks if str(task["task_id"]) == second_id][0]
        assert second_after["status"] == "PENDING"
        assert invoker.invocations == []
    finally:
        _teardown(invoker)


def test_write_like_task_completion_requires_approval_and_executes_once(monkeypatch):
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase23-approval"
    monkeypatch.setattr(
        interpreter,
        "_phase23_llm_task_descriptions",
        lambda _project, _goal: ["Write updated homepage content to index.html", "Run final review"],
    )
    try:
        _create_project(session_id)
        goal = _define_goal(session_id, "launch homepage")
        tasks = _propose_tasks(session_id)
        task_id = str(tasks[0]["task_id"])

        request = interpreter.process_conversational_turn(
            f"Mark task {task_id} as completed",
            session_id=session_id,
        )
        governed = request["governed_result"]
        assert governed["type"] == "approval_required"
        assert governed["envelope"]["intent"] == "plan.user_action_request"
        assert _project_name(session_id) in governed["message"]
        assert str(goal["description"]) in governed["message"]
        assert task_id in governed["message"]
        assert len(invoker.invocations) == 0

        status_before = interpreter.process_conversational_turn(
            f"Task status {task_id}",
            session_id=session_id,
        )
        assert status_before["governed_result"]["type"] == "approval_rejected"
        assert len(invoker.invocations) == 0

        # Re-submit completion request, then approve once.
        request = interpreter.process_conversational_turn(
            f"Mark task {task_id} as completed",
            session_id=session_id,
        )
        assert request["governed_result"]["type"] == "approval_required"
        approved = interpreter.process_conversational_turn("approve", session_id=session_id)
        assert approved["governed_result"]["type"] == "executed"
        assert len(invoker.invocations) == 1
        assert invoker.invocations[0]["intent"] == "plan.user_action_request"

        status_after = interpreter.process_conversational_turn(
            f"Task status {task_id}",
            session_id=session_id,
        )
        governed_status_after = status_after["governed_result"]
        assert governed_status_after["type"] == "task_status"
        assert governed_status_after["task"]["status"] == "COMPLETED"
    finally:
        _teardown(invoker)


def test_advisory_goal_and_task_flows_have_no_unintended_side_effects(monkeypatch):
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase23-advisory"
    before_artifacts = _artifact_snapshot()
    monkeypatch.setattr(
        interpreter,
        "_phase23_llm_task_descriptions",
        lambda _project, _goal: ["Draft launch checklist", "Review launch checklist"],
    )
    try:
        _create_project(session_id)
        goal_turn = interpreter.process_conversational_turn(
            "Define project goal: launch homepage",
            session_id=session_id,
        )
        assert goal_turn["next_state"] == "ready_for_input"
        assert goal_turn["governed_result"]["type"] == "project_goal_defined"

        proposal_turn = interpreter.process_conversational_turn(
            "Propose next tasks for this goal",
            session_id=session_id,
        )
        assert proposal_turn["next_state"] == "ready_for_input"
        assert proposal_turn["governed_result"]["type"] == "project_tasks_proposed"

        listing_turn = interpreter.process_conversational_turn("List tasks", session_id=session_id)
        assert listing_turn["next_state"] == "ready_for_input"
        assert listing_turn["governed_result"]["type"] == "project_tasks"
        assert listing_turn["governed_result"]["type"] != "mode_info"
        assert invoker.invocations == []
    finally:
        _teardown(invoker)
    assert _artifact_snapshot() == before_artifacts


def test_clarify_fallback_for_ambiguous_goal_and_task_references(monkeypatch):
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase23-clarify"
    monkeypatch.setattr(
        interpreter,
        "_phase23_llm_task_descriptions",
        lambda _project, _goal: ["Review content"],
    )
    try:
        _create_project(session_id)

        no_goal = interpreter.process_conversational_turn("Describe goal", session_id=session_id)
        no_goal_governed = no_goal["governed_result"]
        assert no_goal_governed["type"] == "no_action"
        assert no_goal_governed["envelope"]["lane"] == "CLARIFY"
        assert "no goals defined" in no_goal_governed["envelope"]["next_prompt"].lower()

        _define_goal(session_id, "launch homepage")
        _define_goal(session_id, "launch about page")
        ambiguous_goal = interpreter.process_conversational_turn(
            "What are the next tasks for this goal?",
            session_id=session_id,
        )
        ambiguous_goal_governed = ambiguous_goal["governed_result"]
        assert ambiguous_goal_governed["type"] == "no_action"
        assert ambiguous_goal_governed["envelope"]["lane"] == "CLARIFY"
        assert "multiple goals" in ambiguous_goal_governed["envelope"]["next_prompt"].lower()

        ambiguous_task = interpreter.process_conversational_turn(
            "Mark task as completed",
            session_id=session_id,
        )
        ambiguous_task_governed = ambiguous_task["governed_result"]
        assert ambiguous_task_governed["type"] == "no_action"
        assert ambiguous_task_governed["envelope"]["lane"] == "CLARIFY"
        assert "specify which task" in ambiguous_task_governed["envelope"]["next_prompt"].lower()
        assert invoker.invocations == []
    finally:
        _teardown(invoker)
