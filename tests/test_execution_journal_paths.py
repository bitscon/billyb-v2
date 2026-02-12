import shutil

from v2.core.execution.execution_journal import ExecutionJournal


def test_append_recreates_parent_after_cwd_change(tmp_path, monkeypatch):
    base_dir = tmp_path / "executions"
    journal = ExecutionJournal(base_dir=str(base_dir))

    shutil.rmtree(base_dir)
    monkeypatch.chdir("/tmp")

    journal.append({"execution": {"trace_id": "trace-1"}})

    assert journal.records_path.exists()
