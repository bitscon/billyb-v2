from pathlib import Path

import v2.core.runtime as runtime_mod


def _reset_cam_state():
    runtime_mod._cdm_drafts.clear()
    runtime_mod._approved_drafts.clear()
    runtime_mod._approved_drafts_audit.clear()
    runtime_mod._application_attempts.clear()


def _register_draft(
    draft_id: str,
    files_affected: list[str],
    file_operations: list[dict],
    source: str = "CDM",
    output: str = "draft output",
):
    record = {
        "draft_id": draft_id,
        "source": source,
        "intent_summary": "intent",
        "scope_summary": "scope",
        "files_affected": files_affected,
        "file_operations": file_operations,
        "tests_allowed": False,
        "test_commands": [],
        "output": output,
    }
    record["draft_hash"] = runtime_mod._compute_draft_hash(record)
    runtime_mod._cdm_drafts[draft_id] = record
    return record


def test_apply_succeeds_for_valid_approved_draft(tmp_path, monkeypatch):
    _reset_cam_state()
    monkeypatch.setattr(runtime_mod, "_PROJECT_ROOT", tmp_path)
    runtime = runtime_mod.BillyRuntime(config={})

    draft_id = "draft-ok"
    target = "notes/new_file.txt"
    _register_draft(
        draft_id=draft_id,
        files_affected=[target],
        file_operations=[{"action": "create", "path": target, "content": "applied\n"}],
    )
    ok, _message = runtime_mod._approve_cdm_draft(draft_id, "human")
    assert ok

    result = runtime.run_turn(f"apply: {draft_id}", {"trace_id": "trace-cam-success"})

    assert result["status"] == "success"
    assert "- result: success" in result["final_output"]
    assert (tmp_path / target).read_text(encoding="utf-8") == "applied\n"
    assert runtime_mod._application_attempts[-1]["draft_id"] == draft_id
    assert runtime_mod._application_attempts[-1]["result"] == "success"


def test_apply_rejects_unknown_draft_id(tmp_path, monkeypatch):
    _reset_cam_state()
    monkeypatch.setattr(runtime_mod, "_PROJECT_ROOT", tmp_path)
    runtime = runtime_mod.BillyRuntime(config={})

    result = runtime.run_turn("apply: draft-missing", {"trace_id": "trace-cam-missing"})

    assert result["status"] == "error"
    assert result["final_output"] == "Apply rejected: draft_id does not exist."


def test_apply_rejects_unapproved_draft(tmp_path, monkeypatch):
    _reset_cam_state()
    monkeypatch.setattr(runtime_mod, "_PROJECT_ROOT", tmp_path)
    runtime = runtime_mod.BillyRuntime(config={})

    _register_draft(
        draft_id="draft-unapproved",
        files_affected=["pending.txt"],
        file_operations=[{"action": "create", "path": "pending.txt", "content": "pending\n"}],
    )

    result = runtime.run_turn("apply: draft-unapproved", {"trace_id": "trace-cam-unapproved"})

    assert result["status"] == "error"
    assert result["final_output"] == "Apply rejected: draft is not approved."


def test_apply_rejects_hash_mismatch(tmp_path, monkeypatch):
    _reset_cam_state()
    monkeypatch.setattr(runtime_mod, "_PROJECT_ROOT", tmp_path)
    runtime = runtime_mod.BillyRuntime(config={})

    draft_id = "draft-hash"
    draft = _register_draft(
        draft_id=draft_id,
        files_affected=["hash.txt"],
        file_operations=[{"action": "create", "path": "hash.txt", "content": "v1\n"}],
    )
    ok, _message = runtime_mod._approve_cdm_draft(draft_id, "human")
    assert ok
    draft["file_operations"][0]["content"] = "mutated\n"

    result = runtime.run_turn(f"apply: {draft_id}", {"trace_id": "trace-cam-hash"})

    assert result["status"] == "error"
    assert result["final_output"] == "Apply rejected: draft content hash mismatch."


def test_apply_rejects_scope_expansion(tmp_path, monkeypatch):
    _reset_cam_state()
    monkeypatch.setattr(runtime_mod, "_PROJECT_ROOT", tmp_path)
    runtime = runtime_mod.BillyRuntime(config={})

    draft_id = "draft-scope"
    _register_draft(
        draft_id=draft_id,
        files_affected=["allowed.txt"],
        file_operations=[{"action": "create", "path": "other.txt", "content": "bad\n"}],
    )
    ok, _message = runtime_mod._approve_cdm_draft(draft_id, "human")
    assert ok

    result = runtime.run_turn(f"apply: {draft_id}", {"trace_id": "trace-cam-scope"})

    assert result["status"] == "error"
    assert result["final_output"] == "Apply rejected: scope expansion detected."
    assert not (tmp_path / "other.txt").exists()


def test_apply_short_circuits_execution_paths_without_approval(tmp_path, monkeypatch):
    _reset_cam_state()
    monkeypatch.setattr(runtime_mod, "_PROJECT_ROOT", tmp_path)
    runtime = runtime_mod.BillyRuntime(config={})

    _register_draft(
        draft_id="draft-no-approval",
        files_affected=["blocked.txt"],
        file_operations=[{"action": "create", "path": "blocked.txt", "content": "blocked\n"}],
    )

    def _fail(*_args, **_kwargs):
        raise AssertionError("Apply routing must not leak into other runtime paths.")

    monkeypatch.setattr(runtime_mod, "_run_deterministic_loop", _fail)
    monkeypatch.setattr(runtime_mod, "_requires_barn_inspection", _fail)
    monkeypatch.setattr(runtime_mod, "_classify_preinspection_route", _fail)
    monkeypatch.setattr(runtime_mod._docker_runner, "run", _fail)

    result = runtime.run_turn("apply: draft-no-approval", {"trace_id": "trace-cam-guard"})

    assert result["status"] == "error"
    assert result["final_output"] == "Apply rejected: draft is not approved."
    assert not (tmp_path / "blocked.txt").exists()
