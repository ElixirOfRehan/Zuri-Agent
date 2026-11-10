from __future__ import annotations

import json
import shutil

import pytest

from app.agents import load_agent_spec
from app.sandbox import sha256_bytes
from app.storage import Storage
from app.tools import ToolSet

from .util import PROJECT_ROOT, make_settings


def _toolset(tmp_path, allowed=None):
    settings = make_settings(tmp_path)
    storage = Storage(settings)
    task_id = storage.create_task("command test")
    toolset = ToolSet(
        settings,
        storage,
        task_id,
        "engineering",
        allowed_tools=allowed or ["run_command"],
    )
    return settings, storage, task_id, toolset


def _run(toolset, program, args, timeout=120):
    return json.loads(
        toolset.execute(
            "run_command",
            {"program": program, "arguments": args, "timeout_seconds": timeout},
        )
    )


def test_python_command_and_output_event(tmp_path):
    settings, storage, task_id, toolset = _toolset(tmp_path)
    result = _run(toolset, "python", ["-c", "print('hello from tool')"])
    assert result["exit_code"] == 0
    assert "hello from tool" in result["stdout"]
    events = [
        event for event in storage.get_events(task_id) if event["type"] == "command_output"
    ]
    assert events and events[0]["data"]["exit_code"] == 0


def test_blocked_program(tmp_path):
    _settings, _storage, _task, toolset = _toolset(tmp_path)
    result = _run(toolset, "powershell", ["-Command", "echo bad"])
    assert "not allowed" in result["error"]


def test_absolute_argument_blocked(tmp_path):
    _settings, _storage, _task, toolset = _toolset(tmp_path)
    result = _run(toolset, "python", ["C:\\Windows\\win.ini"])
    assert "unsafe argument" in result["error"]


def test_traversal_argument_blocked(tmp_path):
    _settings, _storage, _task, toolset = _toolset(tmp_path)
    result = _run(toolset, "python", ["../secret.txt"])
    assert "unsafe argument" in result["error"]


def test_git_push_blocked(tmp_path):
    _settings, _storage, _task, toolset = _toolset(tmp_path)
    result = _run(toolset, "git", ["push"])
    assert "blocked" in result["error"]


def test_global_git_config_blocked(tmp_path):
    _settings, _storage, _task, toolset = _toolset(tmp_path)
    result = _run(toolset, "git", ["config", "--global", "user.name", "x"])
    assert "global/system" in result["error"]


def test_npm_install_blocked(tmp_path):
    _settings, _storage, _task, toolset = _toolset(tmp_path)
    result = _run(toolset, "npm", ["install"])
    assert "blocked" in result["error"]


def test_timeout(tmp_path):
    _settings, _storage, _task, toolset = _toolset(tmp_path)
    result = _run(
        toolset,
        "python",
        ["-c", "import time; time.sleep(2)"],
        timeout=1,
    )
    assert "timed out" in result["error"]


def test_shell_disabled(tmp_path):
    settings, storage, task_id, toolset = _toolset(tmp_path)
    settings.shell_enabled = False
    result = _run(toolset, "python", ["-c", "print(1)"])
    assert "disabled" in result["error"]


def test_output_is_truncated(tmp_path):
    _settings, _storage, _task, toolset = _toolset(tmp_path)
    result = _run(toolset, "python", ["-c", "print('x' * 30000)"])
    assert result["truncated"] is True
    assert len(result["stdout"]) <= 20000


@pytest.mark.skipif(shutil.which("rea") is None, reason="rea not on PATH")
def test_rea_is_reachable(tmp_path):
    _settings, _storage, _task, toolset = _toolset(tmp_path)
    result = _run(toolset, "rea", ["--version"])
    assert result["exit_code"] == 0
    assert "6.8.0" in result["stdout"]


def test_toolchain_versions(tmp_path):
    _settings, _storage, _task, toolset = _toolset(tmp_path)
    for program in ("git", "pytest", "npm"):
        result = _run(toolset, program, ["--version"])
        assert result.get("exit_code") == 0, result
        assert not result.get("stderr"), result


def test_tool_definitions_include_run_command_and_control(tmp_path):
    _settings, _storage, _task, toolset = _toolset(tmp_path)
    names = [item["function"]["name"] for item in toolset.definitions()]
    assert "run_command" in names
    assert "report_blocked" in names
    assert "write_file" not in names


def test_engineering_agent_profile():
    spec = load_agent_spec(PROJECT_ROOT / "agents" / "engineering" / "profile.json")
    assert spec.id == "engineering"
    assert "run_command" in spec.tools
    assert "run_opencode" in spec.tools
    assert "write_file" in spec.tools
    assert len(spec.system_prompt) > 100
