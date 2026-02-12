import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

import v2.core.runtime as runtime_mod
import v2.core.task_graph as tg
import v2.core.evidence as evidence
import v2.core.causal_trace as causal_trace
import v2.core.introspection as introspection
from v2.core.resolution.resolver import build_task, resolve_task, empty_evidence_bundle
from v2.core.resolution.rules import EvidenceBundle, InspectionMeta
from v2.core.resolution.outcomes import M27_CONTRACT_VERSION, ResolutionOutcome


class TestM27ResolutionEngine(unittest.TestCase):
    def _setup_dirs(self, tmp_path, trace_id="trace-1"):
        tg.TASK_GRAPH_DIR = tmp_path / "task_graph"
        tg.TASK_GRAPH_DIR.mkdir(parents=True, exist_ok=True)
        evidence.EVIDENCE_DIR = tmp_path / "evidence"
        evidence.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        causal_trace.CAUSAL_TRACE_DIR = tmp_path / "causal_traces"
        causal_trace.CAUSAL_TRACE_DIR.mkdir(parents=True, exist_ok=True)
        runtime_mod._execution_journal.base_dir = tmp_path / "executions"
        runtime_mod._execution_journal.base_dir.mkdir(parents=True, exist_ok=True)
        runtime_mod._execution_journal.records_path = runtime_mod._execution_journal.base_dir / "journal.jsonl"
        tg._GRAPHS.clear()
        tg._CURRENT_TRACE_ID = None
        evidence._CURRENT_TRACE_ID = None
        causal_trace._CURRENT_TRACE_ID = None
        runtime_mod._last_introspection_snapshot.clear()
        runtime_mod._last_resolution.clear()
        return trace_id

    def _read_resolution_records(self, journal_path, task_id):
        records = []
        if not journal_path.exists():
            return records
        for line in journal_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            resolution = payload.get("resolution")
            if resolution and resolution.get("task_id") == task_id:
                records.append(resolution)
        return records

    def _read_inspection_records(self, journal_path, origin_task_id):
        records = []
        if not journal_path.exists():
            return records
        for line in journal_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            inspection_task = payload.get("inspection_task")
            if inspection_task and inspection_task.get("origin_task_id") == origin_task_id:
                records.append(inspection_task)
        return records

    def _inspection_completed(self):
        return InspectionMeta(
            completed=True,
            source="introspection",
            inspected_at=datetime.now(timezone.utc).isoformat(),
            scope=["services", "containers", "network", "filesystem"],
        )

    def test_resolver_emits_single_outcome(self):
        task = build_task("task-1", "Locate/Inspect: Locate n8n on the barn [origin:dto scope:read_only]")
        inspection = InspectionMeta(completed=False, source="introspection", inspected_at=None, scope=[])
        outcome = resolve_task(task, empty_evidence_bundle(), inspection).outcome
        self.assertIn(outcome.outcome_type, {"RESOLVED", "BLOCKED", "ESCALATE", "FOLLOW_UP_INSPECTION"})

    def test_resolver_is_deterministic(self):
        task = build_task("task-1", "Locate/Inspect: Locate n8n on the barn [origin:dto scope:read_only]")
        evidence_bundle = EvidenceBundle(
            services_units=["n8n.service loaded active running"],
            services_processes=[],
            services_listening_ports=[],
            containers=[],
            network_listening_sockets=[],
        )
        inspection = self._inspection_completed()
        first = resolve_task(task, evidence_bundle, inspection).outcome.to_dict()
        second = resolve_task(task, evidence_bundle, inspection).outcome.to_dict()
        self.assertEqual(first, second)

    def test_locate_n8n_resolves_found(self):
        task = build_task("task-1", "Locate/Inspect: Locate n8n on the barn [origin:dto scope:read_only]")
        evidence_bundle = EvidenceBundle(
            services_units=["n8n.service loaded active running"],
            services_processes=[],
            services_listening_ports=[],
            containers=[],
            network_listening_sockets=[],
        )
        inspection = self._inspection_completed()
        outcome = resolve_task(task, evidence_bundle, inspection).outcome
        self.assertEqual(outcome.outcome_type, "RESOLVED")

    def test_locate_n8n_resolves_not_found(self):
        task = build_task("task-1", "Locate/Inspect: Locate n8n on the barn [origin:dto scope:read_only]")
        evidence_bundle = empty_evidence_bundle()
        inspection = self._inspection_completed()
        outcome = resolve_task(task, evidence_bundle, inspection).outcome
        self.assertEqual(outcome.outcome_type, "BLOCKED")
        self.assertEqual(outcome.next_step, "/ops Locate n8n on the barn")

    def test_locate_n8n_resolves_ambiguous(self):
        task = build_task("task-1", "Locate/Inspect: Locate n8n on the barn [origin:dto scope:read_only]")
        evidence_bundle = EvidenceBundle(
            services_units=[],
            services_processes=["123 n8n"],
            services_listening_ports=[],
            containers=[],
            network_listening_sockets=[],
        )
        inspection = self._inspection_completed()
        outcome = resolve_task(task, evidence_bundle, inspection).outcome
        self.assertEqual(outcome.outcome_type, "FOLLOW_UP_INSPECTION")

    def test_resolution_does_not_repeat_inspection(self):
        import tempfile
        tmp_dir = tempfile.TemporaryDirectory()
        trace_id = self._setup_dirs(Path(tmp_dir.name))
        calls = []

        def fake_snapshot(scope):
            calls.append(scope)
            return introspection.EnvironmentSnapshot(
                snapshot_id="snap-1",
                collected_at=datetime.now(timezone.utc),
                services={
                    "systemd_units": [],
                    "process_list": [],
                    "listening_ports": [],
                },
                containers={"containers": []},
                network={"listening_sockets": []},
                filesystem={"paths": []},
            )

        original_snapshot = introspection.collect_environment_snapshot
        introspection.collect_environment_snapshot = fake_snapshot
        try:
            response = runtime_mod.run_turn("Locate n8n on the barn", {"trace_id": trace_id})
            output = response["final_output"]
            self.assertEqual(output.get("resolution_type"), "BLOCKED")

            response2 = runtime_mod.run_turn("Locate n8n on the barn", {"trace_id": trace_id})
            output2 = response2["final_output"]
            self.assertEqual(output2.get("resolution_type"), "BLOCKED")
            self.assertEqual(len(calls), 1)
        finally:
            introspection.collect_environment_snapshot = original_snapshot
            tmp_dir.cleanup()

    def test_runtime_resolved_has_no_next_step(self):
        import tempfile
        tmp_dir = tempfile.TemporaryDirectory()
        trace_id = self._setup_dirs(Path(tmp_dir.name))

        def fake_snapshot(scope):
            return introspection.EnvironmentSnapshot(
                snapshot_id="snap-1",
                collected_at=datetime.now(timezone.utc),
                services={
                    "systemd_units": ["n8n.service loaded active running"],
                    "process_list": [],
                    "listening_ports": [],
                },
                containers={"containers": []},
                network={"listening_sockets": []},
                filesystem={"paths": []},
            )

        original_snapshot = introspection.collect_environment_snapshot
        introspection.collect_environment_snapshot = fake_snapshot
        try:
            response = runtime_mod.run_turn("Locate n8n on the barn", {"trace_id": trace_id})
            output = response["final_output"]
            self.assertEqual(output.get("resolution_type"), "RESOLVED")
            self.assertTrue(output.get("next_step") is None)
        finally:
            introspection.collect_environment_snapshot = original_snapshot
            tmp_dir.cleanup()

    def test_runtime_emits_single_resolution(self):
        import tempfile
        tmp_dir = tempfile.TemporaryDirectory()
        trace_id = self._setup_dirs(Path(tmp_dir.name))

        def fake_snapshot(scope):
            return introspection.EnvironmentSnapshot(
                snapshot_id="snap-1",
                collected_at=datetime.now(timezone.utc),
                services={
                    "systemd_units": [],
                    "process_list": [],
                    "listening_ports": [],
                },
                containers={"containers": []},
                network={"listening_sockets": []},
                filesystem={"paths": []},
            )

        original_snapshot = introspection.collect_environment_snapshot
        introspection.collect_environment_snapshot = fake_snapshot
        try:
            response = runtime_mod.run_turn("Locate n8n on the barn", {"trace_id": trace_id})
            output = response["final_output"]
            self.assertEqual(output.get("resolution_type"), "BLOCKED")
        finally:
            introspection.collect_environment_snapshot = original_snapshot
            tmp_dir.cleanup()

    def test_runtime_response_schema(self):
        import tempfile
        tmp_dir = tempfile.TemporaryDirectory()
        trace_id = self._setup_dirs(Path(tmp_dir.name))

        def fake_snapshot(scope):
            return introspection.EnvironmentSnapshot(
                snapshot_id="snap-1",
                collected_at=datetime.now(timezone.utc),
                services={
                    "systemd_units": ["n8n.service loaded active running"],
                    "process_list": [],
                    "listening_ports": [],
                },
                containers={"containers": []},
                network={"listening_sockets": []},
                filesystem={"paths": []},
            )

        original_snapshot = introspection.collect_environment_snapshot
        introspection.collect_environment_snapshot = fake_snapshot
        try:
            response = runtime_mod.run_turn("Locate n8n on the barn", {"trace_id": trace_id})
            output = response["final_output"]
            self.assertEqual(sorted(output.keys()), ["message", "next_step", "resolution_type", "task_id"])
        finally:
            introspection.collect_environment_snapshot = original_snapshot
            tmp_dir.cleanup()

    def test_resolver_emits_contract_version(self):
        task = build_task("task-1", "Locate/Inspect: Locate n8n on the barn [origin:dto scope:read_only]")
        inspection = InspectionMeta(completed=False, source="introspection", inspected_at=None, scope=[])
        outcome = resolve_task(task, empty_evidence_bundle(), inspection).outcome
        self.assertEqual(outcome.contract_version, M27_CONTRACT_VERSION)

    def test_runtime_rejects_contract_version_mismatch(self):
        import tempfile
        from v2.core.resolution import resolver as resolver_mod

        tmp_dir = tempfile.TemporaryDirectory()
        trace_id = self._setup_dirs(Path(tmp_dir.name))

        class BadResult:
            def __init__(self):
                self.outcome = ResolutionOutcome(
                    outcome_type="RESOLVED",
                    message="ok",
                    contract_version="0.9",
                )

        original_resolve = resolver_mod.resolve_task
        original_snapshot = introspection.collect_environment_snapshot

        def fake_snapshot(scope):
            return introspection.EnvironmentSnapshot(
                snapshot_id="snap-1",
                collected_at=datetime.now(timezone.utc),
                services={
                    "systemd_units": ["n8n.service loaded active running"],
                    "process_list": [],
                    "listening_ports": [],
                },
                containers={"containers": []},
                network={"listening_sockets": []},
                filesystem={"paths": []},
            )

        resolver_mod.resolve_task = lambda *_args, **_kwargs: BadResult()
        introspection.collect_environment_snapshot = fake_snapshot
        try:
            error = None
            try:
                runtime_mod.run_turn("Locate n8n on the barn", {"trace_id": trace_id})
            except Exception as exc:
                error = exc
            self.assertIsNotNone(error)
        finally:
            resolver_mod.resolve_task = original_resolve
            introspection.collect_environment_snapshot = original_snapshot
            tmp_dir.cleanup()

    def test_journal_includes_contract_version(self):
        import tempfile
        tmp_dir = tempfile.TemporaryDirectory()
        trace_id = self._setup_dirs(Path(tmp_dir.name))

        def fake_snapshot(scope):
            return introspection.EnvironmentSnapshot(
                snapshot_id="snap-1",
                collected_at=datetime.now(timezone.utc),
                services={
                    "systemd_units": ["n8n.service loaded active running"],
                    "process_list": [],
                    "listening_ports": [],
                },
                containers={"containers": []},
                network={"listening_sockets": []},
                filesystem={"paths": []},
            )

        original_snapshot = introspection.collect_environment_snapshot
        introspection.collect_environment_snapshot = fake_snapshot
        try:
            runtime_mod.run_turn("Locate n8n on the barn", {"trace_id": trace_id})
            graph = tg.load_graph(trace_id)
            task_id = next(iter(graph.tasks.values())).task_id
            records = self._read_resolution_records(runtime_mod._execution_journal.records_path, task_id)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].get("contract_version"), M27_CONTRACT_VERSION)
        finally:
            introspection.collect_environment_snapshot = original_snapshot
            tmp_dir.cleanup()

    def test_next_step_presence_by_type(self):
        import tempfile
        tmp_dir = tempfile.TemporaryDirectory()
        trace_id = self._setup_dirs(Path(tmp_dir.name))

        def fake_snapshot(scope):
            return introspection.EnvironmentSnapshot(
                snapshot_id="snap-1",
                collected_at=datetime.now(timezone.utc),
                services={
                    "systemd_units": [],
                    "process_list": [],
                    "listening_ports": [],
                },
                containers={"containers": []},
                network={"listening_sockets": []},
                filesystem={"paths": []},
            )

        original_snapshot = introspection.collect_environment_snapshot
        introspection.collect_environment_snapshot = fake_snapshot
        try:
            response = runtime_mod.run_turn("Locate n8n on the barn", {"trace_id": trace_id})
            output = response["final_output"]
            self.assertEqual(output.get("resolution_type"), "BLOCKED")
            self.assertTrue(output.get("next_step") is not None)
        finally:
            introspection.collect_environment_snapshot = original_snapshot
            tmp_dir.cleanup()

    def test_runtime_deterministic_response(self):
        import tempfile
        tmp_dir = tempfile.TemporaryDirectory()
        trace_id = self._setup_dirs(Path(tmp_dir.name))

        def fake_snapshot(scope):
            return introspection.EnvironmentSnapshot(
                snapshot_id="snap-1",
                collected_at=datetime.now(timezone.utc),
                services={
                    "systemd_units": ["n8n.service loaded active running"],
                    "process_list": [],
                    "listening_ports": [],
                },
                containers={"containers": []},
                network={"listening_sockets": []},
                filesystem={"paths": []},
            )

        original_snapshot = introspection.collect_environment_snapshot
        introspection.collect_environment_snapshot = fake_snapshot
        try:
            response1 = runtime_mod.run_turn("Locate n8n on the barn", {"trace_id": trace_id})
            response2 = runtime_mod.run_turn("Locate n8n on the barn", {"trace_id": trace_id})
            self.assertEqual(response1["final_output"], response2["final_output"])
        finally:
            introspection.collect_environment_snapshot = original_snapshot
            tmp_dir.cleanup()

    def test_resolution_journal_single_terminal_entry(self):
        import tempfile
        tmp_dir = tempfile.TemporaryDirectory()
        trace_id = self._setup_dirs(Path(tmp_dir.name))

        def fake_snapshot(scope):
            return introspection.EnvironmentSnapshot(
                snapshot_id="snap-1",
                collected_at=datetime.now(timezone.utc),
                services={
                    "systemd_units": ["n8n.service loaded active running"],
                    "process_list": [],
                    "listening_ports": [],
                },
                containers={"containers": []},
                network={"listening_sockets": []},
                filesystem={"paths": []},
            )

        original_snapshot = introspection.collect_environment_snapshot
        introspection.collect_environment_snapshot = fake_snapshot
        try:
            response = runtime_mod.run_turn("Locate n8n on the barn", {"trace_id": trace_id})
            output = response["final_output"]
            self.assertEqual(output.get("resolution_type"), "RESOLVED")

            graph = tg.load_graph(trace_id)
            task_id = next(iter(graph.tasks.values())).task_id
            records = self._read_resolution_records(runtime_mod._execution_journal.records_path, task_id)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].get("resolution_type"), "RESOLVED")
            self.assertTrue(records[0].get("terminal") is True)
        finally:
            introspection.collect_environment_snapshot = original_snapshot
            tmp_dir.cleanup()

    def test_no_post_resolution_journaling(self):
        import tempfile
        tmp_dir = tempfile.TemporaryDirectory()
        trace_id = self._setup_dirs(Path(tmp_dir.name))

        def fake_snapshot(scope):
            return introspection.EnvironmentSnapshot(
                snapshot_id="snap-1",
                collected_at=datetime.now(timezone.utc),
                services={
                    "systemd_units": ["n8n.service loaded active running"],
                    "process_list": [],
                    "listening_ports": [],
                },
                containers={"containers": []},
                network={"listening_sockets": []},
                filesystem={"paths": []},
            )

        original_snapshot = introspection.collect_environment_snapshot
        introspection.collect_environment_snapshot = fake_snapshot
        try:
            runtime_mod.run_turn("Locate n8n on the barn", {"trace_id": trace_id})
            graph = tg.load_graph(trace_id)
            task_id = next(iter(graph.tasks.values())).task_id
            records_before = self._read_resolution_records(runtime_mod._execution_journal.records_path, task_id)
            runtime_mod.run_turn("Locate n8n on the barn", {"trace_id": trace_id})
            records_after = self._read_resolution_records(runtime_mod._execution_journal.records_path, task_id)
            self.assertEqual(len(records_before), 1)
            self.assertEqual(len(records_after), 1)
        finally:
            introspection.collect_environment_snapshot = original_snapshot
            tmp_dir.cleanup()

    def test_follow_up_inspection_journal_links_task(self):
        import tempfile
        tmp_dir = tempfile.TemporaryDirectory()
        trace_id = self._setup_dirs(Path(tmp_dir.name))

        def fake_snapshot(scope):
            return introspection.EnvironmentSnapshot(
                snapshot_id="snap-1",
                collected_at=datetime.now(timezone.utc),
                services={
                    "systemd_units": [],
                    "process_list": ["123 n8n"],
                    "listening_ports": [],
                },
                containers={"containers": []},
                network={"listening_sockets": []},
                filesystem={"paths": []},
            )

        original_snapshot = introspection.collect_environment_snapshot
        introspection.collect_environment_snapshot = fake_snapshot
        try:
            runtime_mod.run_turn("Locate n8n on the barn", {"trace_id": trace_id})
            graph = tg.load_graph(trace_id)
            tasks = list(graph.tasks.values())
            self.assertTrue(len(tasks) >= 2)
            origin_task = None
            for task in tasks:
                if "Locate/Inspect: Locate n8n on the barn" in task.description:
                    origin_task = task
                    break
            self.assertIsNotNone(origin_task)
            journal_path = runtime_mod._execution_journal.records_path
            resolution_records = self._read_resolution_records(journal_path, origin_task.task_id)
            self.assertEqual(len(resolution_records), 1)
            inspection_records = self._read_inspection_records(journal_path, origin_task.task_id)
            self.assertEqual(len(inspection_records), 1)
            new_task_id = inspection_records[0].get("new_task_id")
            self.assertIsNotNone(new_task_id)
            runtime_mod.run_turn("Locate n8n on the barn", {"trace_id": trace_id})
            inspection_records_after = self._read_inspection_records(journal_path, origin_task.task_id)
            self.assertEqual(len(inspection_records_after), 1)
        finally:
            introspection.collect_environment_snapshot = original_snapshot
            tmp_dir.cleanup()

    def test_canonical_fingerprint_order_independent(self):
        payload_a = {
            "services_units": ["b", "a"],
            "containers": [{"name": "z", "ports": "1"}, {"name": "a", "ports": "2"}],
        }
        payload_b = {
            "containers": [{"ports": "2", "name": "a"}, {"ports": "1", "name": "z"}],
            "services_units": ["a", "b"],
        }
        fp_a = runtime_mod._canonical_fingerprint(payload_a)
        fp_b = runtime_mod._canonical_fingerprint(payload_b)
        self.assertEqual(fp_a, fp_b)

    def test_canonical_fingerprint_differs_on_content(self):
        payload_a = {"services_units": ["a"]}
        payload_b = {"services_units": ["b"]}
        fp_a = runtime_mod._canonical_fingerprint(payload_a)
        fp_b = runtime_mod._canonical_fingerprint(payload_b)
        self.assertTrue(fp_a != fp_b)

    def test_resolver_rejects_none_outcome(self):
        from v2.core.resolution import resolver as resolver_mod

        original_apply_rules = resolver_mod.apply_rules

        def fake_apply_rules(_context):
            return None

        resolver_mod.apply_rules = fake_apply_rules
        try:
            task = build_task("task-1", "Locate/Inspect: Locate n8n on the barn [origin:dto scope:read_only]")
            inspection = InspectionMeta(completed=False, source="introspection", inspected_at=None, scope=[])
            error = None
            try:
                resolve_task(task, empty_evidence_bundle(), inspection)
            except Exception as exc:
                error = exc
            self.assertIsNotNone(error)
        finally:
            resolver_mod.apply_rules = original_apply_rules

    def test_resolver_rejects_invalid_resolution_type(self):
        from v2.core.resolution import resolver as resolver_mod
        from v2.core.resolution.outcomes import ResolutionOutcome

        original_apply_rules = resolver_mod.apply_rules

        def fake_apply_rules(_context):
            return ResolutionOutcome(outcome_type="INVALID", message="bad")
        resolver_mod.apply_rules = fake_apply_rules
        try:
            task = build_task("task-1", "Locate/Inspect: Locate n8n on the barn [origin:dto scope:read_only]")
            inspection = InspectionMeta(completed=False, source="introspection", inspected_at=None, scope=[])
            error = None
            try:
                resolve_task(task, empty_evidence_bundle(), inspection)
            except Exception as exc:
                error = exc
            self.assertIsNotNone(error)
        finally:
            resolver_mod.apply_rules = original_apply_rules

    def test_runtime_aborts_on_malformed_resolution(self):
        import tempfile
        from v2.core.resolution import resolver as resolver_mod

        tmp_dir = tempfile.TemporaryDirectory()
        trace_id = self._setup_dirs(Path(tmp_dir.name))

        class BadResult:
            def __init__(self):
                self.outcome = {"bad": "data"}

        original_resolve = resolver_mod.resolve_task
        original_snapshot = introspection.collect_environment_snapshot

        def fake_snapshot(scope):
            return introspection.EnvironmentSnapshot(
                snapshot_id="snap-1",
                collected_at=datetime.now(timezone.utc),
                services={
                    "systemd_units": [],
                    "process_list": [],
                    "listening_ports": [],
                },
                containers={"containers": []},
                network={"listening_sockets": []},
                filesystem={"paths": []},
            )

        resolver_mod.resolve_task = lambda *_args, **_kwargs: BadResult()
        introspection.collect_environment_snapshot = fake_snapshot
        try:
            error = None
            try:
                runtime_mod.run_turn("Locate n8n on the barn", {"trace_id": trace_id})
            except Exception as exc:
                error = exc
            self.assertIsNotNone(error)
        finally:
            resolver_mod.resolve_task = original_resolve
            introspection.collect_environment_snapshot = original_snapshot
            tmp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
