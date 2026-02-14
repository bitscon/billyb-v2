from __future__ import annotations

import json
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
        self.invocations.append({"intent": intent, "parameters": dict(parameters)})
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
            return {"status": "stubbed", "operation": intent, "path": str(path)}
        if intent == "delete_file":
            path = Path(str(parameters.get("path", "")))
            if path.exists() and path.is_file():
                path.unlink()
            return {"status": "stubbed", "operation": intent, "path": str(path)}
        if intent == "read_file":
            path = Path(str(parameters.get("path", "")))
            contents = path.read_text(encoding="utf-8") if path.exists() else ""
            return {"status": "stubbed", "operation": intent, "path": str(path), "contents": contents}
        if intent == "plan.user_action_request":
            return {"status": "stubbed", "accepted": True}
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
    interpreter.set_phase25_enabled(True)
    interpreter.set_phase26_enabled(True)


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


def _define_cmd(name: str, schema: Dict[str, Any], steps: List[Dict[str, Any]]) -> str:
    return (
        f"Define workflow named {name} "
        f"schema {json.dumps(schema, ensure_ascii=True)} "
        f"steps {json.dumps(steps, ensure_ascii=True)}"
    )


def _setup_project(session_id: str) -> None:
    created = _send(session_id, "Create a new project for workflow phase26")
    assert created["type"] == "project_created"


def test_workflow_definition_valid_and_rejections():
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase26-define"
    try:
        _setup_project(session_id)

        valid_schema = {"title": {"required": True}}
        valid_steps = [
            {
                "step_id": "step1",
                "description": "Delegate stylesheet draft",
                "intent": "delegate_to_agent",
                "parameters": {"agent_type": "CODING", "task": "creating stylesheet for {title}"},
                "depends_on": [],
            },
            {
                "step_id": "step2",
                "description": "Write output",
                "intent": "write_file",
                "parameters": {"path": "sandbox/phase26-a.txt", "contents": "Title={title}"},
                "depends_on": ["step1"],
            },
        ]
        defined = _send(session_id, _define_cmd("site_build", valid_schema, valid_steps))
        assert defined["type"] == "workflow_defined"
        assert defined["workflow"]["name"] == "site_build"

        invalid_intent_steps = [
            {
                "step_id": "bad1",
                "description": "Invalid",
                "intent": "unknown_intent",
                "parameters": {},
                "depends_on": [],
            }
        ]
        rejected_intent = _send(session_id, _define_cmd("bad_intent_flow", {}, invalid_intent_steps))
        assert rejected_intent["type"] == "no_action"
        assert rejected_intent["envelope"]["lane"] == "CLARIFY"

        circular_steps = [
            {"step_id": "s1", "description": "A", "intent": "write_file", "parameters": {"path": "sandbox/a.txt", "contents": "a"}, "depends_on": ["s2"]},
            {"step_id": "s2", "description": "B", "intent": "write_file", "parameters": {"path": "sandbox/b.txt", "contents": "b"}, "depends_on": ["s1"]},
        ]
        rejected_cycle = _send(session_id, _define_cmd("cycle_flow", {}, circular_steps))
        assert rejected_cycle["type"] == "no_action"
        assert "cycle" in str(rejected_cycle["envelope"]["next_prompt"]).lower()

        invalid_param_steps = [
            {
                "step_id": "p1",
                "description": "Missing schema placeholder",
                "intent": "write_file",
                "parameters": {"path": "sandbox/p.txt", "contents": "{missing_param}"},
                "depends_on": [],
            }
        ]
        rejected_param = _send(session_id, _define_cmd("bad_params", {"title": {"required": True}}, invalid_param_steps))
        assert rejected_param["type"] == "no_action"
        assert "unknown parameters" in str(rejected_param["envelope"]["next_prompt"]).lower()
    finally:
        _teardown(invoker)


def test_list_describe_and_preview_have_no_side_effects():
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase26-preview"
    before_artifacts = _artifact_snapshot()
    try:
        _setup_project(session_id)
        schema = {"title": {"required": True}}
        steps = [
            {
                "step_id": "step2",
                "description": "Write output",
                "intent": "write_file",
                "parameters": {"path": "sandbox/phase26-preview.txt", "contents": "Title={title}"},
                "depends_on": ["step1"],
            },
            {
                "step_id": "step1",
                "description": "Delegate stylesheet draft",
                "intent": "delegate_to_agent",
                "parameters": {"agent_type": "CODING", "task": "creating stylesheet for {title}"},
                "depends_on": [],
            },
        ]
        assert _send(session_id, _define_cmd("preview_flow", schema, steps))["type"] == "workflow_defined"

        listed = _send(session_id, "List workflows for this project")
        assert listed["type"] == "workflows_list"
        assert any(str(item.get("name", "")) == "preview_flow" for item in listed["workflows"])

        described = _send(session_id, "Describe workflow preview_flow")
        assert described["type"] == "workflow_description"
        assert described["workflow"]["name"] == "preview_flow"

        preview = _send(session_id, "Preview workflow preview_flow with title=Home")
        assert preview["type"] == "workflow_preview"
        ordered_steps = preview["preview"]["steps"]
        assert ordered_steps[0]["step_id"] == "step1"
        assert ordered_steps[1]["step_id"] == "step2"
        assert "Home" in str(ordered_steps[0]["parameters"]["task"])
        assert "Home" in str(ordered_steps[1]["parameters"]["contents"])
        assert invoker.invocations == []
        assert _artifact_snapshot() == before_artifacts
    finally:
        _teardown(invoker)


