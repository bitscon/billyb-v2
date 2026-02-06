from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Literal
import uuid
import yaml

from core.guardrails.invariants import assert_trace_id


TaskStatus = Literal["pending", "ready", "blocked", "done", "failed"]


@dataclass
class TaskNode:
    task_id: str
    parent_id: Optional[str]
    description: str
    status: TaskStatus
    depends_on: List[str]
    created_at: datetime
    updated_at: datetime
    block_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "parent_id": self.parent_id,
            "description": self.description,
            "status": self.status,
            "depends_on": list(self.depends_on),
            "created_at": _dt_to_iso(self.created_at),
            "updated_at": _dt_to_iso(self.updated_at),
            "block_reason": self.block_reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskNode":
        return cls(
            task_id=str(data["task_id"]),
            parent_id=data.get("parent_id"),
            description=str(data["description"]),
            status=_coerce_status(data["status"]),
            depends_on=list(data.get("depends_on") or []),
            created_at=_dt_from_iso(data["created_at"]),
            updated_at=_dt_from_iso(data["updated_at"]),
            block_reason=data.get("block_reason"),
        )


@dataclass
class TaskGraph:
    trace_id: str
    tasks: Dict[str, TaskNode]

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "tasks": {task_id: node.to_dict() for task_id, node in self.tasks.items()},
        }

    @classmethod
    def from_dict(cls, trace_id: str, data: dict) -> "TaskGraph":
        if data.get("trace_id") and data.get("trace_id") != trace_id:
            raise ValueError("Trace ID mismatch in task graph file.")
        raw_tasks = data.get("tasks") or {}
        tasks: Dict[str, TaskNode] = {}
        for task_id, payload in raw_tasks.items():
            node = TaskNode.from_dict(payload)
            if node.task_id != task_id:
                raise ValueError("Task ID mismatch in task graph file.")
            tasks[task_id] = node
        graph = cls(trace_id=trace_id, tasks=tasks)
        _validate_graph(graph)
        return graph


TASK_GRAPH_DIR = Path("v2/state/task_graph")
TASK_GRAPH_DIR.mkdir(parents=True, exist_ok=True)

_GRAPHS: Dict[str, TaskGraph] = {}
_CURRENT_TRACE_ID: Optional[str] = None


ALLOWED_STATUSES: set[str] = {"pending", "ready", "blocked", "done", "failed"}


def create_task(description: str, parent_id: Optional[str] = None) -> str:
    graph = _require_graph()
    task_id = str(uuid.uuid4())
    now = _now()
    node = TaskNode(
        task_id=task_id,
        parent_id=parent_id,
        description=description,
        status="pending",
        depends_on=[],
        created_at=now,
        updated_at=now,
        block_reason=None,
    )
    graph.tasks[task_id] = node
    _validate_graph(graph)
    return task_id


def add_dependency(task_id: str, depends_on: str) -> None:
    graph = _require_graph()
    node = graph.tasks.get(task_id)
    if not node:
        raise ValueError(f"Unknown task_id: {task_id}")
    if depends_on not in node.depends_on:
        node.depends_on.append(depends_on)
    if node.status == "ready" and not _deps_done(node, graph):
        node.status = "blocked"
        if not node.block_reason:
            node.block_reason = f"dependency not ready: {depends_on}"
    if depends_on not in graph.tasks and node.status not in ("done", "failed"):
        node.status = "blocked"
        if not node.block_reason:
            node.block_reason = f"missing dependency: {depends_on}"
    node.updated_at = _now()
    _validate_graph(graph)


def update_status(task_id: str, status: str) -> None:
    graph = _require_graph()
    node = graph.tasks.get(task_id)
    if not node:
        raise ValueError(f"Unknown task_id: {task_id}")
    new_status = _coerce_status(status)
    _ensure_transition(node, new_status, graph)
    node.status = new_status
    node.updated_at = _now()
    _validate_graph(graph)


def block_task(task_id: str, reason: str) -> None:
    if not reason:
        raise ValueError("Block reason is required.")
    graph = _require_graph()
    node = graph.tasks.get(task_id)
    if not node:
        raise ValueError(f"Unknown task_id: {task_id}")
    node.block_reason = reason
    update_status(task_id, "blocked")


def get_ready_tasks() -> List[TaskNode]:
    graph = _require_graph()
    _validate_graph(graph)
    return [
        node
        for node in graph.tasks.values()
        if node.status == "ready" and _deps_done(node, graph)
    ]


def load_graph(trace_id: str) -> TaskGraph:
    assert_trace_id(trace_id)
    path = _graph_path(trace_id)
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ValueError("Task graph file is invalid.")
        graph = TaskGraph.from_dict(trace_id, raw)
    else:
        graph = TaskGraph(trace_id=trace_id, tasks={})
        _save_graph_to_path(graph, path)
    _GRAPHS[trace_id] = graph
    global _CURRENT_TRACE_ID
    _CURRENT_TRACE_ID = trace_id
    return graph


def save_graph(trace_id: str) -> None:
    assert_trace_id(trace_id)
    graph = _GRAPHS.get(trace_id)
    if not graph:
        raise ValueError("Task graph not loaded for trace_id.")
    _validate_graph(graph)
    _save_graph_to_path(graph, _graph_path(trace_id))


def _graph_path(trace_id: str) -> Path:
    return TASK_GRAPH_DIR / f"{trace_id}.yaml"


def _save_graph_to_path(graph: TaskGraph, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = graph.to_dict()
    path.write_text(
        yaml.safe_dump(payload, sort_keys=True),
        encoding="utf-8",
    )


def _require_graph() -> TaskGraph:
    if not _CURRENT_TRACE_ID:
        raise RuntimeError("Task graph not loaded.")
    graph = _GRAPHS.get(_CURRENT_TRACE_ID)
    if not graph:
        raise RuntimeError("Task graph not loaded.")
    return graph


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dt_to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _dt_from_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _coerce_status(status: str) -> TaskStatus:
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"Invalid status: {status}")
    return status  # type: ignore[return-value]


def _deps_done(node: TaskNode, graph: TaskGraph) -> bool:
    for dep_id in node.depends_on:
        dep = graph.tasks.get(dep_id)
        if not dep or dep.status != "done":
            return False
    return True


def _deps_blocking(node: TaskNode, graph: TaskGraph) -> bool:
    for dep_id in node.depends_on:
        dep = graph.tasks.get(dep_id)
        if not dep or dep.status != "done":
            return True
    return False


def _ensure_transition(node: TaskNode, new_status: TaskStatus, graph: TaskGraph) -> None:
    if node.status in ("done", "failed") and new_status != node.status:
        raise ValueError("Terminal status cannot transition.")
    if new_status == "ready" and _deps_blocking(node, graph):
        raise ValueError("Task cannot be ready until dependencies are done.")
    if new_status == "blocked":
        if node.block_reason:
            return
        if _deps_blocking(node, graph):
            return
        raise ValueError("Blocked status requires a block reason or blocking dependency.")


def _validate_graph(graph: TaskGraph) -> None:
    for node in graph.tasks.values():
        if node.status not in ALLOWED_STATUSES:
            raise ValueError(f"Invalid status for task {node.task_id}")
        if node.status == "ready" and _deps_blocking(node, graph):
            raise ValueError(f"Ready task has blocking dependencies: {node.task_id}")
        if node.status == "blocked":
            if node.block_reason:
                continue
            if _deps_blocking(node, graph):
                continue
            raise ValueError(f"Blocked task missing reason and dependencies: {node.task_id}")
