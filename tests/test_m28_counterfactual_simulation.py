from datetime import datetime, timedelta, timezone

import v2.core.counterfactual as counterfactual
import v2.core.evidence as evidence
import v2.core.task_graph as task_graph


def _setup(tmp_path, monkeypatch, trace_id="trace-1"):
    monkeypatch.setattr(evidence, "EVIDENCE_DIR", tmp_path / "evidence")
    evidence.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    evidence._CURRENT_TRACE_ID = None
    evidence.load_evidence(trace_id)

    monkeypatch.setattr(task_graph, "TASK_GRAPH_DIR", tmp_path / "graphs")
    task_graph.TASK_GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    task_graph._CURRENT_TRACE_ID = None
    task_graph._GRAPHS.clear()
    task_graph.load_graph(trace_id)


def test_blocks_on_missing_evidence(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    result = counterfactual.simulate_action(
        task_id="task-1",
        plan_id=None,
        step_id=None,
        proposed_action="claim: nginx running",
        now=now,
    )
    assert result.status == "blocked"
    assert any("missing evidence" in reason for reason in result.reasons)


def test_blocks_on_stale_evidence(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(evidence, "_now", lambda: base)
    evidence.record_evidence(
        claim="nginx running",
        source_type="command",
        source_ref="systemctl",
        raw_content="active",
        ttl_seconds=1,
    )
    now = base + timedelta(seconds=10)
    result = counterfactual.simulate_action(
        task_id="task-1",
        plan_id=None,
        step_id=None,
        proposed_action="claim: nginx running",
        now=now,
    )
    assert result.status == "blocked"
    assert any("stale evidence" in reason for reason in result.reasons)


def test_blocks_on_missing_contract(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    from v2.core import capability_contracts as ccr
    monkeypatch.setattr(ccr, "CAPABILITY_DIR", tmp_path / "capabilities")
    now = datetime.now(timezone.utc)
    result = counterfactual.simulate_action(
        task_id="task-1",
        plan_id=None,
        step_id=None,
        proposed_action="/ops restart nginx",
        now=now,
    )
    assert result.status == "blocked"
    assert any("capability contract" in reason for reason in result.reasons)


def test_unknown_when_no_causal_trace(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    result = counterfactual.simulate_action(
        task_id="task-1",
        plan_id=None,
        step_id=None,
        proposed_action="/exec ls /home/billyb",
        now=now,
    )
    assert result.status == "unknown"
    assert any("causal" in reason for reason in result.reasons)


def test_allowed_with_no_blockers(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    evidence.record_evidence(
        claim="service nginx is running",
        source_type="command",
        source_ref="systemctl",
        raw_content="active",
    )
    now = datetime.now(timezone.utc)
    result = counterfactual.simulate_action(
        task_id=None,
        plan_id=None,
        step_id=None,
        proposed_action="claim: service nginx is running",
        now=now,
    )
    assert result.status == "allowed"
