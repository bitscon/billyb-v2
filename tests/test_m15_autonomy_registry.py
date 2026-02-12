from v2.core.autonomy.autonomy_registry import AutonomyRegistry


def test_grant_allows_scoped_action():
    registry = AutonomyRegistry()
    registry.grant_capability(
        capability="filesystem.write",
        scope={"allowed_paths": ["/home/billyb/"], "deny_patterns": [".ssh", ".git"]},
        limits={"max_actions_per_session": 2, "max_actions_per_minute": 2},
        risk_level="low",
        grantor="human",
    )

    allowed, reason, remaining = registry.is_grant_allowed(
        "filesystem.write",
        {"path": "/home/billyb/example.txt"},
    )
    assert allowed is True
    assert reason == "ok"
    assert remaining["remaining_session"] == 2


def test_grant_denies_out_of_scope_action():
    registry = AutonomyRegistry()
    registry.grant_capability(
        capability="filesystem.write",
        scope={"allowed_paths": ["/home/billyb/"], "deny_patterns": [".ssh", ".git"]},
        limits={"max_actions_per_session": 1, "max_actions_per_minute": 1},
        risk_level="low",
        grantor="human",
    )

    allowed, reason, remaining = registry.is_grant_allowed(
        "filesystem.write",
        {"path": "/etc/passwd"},
    )
    assert allowed is False
    assert reason == "Capability scope violation"
    assert remaining == {}


def test_revocation_blocks_action():
    registry = AutonomyRegistry()
    registry.grant_capability(
        capability="filesystem.read",
        scope={"allowed_paths": ["/home/billyb/"], "deny_patterns": []},
        limits={"max_actions_per_session": 1, "max_actions_per_minute": 1},
        risk_level="low",
        grantor="human",
    )
    registry.revoke_autonomy("filesystem.read")

    allowed, reason, remaining = registry.is_grant_allowed(
        "filesystem.read",
        {"path": "/home/billyb/notes.txt"},
    )
    assert allowed is False
    assert reason == "Capability revoked"
    assert remaining == {}


def test_limits_enforced():
    registry = AutonomyRegistry()
    registry.grant_capability(
        capability="filesystem.write",
        scope={"allowed_paths": ["/home/billyb/"], "deny_patterns": []},
        limits={"max_actions_per_session": 1, "max_actions_per_minute": 1},
        risk_level="low",
        grantor="human",
    )

    allowed, reason, _ = registry.is_grant_allowed(
        "filesystem.write",
        {"path": "/home/billyb/one.txt"},
    )
    assert allowed is True
    assert reason == "ok"
    registry.consume_grant("filesystem.write")

    allowed, reason, remaining = registry.is_grant_allowed(
        "filesystem.write",
        {"path": "/home/billyb/two.txt"},
    )
    assert allowed is False
    assert reason == "Capability limits exceeded"
    assert remaining["remaining_session"] == 0
