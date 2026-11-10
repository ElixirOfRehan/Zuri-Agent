from __future__ import annotations

from app.storage import Storage
from app.tools import OPENCODE_PERMISSIONS, ToolSet

from .util import make_settings


def _toolset(tmp_path):
    settings = make_settings(tmp_path)
    storage = Storage(settings)
    task_id = storage.create_task("opencode test")
    toolset = ToolSet(
        settings,
        storage,
        task_id,
        "engineering",
        allowed_tools=["run_opencode"],
    )
    return toolset


def test_opencode_permissions_deny_shell_and_network():
    assert OPENCODE_PERMISSIONS["permission"]["edit"] == "allow"
    assert OPENCODE_PERMISSIONS["permission"]["bash"] == "deny"
    assert OPENCODE_PERMISSIONS["permission"]["webfetch"] == "deny"
    assert OPENCODE_PERMISSIONS["permission"]["external_directory"] == "deny"
    assert OPENCODE_PERMISSIONS["mcp"]["rea"]["enabled"] is False


def test_opencode_rejects_empty_prompt(tmp_path):
    toolset = _toolset(tmp_path)
    result = toolset.execute("run_opencode", {"prompt": ""})
    assert "empty" in result


def test_opencode_rejects_invalid_model(tmp_path):
    toolset = _toolset(tmp_path)
    result = toolset.execute(
        "run_opencode", {"prompt": "do work", "model": "bad model"}
    )
    assert "invalid model" in result
