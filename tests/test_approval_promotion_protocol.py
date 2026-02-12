import v2.core.runtime as runtime_mod


def _reset_protocol_state():
    runtime_mod._cdm_drafts.clear()
    runtime_mod._approved_drafts.clear()
    runtime_mod._approved_drafts_audit.clear()


def test_approval_succeeds_for_valid_cdm_draft():
    _reset_protocol_state()
    runtime = runtime_mod.BillyRuntime(config={})

    draft_result = runtime.run_turn("draft: update parser in src/parser.py", {"trace_id": "trace-draft"})
    assert draft_result["status"] == "success"
    assert runtime_mod._cdm_drafts
    draft_id = next(iter(runtime_mod._cdm_drafts.keys()))

    approval_result = runtime.run_turn(
        f"approve: {draft_id}",
        {"trace_id": "trace-approve", "approved_by": "chad"},
    )

    assert approval_result["status"] == "success"
    assert "APPROVAL_ACCEPTED" in approval_result["final_output"]
    assert draft_id in runtime_mod._approved_drafts
    record = runtime_mod._approved_drafts[draft_id][0]
    assert record["draft_id"] == draft_id
    assert record["approved_by"] == "chad"
    assert record["status"] == "approved"
    assert record["source"] == "CDM"


def test_approval_fails_for_unknown_draft_id():
    _reset_protocol_state()
    runtime = runtime_mod.BillyRuntime(config={})

    result = runtime.run_turn("approve: draft-unknown", {"trace_id": "trace-unknown"})

    assert result["status"] == "error"
    assert result["final_output"] == "Approval rejected: draft_id does not exist."


def test_approval_fails_for_non_cdm_output():
    _reset_protocol_state()
    runtime = runtime_mod.BillyRuntime(config={})
    output = "not a cdm draft"
    draft_record = {
        "draft_id": "draft-non-cdm",
        "source": "ERM",
        "intent_summary": "non-cdm",
        "scope_summary": "non-cdm",
        "files_affected": ["v2/core/runtime.py"],
        "output": output,
    }
    draft_record["draft_hash"] = runtime_mod._compute_draft_hash(draft_record)
    runtime_mod._cdm_drafts["draft-non-cdm"] = draft_record

    result = runtime.run_turn("approve: draft-non-cdm", {"trace_id": "trace-non-cdm"})

    assert result["status"] == "error"
    assert result["final_output"] == "Approval rejected: draft is not from CDM."


def test_approval_fails_on_hash_mismatch():
    _reset_protocol_state()
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("code: adjust resolver null handling", {"trace_id": "trace-code"})
    draft_id = next(iter(runtime_mod._cdm_drafts.keys()))
    runtime_mod._cdm_drafts[draft_id]["output"] = runtime_mod._cdm_drafts[draft_id]["output"] + "\nmutation"

    result = runtime.run_turn(f"approve: {draft_id}", {"trace_id": "trace-mismatch"})

    assert result["status"] == "error"
    assert result["final_output"] == "Approval rejected: draft content has changed."


def test_approval_records_are_append_only():
    _reset_protocol_state()
    runtime = runtime_mod.BillyRuntime(config={})

    runtime.run_turn("propose: clean up parser contracts", {"trace_id": "trace-propose"})
    draft_id = next(iter(runtime_mod._cdm_drafts.keys()))

    first = runtime.run_turn(f"approve: {draft_id}", {"trace_id": "trace-first"})
    assert first["status"] == "success"
    first_record = dict(runtime_mod._approved_drafts[draft_id][0])
    first_audit_count = len(runtime_mod._approved_drafts_audit)

    second = runtime.run_turn(f"approve: {draft_id}", {"trace_id": "trace-second"})
    assert second["status"] == "error"
    assert second["final_output"] == "Approval rejected: draft was already approved."
    assert len(runtime_mod._approved_drafts[draft_id]) == 1
    assert runtime_mod._approved_drafts[draft_id][0] == first_record
    assert len(runtime_mod._approved_drafts_audit) == first_audit_count


def test_approval_short_circuits_execution_paths(monkeypatch):
    _reset_protocol_state()
    runtime = runtime_mod.BillyRuntime(config={})
    output = "safe cdm output"
    draft_record = {
        "draft_id": "draft-safe",
        "source": "CDM",
        "intent_summary": "safe draft",
        "scope_summary": "read only",
        "files_affected": ["v2/core/runtime.py"],
        "output": output,
    }
    draft_record["draft_hash"] = runtime_mod._compute_draft_hash(draft_record)
    runtime_mod._cdm_drafts["draft-safe"] = draft_record

    def _fail(*_args, **_kwargs):
        raise AssertionError("Approval path must not reach execution-capable branches.")

    monkeypatch.setattr(runtime_mod, "_run_deterministic_loop", _fail)
    monkeypatch.setattr(runtime_mod, "_requires_barn_inspection", _fail)
    monkeypatch.setattr(runtime_mod._docker_runner, "run", _fail)
    monkeypatch.setattr(runtime_mod._memory_store, "write", _fail)
    monkeypatch.setattr(runtime_mod._memory_store, "query", _fail)

    result = runtime.run_turn("approve: draft-safe", {"trace_id": "trace-safe"})

    assert result["status"] == "success"
    assert "APPROVAL_ACCEPTED" in result["final_output"]
