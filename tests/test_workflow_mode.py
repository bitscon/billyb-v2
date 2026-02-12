import json

import v2.core.runtime as runtime_mod


def _reset_workflow_state() -> None:
    runtime_mod._workflows.clear()
    runtime_mod._approved_workflows.clear()
    runtime_mod._workflow_audit.clear()
    runtime_mod._cdm_drafts.clear()
    runtime_mod._approved_drafts.clear()
    runtime_mod._approved_drafts_audit.clear()
    runtime_mod._application_attempts.clear()
    runtime_mod._tool_drafts.clear()
    runtime_mod._approved_tools.clear()
    runtime_mod._tool_approval_audit.clear()
    runtime_mod._registered_tools.clear()
    runtime_mod._tool_registration_audit.clear()
    runtime_mod._pending_tool_executions.clear()
    runtime_mod._tool_execution_audit.clear()


def _define_workflow(runtime: runtime_mod.BillyRuntime, steps: list[dict], trace_id: str = "trace-workflow"):
    before_ids = set(runtime_mod._workflows.keys())
    payload = json.dumps({"steps": steps}, sort_keys=True)
    result = runtime.run_turn(f"workflow: {payload}", {"trace_id": trace_id, "created_by": "human"})
    after_ids = set(runtime_mod._workflows.keys())
    new_ids = list(after_ids - before_ids)
    workflow_id = new_ids[0] if len(new_ids) == 1 else None
    return result, workflow_id


def _register_draft(
    draft_id: str,
    files_affected: list[str],
    file_operations: list[dict],
) -> None:
    record = {
        "draft_id": draft_id,
        "source": "CDM",
        "intent_summary": "intent",
        "scope_summary": "scope",
        "files_affected": files_affected,
        "file_operations": file_operations,
        "tests_allowed": False,
        "test_commands": [],
        "output": "draft output",
    }
    record["draft_hash"] = runtime_mod._compute_draft_hash(record)
    runtime_mod._cdm_drafts[draft_id] = record



def _register_executable_tool(tool_draft_id: str = "tool-draft-workflow-001", tool_name: str = "demo.hello") -> None:
    draft = {
        "tool_draft_id": tool_draft_id,
        "source": "TDM",
        "mode": "tool",
        "tool_name": tool_name,
        "tool_purpose": "Workflow test fixture.",
        "justification": "Workflow test fixture.",
        "inputs": [
            {
                "name": "query",
                "type": "string",
                "required": True,
                "description": "Query text",
            }
        ],
        "outputs": [
            {
                "name": "result_summary",
                "type": "string",
                "description": "Result summary",
            }
        ],
        "declared_side_effects": ["none declared"],
        "safety_constraints": ["Execution requires explicit confirmation."],
        "when_to_use": "For deterministic tests.",
        "when_not_to_use": "Outside deterministic tests.",
        "spec": {
            "name": tool_name,
            "description": "Workflow fixture spec",
            "inputs": [],
            "outputs": [],
            "side_effects": ["none declared"],
            "safety_constraints": [],
            "execution": {"enabled": False},
            "executability": {
                "enabled": True,
                "requires_confirmation": True,
            },
        },
        "output": "fixture output",
    }
    draft["tool_draft_hash"] = runtime_mod._compute_tool_draft_hash(draft)
    runtime_mod._tool_drafts[tool_draft_id] = draft

    ok, _ = runtime_mod._approve_tool_draft(tool_draft_id, "human")
    assert ok
    ok, _ = runtime_mod._register_tool_draft(tool_draft_id, "human")
    assert ok


def _audit_events_for(workflow_id: str) -> list[dict]:
    return [entry for entry in runtime_mod._workflow_audit if entry.get("workflow_id") == workflow_id]


