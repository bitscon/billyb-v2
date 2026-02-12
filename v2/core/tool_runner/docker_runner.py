import subprocess
import tempfile
import time
from pathlib import Path
from v2.core.contracts.loader import validate_trace_event, ContractViolation

class DockerRunner:
    def __init__(self, trace_sink):
        self.trace_sink = trace_sink

    def run(self, tool_spec: dict, image: str, args: list[str], trace_id: str):
        start = time.time()
        workdir = Path(tempfile.mkdtemp(prefix="billy-tool-"))

        permissions = tool_spec["permissions"]
        exec_cfg = permissions["execution"]

        timeout = exec_cfg.get("max_duration_sec", 30)

        self._emit(trace_id, "tool_run_start", {
            "tool_id": tool_spec["id"],
            "image": image,
            "workdir": str(workdir),
        })

        try:
            cmd = [
                "docker", "run", "--rm",
                "--network", "none",
                "-v", f"{workdir}:/workspace",
            ]
            cmd.append(image)
            cmd.extend(args)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            artifact_path = workdir / "output.txt"
            artifact_path.write_text(result.stdout)

            self._emit(trace_id, "tool_run_end", {
                "tool_id": tool_spec["id"],
                "exit_code": result.returncode,
                "artifact": str(artifact_path),
            })

            return {
                "status": "success" if result.returncode == 0 else "error",
                "stdout": result.stdout,
                "stderr": result.stderr,
                "artifact": str(artifact_path),
                "duration_ms": int((time.time() - start) * 1000),
            }

        except Exception as e:
            self._emit(trace_id, "tool_run_end", {
                "tool_id": tool_spec["id"],
                "error": str(e),
            })
            raise

    def _emit(self, trace_id: str, event_type: str, payload: dict):
        event = {
            "trace_id": trace_id,
            "event_id": f"{event_type}-{int(time.time()*1000)}",
            "event_type": event_type,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "actor": {"component": "tool_runner"},
            "payload": payload,
        }
        validate_trace_event(event)
        self.trace_sink.emit(event)
