from pathlib import Path

import core.runtime as runtime_mod
import core.task_graph as tg
import core.evidence as evidence
import core.capability_contracts as ccr


def _setup_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "TASK_GRAPH_DIR", tmp_path / "task_graph")
    tg.TASK_GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(evidence, "EVIDENCE_DIR", tmp_path / "evidence")
    evidence.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ccr, "CAPABILITY_DIR", tmp_path / "capabilities")
    ccr.CAPABILITY_DIR.mkdir(parents=True, exist_ok=True)
    tg._GRAPHS.clear()
    tg._CURRENT_TRACE_ID = None
    evidence._CURRENT_TRACE_ID = None


def _write_contract(dir_path: Path, filename: str, capability: str, ops_required: bool, evidence_list: list[str]):
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / filename).write_text(
        "\n".join(
            [
                f"capability: {capability}",
                "risk_level: high",
                "requires:",
                f"  ops_required: {'true' if ops_required else 'false'}",
                f"  evidence: {evidence_list}",
                "guarantees:",
                "  - journal_entry_created",
            ]
        ),
        encoding="utf-8",
    )


def test_missing_evidence_triggers_refusal(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    tg.load_graph("trace-1")
    task_id = tg.create_task("claim:nginx running")
    tg.update_status(task_id, "ready")
    tg.save_graph("trace-1")
    response = runtime_mod.run_turn("ignored", {"trace_id": "trace-1"})
    output = response["final_output"]
    assert "REFUSAL:" in output
    assert "EVIDENCE_MISSING" in output


def test_conflicting_evidence_triggers_refusal(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    evidence.load_evidence("trace-1")
    evidence.record_evidence("nginx running", "command", "systemctl", "active")
    evidence.record_evidence("nginx running", "command", "systemctl", "inactive")
    tg.load_graph("trace-1")
    task_id = tg.create_task("claim:nginx running")
    tg.update_status(task_id, "ready")
    tg.save_graph("trace-1")
    response = runtime_mod.run_turn("ignored", {"trace_id": "trace-1"})
    output = response["final_output"]
    assert "EVIDENCE_CONFLICT" in output


def test_ambiguous_capability_triggers_refusal(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    _write_contract(ccr.CAPABILITY_DIR, "one.yaml", "filesystem.write", False, [])
    _write_contract(ccr.CAPABILITY_DIR, "two.yaml", "filesystem.write", False, [])
    tg.load_graph("trace-1")
    task_id = tg.create_task("/exec touch /tmp/m23.txt")
    tg.update_status(task_id, "ready")
    tg.save_graph("trace-1")
    response = runtime_mod.run_turn("ignored", {"trace_id": "trace-1"})
    output = response["final_output"]
    assert "CAPABILITY_AMBIGUOUS" in output


def test_recursive_delete_path_triggers_refusal(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    _write_contract(ccr.CAPABILITY_DIR, "filesystem.delete.yaml", "filesystem.delete", False, [])
    tg.load_graph("trace-1")
    task_id = tg.create_task("/exec rm -r /tmp/m23")
    tg.update_status(task_id, "ready")
    tg.save_graph("trace-1")
    response = runtime_mod.run_turn("ignored", {"trace_id": "trace-1"})
    output = response["final_output"]
    assert "SCOPE_RECURSIVE" in output


def test_destructive_without_ack_triggers_refusal(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    _write_contract(ccr.CAPABILITY_DIR, "filesystem.delete.yaml", "filesystem.delete", False, [])
    tg.load_graph("trace-1")
    task_id = tg.create_task("/exec rm /tmp/m23.txt")
    tg.update_status(task_id, "ready")
    tg.save_graph("trace-1")
    response = runtime_mod.run_turn("ignored", {"trace_id": "trace-1"})
    output = response["final_output"]
    assert "IRREVERSIBLE_NO_ACK" in output


def test_failure_overrides_ccr_approval(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    _write_contract(ccr.CAPABILITY_DIR, "filesystem.delete.yaml", "filesystem.delete", False, [])
    evidence.load_evidence("trace-1")
    evidence.record_evidence("approved", "observation", "manual", "ok")
    tg.load_graph("trace-1")
    task_id = tg.create_task("/exec rm /tmp/m23.txt")
    tg.update_status(task_id, "ready")
    tg.save_graph("trace-1")
    response = runtime_mod.run_turn("ignored", {"trace_id": "trace-1"})
    output = response["final_output"]
    assert "IRREVERSIBLE_NO_ACK" in output


def test_failure_overrides_ops(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    _write_contract(ccr.CAPABILITY_DIR, "restart.yaml", "restart_service", True, [])
    tg.load_graph("trace-1")
    task_id = tg.create_task("/ops restart nginx")
    tg.update_status(task_id, "ready")
    tg.save_graph("trace-1")
    response = runtime_mod.run_turn("ignored", {"trace_id": "trace-1"})
    output = response["final_output"]
    assert "CAPABILITY_AMBIGUOUS" in output
