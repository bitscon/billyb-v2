import v2.core.runtime as runtime_mod


def _reset_trm_state():
    runtime_mod._tool_drafts.clear()
    runtime_mod._approved_tools.clear()
    runtime_mod._tool_approval_audit.clear()
    runtime_mod._registered_tools.clear()
    runtime_mod._tool_registration_audit.clear()


def test_tool_registration_succeeds_for_approved_tool_draft():
    _reset_trm_state()
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("tool: design log.scan for diagnostics", {"trace_id": "trace-tdm"})
    tool_draft_id, draft = next(iter(runtime_mod._tool_drafts.items()))
    runtime.run_turn(f"approve tool: {tool_draft_id}", {"trace_id": "trace-approve"})

    result = runtime.run_turn(
        f"register tool: {tool_draft_id}",
        {"trace_id": "trace-register", "registered_by": "chad"},
    )

    assert result["status"] == "success"
    assert "TOOL_REGISTRATION_ACCEPTED" in result["final_output"]
    assert "This tool is registered and visible, but not executable." in result["final_output"]
    key = f"{draft['tool_name']}@{tool_draft_id}"
    assert key in runtime_mod._registered_tools
    entry = runtime_mod._registered_tools[key]
    assert entry["visibility"] == "visible"
    assert entry["executability"] is False
    assert entry["tool_draft_id"] == tool_draft_id
    assert runtime_mod._tool_registration_audit


def test_tool_registration_rejects_unknown_tool_draft_id():
    _reset_trm_state()
    runtime = runtime_mod.BillyRuntime(config={})

    result = runtime.run_turn("register tool: tool-draft-missing", {"trace_id": "trace-missing"})

    assert result["status"] == "error"
    assert result["final_output"] == "Tool registration rejected: tool_draft_id does not exist."
    assert not runtime_mod._registered_tools


def test_tool_registration_rejects_unapproved_tool_draft():
    _reset_trm_state()
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("define tool: parser.guard for configs", {"trace_id": "trace-draft"})
    tool_draft_id = next(iter(runtime_mod._tool_drafts.keys()))

    result = runtime.run_turn(f"register tool: {tool_draft_id}", {"trace_id": "trace-unapproved"})

    assert result["status"] == "error"
    assert result["final_output"] == "Tool registration rejected: tool draft is not approved."
    assert not runtime_mod._registered_tools


def test_tool_registration_rejects_hash_mismatch():
    _reset_trm_state()
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("propose tool: cache.audit for traces", {"trace_id": "trace-draft"})
    tool_draft_id = next(iter(runtime_mod._tool_drafts.keys()))
    runtime.run_turn(f"approve tool: {tool_draft_id}", {"trace_id": "trace-approve"})
    runtime_mod._tool_drafts[tool_draft_id]["spec"]["description"] = "mutated"

    result = runtime.run_turn(f"register tool: {tool_draft_id}", {"trace_id": "trace-hash"})

    assert result["status"] == "error"
    assert result["final_output"] == "Tool registration rejected: tool draft hash mismatch."
    assert not runtime_mod._registered_tools


def test_tool_registration_rejects_duplicate_registration():
    _reset_trm_state()
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("design tool: trace.guard for services", {"trace_id": "trace-draft"})
    tool_draft_id = next(iter(runtime_mod._tool_drafts.keys()))
    runtime.run_turn(f"approve tool: {tool_draft_id}", {"trace_id": "trace-approve"})

    first = runtime.run_turn(f"register tool: {tool_draft_id}", {"trace_id": "trace-first"})
    second = runtime.run_turn(f"register tool: {tool_draft_id}", {"trace_id": "trace-second"})

    assert first["status"] == "success"
    assert second["status"] == "error"
    assert second["final_output"] == "Tool registration rejected: tool draft is already registered."
    assert len(runtime_mod._registered_tools) == 1
    assert len(runtime_mod._tool_registration_audit) == 1


def test_registered_tools_are_visible_to_erm_and_cdm():
    _reset_trm_state()
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("tool: define metrics.scan for logs", {"trace_id": "trace-draft"})
    tool_draft_id, draft = next(iter(runtime_mod._tool_drafts.items()))
    runtime.run_turn(f"approve tool: {tool_draft_id}", {"trace_id": "trace-approve"})
    runtime.run_turn(f"register tool: {tool_draft_id}", {"trace_id": "trace-register"})
    label = f"{draft['tool_name']}@{tool_draft_id}"

    erm = runtime.run_turn("engineer: map diagnostics flow", {"trace_id": "trace-erm"})
    cdm = runtime.run_turn("draft: update diagnostics docs", {"trace_id": "trace-cdm"})

    assert label in erm["final_output"]
    assert label in cdm["final_output"]


def test_registered_tools_are_not_executable(monkeypatch):
    _reset_trm_state()
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("tool: create inert.tool proposal", {"trace_id": "trace-draft"})
    tool_draft_id, draft = next(iter(runtime_mod._tool_drafts.items()))
    runtime.run_turn(f"approve tool: {tool_draft_id}", {"trace_id": "trace-approve"})
    runtime.run_turn(f"register tool: {tool_draft_id}", {"trace_id": "trace-register"})

    def _fail(*_args, **_kwargs):
        raise AssertionError("Registered tools must not execute.")

    monkeypatch.setattr(runtime_mod._docker_runner, "run", _fail)
    result = runtime.run_turn(
        f'run tool: {draft["tool_name"]} {{"query":"x"}}',
        {"trace_id": "trace-run"},
    )

    assert result["status"] == "error"
    assert result["final_output"] == "Tool execution rejected: executability is disabled."


def test_tool_registration_short_circuits_runtime_leakage(monkeypatch):
    _reset_trm_state()
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("tool: define audit.guard", {"trace_id": "trace-draft"})
    tool_draft_id = next(iter(runtime_mod._tool_drafts.keys()))
    runtime.run_turn(f"approve tool: {tool_draft_id}", {"trace_id": "trace-approve"})

    def _fail(*_args, **_kwargs):
        raise AssertionError("TRM must not leak into unrelated runtime paths.")

    monkeypatch.setattr(runtime_mod, "_run_deterministic_loop", _fail)
    monkeypatch.setattr(runtime_mod, "_requires_barn_inspection", _fail)
    monkeypatch.setattr(runtime_mod, "_classify_preinspection_route", _fail)
    monkeypatch.setattr(runtime_mod._docker_runner, "run", _fail)

    result = runtime.run_turn(f"register tool: {tool_draft_id}", {"trace_id": "trace-register-safe"})

    assert result["status"] == "success"
    assert "TOOL_REGISTRATION_ACCEPTED" in result["final_output"]
