import pytest

import v2.core.runtime as runtime_mod


@pytest.mark.parametrize(
    "user_input, expected_fragment",
    [
        ("/exec systemctl restart nginx", "legacy interaction '/exec'"),
        ("/ops restart nginx", "legacy interaction '/ops'"),
        ("/ops restart cmdb", "legacy interaction '/ops'"),
    ],
)
def test_legacy_ops_and_exec_commands_are_hard_rejected(user_input: str, expected_fragment: str):
    result = runtime_mod.run_turn(user_input, {"trace_id": "trace-m17-legacy"})

    assert result["status"] == "error"
    assert expected_fragment in result["final_output"]
