import v2.core.runtime as runtime_mod


def _reset_tem_state():
    runtime_mod._tool_drafts.clear()
    runtime_mod._approved_tools.clear()
    runtime_mod._tool_approval_audit.clear()
    runtime_mod._registered_tools.clear()
    runtime_mod._tool_registration_audit.clear()
    runtime_mod._pending_tool_executions.clear()
    runtime_mod._tool_execution_audit.clear()


def _make_tool_draft(
    tool_draft_id: str,
    tool_name: str = "demo.hello",
    executability_enabled: bool = True,
    requires_confirmation: bool = True,
    declared_side_effects: list[str] | None = None,
    inputs: list[dict] | None = None,
):
    if declared_side_effects is None:
        declared_side_effects = ["none declared"]
    if inputs is None:
        inputs = [
            {
                "name": "query",
                "type": "string",
                "required": True,
                "description": "Query text",
            }
        ]
    record = {
        "tool_draft_id": tool_draft_id,
        "source": "TDM",
        "mode": "tool",
        "tool_name": tool_name,
        "tool_purpose": "Test tool execution flow.",
        "justification": "Test fixture",
        "inputs": inputs,
        "outputs": [
            {
                "name": "result_summary",
                "type": "string",
                "description": "Result",
            }
        ],
        "declared_side_effects": declared_side_effects,
        "safety_constraints": ["Execution requires explicit confirmation."],
        "when_to_use": "For tests.",
        "when_not_to_use": "Outside tests.",
        "spec": {
            "name": tool_name,
            "description": "Fixture spec",
            "inputs": [],
            "outputs": [],
            "side_effects": declared_side_effects,
            "safety_constraints": [],
            "execution": {"enabled": False},
            "executability": {
                "enabled": executability_enabled,
                "requires_confirmation": requires_confirmation,
            },
        },
        "output": "fixture output",
    }
    record["tool_draft_hash"] = runtime_mod._compute_tool_draft_hash(record)
    return record


def _register_fixture_tool(
    tool_draft_id: str = "tool-draft-tem-001",
    tool_name: str = "demo.hello",
    executability_enabled: bool = True,
    requires_confirmation: bool = True,
    declared_side_effects: list[str] | None = None,
    inputs: list[dict] | None = None,
):
    draft = _make_tool_draft(
        tool_draft_id=tool_draft_id,
        tool_name=tool_name,
        executability_enabled=executability_enabled,
        requires_confirmation=requires_confirmation,
        declared_side_effects=declared_side_effects,
        inputs=inputs,
    )
    runtime_mod._tool_drafts[tool_draft_id] = draft
    ok, _ = runtime_mod._approve_tool_draft(tool_draft_id, "human")
    assert ok
    ok, _ = runtime_mod._register_tool_draft(tool_draft_id, "human")
    assert ok
    return draft


def test_tem_rejects_unknown_tool():
    _reset_tem_state()
    runtime = runtime_mod.BillyRuntime(config={})

    result = runtime.run_turn('run tool: missing.tool {"query":"x"}', {"trace_id": "trace-unknown-tool"})

    assert result["status"] == "error"
    assert result["final_output"] == "Tool execution rejected: tool is not registered."


def test_tem_rejects_unapproved_tool():
    _reset_tem_state()
    runtime = runtime_mod.BillyRuntime(config={})

    runtime_mod._registered_tools["demo.hello@tool-draft-unapproved"] = {
        "registration_key": "demo.hello@tool-draft-unapproved",
        "tool_name": "demo.hello",
        "tool_draft_id": "tool-draft-unapproved",
        "intent": "unapproved",
        "contract": {"inputs": [], "outputs": []},
        "declared_side_effects": ["none declared"],
        "safety_constraints": [],
        "visibility": "visible",
        "executability": True,
        "requires_confirmation": True,
        "registered_by": "human",
        "registered_at": "2026-01-01T00:00:00+00:00",
        "source": "TRM",
    }

    result = runtime.run_turn('run tool: demo.hello {"query":"x"}', {"trace_id": "trace-unapproved-tool"})

    assert result["status"] == "error"
    assert result["final_output"] == "Tool execution rejected: tool is not approved."


def test_tem_rejects_unregistered_tool():
    _reset_tem_state()
    runtime = runtime_mod.BillyRuntime(config={})

    draft = _make_tool_draft("tool-draft-not-registered", tool_name="demo.hello")
    runtime_mod._tool_drafts["tool-draft-not-registered"] = draft
    ok, _ = runtime_mod._approve_tool_draft("tool-draft-not-registered", "human")
    assert ok

    result = runtime.run_turn('run tool: demo.hello {"query":"x"}', {"trace_id": "trace-unregistered-tool"})

    assert result["status"] == "error"
    assert result["final_output"] == "Tool execution rejected: tool is not registered."


def test_tem_rejects_executability_disabled():
    _reset_tem_state()
    runtime = runtime_mod.BillyRuntime(config={})
    _register_fixture_tool(executability_enabled=False)

    result = runtime.run_turn('run tool: demo.hello {"query":"x"}', {"trace_id": "trace-disabled"})

    assert result["status"] == "error"
    assert result["final_output"] == "Tool execution rejected: executability is disabled."


