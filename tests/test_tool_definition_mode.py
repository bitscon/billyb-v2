import v2.core.runtime as runtime_mod


def _reset_tdm_state():
    runtime_mod._tool_drafts.clear()
    runtime_mod._approved_tools.clear()
    runtime_mod._tool_approval_audit.clear()


def _make_tool_record(tool_draft_id: str, source: str = "TDM") -> dict:
    record = {
        "tool_draft_id": tool_draft_id,
        "source": source,
        "tool_name": "log.scan",
        "tool_purpose": "Scan logs for specific patterns.",
        "justification": "Reusable contract for log scanning.",
        "inputs": [
            {
                "name": "request_context",
                "type": "string",
                "required": True,
                "description": "Context input",
            }
        ],
        "outputs": [
            {
                "name": "result_summary",
                "type": "string",
                "description": "Summary output",
            }
        ],
        "declared_side_effects": ["none declared"],
        "safety_constraints": ["Execution disabled"],
        "when_to_use": "Use for log pattern design.",
        "when_not_to_use": "Do not use for execution.",
        "spec": {
            "name": "log.scan",
            "description": "Scan logs for specific patterns.",
            "inputs": [],
            "outputs": [],
            "side_effects": [],
            "safety_constraints": [],
            "execution": {"enabled": False},
        },
        "output": "tool draft output",
    }
    record["tool_draft_hash"] = runtime_mod._compute_tool_draft_hash(record)
    return record


def test_tdm_run_turn_routes_explicit_prefix_and_is_read_only(monkeypatch):
    _reset_tdm_state()
    runtime = runtime_mod.BillyRuntime(config={})

    def _fail(*_args, **_kwargs):
        raise AssertionError("TDM should short-circuit before execution/ops paths.")

    monkeypatch.setattr(runtime_mod, "_run_deterministic_loop", _fail)
    monkeypatch.setattr(runtime_mod, "_requires_barn_inspection", _fail)
    monkeypatch.setattr(runtime_mod._docker_runner, "run", _fail)
    monkeypatch.setattr(runtime_mod._tool_registry, "register", _fail)

    result = runtime.run_turn("tool: design log.scan for service diagnostics", {})

    assert result["status"] == "success"
    assert result["tool_calls"] == []
    output = result["final_output"]
    headings = [
        "Tool Intent",
        "Justification",
        "Tool Contract",
        "Inputs",
        "Outputs",
        "Declared side effects",
        "Safety Constraints",
        "Usage Guidance",
        "When to use",
        "When not to use",
        "Proposed Specification",
        "YAML / JSON (draft only)",
        "Approval Request",
    ]
    positions = [output.index(h) for h in headings]
    assert positions == sorted(positions)
    assert runtime_mod._tool_drafts


def test_tdm_draft_has_id_and_stable_hash():
    _reset_tdm_state()
    runtime = runtime_mod.BillyRuntime(config={})

    result = runtime.run_turn("define tool: parser.audit for config files", {"trace_id": "trace-tdm"})

    assert result["status"] == "success"
    tool_draft_id, record = next(iter(runtime_mod._tool_drafts.items()))
    assert tool_draft_id.startswith("tool-draft-")
    assert isinstance(record.get("tool_draft_hash"), str)
    assert len(record["tool_draft_hash"]) == 64
    assert record["tool_draft_hash"] == runtime_mod._compute_tool_draft_hash(record)
    assert tool_draft_id in result["final_output"]
    assert record["tool_draft_hash"] in result["final_output"]


def test_ask_routes_explicit_tdm_prefix_to_runtime(monkeypatch):
    _reset_tdm_state()
    runtime = runtime_mod.BillyRuntime(config={})
    observed = {}

    def _fail_llm(_prompt: str) -> str:
        raise AssertionError("Explicit TDM input should not call _llm_answer.")

    def _fake_run_turn(user_input: str, session_context: dict):
        observed["user_input"] = user_input
        observed["trace_id"] = session_context.get("trace_id")
        return {"final_output": "tdm-output", "tool_calls": [], "status": "success", "trace_id": "trace-tdm"}

    monkeypatch.setattr(runtime, "_llm_answer", _fail_llm)
    monkeypatch.setattr(runtime, "run_turn", _fake_run_turn)

    response = runtime.ask("design tool: trace.analyzer for audits")

    assert response == "tdm-output"
    assert observed["user_input"] == "design tool: trace.analyzer for audits"
    assert observed["trace_id"]


