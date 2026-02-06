from datetime import datetime, timezone

import core.runtime as runtime_mod
import core.task_graph as tg
import core.evidence as evidence
import core.causal_trace as causal_trace
import core.introspection as introspection


def _setup_dirs(tmp_path, monkeypatch, trace_id="trace-1"):
    monkeypatch.setattr(tg, "TASK_GRAPH_DIR", tmp_path / "task_graph")
    tg.TASK_GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(evidence, "EVIDENCE_DIR", tmp_path / "evidence")
    evidence.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(causal_trace, "CAUSAL_TRACE_DIR", tmp_path / "causal_traces")
    causal_trace.CAUSAL_TRACE_DIR.mkdir(parents=True, exist_ok=True)
    tg._GRAPHS.clear()
    tg._CURRENT_TRACE_ID = None
    evidence._CURRENT_TRACE_ID = None
    causal_trace._CURRENT_TRACE_ID = None
    return trace_id


def test_inspection_task_triggers_introspection_once(tmp_path, monkeypatch):
    trace_id = _setup_dirs(tmp_path, monkeypatch)
    calls = []

    def fake_snapshot(scope):
        calls.append(scope)
        return introspection.EnvironmentSnapshot(
            snapshot_id="snap-1",
            collected_at=datetime.now(timezone.utc),
            services={"systemd_units": []},
            containers={"containers": []},
            network={"listening_sockets": []},
            filesystem={"paths": []},
        )

    monkeypatch.setattr(introspection, "collect_environment_snapshot", fake_snapshot)

    response = runtime_mod.run_turn("Locate n8n on the barn", {"trace_id": trace_id})
    output = response["final_output"]
    assert "TASK ORIGINATION:" in output
    assert "TASK SELECTION:" in output
    assert "INTROSPECTION:" in output

    graph = tg.load_graph(trace_id)
    task = next(iter(graph.tasks.values()))
    assert task.status in ("ready", "blocked")

    claim = f"task:{task.task_id}:introspection"
    records = evidence.list_evidence(claim)
    assert records

    response2 = runtime_mod.run_turn("Locate n8n on the barn", {"trace_id": trace_id})
    records2 = evidence.list_evidence(claim)
    assert len(records2) == len(records)
    assert len(calls) == 1
