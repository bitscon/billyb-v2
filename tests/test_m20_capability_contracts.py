from pathlib import Path

import pytest

import v2.core.runtime as runtime_mod
import v2.core.capability_contracts as ccr
import v2.core.evidence as evidence


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


def _write_contract(dir_path: Path, name: str, ops_required: bool, evidence_list: list[str], risk: str = "low"):
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{name}.yaml").write_text(
        "\n".join(
            [
                f"capability: {name}",
                f"risk_level: {risk}",
                "requires:",
                f"  ops_required: {'true' if ops_required else 'false'}",
                f"  evidence: {evidence_list}",
                "guarantees:",
                "  - journal_entry_created",
            ]
        ),
        encoding="utf-8",
    )


def test_missing_contract_blocks_execution(tmp_path, monkeypatch):
    _reset_runtime_state(tmp_path)
    empty_contract_dir = tmp_path / "capabilities"
    monkeypatch.setattr(ccr, "CAPABILITY_DIR", empty_contract_dir)

    target = "/home/billyb/workspaces/billyb-v2/tmp_m20_missing_contract.txt"
    target_path = Path(target)
    if target_path.exists():
        target_path.unlink()

    response = runtime_mod.run_turn(f"/exec touch {target}", {})
    assert response["status"] == "error"
    assert "missing capability contract" in response["final_output"].lower()
    assert not target_path.exists()


def test_missing_evidence_blocks_execution(tmp_path, monkeypatch):
    contract_dir = tmp_path / "capabilities"
    monkeypatch.setattr(ccr, "CAPABILITY_DIR", contract_dir)
    _write_contract(contract_dir, "fact_check", False, ["claim-1"], risk="low")

    evidence_dir = tmp_path / "evidence"
    monkeypatch.setattr(evidence, "EVIDENCE_DIR", evidence_dir)
    evidence.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    evidence._CURRENT_TRACE_ID = None

    contract = ccr.load_contract("fact_check")
    ok, reason = ccr.validate_preconditions(contract, {"trace_id": "trace-1", "via_ops": False})
    assert ok is False
    assert reason == "blocked(reason=\"no evidence\")"


def test_ops_required_rejected_outside_ops(tmp_path, monkeypatch):
    _reset_runtime_state(tmp_path)
    contract_dir = tmp_path / "capabilities"
    monkeypatch.setattr(ccr, "CAPABILITY_DIR", contract_dir)
    _write_contract(contract_dir, "filesystem.write", True, [], risk="medium")

    target = "/home/billyb/workspaces/billyb-v2/tmp_m20_ops_required.txt"
    target_path = Path(target)
    if target_path.exists():
        target_path.unlink()

    response = runtime_mod.run_turn(f"/exec touch {target}", {})
    assert response["status"] == "error"
    assert "requires /ops" in response["final_output"].lower()
    assert not target_path.exists()


def test_valid_contract_passes_validation(tmp_path, monkeypatch):
    contract_dir = tmp_path / "capabilities"
    monkeypatch.setattr(ccr, "CAPABILITY_DIR", contract_dir)
    _write_contract(contract_dir, "filesystem.read", False, [], risk="low")

    contract = ccr.load_contract("filesystem.read")
    ok, reason = ccr.validate_preconditions(contract, {"trace_id": "trace-1", "via_ops": False})
    assert ok is True
    assert reason == ""


def test_risk_level_is_preserved(tmp_path, monkeypatch):
    contract_dir = tmp_path / "capabilities"
    monkeypatch.setattr(ccr, "CAPABILITY_DIR", contract_dir)
    _write_contract(contract_dir, "filesystem.delete", False, [], risk="high")

    contract = ccr.load_contract("filesystem.delete")
    assert contract.risk_level == "high"
