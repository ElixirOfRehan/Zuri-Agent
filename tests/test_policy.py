from __future__ import annotations

from app.policy import Policy


def test_policy_blocks_goal_and_alternatives():
    policy = Policy()
    assert policy.forbidden_reason("Steal the user's password") is not None
    assert policy.forbidden_reason("Bypass the license and copy the app") is not None
    assert policy.forbidden_reason("Create notes/hello.md with hello") is None
    assert policy.forbidden_reason("Reverse engineer an authorized game") is None


def test_policy_custom_pattern():
    policy = Policy([(r"\bmagic\b", "magic block")])
    assert "magic block" in policy.forbidden_reason("do magic")
    assert policy.forbidden_reason("do normal work") is None
