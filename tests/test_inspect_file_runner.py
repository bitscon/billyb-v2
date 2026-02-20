from __future__ import annotations

import builtins
from pathlib import Path

import v2.core.tools.inspect_file_runner as inspect_mod


def test_inspect_file_rejects_parent_traversal(tmp_path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    result = inspect_mod.inspect_file(
        {
            "path": "../etc/passwd",
        },
        workspace_root,
    )

    assert result["status"] == "error"
    assert result["error"]["code"] == inspect_mod.ERROR_PATH_TRAVERSAL_FORBIDDEN
    assert result["entry_type"] == "other"


def test_inspect_file_rejects_symlink(tmp_path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    target = workspace_root / "target.txt"
    target.write_text("hello", encoding="utf-8")
    link = workspace_root / "link.txt"
    link.symlink_to(target)

    result = inspect_mod.inspect_file(
        {
            "path": "link.txt",
        },
        workspace_root,
    )

    assert result["status"] == "error"
    assert result["error"]["code"] == inspect_mod.ERROR_SYMLINK_NOT_ALLOWED
    assert result["entry_type"] == "symlink"
    assert result["exists"] is True


def test_inspect_file_hash_limit_enforced(tmp_path, monkeypatch):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    candidate = workspace_root / "large.txt"
    candidate.write_text("x" * 32, encoding="utf-8")
    monkeypatch.setattr(inspect_mod, "MAX_HASH_FILE_BYTES", 8)

    result = inspect_mod.inspect_file(
        {
            "path": "large.txt",
            "include_sha256": True,
        },
        workspace_root,
    )

    assert result["status"] == "error"
    assert result["error"]["code"] == inspect_mod.ERROR_HASH_LIMIT_EXCEEDED
    assert result["sha256"] is None
    assert result["sha256_scope"] == "none"


def test_inspect_file_opened_read_only_and_does_not_modify_file(tmp_path, monkeypatch):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    candidate = workspace_root / "note.txt"
    candidate.write_text("immutable", encoding="utf-8")
    before = candidate.read_bytes()
    before_mtime = candidate.stat().st_mtime_ns
    seen_modes: list[str] = []
    real_open = builtins.open

    def _spy_open(*args, **kwargs):
        mode = kwargs.get("mode")
        if mode is None and len(args) >= 2:
            mode = args[1]
        mode = str(mode or "r")
        seen_modes.append(mode)
        assert "w" not in mode
        assert "a" not in mode
        assert "+" not in mode
        return real_open(*args, **kwargs)

    monkeypatch.setattr(builtins, "open", _spy_open)

    result = inspect_mod.inspect_file(
        {
            "path": "note.txt",
        },
        workspace_root,
    )

    assert result["status"] == "ok"
    assert seen_modes
    assert set(seen_modes) == {"rb"}
    assert candidate.read_bytes() == before
    assert candidate.stat().st_mtime_ns == before_mtime


def test_inspect_file_response_matches_contract_shape(tmp_path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    candidate = workspace_root / "ok.txt"
    candidate.write_text("hello", encoding="utf-8")

    ok = inspect_mod.inspect_file(
        {
            "path": "ok.txt",
            "offset_bytes": 0,
            "max_excerpt_bytes": 5,
            "encoding": "utf-8",
            "include_sha256": False,
        },
        workspace_root,
    )

    assert set(ok.keys()) == inspect_mod._OUTPUT_FIELDS
    assert ok["status"] == "ok"
    assert ok["error"] is None
    assert ok["entry_type"] == "file"
    assert ok["excerpt"] == "hello"
    assert ok["sha256_scope"] == "none"

    missing = inspect_mod.inspect_file(
        {
            "path": "missing.txt",
        },
        workspace_root,
    )

    assert set(missing.keys()) == inspect_mod._OUTPUT_FIELDS
    assert missing["status"] == "error"
    assert set(missing["error"].keys()) == {"code", "message", "path", "normalized_path", "retryable"}
    assert missing["error"]["code"] in inspect_mod._ALLOWED_ERROR_CODES


def test_inspect_directory_rejects_parent_traversal(tmp_path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    result = inspect_mod.inspect_directory(
        {
            "path": "../outside",
        },
        workspace_root,
    )

    assert result["status"] == "error"
    assert result["error"]["code"] == inspect_mod.ERROR_PATH_TRAVERSAL_FORBIDDEN
    assert set(result.keys()) == inspect_mod._DIRECTORY_OUTPUT_FIELDS


def test_inspect_directory_reports_symlink_without_traversal(tmp_path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    (outside_root / "secret.txt").write_text("secret", encoding="utf-8")
    (workspace_root / "external_link").symlink_to(outside_root)

    result = inspect_mod.inspect_directory(
        {
            "path": ".",
            "max_depth": 4,
            "page_size": 50,
            "include_hidden": True,
        },
        workspace_root,
    )

    assert result["status"] == "ok"
    symlink_rows = [row for row in result["entries"] if row["name"] == "external_link"]
    assert symlink_rows
    assert symlink_rows[0]["entry_type"] == "symlink"
    assert symlink_rows[0]["symlink_target_within_allowlist"] is False
    assert not any("/external_link/secret.txt" in str(row["path"]) for row in result["entries"])


def test_inspect_directory_pagination(tmp_path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "a.txt").write_text("a", encoding="utf-8")
    (workspace_root / "b.txt").write_text("b", encoding="utf-8")
    (workspace_root / "c.txt").write_text("c", encoding="utf-8")

    first = inspect_mod.inspect_directory(
        {
            "path": ".",
            "max_depth": 1,
            "page_size": 2,
            "include_hidden": True,
        },
        workspace_root,
    )
    assert first["status"] == "ok"
    assert len(first["entries"]) == 2
    assert first["next_page_token"] is not None

    second = inspect_mod.inspect_directory(
        {
            "path": ".",
            "max_depth": 1,
            "page_size": 2,
            "page_token": first["next_page_token"],
            "include_hidden": True,
        },
        workspace_root,
    )
    assert second["status"] == "ok"
    assert len(second["entries"]) == 1
    assert second["next_page_token"] is None

    first_names = {row["name"] for row in first["entries"]}
    second_names = {row["name"] for row in second["entries"]}
    assert first_names.isdisjoint(second_names)
    assert first_names | second_names == {"a.txt", "b.txt", "c.txt"}


def test_inspect_directory_respects_depth_limit(tmp_path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "level1").mkdir()
    (workspace_root / "level1" / "level2").mkdir()
    (workspace_root / "level1" / "level2" / "deep.txt").write_text("deep", encoding="utf-8")

    shallow = inspect_mod.inspect_directory(
        {
            "path": ".",
            "max_depth": 1,
            "page_size": 50,
            "include_hidden": True,
        },
        workspace_root,
    )
    assert shallow["status"] == "ok"
    shallow_paths = {str(row["path"]) for row in shallow["entries"]}
    assert str((workspace_root / "level1")) in shallow_paths
    assert str((workspace_root / "level1" / "level2")) not in shallow_paths

    deep = inspect_mod.inspect_directory(
        {
            "path": ".",
            "max_depth": 2,
            "page_size": 50,
            "include_hidden": True,
        },
        workspace_root,
    )
    assert deep["status"] == "ok"
    deep_paths = {str(row["path"]) for row in deep["entries"]}
    assert str((workspace_root / "level1" / "level2")) in deep_paths
