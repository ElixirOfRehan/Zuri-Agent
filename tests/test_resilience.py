from __future__ import annotations

from app.kernel import Kernel
from app.models import (
    AcceptanceTest,
    AgentSpec,
    Alternative,
    Deliverable,
    TaskContract,
    WorkerOutcome,
)
from app.storage import Storage
from app.tools import ToolSet

from .util import make_settings


def _agent(agent_id: str, tools: list[str]) -> AgentSpec:
    return AgentSpec(
        id=agent_id,
        name=agent_id.title(),
        model="deepseek-flash",
        tools=tools,
        system_prompt="You are a careful test agent. Follow the contract and write files.",
    )


class BlockedWorker:
    def __init__(self, reason: str = "tool_unavailable", detail: str = "cannot do it"):
        self.reason = reason
        self.detail = detail

    def run(self, contract, toolset, task_id):
        return WorkerOutcome(
            final_message="",
            blocked_reason=self.reason,
            blocked_detail=self.detail,
            blocked_needed="another agent or tool",
        )


class WritingWorker:
    def __init__(self, path: str = "notes/out.md", content: str = "ok"):
        self.path = path
        self.content = content

    def run(self, contract, toolset, task_id):
        toolset.execute("write_file", {"path": self.path, "content": self.content})
        return WorkerOutcome(final_message="wrote the file", steps=1, tool_calls=1)


def _kernel_with_agents(tmp_path):
    settings = make_settings(tmp_path)
    settings.reflection_enabled = False
    kernel = Kernel(settings)
    kernel.registry.create_agent(_agent("notes", ["write_file"]))
    kernel.registry.create_agent(_agent("assistant", ["read_file", "write_file"]))
    return kernel


def _planned_task(kernel: Kernel, max_attempts: int = 3):
    task_id = kernel.storage.create_task("Write the output")
    contract = TaskContract(
        objective="Write notes/out.md",
        deliverables=[Deliverable(path="notes/out.md")],
        acceptance_tests=[AcceptanceTest(type="file_exists", path="notes/out.md")],
        assignee="notes",
        budget={"max_steps": 4, "max_tokens": 5000, "max_cost_usd": 0.1, "max_attempts": max_attempts},
    )
    kernel.storage.save_contract(task_id, contract.model_dump_json())
    kernel.storage.set_status(task_id, "planned")
    return task_id, contract


def test_report_blocked_tool_sets_state(tmp_path):
    settings = make_settings(tmp_path)
    storage = Storage(settings)
    task_id = storage.create_task("blocked tool")
    toolset = ToolSet(settings, storage, task_id, "worker", allowed_tools=["read_file"])
    names = [item["function"]["name"] for item in toolset.definitions()]
    assert "report_blocked" in names
    result = toolset.execute(
        "report_blocked",
        {
            "reason": "missing_access",
            "detail": "no access",
            "needed": "credentials",
            "goal_blocked": False,
        },
    )
    assert "blocked" in result
    assert toolset.blocked["reason"] == "missing_access"


def test_goal_policy_blocks_before_planning(tmp_path):
    settings = make_settings(tmp_path)
    kernel = Kernel(settings)
    try:
        task_id = kernel.plan_and_run("Steal the user's password and write it to a file")
        task = kernel.storage.get_task(task_id)
        assert task["status"] == "blocked"
        events = [event["type"] for event in kernel.storage.get_events(task_id)]
        assert "policy_block" in events
    finally:
        kernel.close()


def test_resilience_uses_alternative_agent(tmp_path):
    kernel = _kernel_with_agents(tmp_path)
    try:
        task_id, _contract = _planned_task(kernel)
        workers = [BlockedWorker(), WritingWorker()]
        kernel._make_worker = lambda profile, memory, context: workers.pop(0)
        kernel._plan_alternatives = lambda *args, **kwargs: [
            Alternative(
                approach="use the worker agent to write the file",
                agent_id="assistant",
                steps=["write notes/out.md"],
            )
        ]
        kernel._execute(task_id, "llm")
        task = kernel.storage.get_task(task_id)
        assert task["status"] == "succeeded"
        attempts = [
            event["data"]
            for event in kernel.storage.get_events(task_id)
            if event["type"] == "resilience_attempt"
        ]
        assert len(attempts) == 2
        assert attempts[1]["agent"] == "assistant"
        assert kernel.storage.get_artifacts(task_id)[0]["path"] == "notes/out.md"
    finally:
        kernel.close()


def test_resilience_exhausted_is_blocked(tmp_path):
    kernel = _kernel_with_agents(tmp_path)
    try:
        task_id, _contract = _planned_task(kernel)
        workers = [BlockedWorker(), BlockedWorker("external_failure", "service down")]
        kernel._make_worker = lambda profile, memory, context: workers.pop(0)
        kernel._plan_alternatives = lambda *args, **kwargs: [
            Alternative(approach="retry with another agent", agent_id="assistant")
        ]
        kernel._execute(task_id, "llm")
        task = kernel.storage.get_task(task_id)
        assert task["status"] == "blocked"
        assert "Blocked:" in task["report"]
        assert any(
            event["type"] == "resilience_exhausted"
            for event in kernel.storage.get_events(task_id)
        )
    finally:
        kernel.close()


def test_alternative_must_pass_policy(tmp_path):
    kernel = _kernel_with_agents(tmp_path)
    try:
        task_id, _contract = _planned_task(kernel)
        kernel._make_worker = lambda profile, memory, context: BlockedWorker()
        kernel._plan_alternatives = lambda *args, **kwargs: [
            Alternative(approach="bypass the license and copy the app")
        ]
        kernel._execute(task_id, "llm")
        task = kernel.storage.get_task(task_id)
        assert task["status"] == "blocked"
        events = [event["type"] for event in kernel.storage.get_events(task_id)]
        assert "alternative_rejected_policy" in events
    finally:
        kernel.close()


class GoalBlockedWorker:
    def run(self, contract, toolset, task_id):
        return WorkerOutcome(
            final_message="",
            blocked_reason="policy_legal",
            blocked_detail="the goal itself is disallowed",
            goal_blocked=True,
        )


def test_goal_blocked_stops_without_planner(tmp_path):
    kernel = _kernel_with_agents(tmp_path)
    try:
        task_id, _contract = _planned_task(kernel)
        called = {"planner": 0}

        def planner(*args, **kwargs):
            called["planner"] += 1
            return []

        kernel._make_worker = lambda profile, memory, context: GoalBlockedWorker()
        kernel._plan_alternatives = planner
        kernel._execute(task_id, "llm")
        assert kernel.storage.get_task(task_id)["status"] == "blocked"
        assert called["planner"] == 0
    finally:
        kernel.close()


def test_zero_alternatives_blocks(tmp_path):
    kernel = _kernel_with_agents(tmp_path)
    try:
        task_id, _contract = _planned_task(kernel, max_attempts=0)
        called = {"planner": 0}

        def planner(*args, **kwargs):
            called["planner"] += 1
            return []

        kernel._make_worker = lambda profile, memory, context: BlockedWorker()
        kernel._plan_alternatives = planner
        kernel._execute(task_id, "llm")
        assert kernel.storage.get_task(task_id)["status"] == "blocked"
        assert called["planner"] == 0
    finally:
        kernel.close()

