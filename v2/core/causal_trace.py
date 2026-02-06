from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Union
import json
import uuid

from core.guardrails.invariants import assert_trace_id
from core import evidence as evidence_store


CausalNodeType = str
ALLOWED_NODE_TYPES: set[str] = {"EVIDENCE", "DECISION", "ACTION", "OUTCOME", "BLOCKER"}
ALLOWED_RELATIONSHIPS: set[str] = {"caused_by", "requires", "blocked_by"}


@dataclass(frozen=True)
class CausalNode:
    node_id: str
    node_type: CausalNodeType
    description: str
    related_task_id: Optional[str]
    related_plan_id: Optional[str]
    related_step_id: Optional[str]
    timestamp: datetime

    def to_dict(self) -> dict:
        return {
            "record_type": "node",
            "node_id": self.node_id,
            "node_type": self.node_type,
            "description": self.description,
            "related_task_id": self.related_task_id,
            "related_plan_id": self.related_plan_id,
            "related_step_id": self.related_step_id,
            "timestamp": _dt_to_iso(self.timestamp),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CausalNode":
        return cls(
            node_id=str(data["node_id"]),
            node_type=_coerce_node_type(data["node_type"]),
            description=str(data["description"]),
            related_task_id=data.get("related_task_id"),
            related_plan_id=data.get("related_plan_id"),
            related_step_id=data.get("related_step_id"),
            timestamp=_dt_from_iso(data["timestamp"]),
        )


@dataclass(frozen=True)
class CausalEdge:
    from_node_id: str
    to_node_id: str
    relationship: str

    def to_dict(self) -> dict:
        return {
            "record_type": "edge",
            "from_node_id": self.from_node_id,
            "to_node_id": self.to_node_id,
            "relationship": self.relationship,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CausalEdge":
        return cls(
            from_node_id=str(data["from_node_id"]),
            to_node_id=str(data["to_node_id"]),
            relationship=_coerce_relationship(data["relationship"]),
        )


CAUSAL_TRACE_DIR = Path("v2/state/causal_traces")
CAUSAL_TRACE_DIR.mkdir(parents=True, exist_ok=True)

_CURRENT_TRACE_ID: Optional[str] = None


def load_trace(trace_id: str) -> Path:
    assert_trace_id(trace_id)
    global _CURRENT_TRACE_ID
    _CURRENT_TRACE_ID = trace_id
    path = _trace_path(trace_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()
    return path


def record_causal_node(node: CausalNode) -> None:
    _validate_node(node)
    path = _require_path()
    _append_line(path, node.to_dict())


def record_causal_edge(edge: CausalEdge) -> None:
    _validate_edge(edge)
    path = _require_path()
    _append_line(path, edge.to_dict())


def create_node(
    node_type: str,
    description: str,
    related_task_id: Optional[str] = None,
    related_plan_id: Optional[str] = None,
    related_step_id: Optional[str] = None,
) -> CausalNode:
    node = CausalNode(
        node_id=str(uuid.uuid4()),
        node_type=_coerce_node_type(node_type),
        description=description,
        related_task_id=related_task_id,
        related_plan_id=related_plan_id,
        related_step_id=related_step_id,
        timestamp=_now(),
    )
    record_causal_node(node)
    return node


def create_edge(from_node_id: str, to_node_id: str, relationship: str) -> CausalEdge:
    edge = CausalEdge(
        from_node_id=from_node_id,
        to_node_id=to_node_id,
        relationship=_coerce_relationship(relationship),
    )
    record_causal_edge(edge)
    return edge


def get_causal_trace(
    task_id: Optional[str] = None,
    plan_id: Optional[str] = None,
) -> List[Union[CausalNode, CausalEdge]]:
    path = _require_path(allow_missing=True)
    if not path or not path.exists():
        return []
    nodes: List[CausalNode] = []
    edges: List[CausalEdge] = []
    for record in _iter_records(path):
        if isinstance(record, CausalNode):
            nodes.append(record)
        else:
            edges.append(record)

    if not task_id and not plan_id:
        return nodes + edges

    filtered_nodes = [
        node
        for node in nodes
        if (task_id and node.related_task_id == task_id)
        or (plan_id and node.related_plan_id == plan_id)
    ]
    node_ids = {node.node_id for node in filtered_nodes}
    filtered_edges = [edge for edge in edges if edge.from_node_id in node_ids or edge.to_node_id in node_ids]

    related_node_ids = set(node_ids)
    for edge in filtered_edges:
        related_node_ids.add(edge.from_node_id)
        related_node_ids.add(edge.to_node_id)

    expanded_nodes = [node for node in nodes if node.node_id in related_node_ids]
    return expanded_nodes + filtered_edges


def find_latest_node_id(node_type: str, description: str) -> Optional[str]:
    path = _require_path(allow_missing=True)
    if not path or not path.exists():
        return None
    latest: Optional[CausalNode] = None
    for record in _iter_records(path):
        if isinstance(record, CausalNode) and record.node_type == node_type and record.description == description:
            if not latest or record.timestamp > latest.timestamp:
                latest = record
    return latest.node_id if latest else None


def explain_causal_chain(task_id: str) -> Optional[List[str]]:
    records = get_causal_trace(task_id=task_id)
    nodes = [r for r in records if isinstance(r, CausalNode)]
    edges = [r for r in records if isinstance(r, CausalEdge)]
    if not nodes:
        return None
    if not edges:
        return None
    now = datetime.now(timezone.utc)
    for node in nodes:
        if node.node_type == "EVIDENCE":
            if evidence_store.needs_revalidation(node.description, now):
                return None
    inbound = {node.node_id: 0 for node in nodes}
    for edge in edges:
        if edge.to_node_id in inbound:
            inbound[edge.to_node_id] += 1
    for node in nodes:
        if node.node_type != "EVIDENCE" and inbound[node.node_id] == 0:
            return None
    # Topological order for causal chain, deterministic by timestamp then id.
    graph = {node.node_id: [] for node in nodes}
    indegree = {node.node_id: 0 for node in nodes}
    for edge in edges:
        if edge.from_node_id in graph and edge.to_node_id in graph:
            graph[edge.from_node_id].append(edge.to_node_id)
            indegree[edge.to_node_id] += 1

    queue = sorted(
        [node for node in nodes if indegree[node.node_id] == 0],
        key=lambda n: (n.timestamp, n.node_id),
    )
    ordered: List[CausalNode] = []
    while queue:
        current = queue.pop(0)
        ordered.append(current)
        for neighbor in graph[current.node_id]:
            indegree[neighbor] -= 1
            if indegree[neighbor] == 0:
                next_node = next(n for n in nodes if n.node_id == neighbor)
                queue.append(next_node)
                queue.sort(key=lambda n: (n.timestamp, n.node_id))

    if len(ordered) != len(nodes):
        return None
    return [node.description for node in ordered]


def _trace_path(trace_id: str) -> Path:
    return CAUSAL_TRACE_DIR / f"{trace_id}.jsonl"


def _require_path(allow_missing: bool = False) -> Optional[Path]:
    if not _CURRENT_TRACE_ID:
        raise RuntimeError("Causal trace not loaded.")
    path = _trace_path(_CURRENT_TRACE_ID)
    if allow_missing:
        return path
    if not path.exists():
        raise RuntimeError("Causal trace store not initialized.")
    return path


def _append_line(path: Path, payload: dict) -> None:
    line = json.dumps(payload, sort_keys=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _iter_records(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_num, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid causal record at line {line_num}.") from exc
            if data.get("record_type") == "node":
                yield CausalNode.from_dict(data)
            elif data.get("record_type") == "edge":
                yield CausalEdge.from_dict(data)
            else:
                raise ValueError(f"Invalid causal record at line {line_num}.")


def _validate_node(node: CausalNode) -> None:
    _coerce_node_type(node.node_type)
    if not node.node_id or not node.description:
        raise ValueError("node_id and description are required.")


def _validate_edge(edge: CausalEdge) -> None:
    _coerce_relationship(edge.relationship)
    if not edge.from_node_id or not edge.to_node_id:
        raise ValueError("from_node_id and to_node_id are required.")


def _coerce_node_type(node_type: str) -> CausalNodeType:
    if node_type not in ALLOWED_NODE_TYPES:
        raise ValueError(f"Invalid node_type: {node_type}")
    return node_type


def _coerce_relationship(relationship: str) -> str:
    if relationship not in ALLOWED_RELATIONSHIPS:
        raise ValueError(f"Invalid relationship: {relationship}")
    return relationship


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
