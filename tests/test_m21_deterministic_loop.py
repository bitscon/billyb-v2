from pathlib import Path

import v2.core.runtime as runtime_mod
import v2.core.task_graph as tg
import v2.core.evidence as evidence
import v2.core.capability_contracts as ccr


def _reset_state():
    tg._GRAPHS.clear()
    tg._CURRENT_TRACE_ID = None
    evidence._CURRENT_TRACE_ID = None


def _setup_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "TASK_GRAPH_DIR", tmp_path / "task_graph")
    tg.TASK_GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(evidence, "EVIDENCE_DIR", tmp_path / "evidence")
    evidence.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ccr, "CAPABILITY_DIR", tmp_path / "capabilities")
    ccr.CAPABILITY_DIR.mkdir(parents=True, exist_ok=True)
    _reset_state()


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


def test_no_tasks_blocks_selection(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    response = runtime_mod.run_turn("claim:service exists", {"trace_id": "trace-1"})
    output = response["final_output"]
    assert "TASK SELECTION:" in output
    assert "selected: none" in output


def test_missing_evidence_blocks_progress(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    tg.load_graph("trace-1")
    task_id = tg.create_task("claim:nginx exists")
    tg.update_status(task_id, "ready")
    tg.save_graph("trace-1")
    response = runtime_mod.run_turn("ignored", {"trace_id": "trace-1"})
    output = response["final_output"]
    assert "REFUSAL:" in output
    assert "EVIDENCE_MISSING" in output


def test_missing_capability_blocks_progress(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    tg.load_graph("trace-1")
    task_id = tg.create_task("/exec touch /tmp/m21.txt")
    tg.update_status(task_id, "ready")
    tg.save_graph("trace-1")
    response = runtime_mod.run_turn("ignored", {"trace_id": "trace-1"})
    output = response["final_output"]
    assert "REFUSAL:" in output
    assert "CAPABILITY_MISSING" in output


def test_ops_required_capability_produces_ops_next_step(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    _write_contract(ccr.CAPABILITY_DIR, "restart_service", True, [], risk="high")
    tg.load_graph("trace-1")
    task_id = tg.create_task("/ops restart nginx")
    tg.update_status(task_id, "ready")
    tg.save_graph("trace-1")
    response = runtime_mod.run_turn("ignored", {"trace_id": "trace-1"})
    output = response["final_output"]
    assert "REFUSAL:" in output
    assert "CAPABILITY_AMBIGUOUS" in output


def test_completed_task_produces_none_next_step(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    tg.load_graph("trace-1")
    task_id = tg.create_task("claim:done")
    tg.update_status(task_id, "done")
    tg.save_graph("trace-1")
    response = runtime_mod.run_turn("ignored", {"trace_id": "trace-1"})
    output = response["final_output"]
    assert "selected: none" in output