def test_workflow_creation_supports_allowed_step_types_and_identity_changes():
    _reset_workflow_state()
    runtime = runtime_mod.BillyRuntime(config={})

    first_result, first_workflow_id = _define_workflow(
        runtime,
        [
            {"type": "cam.apply", "draft_id": "draft-a"},
            {"type": "tem.run", "tool_name": "demo.hello", "payload": {"query": "x"}},
            {"type": "tem.confirm", "tool_name": "demo.hello"},
        ],
        trace_id="trace-workflow-first",
    )

    second_result, second_workflow_id = _define_workflow(
        runtime,
        [{"type": "cam.apply", "draft_id": "draft-b"}],
        trace_id="trace-workflow-second",
    )

    assert first_result["status"] == "success"
    assert second_result["status"] == "success"
    assert "WORKFLOW_DEFINED" in first_result["final_output"]
    assert first_workflow_id is not None
    assert second_workflow_id is not None
    assert first_workflow_id != second_workflow_id
    assert runtime_mod._workflows[first_workflow_id]["workflow_hash"] != runtime_mod._workflows[second_workflow_id]["workflow_hash"]


def test_workflow_artifact_is_immutable_via_hash_check():
    _reset_workflow_state()
    runtime = runtime_mod.BillyRuntime(config={})

    define_result, workflow_id = _define_workflow(
        runtime,
        [{"type": "cam.apply", "draft_id": "draft-immutable"}],
        trace_id="trace-workflow-immutable-define",
    )
    assert define_result["status"] == "success"
    assert workflow_id is not None

    runtime_mod._workflows[workflow_id]["steps"][0]["draft_id"] = "draft-mutated"

    approval_result = runtime.run_turn(
        f"approve workflow: {workflow_id}",
        {"trace_id": "trace-workflow-immutable-approve"},
    )

    assert approval_result["status"] == "error"
    assert approval_result["final_output"] == "Workflow approval rejected: workflow artifact has changed."
    assert workflow_id not in runtime_mod._approved_workflows


def test_workflow_execution_requires_explicit_approval():
    _reset_workflow_state()
    runtime = runtime_mod.BillyRuntime(config={})

    define_result, workflow_id = _define_workflow(
        runtime,
        [{"type": "cam.apply", "draft_id": "draft-needs-approval"}],
        trace_id="trace-workflow-needs-approval-define",
    )
    assert define_result["status"] == "success"
    assert workflow_id is not None

    run_result = runtime.run_turn(
        f"run workflow: {workflow_id}",
        {"trace_id": "trace-workflow-needs-approval-run"},
    )

    assert run_result["status"] == "error"
    assert run_result["final_output"] == "Workflow execution rejected: workflow is not approved."


def test_workflow_cam_step_revalidates_using_cam_checks():
    _reset_workflow_state()
    runtime = runtime_mod.BillyRuntime(config={})

    _register_draft(
        draft_id="draft-unapproved",
        files_affected=["notes/unapproved.txt"],
        file_operations=[{"action": "create", "path": "notes/unapproved.txt", "content": "x\n"}],
    )

    define_result, workflow_id = _define_workflow(
        runtime,
        [{"type": "cam.apply", "draft_id": "draft-unapproved"}],
        trace_id="trace-workflow-cam-define",
    )
    assert define_result["status"] == "success"
    runtime.run_turn(f"approve workflow: {workflow_id}", {"trace_id": "trace-workflow-cam-approve"})

    run_result = runtime.run_turn(f"run workflow: {workflow_id}", {"trace_id": "trace-workflow-cam-run"})

    assert run_result["status"] == "error"
    assert "Apply rejected: draft is not approved." in run_result["final_output"]
    step_events = [event for event in _audit_events_for(workflow_id) if event.get("event_type") == "workflow_step"]
    assert len(step_events) == 1
    assert step_events[0]["details"]["mapped_mode"] == "CAM"
    assert step_events[0]["details"]["validation_outcome"] == "passed"
    assert step_events[0]["details"]["execution_outcome"] == "failed"


def test_workflow_tem_step_revalidates_using_tem_checks():
    _reset_workflow_state()
    runtime = runtime_mod.BillyRuntime(config={})

    _register_executable_tool(tool_name="demo.hello")
    define_result, workflow_id = _define_workflow(
        runtime,
        [{"type": "tem.run", "tool_name": "demo.hello", "payload": {}}],
        trace_id="trace-workflow-tem-define",
    )
    assert define_result["status"] == "success"
    runtime.run_turn(f"approve workflow: {workflow_id}", {"trace_id": "trace-workflow-tem-approve"})

    run_result = runtime.run_turn(f"run workflow: {workflow_id}", {"trace_id": "trace-workflow-tem-run"})

    assert run_result["status"] == "error"
    assert "Tool execution rejected: payload is missing required fields." in run_result["final_output"]
    step_events = [event for event in _audit_events_for(workflow_id) if event.get("event_type") == "workflow_step"]
    assert len(step_events) == 1
    assert step_events[0]["details"]["mapped_mode"] == "TEM"
    assert step_events[0]["details"]["validation_outcome"] == "passed"
    assert step_events[0]["details"]["execution_outcome"] == "failed"


