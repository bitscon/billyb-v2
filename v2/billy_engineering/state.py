from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

STATE_PATH = Path(__file__).resolve().parent / "state" / "engineering_state.json"

DEFAULT_STATE: Dict[str, Any] = {
    "phase": "draft",
    "current_task_id": None,
    "updated_at": None,
}


def _write_state(state: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")


def load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        _write_state(DEFAULT_STATE.copy())
        return DEFAULT_STATE.copy()

    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("State file is not a dict.")
        return data
    except Exception:
        _write_state(DEFAULT_STATE.copy())
        return DEFAULT_STATE.copy()


def update_state(**kwargs: Any) -> Dict[str, Any]:
    state = load_state()
    state.update(kwargs)
    state["updated_at"] = datetime.utcnow().isoformat() + "Z"
    _write_state(state)
    return state
