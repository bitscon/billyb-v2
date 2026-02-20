from __future__ import annotations

import copy
import os
from pathlib import Path

import v2.core.runtime as runtime_mod
import v2.core.tools.inspect_file_runner as inspect_mod


def _stat_snapshot(path: Path) -> tuple[int, int, int, int]:
    stat_result = os.lstat(path)
    return (
        stat_result.st_mode,
        stat_result.st_size,
        stat_result.st_mtime_ns,
        stat_result.st_ctime_ns,
    )


def test_phase28_inspection_tools_cannot_escalate_or_invoke_tools(tmp_path):
    # Invariant 1: inspection returns data only and does not trigger routing/tool execution side effects.
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    target_file = workspace_root / "note.txt"
    target_file.write_text("phase28-safe", encoding="utf-8")
    (workspace_root / "nested").mkdir()

    before_state = {
        "pending_tool_executions": copy.deepcopy(runtime_mod._pending_tool_executions),
        "tool_execution_audit": copy.deepcopy(runtime_mod._tool_execution_audit),
        "pending_exec_proposals": copy.deepcopy(runtime_mod._pending_exec_proposals),
        "pending_ops_plans": copy.deepcopy(runtime_mod._pending_ops_plans),
        "last_inspection": copy.deepcopy(runtime_mod._last_inspection),
        "last_introspection_snapshot": copy.deepcopy(runtime_mod._last_introspection_snapshot),
    }

    file_result = inspect_mod.inspect_file({"path": "note.txt"}, workspace_root)
    directory_result = inspect_mod.inspect_directory({"path": ".", "max_depth": 2, "page_size": 50}, workspace_root)

    assert file_result["status"] == "ok"
    assert directory_result["status"] == "ok"
    for payload in (file_result, directory_result):
        assert payload.get("error") is None
        assert "tool_calls" not in payload
        assert "next_step" not in payload
        assert "route" not in payload

    assert runtime_mod._pending_tool_executions == before_state["pending_tool_executions"]
    assert runtime_mod._tool_execution_audit == before_state["tool_execution_audit"]
    assert runtime_mod._pending_exec_proposals == before_state["pending_exec_proposals"]
    assert runtime_mod._pending_ops_plans == before_state["pending_ops_plans"]
    assert runtime_mod._last_inspection == before_state["last_inspection"]
    assert runtime_mod._last_introspection_snapshot == before_state["last_introspection_snapshot"]


def test_phase28_inspection_tools_cannot_mutate_filesystem_state(tmp_path):
    # Invariant 2: inspected files/directories remain byte-for-byte and metadata stable.
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    target_file = workspace_root / "artifact.txt"
    target_file.write_text("immutable-content", encoding="utf-8")
    target_dir = workspace_root / "folder"
    target_dir.mkdir()
    nested_file = target_dir / "nested.txt"
    nested_file.write_text("nested-content", encoding="utf-8")

    file_bytes_before = target_file.read_bytes()
    nested_bytes_before = nested_file.read_bytes()
    root_stat_before = _stat_snapshot(workspace_root)
    file_stat_before = _stat_snapshot(target_file)
    dir_stat_before = _stat_snapshot(target_dir)
    nested_stat_before = _stat_snapshot(nested_file)

    file_result = inspect_mod.inspect_file({"path": "artifact.txt", "include_sha256": True}, workspace_root)
    directory_result = inspect_mod.inspect_directory(
        {"path": ".", "max_depth": 3, "page_size": 50, "include_hidden": True},
        workspace_root,
    )

    assert file_result["status"] == "ok"
    assert directory_result["status"] == "ok"
    assert target_file.read_bytes() == file_bytes_before
    assert nested_file.read_bytes() == nested_bytes_before
    assert _stat_snapshot(workspace_root) == root_stat_before
    assert _stat_snapshot(target_file) == file_stat_before
    assert _stat_snapshot(target_dir) == dir_stat_before
    assert _stat_snapshot(nested_file) == nested_stat_before


def test_phase28_natural_language_cannot_trigger_inspection_tools(monkeypatch):
    # Invariant 3: conversational phrases must not route into deterministic inspection execution.
    runtime = runtime_mod.BillyRuntime(config={})

    def _fail_loop(_user_input: str, _trace_id: str):
        raise AssertionError("Natural language request unexpectedly triggered deterministic inspection loop.")

    monkeypatch.setattr(runtime_mod, "_run_deterministic_loop", _fail_loop)

    for phrase in ("read this directory", "show files"):
        result = runtime.run_turn(phrase, {"trace_id": f"trace-phase28-no-inspect-{abs(hash(phrase))}"})
        assert result["status"] == "success"
        assert result.get("mode") == "conversation_layer"
        assert result.get("tool_calls") == []


def test_phase28_inspection_output_not_injected_into_conversation_context(tmp_path, monkeypatch):
    # Invariant 4: inspection output is returned only to caller and does not alter conversational context.
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    marker = "PHASE28_SENTINEL_VALUE"
    target_file = workspace_root / "context.txt"
    target_file.write_text(marker, encoding="utf-8")

    runtime = runtime_mod.BillyRuntime(config={})
    captured_before = runtime.get_captured_content_last(10)

    inspected_file = inspect_mod.inspect_file({"path": "context.txt"}, workspace_root)
    inspected_dir = inspect_mod.inspect_directory({"path": ".", "max_depth": 1, "page_size": 20}, workspace_root)

    observed: dict[str, str] = {}

    def _fake_llm(prompt: str) -> str:
        observed["prompt"] = prompt
        return "read-only-response"

    monkeypatch.setattr(runtime, "_llm_answer", _fake_llm)

    response = runtime.run_turn("tell me a fun fact about octopuses", {"trace_id": "trace-phase28-context-boundary"})

    assert inspected_file["status"] == "ok"
    assert inspected_dir["status"] == "ok"
    assert marker in str(inspected_file.get("excerpt", ""))
    assert response["status"] == "success"
    assert response["final_output"] == "read-only-response"
    assert observed["prompt"] == "tell me a fun fact about octopuses"
    assert marker not in observed["prompt"]
    assert runtime.get_captured_content_last(10) == captured_before
