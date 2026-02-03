from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Optional

WORKSPACE_ROOT = Path(__file__).resolve().parent / "workspace"

_TASK_PREFIX = "task_"
_TASK_VERSION_PREFIX = "__v"


def ensure_workspace_root() -> Path:
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    return WORKSPACE_ROOT


def slugify(text: str, max_len: int = 40) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        text = "task"
    return text[:max_len]


def create_task_dir(prompt: str, now: Optional[datetime] = None) -> Path:
    ensure_workspace_root()
    now = now or datetime.utcnow()
    slug = slugify(prompt)
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    base_name = f"{_TASK_PREFIX}{slug}{_TASK_VERSION_PREFIX}{timestamp}"

    candidate = WORKSPACE_ROOT / base_name
    if not candidate.exists():
        candidate.mkdir(parents=True, exist_ok=False)
        return candidate

    # If we somehow collide, append a counter.
    for i in range(1, 1000):
        candidate = WORKSPACE_ROOT / f"{base_name}_{i}"
        if not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=False)
            return candidate

    raise RuntimeError("Unable to create unique task directory.")


def _assert_within_workspace(path: Path) -> None:
    resolved = path.resolve()
    if not resolved.is_relative_to(WORKSPACE_ROOT.resolve()):
        raise ValueError("Attempted write outside workspace root.")


def write_artifact(task_dir: Path, filename: str, content: str) -> Path:
    ensure_workspace_root()
    if "/" in filename or "\\" in filename:
        raise ValueError("Artifact filename must not include path separators.")

    target = (task_dir / filename).resolve()
    _assert_within_workspace(target)

    # Enforce immutability: fail if the file already exists.
    with open(target, "x", encoding="utf-8") as f:
        f.write(content.rstrip() + "\n")

    return target


def list_task_dirs() -> list[Path]:
    ensure_workspace_root()
    return sorted([p for p in WORKSPACE_ROOT.iterdir() if p.is_dir()])
