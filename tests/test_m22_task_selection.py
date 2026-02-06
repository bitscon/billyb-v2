from datetime import datetime, timezone, timedelta
from pathlib import Path

import core.task_selector as selector
import core.task_graph as tg
import core.evidence as evidence
import core.capability_contracts as ccr


def _setup_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence, "EVIDENCE_DIR", tmp_path / "evidence")
    evidence.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ccr, "CAPABILITY_DIR", tmp_path / "capabilities")
    ccr.CAPABILITY_DIR.mkdir(parents=True, exist_ok=True)


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


def _task(task_id: str, description: str, status: str, created_at: datetime, depends_on=None):
    return tg.TaskNode(
        task_id=task_id,
        parent_id=None,
        description=description,
        status=status,
        depends_on=depends_on or [],
        created_at=created_at,
        updated_at=created_at,
        block_reason=None,
    )


def test_explicit_reference_wins(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    tasks = [
        _task("t1", "claim:alpha", "ready", now),
        _task("t2", "claim:beta", "ready", now + timedelta(seconds=1)),
    ]
    evidence.load_evidence("trace-1")
    evidence.record_evidence("alpha", "observation", "manual", "ok")
    evidence.record_evidence("beta", "observation", "manual", "ok")

    context = selector.SelectionContext(user_input="work on t2", trace_id="trace-1", via_ops=False)
    result = selector.select_next_task(tasks, context)
    assert result.status == "selected"
    assert result.task_id == "t2"


def test_oldest_ready_selected(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    tasks = [
        _task("t1", "claim:alpha", "ready", now),
        _task("t2", "claim:beta", "ready", now + timedelta(seconds=5)),
    ]
    evidence.load_evidence("trace-1")
    evidence.record_evidence("alpha", "observation", "manual", "ok")
    evidence.record_evidence("beta", "observation", "manual", "ok")

    context = selector.SelectionContext(user_input="ignored", trace_id="trace-1", via_ops=False)
    result = selector.select_next_task(tasks, context)
    assert result.task_id == "t1"


def test_blocked_tasks_skipped(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    tasks = [
        _task("t1", "claim:alpha", "blocked", now),
        _task("t2", "claim:beta", "ready", now + timedelta(seconds=1)),
    ]
    evidence.load_evidence("trace-1")
    evidence.record_evidence("beta", "observation", "manual", "ok")

    context = selector.SelectionContext(user_input="ignored", trace_id="trace-1", via_ops=False)
    result = selector.select_next_task(tasks, context)
    assert result.task_id == "t2"


def test_missing_evidence_disqualifies(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    tasks = [
        _task("t1", "claim:alpha", "ready", now),
        _task("t2", "claim:beta", "ready", now + timedelta(seconds=1)),
    ]
    evidence.load_evidence("trace-1")
    evidence.record_evidence("beta", "observation", "manual", "ok")

    context = selector.SelectionContext(user_input="ignored", trace_id="trace-1", via_ops=False)
    result = selector.select_next_task(tasks, context)
    assert result.task_id == "t2"


def test_tie_breaker_deterministic(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    parent = _task("p1", "claim:parent", "done", now - timedelta(seconds=10))
    child_shallow = _task("a1", "claim:alpha", "ready", now, depends_on=[])
    child_deep = _task("b1", "claim:beta", "ready", now, depends_on=["p1"])

    tasks = [parent, child_shallow, child_deep]
    evidence.load_evidence("trace-1")
    evidence.record_evidence("alpha", "observation", "manual", "ok")
    evidence.record_evidence("beta", "observation", "manual", "ok")
    evidence.record_evidence("parent", "observation", "manual", "ok")

    context = selector.SelectionContext(user_input="ignored", trace_id="trace-1", via_ops=False)
    result = selector.select_next_task(tasks, context)
    assert result.task_id == "a1"


def test_no_eligible_tasks_blocked(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    tasks = [
        _task("t1", "claim:alpha", "blocked", now),
    ]
    context = selector.SelectionContext(user_input="ignored", trace_id="trace-1", via_ops=False)
    result = selector.select_next_task(tasks, context)
    assert result.status == "blocked"
    assert result.task_id is None