def test_tem_rejects_schema_mismatch():
    _reset_tem_state()
    runtime = runtime_mod.BillyRuntime(config={})
    _register_fixture_tool()

    missing = runtime.run_turn("run tool: demo.hello {}", {"trace_id": "trace-missing-field"})
    assert missing["status"] == "error"
    assert missing["final_output"] == "Tool execution rejected: payload is missing required fields."

    extra = runtime.run_turn(
        'run tool: demo.hello {"query":"x","unexpected":"y"}',
        {"trace_id": "trace-extra-field"},
    )
    assert extra["status"] == "error"
    assert extra["final_output"] == "Tool execution rejected: payload contains unsupported fields."


def test_tem_rejects_side_effect_scope_violation():
    _reset_tem_state()
    runtime = runtime_mod.BillyRuntime(config={})
    _register_fixture_tool(
        declared_side_effects=["none declared"],
        inputs=[
            {
                "name": "query",
                "type": "string",
                "required": True,
                "description": "Query text",
            },
            {
                "name": "target_path",
                "type": "string",
                "required": False,
                "description": "Optional target path",
            },
        ],
    )

    result = runtime.run_turn(
        'run tool: demo.hello {"query":"x","target_path":"/tmp/demo.txt"}',
        {"trace_id": "trace-scope"},
    )

    assert result["status"] == "error"
    assert result["final_output"] == "Tool execution rejected: side-effect scope exceeds declaration."


def test_tem_run_tool_does_not_execute_before_confirmation(monkeypatch):
    _reset_tem_state()
    runtime = runtime_mod.BillyRuntime(config={})
    _register_fixture_tool()

    called = {"count": 0}

    def _fake_run(*_args, **_kwargs):
        called["count"] += 1
        return {"status": "success", "stdout": "ok", "stderr": "", "artifact": "a.txt"}

    monkeypatch.setattr(runtime_mod._docker_runner, "run", _fake_run)

    pending = runtime.run_turn('run tool: demo.hello {"query":"x"}', {"trace_id": "trace-pending"})

    assert pending["status"] == "success"
    assert "TOOL_EXECUTION_PENDING" in pending["final_output"]
    assert called["count"] == 0
    assert not runtime_mod._tool_execution_audit


def test_tem_executes_only_after_confirmation_and_confirm_not_reusable(monkeypatch):
    _reset_tem_state()
    runtime = runtime_mod.BillyRuntime(config={})
    _register_fixture_tool()

    called = {"count": 0}

    def _fake_run(*_args, **_kwargs):
        called["count"] += 1
        return {"status": "success", "stdout": "done", "stderr": "", "artifact": "out.txt"}

    monkeypatch.setattr(runtime_mod._docker_runner, "run", _fake_run)

    pending = runtime.run_turn('run tool: demo.hello {"query":"x"}', {"trace_id": "trace-run"})
    assert pending["status"] == "success"

    confirmed = runtime.run_turn("confirm run tool: demo.hello", {"trace_id": "trace-confirm"})
    assert confirmed["status"] == "success"
    assert "TOOL_EXECUTION_RESULT" in confirmed["final_output"]
    assert called["count"] == 1
    assert len(runtime_mod._tool_execution_audit) == 1

    reused = runtime.run_turn("confirm run tool: demo.hello", {"trace_id": "trace-reuse"})
    assert reused["status"] == "error"
    assert reused["final_output"] == "Tool execution rejected: no pending execution for this tool."
    assert called["count"] == 1


def test_tem_no_routing_or_ops_leakage(monkeypatch):
    _reset_tem_state()
    runtime = runtime_mod.BillyRuntime(config={})
    _register_fixture_tool()

    def _fail(*_args, **_kwargs):
        raise AssertionError("TEM path must not leak into other runtime routes.")

    monkeypatch.setattr(runtime_mod, "_run_deterministic_loop", _fail)
    monkeypatch.setattr(runtime_mod, "_requires_barn_inspection", _fail)
    monkeypatch.setattr(runtime_mod, "_classify_preinspection_route", _fail)
    monkeypatch.setattr(runtime_mod._docker_runner, "run", _fail)

    result = runtime.run_turn('run tool: demo.hello {"query":"x"}', {"trace_id": "trace-no-leak"})

    assert result["status"] == "success"
    assert "TOOL_EXECUTION_PENDING" in result["final_output"]


def test_tem_execution_audit_is_append_only(monkeypatch):
    _reset_tem_state()
    runtime = runtime_mod.BillyRuntime(config={})
    _register_fixture_tool()

    def _fake_run(*_args, **_kwargs):
        return {"status": "success", "stdout": "ok", "stderr": "", "artifact": "a.txt"}

    monkeypatch.setattr(runtime_mod._docker_runner, "run", _fake_run)

    runtime.run_turn('run tool: demo.hello {"query":"x"}', {"trace_id": "trace-audit-1"})
    runtime.run_turn("confirm run tool: demo.hello", {"trace_id": "trace-audit-1-confirm"})
    first_record = dict(runtime_mod._tool_execution_audit[0])

    runtime.run_turn('run tool: demo.hello {"query":"y"}', {"trace_id": "trace-audit-2"})
    runtime.run_turn("confirm run tool: demo.hello", {"trace_id": "trace-audit-2-confirm"})

    assert len(runtime_mod._tool_execution_audit) == 2
    assert runtime_mod._tool_execution_audit[0] == first_record