def test_ask_requires_explicit_tdm_prefix(monkeypatch):
    _reset_tdm_state()
    runtime = runtime_mod.BillyRuntime(config={})
    llm_calls = []

    def _fake_llm(prompt: str) -> str:
        llm_calls.append(prompt)
        return "llm-response"

    def _fail_run_turn(_user_input: str, _session_context: dict):
        raise AssertionError("Non-prefixed tool wording should not route to TDM.")

    monkeypatch.setattr(runtime, "_llm_answer", _fake_llm)
    monkeypatch.setattr(runtime, "run_turn", _fail_run_turn)

    response = runtime.ask("please design a tool for audits")

    assert response == "llm-response"
    assert llm_calls == ["please design a tool for audits"]


def test_tool_approval_succeeds_for_valid_tool_draft():
    _reset_tdm_state()
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("propose tool: cache.inspect for debugging", {"trace_id": "trace-tool-draft"})
    tool_draft_id = next(iter(runtime_mod._tool_drafts.keys()))

    result = runtime.run_turn(
        f"approve tool: {tool_draft_id}",
        {"trace_id": "trace-tool-approve", "approved_by": "chad"},
    )

    assert result["status"] == "success"
    assert "TOOL_APPROVAL_ACCEPTED" in result["final_output"]
    assert tool_draft_id in runtime_mod._approved_tools
    approval = runtime_mod._approved_tools[tool_draft_id][0]
    assert approval["tool_draft_id"] == tool_draft_id
    assert approval["approved_by"] == "chad"
    assert approval["status"] == "approved"
    assert approval["source"] == "TDM"
    assert runtime_mod._tool_approval_audit


def test_tool_approval_fails_for_unknown_tool_draft_id():
    _reset_tdm_state()
    runtime = runtime_mod.BillyRuntime(config={})

    result = runtime.run_turn("approve tool: tool-draft-missing", {"trace_id": "trace-tool-missing"})

    assert result["status"] == "error"
    assert result["final_output"] == "Tool approval rejected: tool_draft_id does not exist."


def test_tool_approval_fails_for_non_tdm_source():
    _reset_tdm_state()
    runtime = runtime_mod.BillyRuntime(config={})
    runtime_mod._tool_drafts["tool-draft-non-tdm"] = _make_tool_record("tool-draft-non-tdm", source="CDM")

    result = runtime.run_turn("approve tool: tool-draft-non-tdm", {"trace_id": "trace-tool-non-tdm"})

    assert result["status"] == "error"
    assert result["final_output"] == "Tool approval rejected: draft is not from TDM."


def test_tool_approval_fails_on_hash_mismatch():
    _reset_tdm_state()
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("tool: build deploy.guard contract", {"trace_id": "trace-tool-hash"})
    tool_draft_id = next(iter(runtime_mod._tool_drafts.keys()))
    runtime_mod._tool_drafts[tool_draft_id]["spec"]["description"] = "mutated"

    result = runtime.run_turn(f"approve tool: {tool_draft_id}", {"trace_id": "trace-tool-hash-check"})

    assert result["status"] == "error"
    assert result["final_output"] == "Tool approval rejected: draft content hash mismatch."


def test_tool_approval_short_circuits_execution_paths(monkeypatch):
    _reset_tdm_state()
    runtime = runtime_mod.BillyRuntime(config={})
    runtime_mod._tool_drafts["tool-draft-safe"] = _make_tool_record("tool-draft-safe", source="TDM")

    def _fail(*_args, **_kwargs):
        raise AssertionError("Tool approval must not leak into execution/ops/tool paths.")

    monkeypatch.setattr(runtime_mod, "_run_deterministic_loop", _fail)
    monkeypatch.setattr(runtime_mod, "_requires_barn_inspection", _fail)
    monkeypatch.setattr(runtime_mod, "_classify_preinspection_route", _fail)
    monkeypatch.setattr(runtime_mod._docker_runner, "run", _fail)
    monkeypatch.setattr(runtime_mod._tool_registry, "register", _fail)

    result = runtime.run_turn("approve tool: tool-draft-safe", {"trace_id": "trace-tool-safe"})

    assert result["status"] == "success"
    assert "TOOL_APPROVAL_ACCEPTED" in result["final_output"]
