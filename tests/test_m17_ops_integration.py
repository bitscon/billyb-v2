import json
import subprocess
from pathlib import Path

import v2.core.runtime as runtime_mod


def _reset_ops_state(tmp_path: Path) -> None:
    runtime_mod._pending_ops_plans.clear()
    runtime_mod._ops_contract_dir = tmp_path / "ops"
    runtime_mod._ops_contract_dir.mkdir(parents=True, exist_ok=True)
    runtime_mod._ops_journal_path = runtime_mod._ops_contract_dir / "journal.jsonl"
    runtime_mod._ops_state_path = runtime_mod._ops_contract_dir / "state.json"
    if runtime_mod._ops_journal_path.exists():
        runtime_mod._ops_journal_path.unlink()
    if runtime_mod._ops_state_path.exists():
        runtime_mod._ops_state_path.unlink()


def _read_journal(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _extract_id(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("id: "):
            return line.replace("id: ", "", 1).strip()
    return ""


def test_high_risk_requires_ops(tmp_path):
    _reset_ops_state(tmp_path)
    response = runtime_mod.run_turn("/exec systemctl restart nginx", {})
    assert "high-risk operation requires /ops" in response["final_output"]


def test_ops_requires_approval(tmp_path, monkeypatch):
    _reset_ops_state(tmp_path)

    response = runtime_mod.run_turn("/ops systemctl restart nginx", {"user_id": "tester"})
    assert "OPS_PLAN" in response["final_output"]
    ops_id = _extract_id(response["final_output"])
    assert ops_id

    monkeypatch.setattr(
        runtime_mod,
        "_execute_shell_command",
        lambda command, working_dir: subprocess.CompletedProcess(
            args=command, returncode=0, stdout="ok\n", stderr=""
        ),
    )

    approval = runtime_mod.run_turn(f"APPROVE {ops_id}", {"user_id": "tester"})
    assert "OPS_RESULT" in approval["final_output"]
    assert "status: SUCCESS" in approval["final_output"]

    journal = _read_journal(runtime_mod._ops_journal_path)
    events = [entry["event"] for entry in journal]
    assert "intent" in events
    assert "plan" in events
    assert "approval" in events
    assert "execution" in events
    assert "result" in events


def test_ops_id_mismatch_blocks(tmp_path):
    _reset_ops_state(tmp_path)

    runtime_mod.run_turn("/ops systemctl restart nginx", {})
    response = runtime_mod.run_turn("APPROVE ops-20990101-999", {})
    assert "Ops approval rejected" in response["final_output"]


def test_ops_no_auto_rollback(tmp_path, monkeypatch):
    _reset_ops_state(tmp_path)

    response = runtime_mod.run_turn("/ops systemctl restart nginx", {})
    ops_id = _extract_id(response["final_output"])

    monkeypatch.setattr(
        runtime_mod,
        "_execute_shell_command",
        lambda command, working_dir: subprocess.CompletedProcess(
            args=command, returncode=1, stdout="", stderr="fail"
        ),
    )

    approval = runtime_mod.run_turn(f"APPROVE {ops_id}", {})
    assert "status: FAILED" in approval["final_output"]
    assert "recommendation: manual rollback" in approval["final_output"]
