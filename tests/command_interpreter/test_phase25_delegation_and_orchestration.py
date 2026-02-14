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


def test_list_delegation_capabilities():
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase25-capabilities"
    try:
        result = _send(session_id, "List delegation capabilities for this project")
        assert result["type"] == "delegation_capabilities"
        assert "CODING" in result["message"]
        assert "REFACTORING" in result["message"]
        assert invoker.invocations == []
    finally:
        _teardown(invoker)


def test_delegation_contract_construction():
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase25-contract"
    try:
        _send(session_id, "Create a new project for website")
        _send(session_id, "Define project goal: Build homepage")
        _send(session_id, "Propose next tasks for this project")

        result = _send(session_id, "Delegate the task of creating the stylesheet to a coding agent")
        assert result["type"] == "approval_required"
        assert result["envelope"]["intent"] == "plan.user_action_request"
        assert "agent_type: CODING" in result["message"]
        assert "Delegation dlg-" in result["message"]
        assert invoker.invocations == []
    finally:
        _teardown(invoker)


def test_delegation_approval_and_execution_flow():
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase25-approval-flow"
    before_artifacts = _artifact_snapshot()
    try:
        before = _send(session_id, "Delegate generating navigation code to a coding agent")
        assert before["type"] == "approval_required"
        assert invoker.invocations == []

        approved = _send(session_id, "approve")
        assert approved["type"] == "executed"
        assert "captured_label" in approved
        assert "captured_content_id" in approved
        assert "delegation_id" in approved
        assert "Delegation" in approved["message"]

        captured = interpreter.get_captured_content_by_label(str(approved["captured_label"]))
        assert len(captured) == 1
        assert str(captured[0]["content_id"]) == str(approved["captured_content_id"])

        working = _send(session_id, "what is current working set")
        assert working["type"] == "working_set_info"
        assert str(approved["captured_label"]) in working["message"]

        after_artifacts = _artifact_snapshot()
        assert after_artifacts == before_artifacts
        assert [item["intent"] for item in invoker.invocations] == ["plan.user_action_request"]
    finally:
        _teardown(invoker)


def test_delegation_failure_path_unknown_agent():
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase25-failure-agent"
    try:
        bad = _send(session_id, "Delegate this task to an unknown agent type")
        assert bad["type"] == "no_action"
        assert bad["envelope"]["lane"] == "CLARIFY"
        assert "specialist agent type" in str(bad["envelope"]["next_prompt"]).lower()
        assert invoker.invocations == []
    finally:
        _teardown(invoker)


def test_delegation_scope_enforcement():
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase25-scope"
    try:
        result = _send(session_id, "Delegate deletion of /etc/passwd to a coding agent")
        assert result["type"] == "no_action"
        assert result["envelope"]["lane"] == "CLARIFY"
        prompt = str(result["envelope"]["next_prompt"]).lower()
        assert "delegation rejected" in prompt
        assert invoker.invocations == []
    finally:
        _teardown(invoker)


def test_describe_delegation_result():
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase25-describe-result"
    try:
        requested = _send(session_id, "Delegate code tweak task to coding agent")
        assert requested["type"] == "approval_required"
        approved = _send(session_id, "approve")
        assert approved["type"] == "executed"
        desc = _send(session_id, "Describe the result of the last delegation")
        assert desc["type"] == "delegation_result"
        assert "delegation result" in str(desc["message"]).lower()
        assert str(approved["delegation_id"]) in str(desc["message"])
    finally:
        _teardown(invoker)


def test_governance_constraints_and_action_behavior_remain_intact():
    invoker = LocalInvoker()
    interpreter.set_tool_invoker(invoker)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase25-governance"
    try:
        result = _send(session_id, "Delegate code generation for another task to a coding agent")
        assert result["type"] == "approval_required"
        assert invoker.invocations == []

        followup = _send(session_id, "Generate content only unrelated")
        assert followup["type"] == "approval_rejected"
        assert invoker.invocations == []

        action_request = _send(session_id, 'write text "hello" to file phase25-action.txt in my workspace')
        assert action_request["type"] == "approval_required"
        assert action_request["envelope"]["intent"] == "write_file"
        assert invoker.invocations == []
    finally:
        _teardown(invoker)
