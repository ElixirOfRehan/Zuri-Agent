from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.kernel import Kernel
from app.models import AcceptanceTest, AgentSpec, Deliverable, TaskContract
from app.redact import redact
from app.registry import AgentRegistry
from app.sandbox import sha256_bytes
from app.storage import Storage
from app.tools import ToolSet
from app.verifier import Verifier

from .util import make_settings


def _agent(agent_id: str = "worker", tools=None) -> AgentSpec:
    return AgentSpec(
        id=agent_id,
        name=agent_id.title(),
        model="deepseek-flash",
        tools=tools if tools is not None else ["list_dir", "read_file", "write_file"],
        system_prompt="You are a careful test agent. Follow the contract and write files.",
    )


def _contract(test: AcceptanceTest) -> TaskContract:
    return TaskContract(
        objective="Edge case",
        deliverables=[Deliverable(path="notes/edge.md")],
        acceptance_tests=[test],
    )


def _prepare(tmp_path, data: bytes):
    settings = make_settings(tmp_path)
    storage = Storage(settings)
    task_id = storage.create_task("edge")
    target = settings.workspace_dir / "notes" / "edge.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(data)
    storage.add_artifact(task_id, "notes/edge.md", data, sha256_bytes(data), "worker")
    return settings, storage, task_id, target


def test_missing_file_after_artifact_fails(tmp_path):
    settings, storage, task_id, target = _prepare(tmp_path, b"hello\n")
    target.unlink()
    results = Verifier(settings, storage).run(
        task_id, _contract(AcceptanceTest(type="file_exists", path="notes/edge.md"))
    )
    assert any(not item.passed for item in results)


def test_empty_file_fails_not_empty(tmp_path):
    settings, storage, task_id, _target = _prepare(tmp_path, b"")
    results = Verifier(settings, storage).run(
        task_id,
        _contract(AcceptanceTest(type="file_not_empty", path="notes/edge.md")),
    )
    assert any(not item.passed for item in results)


def test_unicode_case_insensitive_contains(tmp_path):
    settings, storage, task_id, _target = _prepare(
        tmp_path, "Straße\n".encode("utf-8")
    )
    results = Verifier(settings, storage).run(
        task_id,
        _contract(
            AcceptanceTest(
                type="file_contains", path="notes/edge.md", text="strasse"
            )
        ),
    )
    assert all(item.passed for item in results)


def test_latest_verification_run_only(tmp_path):
    settings, storage, task_id, _target = _prepare(tmp_path, b"hello\n")
    contract = _contract(
        AcceptanceTest(type="file_exists", path="notes/edge.md")
    )
    verifier = Verifier(settings, storage)
    verifier.run(task_id, contract)
    verifier.run(task_id, contract)
    latest = storage.get_verifications(task_id)
    assert len(latest) == 2
    assert storage.verification_run_count(task_id) == 2


def test_delete_nonexistent_agent(tmp_path):
    settings = make_settings(tmp_path)
    registry = AgentRegistry(settings, Storage(settings))
    with pytest.raises(ValueError, match="not found"):
        registry.delete_agent("missing", "missing", "DELETE missing")


def test_restore_nonexistent_agent(tmp_path):
    settings = make_settings(tmp_path)
    registry = AgentRegistry(settings, Storage(settings))
    with pytest.raises(ValueError, match="no trash snapshot"):
        registry.restore_agent("missing")


def test_double_approve_rejected(tmp_path):
    settings = make_settings(tmp_path)
    registry = AgentRegistry(settings, Storage(settings))
    proposal = registry.propose_create("make worker", _agent("temp"))
    registry.approve_proposal(proposal.proposal_id)
    with pytest.raises(ValueError, match="not pending"):
        registry.approve_proposal(proposal.proposal_id)


def test_unknown_model_rejected(tmp_path):
    settings = make_settings(tmp_path)
    registry = AgentRegistry(settings, Storage(settings))
    spec = _agent("badmodel")
    spec = spec.model_copy(update={"model": "gpt-4"})
    with pytest.raises(ValueError, match="model must be"):
        registry.create_agent(spec)


def test_empty_tools_rejected(tmp_path):
    settings = make_settings(tmp_path)
    registry = AgentRegistry(settings, Storage(settings))
    with pytest.raises(ValueError, match="at least one tool"):
        registry.create_agent(_agent("notools", tools=[]))


def test_invalid_agent_id_rejected():
    with pytest.raises(ValidationError):
        AgentSpec(
            id="Bad ID",
            name="Bad",
            model="deepseek-flash",
            tools=["read_file"],
            system_prompt="A valid long system prompt for the test agent.",
        )


def test_tool_path_escape_returns_error(tmp_path):
    settings = make_settings(tmp_path)
    storage = Storage(settings)
    task_id = storage.create_task("edge")
    toolset = ToolSet(settings, storage, task_id, "worker")
    result = toolset.execute("read_file", {"path": "../outside.txt"})
    assert "sandbox" in result


def test_cost_estimate():
    settings = make_settings(Path("."))
    assert settings.estimate_cost("deepseek-flash", 1_000_000, 1_000_000) == pytest.approx(0.75)
    assert settings.estimate_cost("deepseek-v4-pro", 1_000_000, 1_000_000) == pytest.approx(2.64)


def test_secret_redaction():
    text = "key sk-abc123456 and Bearer token123"
    cleaned = redact(text)
    assert "sk-abc123456" not in cleaned
    assert "token123" not in cleaned


def test_restore_multiple_snapshots(tmp_path):
    settings = make_settings(tmp_path)
    registry = AgentRegistry(settings, Storage(settings))
    registry.create_agent(_agent("notes"))
    registry.delete_agent("notes", "notes", "DELETE notes")
    registry.restore_agent("notes")
    registry.delete_agent("notes", "notes", "DELETE notes")
    registry.restore_agent("notes")
    assert registry.get("notes") is not None
    actions = [event["action"] for event in registry.history("notes")]
    assert actions.count("agent_soft_deleted") == 2
    assert actions.count("agent_restored") == 2


def test_event_redaction(tmp_path):
    settings = make_settings(tmp_path)
    storage = Storage(settings)
    task_id = storage.create_task("redact")
    storage.add_event(
        task_id,
        "worker",
        "message",
        {"text": "key sk-abc123456 and Bearer token123"},
    )
    events = storage.get_events(task_id)
    serialized = __import__("json").dumps(events)
    assert "sk-abc123456" not in serialized
    assert "token123" not in serialized
    ledger = (settings.data_dir / "ledger.jsonl").read_text(encoding="utf-8")
    assert "sk-abc123456" not in ledger
    storage.close()


def test_planner_failure_becomes_failed_task(tmp_path):
    settings = make_settings(tmp_path)
    kernel = Kernel(settings)
    try:
        kernel.registry.create_agent(_agent("worker"), source="system")

        class FailingBoss:
            def plan(self, *args, **kwargs):
                raise RuntimeError("boom")

        kernel._boss_agent = FailingBoss()
        task_id = kernel.plan_and_run("do something")
        task = kernel.storage.get_task(task_id)
        assert task["status"] == "failed"
        events = kernel.storage.get_events(task_id)
        assert any(
            event["type"] == "error" and "boom" in event["data"].get("error", "")
            for event in events
        )
        report = task["report"] or ""
        assert "boom" in report
    finally:
        kernel.close()