def test_workflow_execution_nested_governance_and_status():
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase26-run"
    before_artifacts = _artifact_snapshot()
    output_path = Path.home() / "sandbox" / "phase26-run-output.txt"
    try:
        _setup_project(session_id)
        schema = {"title": {"required": True}}
        steps = [
            {
                "step_id": "step1",
                "description": "Delegate stylesheet draft",
                "intent": "delegate_to_agent",
                "parameters": {"agent_type": "CODING", "task": "creating stylesheet for {title}"},
                "depends_on": [],
            },
            {
                "step_id": "step2",
                "description": "Write output",
                "intent": "write_file",
                "parameters": {"path": str(output_path), "contents": "Title={title}"},
                "depends_on": ["step1"],
            },
        ]
        assert _send(session_id, _define_cmd("exec_flow", schema, steps))["type"] == "workflow_defined"

        run_request = _send(session_id, "Run workflow exec_flow with title=Home")
        assert run_request["type"] == "approval_required"
        assert run_request["envelope"]["intent"] == "plan.user_action_request"

        pending_status = _send(session_id, "workflow status")
        assert pending_status["type"] == "workflow_status"
        assert pending_status["workflow_run"]["status"] == "PENDING_APPROVAL"

        started = _send(session_id, "approve")
        assert started["type"] == "executed"
        assert started.get("workflow_status") == "RUNNING"
        run_id = str(started.get("workflow_run_id", ""))
        assert run_id

        during = _send(session_id, "workflow status")
        assert during["type"] == "workflow_status"
        assert during["workflow_run"]["status"] == "RUNNING"

        step1 = _send(session_id, "approve")
        assert step1["type"] == "workflow_step_executed"
        assert str(step1.get("workflow_step_id", "")) == "step1"
        assert step1.get("workflow_status") == "RUNNING"
        assert str(step1.get("delegation_id", "")).startswith("dlg-")
        diagnostics = interpreter.get_working_set_diagnostics(session_id)
        assert diagnostics["has_working_set"] is True

        step2 = _send(session_id, "approve")
        assert step2["type"] == "workflow_step_executed"
        assert str(step2.get("workflow_step_id", "")) == "step2"
        assert step2.get("workflow_status") == "COMPLETED"
        assert output_path.exists()
        assert output_path.read_text(encoding="utf-8") == "Title=Home"

        done = _send(session_id, "workflow status")
        assert done["type"] == "workflow_status"
        assert done["workflow_run"]["status"] == "COMPLETED"

        intents = [item["intent"] for item in invoker.invocations]
        assert intents == ["plan.user_action_request", "plan.user_action_request", "write_file"]
        assert _artifact_snapshot() == before_artifacts
    finally:
        try:
            if output_path.exists():
                output_path.unlink()
        except Exception:
            pass
        _teardown(invoker)


def test_workflow_cancel_mid_run_requires_approval_and_stops_remaining_steps():
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase26-cancel"
    output_path = Path.home() / "sandbox" / "phase26-cancel-output.txt"
    try:
        _setup_project(session_id)
        schema = {"title": {"required": True}}
        steps = [
            {
                "step_id": "step1",
                "description": "Write output",
                "intent": "write_file",
                "parameters": {"path": str(output_path), "contents": "Title={title}"},
                "depends_on": [],
            },
            {
                "step_id": "step2",
                "description": "Second write",
                "intent": "write_file",
                "parameters": {"path": str(Path.home() / "sandbox" / "phase26-cancel-output-2.txt"), "contents": "done"},
                "depends_on": ["step1"],
            },
        ]
        assert _send(session_id, _define_cmd("cancel_flow", schema, steps))["type"] == "workflow_defined"
        assert _send(session_id, "Run workflow cancel_flow with title=Draft")["type"] == "approval_required"
        assert _send(session_id, "approve")["type"] == "executed"

        cancel_request = _send(session_id, "Cancel current workflow")
        assert cancel_request["type"] == "approval_required"
        canceled = _send(session_id, "approve")
        assert canceled["type"] == "executed"
        assert canceled.get("workflow_status") == "CANCELED"

        status = _send(session_id, "workflow status")
        assert status["type"] == "workflow_status"
        assert status["workflow_run"]["status"] == "CANCELED"

        assert output_path.exists() is False
    finally:
        try:
            if output_path.exists():
                output_path.unlink()
        except Exception:
            pass
        second = Path.home() / "sandbox" / "phase26-cancel-output-2.txt"
        try:
            if second.exists():
                second.unlink()
        except Exception:
            pass
        _teardown(invoker)


def test_workflow_clarify_fallback_for_ambiguous_or_missing_parameters():
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase26-clarify"
    try:
        _setup_project(session_id)
        schema = {"title": {"required": True}}
        steps = [
            {
                "step_id": "step1",
                "description": "Write output",
                "intent": "write_file",
                "parameters": {"path": "sandbox/phase26-clarify.txt", "contents": "Title={title}"},
                "depends_on": [],
            }
        ]
        assert _send(session_id, _define_cmd("clarify_flow", schema, steps))["type"] == "workflow_defined"

        ambiguous = _send(session_id, "Describe workflow")
        assert ambiguous["type"] == "no_action"
        assert ambiguous["envelope"]["lane"] == "CLARIFY"

        missing = _send(session_id, "Run workflow clarify_flow")
        assert missing["type"] == "no_action"
        assert missing["envelope"]["lane"] == "CLARIFY"
        assert "missing required workflow parameters" in str(missing["envelope"]["next_prompt"]).lower()

        unknown = _send(session_id, "Run workflow does_not_exist with title=Home")
        assert unknown["type"] == "no_action"
        assert unknown["envelope"]["lane"] == "CLARIFY"
    finally:
        _teardown(invoker)