def test_workflow_stops_on_first_failure_and_does_not_execute_remaining_steps(monkeypatch):
    _reset_workflow_state()
    runtime = runtime_mod.BillyRuntime(config={})

    calls = {"confirm": 0}

    def _fake_confirm(*_args, **_kwargs):
        calls["confirm"] += 1
        return True, "should not be called"

    monkeypatch.setattr(runtime_mod, "_handle_confirm_run_tool", _fake_confirm)

    define_result, workflow_id = _define_workflow(
        runtime,
        [
            {"type": "cam.apply", "draft_id": "draft-missing"},
            {"type": "tem.confirm", "tool_name": "demo.hello"},
        ],
        trace_id="trace-workflow-failstop-define",
    )
    assert define_result["status"] == "success"
    runtime.run_turn(f"approve workflow: {workflow_id}", {"trace_id": "trace-workflow-failstop-approve"})

    run_result = runtime.run_turn(f"run workflow: {workflow_id}", {"trace_id": "trace-workflow-failstop-run"})

    assert run_result["status"] == "error"
    assert "- completed_steps: 0" in run_result["final_output"]
    assert "- failed_step: 1" in run_result["final_output"]
    assert calls["confirm"] == 0
    assert runtime_mod._workflows[workflow_id]["status"] == "failed"
    step_events = [event for event in _audit_events_for(workflow_id) if event.get("event_type") == "workflow_step"]
    assert len(step_events) == 1


def test_workflow_audit_records_lifecycle_and_step_details_on_success(tmp_path, monkeypatch):
    _reset_workflow_state()
    monkeypatch.setattr(runtime_mod, "_PROJECT_ROOT", tmp_path)
    runtime = runtime_mod.BillyRuntime(config={})

    _register_draft(
        draft_id="draft-success",
        files_affected=["notes/workflow-success.txt"],
        file_operations=[
            {"action": "create", "path": "notes/workflow-success.txt", "content": "ok\n"}
        ],
    )
    ok, _ = runtime_mod._approve_cdm_draft("draft-success", "human")
    assert ok

    define_result, workflow_id = _define_workflow(
        runtime,
        [{"type": "cam.apply", "draft_id": "draft-success"}],
        trace_id="trace-workflow-audit-define",
    )
    assert define_result["status"] == "success"

    approve_result = runtime.run_turn(
        f"approve workflow: {workflow_id}",
        {"trace_id": "trace-workflow-audit-approve", "approved_by": "chad"},
    )
    assert approve_result["status"] == "success"

    run_result = runtime.run_turn(
        f"run workflow: {workflow_id}",
        {"trace_id": "trace-workflow-audit-run"},
    )

    assert run_result["status"] == "success"
    assert "- result: success" in run_result["final_output"]
    assert (tmp_path / "notes/workflow-success.txt").read_text(encoding="utf-8") == "ok\n"

    events = _audit_events_for(workflow_id)
    event_types = [event["event_type"] for event in events]
    assert event_types == [
        "workflow_defined",
        "workflow_approved",
        "workflow_run_started",
        "workflow_step",
        "workflow_terminal",
    ]

    step_event = events[3]
    assert step_event["details"]["mapped_mode"] == "CAM"
    assert step_event["details"]["validation_outcome"] == "passed"
    assert step_event["details"]["execution_outcome"] == "success"
    assert step_event["details"]["side_effect_summary"] == "code application via CAM"

    terminal_event = events[4]
    assert terminal_event["details"]["terminal_outcome"] == "success"
    assert terminal_event["details"]["completed_steps"] == 1


