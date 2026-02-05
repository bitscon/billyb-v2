import json
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


def test_exec_auto_then_revoke_falls_back(tmp_path):
    _reset_runtime_state(tmp_path)

    grant = runtime_mod.run_turn(
        "GRANT_CAPABILITY\nname: filesystem.write\nscope: default",
        {},
    )
    assert grant["status"] == "success"

    target = "/home/billyb/workspaces/billyb-v2/tmp_m15_autotest.txt"
    target_path = Path(target)
    if target_path.exists():
        target_path.unlink()

    result = runtime_mod.run_turn(f"/exec touch {target}", {})
    assert result["status"] == "success"
    assert "EXECUTION_RESULT" in result["final_output"]
    assert "PROPOSED_ACTION" not in result["final_output"]
    assert target_path.exists()

    journal = _read_journal(runtime_mod._exec_contract_journal_path)
    assert any(entry["event"] == "auto_execution" for entry in journal)
    result_entry = next(
        entry for entry in journal
        if entry["event"] == "result" and entry["payload"].get("capability") == "filesystem.write"
    )
    assert result_entry["payload"]["limits_remaining"]["remaining_session"] == 9

    revoke = runtime_mod.run_turn("/revoke_autonomy filesystem.write", {})
    assert revoke["status"] == "success"

    target2 = "/home/billyb/workspaces/billyb-v2/tmp_m15_autotest2.txt"
    target2_path = Path(target2)
    if target2_path.exists():
        target2_path.unlink()

    fallback = runtime_mod.run_turn(f"/exec touch {target2}", {})
    assert "PROPOSED_ACTION" in fallback["final_output"]
    assert not target2_path.exists()

    if target_path.exists():
        target_path.unlink()


def test_exec_deny_out_of_scope_path(tmp_path):
    _reset_runtime_state(tmp_path)

    grant = runtime_mod.run_turn(
        "GRANT_CAPABILITY\nname: filesystem.write\nscope: default",
        {},
    )
    assert grant["status"] == "success"

    forbidden = "/etc/forbidden_m15.txt"
    forbidden_path = Path(forbidden)
    if forbidden_path.exists():
        forbidden_path.unlink()

    response = runtime_mod.run_turn(f"/exec touch {forbidden}", {})
    assert "PROPOSED_ACTION" in response["final_output"]
    assert not forbidden_path.exists()

    journal = _read_journal(runtime_mod._exec_contract_journal_path)
    assert any(entry["event"] == "proposal" for entry in journal)
    assert not any(entry["event"] == "auto_execution" for entry in journal)

    allowed, reason, remaining = runtime_mod._autonomy_registry.is_grant_allowed(
        "filesystem.write",
        {"path": forbidden},
    )
    assert allowed is False
    assert reason == "Capability scope violation"
    assert remaining == {}
