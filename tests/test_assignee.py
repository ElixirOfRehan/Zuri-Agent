from __future__ import annotations

import pytest

from app.models import AgentSpec
from app.storage import Storage
from app.tools import ToolSet

from .util import make_settings


def _agent(agent_id: str, tools: list[str]) -> AgentSpec:
    return AgentSpec(
        id=agent_id,
        name=agent_id.title(),
        model="deepseek-flash",
        tools=tools,
        system_prompt="You are a test agent with a narrow tool grant. Follow the contract.",
    )


def test_tool_filtering_definitions_and_execution(tmp_path):
    settings = make_settings(tmp_path)
    storage = Storage(settings)
    task_id = storage.create_task("test")
    toolset = ToolSet(
        settings, storage, task_id, "worker", allowed_tools=["read_file"]
    )
    names = [item["function"]["name"] for item in toolset.definitions()]
    assert names == ["read_file"]
    result = toolset.execute("write_file", {"path": "x.txt", "content": "x"})
    assert "not granted" in result


def test_assignable_excludes_system_roles(tmp_path):
    from app.kernel import Kernel

    settings = make_settings(tmp_path)
    kernel = Kernel(settings)
    try:
        kernel.registry.create_agent(_agent("worker", ["read_file"]), source="system")
        kernel.registry.create_agent(_agent("boss", []), source="system")
        kernel.registry.create_agent(_agent("notes", ["read_file", "write_file"]))
        assignable = [agent.id for agent in kernel.registry.assignable()]
        assert assignable == ["notes", "worker"]
        assert kernel.validate_assignee("notes").id == "notes"
        with pytest.raises(ValueError, match="unknown assignee"):
            kernel.validate_assignee("missing")
        with pytest.raises(ValueError, match="not assignable"):
            kernel.validate_assignee("boss")
    finally:
        kernel.close()
