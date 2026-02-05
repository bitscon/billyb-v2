import json
import time
import subprocess
from pathlib import Path

import v2.core.runtime as runtime_mod


def _reset_runtime_state(tmp_path: Path) -> None:
    runtime_mod._pending_exec_proposals.clear()
    runtime_mod._autonomy_registry._grants = {}
    runtime_mod._autonomy_registry._grant_history = {}
    runtime_mod._autonomy_registry._grant_counts = {}

    runtime_mod._exec_contract_dir = tmp_path / "execution_contract"
    runtime_mod._exec_contract_dir.mkdir(parents=True, exist_ok=True)
    runtime_mod._exec_contract_journal_path = runtime_mod._exec_contract_dir / "journal.jsonl"
    runtime_mod._exec_contract_state_path = runtime_mod._exec_contract_dir / "state.json"

    if runtime_mod._exec_contract_journal_path.exists():
        runtime_mod._exec_contract_journal_path.unlink()
    if runtime_mod._exec_contract_state_path.exists():
        runtime_mod._exec_contract_state_path.unlink()


def _read_journal(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _extract_id(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("id: "):
            return line.replace("id: ", "", 1).strip()
    return ""


def _setup_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    repo.mkdir()
    subprocess.check_call(["git", "-c", "init.defaultBranch=main", "init"], cwd=str(repo))
    subprocess.check_call(["git", "config", "user.email", "test@example.com"], cwd=str(repo))
    subprocess.check_call(["git", "config", "user.name", "Test User"], cwd=str(repo))
    (repo / "README.md").write_text("test\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "README.md"], cwd=str(repo))
    subprocess.check_call(["git", "commit", "-m", "init"], cwd=str(repo))
    subprocess.check_call(["git", "init", "--bare", str(remote)], cwd=str(tmp_path))
    subprocess.check_call(["git", "remote", "add", "origin", str(remote)], cwd=str(repo))
    subprocess.check_call(["git", "push", "-u", "origin", "main"], cwd=str(repo))
    return repo


def test_delete_requires_approval_and_executes(tmp_path):
    _reset_runtime_state(tmp_path)

    grant = runtime_mod.run_turn(
        "GRANT_CAPABILITY\nname: filesystem.delete\nscope: default",
        {},
    )
    assert grant["status"] == "success"

    target = "/home/billyb/workspaces/billyb-v2/tmp_m16_delete.txt"
    target_path = Path(target)
    target_path.write_text("temp\n", encoding="utf-8")

    response = runtime_mod.run_turn(f"/exec rm {target}", {})
    assert "PROPOSED_ACTION" in response["final_output"]
    approval_id = _extract_id(response["final_output"])
    assert approval_id

    exec_result = runtime_mod.run_turn(f"APPROVE {approval_id}", {})
    assert "EXECUTION_RESULT" in exec_result["final_output"]
    assert not target_path.exists()

    journal = _read_journal(runtime_mod._exec_contract_journal_path)
    result_entry = next(
        entry for entry in journal
        if entry["event"] == "result" and entry["payload"].get("id") == approval_id
    )
    assert result_entry["payload"]["limits_remaining"]["remaining_session"] == 4


def test_delete_denies_without_grant(tmp_path):
    _reset_runtime_state(tmp_path)

    response = runtime_mod.run_turn(
        "/exec rm /home/billyb/workspaces/billyb-v2/tmp_m16_delete2.txt",
        {},
    )
    assert "Execution denied: capability not granted." in response["final_output"]
    assert "PROPOSED_ACTION" not in response["final_output"]


def test_delete_scope_violation_denied(tmp_path):
    _reset_runtime_state(tmp_path)

    runtime_mod.run_turn(
        "GRANT_CAPABILITY\nname: filesystem.delete\nscope: default",
        {},
    )

    response = runtime_mod.run_turn("/exec rm /etc/forbidden_m16.txt", {})
    assert "Execution denied: Capability scope violation" in response["final_output"]

    journal = _read_journal(runtime_mod._exec_contract_journal_path)
    assert any(entry["event"] == "capability_denied" for entry in journal)


def test_delete_revocation_blocks(tmp_path):
    _reset_runtime_state(tmp_path)

    runtime_mod.run_turn(
        "GRANT_CAPABILITY\nname: filesystem.delete\nscope: default",
        {},
    )
    runtime_mod.run_turn("/revoke_autonomy filesystem.delete", {})

    response = runtime_mod.run_turn(
        "/exec rm /home/billyb/workspaces/billyb-v2/tmp_m16_delete3.txt",
        {},
    )
    assert "Execution denied: Capability revoked" in response["final_output"]


def test_delete_limit_exhaustion(tmp_path):
    _reset_runtime_state(tmp_path)

    runtime_mod.run_turn(
        "GRANT_CAPABILITY\nname: filesystem.delete\nscope: default\nmax_actions: 1",
        {},
    )

    target = "/home/billyb/workspaces/billyb-v2/tmp_m16_delete4.txt"
    target_path = Path(target)
    target_path.write_text("temp\n", encoding="utf-8")

    response = runtime_mod.run_turn(f"/exec rm {target}", {})
    approval_id = _extract_id(response["final_output"])
    runtime_mod.run_turn(f"APPROVE {approval_id}", {})

    second = runtime_mod.run_turn(
        "/exec rm /home/billyb/workspaces/billyb-v2/tmp_m16_delete5.txt",
        {},
    )
    assert "Execution denied: Capability limits exceeded" in second["final_output"]


def test_delete_expiration_denied(tmp_path):
    _reset_runtime_state(tmp_path)

    runtime_mod.run_turn(
        "GRANT_CAPABILITY\nname: filesystem.delete\nscope: default\nmode: auto\nexpires_in: 1s",
        {},
    )
    time.sleep(1.1)

    response = runtime_mod.run_turn(
        "/exec rm /home/billyb/workspaces/billyb-v2/tmp_m16_delete6.txt",
        {},
    )
    assert "Execution denied: Capability expired" in response["final_output"]


def test_git_push_requires_approval(tmp_path, monkeypatch):
    _reset_runtime_state(tmp_path)
    repo = _setup_git_repo(tmp_path)
    monkeypatch.setenv("BILLY_REPO_ROOT", str(repo))

    runtime_mod.run_turn(
        "GRANT_CAPABILITY\nname: git.push\nscope: default",
        {},
    )

    response = runtime_mod.run_turn("/exec git push", {})
    assert "PROPOSED_ACTION" in response["final_output"]
    approval_id = _extract_id(response["final_output"])
    assert approval_id

    result = runtime_mod.run_turn(f"APPROVE {approval_id}", {})
    assert "EXECUTION_RESULT" in result["final_output"]
    assert "exit_code: 0" in result["final_output"]


def test_git_push_denies_without_grant(tmp_path, monkeypatch):
    _reset_runtime_state(tmp_path)
    repo = _setup_git_repo(tmp_path)
    monkeypatch.setenv("BILLY_REPO_ROOT", str(repo))

    response = runtime_mod.run_turn("/exec git push", {})
    assert "Execution denied: capability not granted." in response["final_output"]


def test_git_push_unclean_denied(tmp_path, monkeypatch):
    _reset_runtime_state(tmp_path)
    repo = _setup_git_repo(tmp_path)
    monkeypatch.setenv("BILLY_REPO_ROOT", str(repo))

    runtime_mod.run_turn(
        "GRANT_CAPABILITY\nname: git.push\nscope: default",
        {},
    )
    (repo / "untracked.txt").write_text("dirty\n", encoding="utf-8")

    response = runtime_mod.run_turn("/exec git push", {})
    assert "Execution denied: working tree not clean." in response["final_output"]

    journal = _read_journal(runtime_mod._exec_contract_journal_path)
    assert any(entry["event"] == "capability_denied" for entry in journal)


def test_git_push_revocation_blocks(tmp_path, monkeypatch):
    _reset_runtime_state(tmp_path)
    repo = _setup_git_repo(tmp_path)
    monkeypatch.setenv("BILLY_REPO_ROOT", str(repo))

    runtime_mod.run_turn(
        "GRANT_CAPABILITY\nname: git.push\nscope: default",
        {},
    )
    runtime_mod.run_turn("/revoke_autonomy git.push", {})

    response = runtime_mod.run_turn("/exec git push", {})
    assert "Execution denied: Capability revoked" in response["final_output"]


def test_git_push_limit_exhaustion(tmp_path, monkeypatch):
    _reset_runtime_state(tmp_path)
    repo = _setup_git_repo(tmp_path)
    monkeypatch.setenv("BILLY_REPO_ROOT", str(repo))

    runtime_mod.run_turn(
        "GRANT_CAPABILITY\nname: git.push\nscope: default\nmax_actions: 1",
        {},
    )

    response = runtime_mod.run_turn("/exec git push", {})
    approval_id = _extract_id(response["final_output"])
    runtime_mod.run_turn(f"APPROVE {approval_id}", {})

    second = runtime_mod.run_turn("/exec git push", {})
    assert "Execution denied: Capability limits exceeded" in second["final_output"]


def test_git_push_expiration_denied(tmp_path, monkeypatch):
    _reset_runtime_state(tmp_path)
    repo = _setup_git_repo(tmp_path)
    monkeypatch.setenv("BILLY_REPO_ROOT", str(repo))

    runtime_mod.run_turn(
        "GRANT_CAPABILITY\nname: git.push\nscope: default\nmode: auto\nexpires_in: 1s",
        {},
    )
    time.sleep(1.1)

    response = runtime_mod.run_turn("/exec git push", {})
    assert "Execution denied: Capability expired" in response["final_output"]
