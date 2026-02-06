import pytest

import v2.core.task_graph as tg


def _reset_task_graph():
    tg._GRAPHS.clear()
    tg._CURRENT_TRACE_ID = None


def _setup_tmp_graph(tmp_path, monkeypatch, trace_id="trace-1"):
    monkeypatch.setattr(tg, "TASK_GRAPH_DIR", tmp_path / "task_graph")
    tg.TASK_GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    _reset_task_graph()
    return tg.load_graph(trace_id)


def test_graph_persists_after_reload(tmp_path, monkeypatch):
    _setup_tmp_graph(tmp_path, monkeypatch)
    task_id = tg.create_task("ship it")
    tg.update_status(task_id, "done")
    tg.save_graph("trace-1")

    _reset_task_graph()
    tg.load_graph("trace-1")
    graph = tg._GRAPHS["trace-1"]

    assert task_id in graph.tasks
    assert graph.tasks[task_id].status == "done"


def test_dependencies_enforce_readiness(tmp_path, monkeypatch):
    _setup_tmp_graph(tmp_path, monkeypatch)
    parent = tg.create_task("parent")
    child = tg.create_task("child")

    tg.add_dependency(child, parent)

    with pytest.raises(ValueError):
        tg.update_status(child, "ready")

    tg.update_status(parent, "done")
    tg.update_status(child, "ready")


def test_blocked_tasks_stay_blocked(tmp_path, monkeypatch):
    _setup_tmp_graph(tmp_path, monkeypatch)
    task_id = tg.create_task("blocked")

    tg.add_dependency(task_id, "missing-task")
    graph = tg._GRAPHS["trace-1"]
    assert graph.tasks[task_id].status == "blocked"

    ready = tg.get_ready_tasks()
    assert task_id not in {node.task_id for node in ready}

    with pytest.raises(ValueError):
        tg.update_status(task_id, "ready")


def test_invalid_transitions_fail(tmp_path, monkeypatch):
    _setup_tmp_graph(tmp_path, monkeypatch)
    task_id = tg.create_task("terminal")

    tg.update_status(task_id, "done")
    with pytest.raises(ValueError):
        tg.update_status(task_id, "pending")


def test_multiple_tasks_do_not_collide(tmp_path, monkeypatch):
    _setup_tmp_graph(tmp_path, monkeypatch)
    task_ids = {tg.create_task(f"task-{idx}") for idx in range(5)}

    assert len(task_ids) == 5
