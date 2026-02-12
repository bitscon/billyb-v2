from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import getpass
import json
import os
import platform
import shutil
import socket
import subprocess
import uuid

from v2.core.evidence import record_evidence

ALLOWED_SCOPES = {"host", "services", "containers", "filesystem", "network"}
DEFAULT_SCOPE = ["host", "services", "containers", "filesystem", "network"]
DEFAULT_TTL_SECONDS = 300
READONLY_COMMANDS = {
    "uptime",
    "systemctl",
    "ps",
    "ss",
    "docker",
    "podman",
    "mount",
    "ip",
    "ifconfig",
}

SAFE_PATHS = [
    "/",
    "/etc",
    "/etc/systemd/system",
    "/lib/systemd/system",
    "/var",
    "/opt",
    "/srv",
    "/home",
    "/home/billyb",
]


@dataclass
class EnvironmentSnapshot:
    snapshot_id: str
    collected_at: datetime
    host: Dict[str, Any] = field(default_factory=dict)
    services: Dict[str, Any] = field(default_factory=dict)
    containers: Dict[str, Any] = field(default_factory=dict)
    filesystem: Dict[str, Any] = field(default_factory=dict)
    network: Dict[str, Any] = field(default_factory=dict)


class IntrospectionError(RuntimeError):
    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


def collect_environment_snapshot(scope: List[str]) -> EnvironmentSnapshot:
    if not scope:
        raise IntrospectionError("SCOPE_INVALID", "Scope is required for introspection.")
    invalid = [item for item in scope if item not in ALLOWED_SCOPES]
    if invalid:
        raise IntrospectionError("SCOPE_INVALID", f"Scope includes unsupported categories: {invalid}")

    snapshot = EnvironmentSnapshot(
        snapshot_id=str(uuid.uuid4()),
        collected_at=datetime.now(timezone.utc),
    )

    if "host" in scope:
        host = _probe_host()
        snapshot.host = host
        _record_section_evidence("host", host)
    if "services" in scope:
        services = _probe_services()
        snapshot.services = services
        _record_section_evidence("services", services)
    if "containers" in scope:
        containers = _probe_containers()
        snapshot.containers = containers
        _record_section_evidence("containers", containers)
    if "filesystem" in scope:
        filesystem = _probe_filesystem()
        snapshot.filesystem = filesystem
        _record_section_evidence("filesystem", filesystem)
    if "network" in scope:
        network = _probe_network()
        snapshot.network = network
        _record_section_evidence("network", network)

    return snapshot


def _probe_host() -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "hostname": socket.gethostname(),
        "os": platform.platform(),
        "uptime": _run_command(["uptime", "-p"])[1],
        "current_user": getpass.getuser(),
        "pid_namespace": _safe_readlink("/proc/self/ns/pid"),
    }
    return data


def _probe_services() -> Dict[str, Any]:
    systemd_ok, systemd_out = _run_command(
        ["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--no-legend"]
    )
    ps_ok, ps_out = _run_command(["ps", "-eo", "pid,comm"])
    ss_ok, ss_out = _run_command(["ss", "-lntu"])
    return {
        "systemd_available": systemd_ok,
        "systemd_units": _split_lines(systemd_out) if systemd_ok else [],
        "process_list": _split_lines(ps_out) if ps_ok else [],
        "listening_ports": _split_lines(ss_out) if ss_ok else [],
    }


def _probe_containers() -> Dict[str, Any]:
    docker_path = shutil.which("docker")
    podman_path = shutil.which("podman")
    if docker_path and podman_path:
        raise IntrospectionError(
            "ENV_AMBIGUOUS",
            "Multiple container runtimes detected (docker and podman).",
        )

    if docker_path:
        ok, out = _run_command(["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"])
        return {
            "runtime": "docker",
            "available": ok,
            "containers": _parse_container_lines(out) if ok else [],
        }
    if podman_path:
        ok, out = _run_command(["podman", "ps", "--format", "{{.Names}}\t{{.Ports}}"])
        return {
            "runtime": "podman",
            "available": ok,
            "containers": _parse_container_lines(out) if ok else [],
        }
    return {
        "runtime": None,
        "available": False,
        "containers": [],
    }


def _probe_filesystem() -> Dict[str, Any]:
    paths = []
    for path in SAFE_PATHS:
        info = _path_metadata(path)
        if info:
            paths.append(info)
    mount_ok, mount_out = _run_command(["mount"])
    return {
        "paths": paths,
        "mounts": _split_lines(mount_out) if mount_ok else [],
    }


def _probe_network() -> Dict[str, Any]:
    ip_cmd = ["ip", "-o", "addr", "show"]
    if not shutil.which("ip"):
        ip_cmd = ["ifconfig", "-a"]
    ip_ok, ip_out = _run_command(ip_cmd)
    ss_ok, ss_out = _run_command(["ss", "-lntu"])
    return {
        "interfaces": _split_lines(ip_out) if ip_ok else [],
        "listening_sockets": _split_lines(ss_out) if ss_ok else [],
    }


def _record_section_evidence(section: str, data: Dict[str, Any]) -> None:
    for key, value in data.items():
        claim = f"{section}.{key}"
        raw = json.dumps(value, sort_keys=True)
        record_evidence(
            claim=claim,
            source_type="introspection",
            source_ref=f"m25:{section}",
            raw_content=raw,
            ttl_seconds=DEFAULT_TTL_SECONDS,
        )


def _run_command(command: List[str], timeout: int = 3) -> Tuple[bool, str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError:
        return False, "command not found"
    except subprocess.TimeoutExpired:
        return False, "command timed out"
    except Exception as exc:
        return False, f"command failed: {exc}"

    stderr = (result.stderr or "").strip()
    if stderr and "permission denied" in stderr.lower():
        raise IntrospectionError("PRIVILEGE_REQUIRED", f"Probe requires elevated privileges: {' '.join(command)}")

    output = (result.stdout or "").strip()
    if not output:
        output = stderr
    return result.returncode == 0, output or "no output"


def _split_lines(output: str) -> List[str]:
    return [line.strip() for line in output.splitlines() if line.strip()]


def _parse_container_lines(output: str) -> List[Dict[str, str]]:
    containers = []
    for line in output.splitlines():
        if not line.strip():
            continue
        name, ports = (line.split("\t", 1) + [""])[:2]
        containers.append({"name": name.strip(), "ports": ports.strip()})
    return containers


def _safe_readlink(path: str) -> str:
    try:
        return os.readlink(path)
    except Exception:
        return "unavailable"


def _path_metadata(path: str) -> Optional[Dict[str, Any]]:
    try:
        exists = os.path.exists(path)
    except Exception:
        return None
    if not exists:
        return {"path": path, "exists": False}
    try:
        stat = os.stat(path, follow_symlinks=False)
    except Exception:
        return {"path": path, "exists": True, "stat": "unavailable"}
    info: Dict[str, Any] = {
        "path": path,
        "exists": True,
        "mode": oct(stat.st_mode & 0o777),
        "uid": stat.st_uid,
        "gid": stat.st_gid,
        "is_dir": os.path.isdir(path),
    }
    if info["is_dir"]:
        try:
            entries = sorted(os.listdir(path))[:50]
            info["entries"] = entries
        except Exception:
            info["entries"] = []
    return info
