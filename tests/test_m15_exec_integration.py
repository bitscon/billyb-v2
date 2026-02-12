import pytest

import v2.core.runtime as runtime_mod


@pytest.mark.parametrize(
    "user_input, expected_fragment",
    [
        ("GRANT_CAPABILITY\nname: filesystem.write\nscope: default", "legacy capability-grant command"),
        ("/exec touch /tmp/m15.txt", "legacy interaction '/exec'"),
        ("/revoke_autonomy filesystem.write", "legacy interaction '/revoke_autonomy'"),
    ],
)
def test_legacy_exec_contract_commands_are_hard_rejected(user_input: str, expected_fragment: str):
    result = runtime_mod.run_turn(user_input, {"trace_id": "trace-m15-legacy"})

    assert result["status"] == "error"
    assert expected_fragment in result["final_output"]
