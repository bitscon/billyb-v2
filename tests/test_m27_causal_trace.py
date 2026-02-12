from datetime import datetime, timezone

import v2.core.causal_trace as causal_trace
import v2.core.evidence as evidence
import v2.core.introspection as introspection
import v2.core.task_graph as task_graph
from v2.core.runtime import _run_deterministic_loop


def _setup_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence, "EVIDENCE_DIR", tmp_path / "evidence")
    evidence.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    evidence._CURRENT_TRACE_ID = None

    monkeypatch.setattr(causal_trace, "CAUSAL_TRACE_DIR", tmp_path / "causal")
    causal_trace.CAUSAL_TRACE_DIR.mkdir(parents=True, exist_ok=True)
    causal_trace._CURRENT_TRACE_ID = None

    monkeypatch.setattr(task_graph, "TASK_GRAPH_DIR", tmp_path / "task_graph")
    task_graph.TASK_GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    task_graph._CURRENT_TRACE_ID = None


def _prepare_ready_task(trace_id: str, description: str):
    graph = task_graph.load_graph(trace_id)
    task_id = task_graph.create_task(description)
    task_graph.update_status(task_id, "ready")
    task_graph.save_graph(trace_id)
    return task_id


def test_evidence_creates_causal_node(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    evidence.load_evidence("trace-1")
    causal_trace.load_trace("trace-1")
    evidence.record_evidence(
        claim="host.hostname",
        source_type="introspection",
        source_ref="m25:host",
        raw_content="host-a",
    )
    records = causal_trace.get_causal_trace()
    nodes = [r for r in records if isinstance(r, causal_trace.CausalNode)]
    assert any(node.node_type == "EVIDENCE" and node.description == "host.hostname" for node in nodes)


def test_decision_creates_causal_node(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    evidence.load_evidence("trace-1")
    causal_trace.load_trace("trace-1")
    _prepare_ready_task("trace-1", "noop task")
    monkeypatch.setattr(introspection, "collect_environment_snapshot", lambda scope: introspection.EnvironmentSnapshot(
        snapshot_id="snap", collected_at=datetime.now(timezone.utc)
    ))
    _run_deterministic_loop("run", "trace-1")
    records = causal_trace.get_causal_trace()
    nodes = [r for r in records if isinstance(r, causal_trace.CausalNode)]
    assert any(node.node_type == "DECISION" for node in nodes)


def test_edges_link_nodes_correctly(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    evidence.load_evidence("trace-1")
    causal_trace.load_trace("trace-1")
    evidence.record_evidence(
        claim="alpha",
        source_type="command",
        source_ref="echo alpha",
        raw_content="alpha",
    )
    task_id = _prepare_ready_task("trace-1", "claim: alpha")
    monkeypatch.setattr(introspection, "collect_environment_snapshot", lambda scope: introspection.EnvironmentSnapshot(
        snapshot_id="snap", collected_at=datetime.now(timezone.utc)
    ))
    _run_deterministic_loop("run", "trace-1")
    records = causal_trace.get_causal_trace(task_id=task_id)
    edges = [r for r in records if isinstance(r, causal_trace.CausalEdge)]
    assert any(edge.relationship == "caused_by" for edge in edges)


def test_append_only(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    causal_trace.load_trace("trace-1")
    causal_trace.create_node("DECISION", "first")
    causal_trace.create_node("DECISION", "second")
    path = causal_trace.CAUSAL_TRACE_DIR / "trace-1.jsonl"
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_missing_causal_link_results_unknown(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    causal_trace.load_trace("trace-1")
    node = causal_trace.create_node("DECISION", "only decision", related_task_id="task-1")
    chain = causal_trace.explain_causal_chain("task-1")
    assert chain is None


def test_causal_trace_answers_match_nodes(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    causal_trace.load_trace("trace-1")
    evidence_node = causal_trace.create_node("EVIDENCE", "evidence", related_task_id="task-1")
    decision_node = causal_trace.create_node("DECISION", "decision", related_task_id="task-1")
    outcome_node = causal_trace.create_node("OUTCOME", "outcome", related_task_id="task-1")
    causal_trace.create_edge(evidence_node.node_id, decision_node.node_id, "caused_by")
    causal_trace.create_edge(decision_node.node_id, outcome_node.node_id, "caused_by")
    chain = causal_trace.explain_causal_chain("task-1")
    assert chain is not None
    assert "evidence" in chain
    assert "decision" in chain
    assert "outcome" in chain