def test_workflow_rejects_invalid_step_type_and_fields():
    _reset_workflow_state()
    runtime = runtime_mod.BillyRuntime(config={})

    invalid_type = runtime.run_turn(
        'workflow: {"steps":[{"type":"unknown.step"}]}',
        {"trace_id": "trace-workflow-invalid-type"},
    )
    assert invalid_type["status"] == "error"
    assert "Workflow rejected: step 1 uses unsupported type" in invalid_type["final_output"]

    invalid_fields = runtime.run_turn(
        'workflow: {"steps":[{"type":"cam.apply","draft_id":"d1","extra":true}]}',
        {"trace_id": "trace-workflow-invalid-fields"},
    )
    assert invalid_fields["status"] == "error"
    assert invalid_fields["final_output"] == "Workflow rejected: step 1 has unsupported fields."
    assert not runtime_mod._workflows


def test_workflow_maturity_sync_violation_rejects_operation(monkeypatch):
    _reset_workflow_state()
    runtime = runtime_mod.BillyRuntime(config={})

    monkeypatch.setitem(
        runtime_mod._WORKFLOW_LAYER_MATURITY_DECLARATIONS,
        "reasoning",
        {"highest_supported": 3, "lowest_required_upstream": 1},
    )

    result = runtime.run_turn(
        'workflow: {"steps":[{"type":"cam.apply","draft_id":"draft-a"}]}',
        {"trace_id": "trace-workflow-maturity"},
    )

    assert result["status"] == "error"
    assert result["final_output"] == "Workflow rejected: maturity sync violation in layer 'reasoning'."


def test_workflow_commands_short_circuit_other_runtime_paths(monkeypatch):
    _reset_workflow_state()
    runtime = runtime_mod.BillyRuntime(config={})

    def _fail(*_args, **_kwargs):
        raise AssertionError("Workflow mode must not leak into unrelated runtime paths.")

    monkeypatch.setattr(runtime_mod, "_run_deterministic_loop", _fail)
    monkeypatch.setattr(runtime_mod, "_requires_barn_inspection", _fail)
    monkeypatch.setattr(runtime_mod, "_classify_preinspection_route", _fail)

    result = runtime.run_turn(
        'workflow: {"steps":[{"type":"cam.apply","draft_id":"draft-a"}]}',
        {"trace_id": "trace-workflow-short-circuit"},
    )

    assert result["status"] == "success"
    assert "WORKFLOW_DEFINED" in result["final_output"]


def test_workflow_approval_does_not_imply_execution():
    _reset_workflow_state()
    runtime = runtime_mod.BillyRuntime(config={})

    define_result, workflow_id = _define_workflow(
        runtime,
        [{"type": "cam.apply", "draft_id": "draft-a"}],
        trace_id="trace-workflow-approval-only-define",
    )
    assert define_result["status"] == "success"

    approve_result = runtime.run_turn(
        f"approve workflow: {workflow_id}",
        {"trace_id": "trace-workflow-approval-only-approve"},
    )

    assert approve_result["status"] == "success"
    assert runtime_mod._workflows[workflow_id]["status"] == "approved"
    event_types = [event["event_type"] for event in _audit_events_for(workflow_id)]
    assert "workflow_run_started" not in event_types
    assert "workflow_terminal" not in event_types


def test_ask_routes_explicit_workflow_command_to_runtime(monkeypatch):
    _reset_workflow_state()
    runtime = runtime_mod.BillyRuntime(config={})
    observed = {}

    def _fail_llm(_prompt: str) -> str:
        raise AssertionError("Workflow control commands must not route to _llm_answer.")

    def _fake_run_turn(user_input: str, session_context: dict):
        observed["user_input"] = user_input
        observed["trace_id"] = session_context.get("trace_id")
        return {
            "final_output": "workflow-output",
            "tool_calls": [],
            "status": "success",
            "trace_id": "trace-workflow-ask",
        }

    monkeypatch.setattr(runtime, "_llm_answer", _fail_llm)
    monkeypatch.setattr(runtime, "run_turn", _fake_run_turn)

    response = runtime.ask('workflow: {"steps":[{"type":"cam.apply","draft_id":"draft-a"}]}')

    assert response == "workflow-output"
    assert observed["user_input"] == 'workflow: {"steps":[{"type":"cam.apply","draft_id":"draft-a"}]}'
    assert observed["trace_id"]
