import v2.core.runtime as runtime_mod
import v2.core.task_graph as tg
import v2.core.evidence as evidence
import v2.core.causal_trace as causal_trace
import v2.core.introspection as introspection


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
    monkeypatch.setattr(introspection, "collect_environment_snapshot", lambda scope: None)
    return trace_id


def test_creates_task_when_none_exist(tmp_path, monkeypatch):
    trace_id = _setup_dirs(tmp_path, monkeypatch)
    response = runtime_mod.run_turn("locate n8n on the barn", {"trace_id": trace_id})
    output = response["final_output"]
    assert "TASK ORIGINATION:" in output
    assert "TASK SELECTION:" in output

    graph = tg.load_graph(trace_id)
    assert len(graph.tasks) == 1
    task = next(iter(graph.tasks.values()))
    assert task.status == "ready"
    assert task.description.startswith("Locate/Inspect:")


def test_does_not_create_task_if_blocked_tasks_exist(tmp_path, monkeypatch):
    trace_id = _setup_dirs(tmp_path, monkeypatch)
    tg.load_graph(trace_id)
    task_id = tg.create_task("claim:blocked")
    tg.block_task(task_id, "pre-blocked")
    tg.save_graph(trace_id)

    response = runtime_mod.run_turn("locate n8n", {"trace_id": trace_id})
    output = response["final_output"]
    assert "TASK ORIGINATION:" not in output

    graph = tg.load_graph(trace_id)
    assert len(graph.tasks) == 1


def test_deterministic_classification():
    assert runtime_mod._classify_dto_type("check what ports are open") == "inspection"
    assert runtime_mod._classify_dto_type("restart nginx") == "action"
    assert runtime_mod._classify_dto_type("why is nginx failing") == "analysis"


def test_exactly_one_task_created(tmp_path, monkeypatch):
    trace_id = _setup_dirs(tmp_path, monkeypatch)
    runtime_mod.run_turn("locate n8n on the barn", {"trace_id": trace_id})
    graph = tg.load_graph(trace_id)
    assert len(graph.tasks) == 1
