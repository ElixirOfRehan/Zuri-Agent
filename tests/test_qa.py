from __future__ import annotations

from app.kernel import Kernel
from app.models import (
    AcceptanceTest,
    AgentSpec,
    Deliverable,
    QAReview,
    TaskContract,
)
from app.sandbox import sha256_bytes
from app.storage import Storage
from app.verifier import Verifier

from .util import make_settings


class FakeQA:
    def __init__(self, result=None, error=None):
        self.result = result or QAReview(verdict="pass", notes=["looks good"])
        self.error = error
        self.calls = 0

    def review(self, *args, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def _agent(agent_id: str, tools: list[str]) -> AgentSpec:
    return AgentSpec(
        id=agent_id,
        name=agent_id.title(),
        model="deepseek-flash",
        tools=tools,
        system_prompt="You are a careful test agent. Follow the contract and write files.",
    )


def _running_task(tmp_path, agent: str = "engineering"):
    settings = make_settings(tmp_path)
    settings.reflection_enabled = False
    settings.qa_enabled = True
    kernel = Kernel(settings)
    kernel.registry.create_agent(
        _agent("engineering", ["list_dir", "read_file", "write_file", "run_command"])
    )
    kernel.registry.create_agent(_agent("notes", ["read_file", "write_file"]))
    task_id = kernel.storage.create_task("Write a file")
    contract = TaskContract(
        objective="Write notes/out.md",
        deliverables=[Deliverable(path="notes/out.md")],
        acceptance_tests=[AcceptanceTest(type="file_exists", path="notes/out.md")],
        assignee=agent,
    )
    kernel.storage.save_contract(task_id, contract.model_dump_json())
    kernel.storage.set_status(task_id, "running")
    target = settings.workspace_dir / "notes" / "out.md"
    target.parent.mkdir(parents=True)
    data = b"# out\n"
    target.write_bytes(data)
    kernel.storage.add_artifact(
        task_id, "notes/out.md", data, sha256_bytes(data), "worker"
    )
    Verifier(settings, kernel.storage).run(task_id, contract)
    kernel.storage.add_event(
        task_id,
        "worker",
        "command_output",
        {"program": "python", "arguments": ["x.py"], "exit_code": 0, "stdout": "ok"},
    )
    return kernel, task_id


def test_engineering_success_runs_qa_and_stores_verdict(tmp_path):
    kernel, task_id = _running_task(tmp_path)
    try:
        fake = FakeQA(QAReview(verdict="pass", notes=["evidence is consistent"]))
        kernel.qa = fake
        kernel._succeed(task_id)
        task = kernel.storage.get_task(task_id)
        assert task["status"] == "succeeded"
        assert fake.calls == 1
        events = [event for event in kernel.storage.get_events(task_id)]
        qa = [event for event in events if event["type"] == "qa_review"]
        assert qa and qa[0]["data"]["verdict"] == "pass"
        assert "QA" in task["report"]
        assert "QA: pass" in task["report"]
    finally:
        kernel.close()


def test_qa_failure_is_advisory_only(tmp_path):
    kernel, task_id = _running_task(tmp_path)
    try:
        kernel.qa = FakeQA(
            QAReview(verdict="fail", issues=["missing test coverage"])
        )
        kernel._succeed(task_id)
        task = kernel.storage.get_task(task_id)
        assert task["status"] == "succeeded"
        assert "QA flagged issues" in task["report"]
        assert "missing test coverage" in task["report"]
    finally:
        kernel.close()


def test_qa_error_does_not_break_success(tmp_path):
    kernel, task_id = _running_task(tmp_path)
    try:
        kernel.qa = FakeQA(error=RuntimeError("qa down"))
        kernel._succeed(task_id)
        task = kernel.storage.get_task(task_id)
        assert task["status"] == "succeeded"
        events = [event["type"] for event in kernel.storage.get_events(task_id)]
        assert "qa_error" in events
    finally:
        kernel.close()


def test_notes_task_skips_qa(tmp_path):
    kernel, task_id = _running_task(tmp_path, agent="notes")
    try:
        fake = FakeQA()
        kernel.qa = fake
        kernel._succeed(task_id)
        assert kernel.storage.get_task(task_id)["status"] == "succeeded"
        assert fake.calls == 0
    finally:
        kernel.close()


def test_qa_disabled(tmp_path):
    kernel, task_id = _running_task(tmp_path)
    try:
        kernel.settings.qa_enabled = False
        fake = FakeQA()
        kernel.qa = fake
        kernel._succeed(task_id)
        assert fake.calls == 0
    finally:
        kernel.close()
