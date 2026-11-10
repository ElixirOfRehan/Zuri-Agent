from __future__ import annotations

import pytest

from app.kernel import Kernel
from app.models import (
    AcceptanceTest,
    AgentSpec,
    Deliverable,
    MemoryEntry,
    ReflectionFact,
    ReflectionResult,
    ReflectionSuggestion,
    TaskContract,
)
from app.registry import AgentRegistry
from app.sandbox import sha256_bytes
from app.storage import Storage
from app.verifier import Verifier

from .util import make_settings


def _agent(agent_id: str = "notes") -> AgentSpec:
    return AgentSpec(
        id=agent_id,
        name=agent_id.title(),
        model="deepseek-flash",
        tools=["read_file", "write_file"],
        system_prompt="You are a careful notes agent. Follow the contract and write files.",
    )


class FakeReflector:
    def __init__(self, result: ReflectionResult | None = None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls = 0

    def review(self, *args, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def test_style_update_and_version(tmp_path):
    settings = make_settings(tmp_path)
    registry = AgentRegistry(settings, Storage(settings))
    registry.create_agent(_agent())
    updated = registry.update_profile(
        "notes", style={"tone": "friendly", "length": "standard"}, reason="test"
    )
    assert updated.version == 2
    assert updated.effective_style()["tone"] == "friendly"
    assert (settings.root / "agents" / "notes" / "profiles" / "v0002.json").exists()
    with pytest.raises(ValueError, match="unknown style keys"):
        registry.update_profile("notes", style={"color": "red"}, reason="bad")


def test_rollback_profile_creates_new_version(tmp_path):
    settings = make_settings(tmp_path)
    registry = AgentRegistry(settings, Storage(settings))
    registry.create_agent(_agent())
    registry.update_profile("notes", style={"tone": "formal"}, reason="change")
    restored = registry.rollback_profile("notes", 1)
    assert restored.version == 3
    assert restored.effective_style()["tone"] == "direct"
    assert registry.list_versions("notes") == [1, 2, 3]
    with pytest.raises(ValueError, match="version not found"):
        registry.rollback_profile("notes", 99)


def test_memory_remember_and_forget(tmp_path):
    settings = make_settings(tmp_path)
    registry = AgentRegistry(settings, Storage(settings))
    registry.create_agent(_agent())
    entry = registry.remember_user_fact("notes", "The user prefers short notes.")
    assert entry.kind == "user_fact"
    assert len(registry.load_memory("notes")) == 1
    registry.forget_memory("notes", entry.id)
    assert registry.load_memory("notes") == []
    forgotten = registry.load_memory("notes", include_forgotten=True)
    assert forgotten[0].status == "forgotten"


def test_pending_change_tools_approval(tmp_path):
    settings = make_settings(tmp_path)
    registry = AgentRegistry(settings, Storage(settings))
    registry.create_agent(_agent())
    change = registry.add_change(
        "notes", kind="tools", proposed='["read_file"]', reason="less is safer"
    )
    assert registry.list_changes("notes")[0].status == "pending"
    approved = registry.approve_change("notes", change.change_id)
    assert approved.status == "approved"
    updated = registry.get("notes")
    assert updated.tools == ["read_file"]
    assert updated.version == 2


def test_invalid_pending_change_stays_pending(tmp_path):
    settings = make_settings(tmp_path)
    registry = AgentRegistry(settings, Storage(settings))
    registry.create_agent(_agent())
    change = registry.add_change(
        "notes", kind="tools", proposed='["shell"]', reason="bad tool"
    )
    with pytest.raises(ValueError, match="unknown tools"):
        registry.approve_change("notes", change.change_id)
    assert registry.list_changes("notes")[0].status == "pending"


def test_reject_pending_change(tmp_path):
    settings = make_settings(tmp_path)
    registry = AgentRegistry(settings, Storage(settings))
    registry.create_agent(_agent())
    change = registry.add_change(
        "notes", kind="model", proposed="deepseek-v4-pro", reason="more power"
    )
    rejected = registry.reject_change("notes", change.change_id)
    assert rejected.status == "rejected"
    assert registry.get("notes").model == "deepseek-flash"


def test_duplicate_pending_change_is_reused(tmp_path):
    settings = make_settings(tmp_path)
    registry = AgentRegistry(settings, Storage(settings))
    registry.create_agent(_agent())
    first = registry.add_change(
        "notes", kind="style", proposed='{"approval": "balanced"}', reason="x"
    )
    second = registry.add_change(
        "notes", kind="style", proposed='{"approval": "balanced"}', reason="y"
    )
    assert first.change_id == second.change_id
    assert len(registry.list_changes("notes")) == 1


def _succeeded_task(tmp_path):
    settings = make_settings(tmp_path)
    kernel = Kernel(settings)
    kernel.registry.create_agent(_agent())
    task_id = kernel.storage.create_task("Reflect on this task")
    contract = TaskContract(
        objective="Write a note",
        deliverables=[Deliverable(path="notes/x.md")],
        acceptance_tests=[AcceptanceTest(type="file_exists", path="notes/x.md")],
        assignee="notes",
    )
    kernel.storage.save_contract(task_id, contract.model_dump_json())
    target = settings.workspace_dir / "notes" / "x.md"
    target.parent.mkdir(parents=True)
    data = b"# Note\n"
    target.write_bytes(data)
    artifact = kernel.storage.add_artifact(
        task_id, "notes/x.md", data, sha256_bytes(data), "worker"
    )
    Verifier(settings, kernel.storage).run(task_id, contract)
    kernel.storage.set_status(task_id, "succeeded")
    return kernel, task_id, artifact, contract


def test_reflection_applies_safe_changes(tmp_path):
    kernel, task_id, artifact, contract = _succeeded_task(tmp_path)
    try:
        kernel.reflector = FakeReflector(
            ReflectionResult(
                facts=[
                    ReflectionFact(
                        text="The user prefers concise markdown.",
                        kind="preference",
                        evidence=[artifact["id"]],
                    )
                ],
                sop_notes=["Always verify the file after writing."],
                style={"tone": "friendly"},
                suggestions=[
                    ReflectionSuggestion(
                        kind="tools",
                        proposed='["read_file"]',
                        reason="read-only would be safer",
                    )
                ],
            )
        )
        summary = kernel.reflect_task(task_id)
        assert summary["facts"] == 1
        assert summary["sop_notes"] == 1
        assert summary["suggestions"] == 1
        profile = kernel.registry.get("notes")
        assert profile.version == 2
        assert profile.effective_style()["tone"] == "friendly"
        assert "Always verify the file after writing." in profile.sop_notes
        memory = kernel.registry.load_memory("notes")
        assert memory[0].text.startswith("The user prefers concise")
        assert memory[0].evidence == [artifact["id"]]
        changes = kernel.registry.list_changes("notes")
        assert len(changes) == 1
        events = [event["type"] for event in kernel.storage.get_events(task_id)]
        assert "mind_updated" in events
    finally:
        kernel.close()


def test_reflection_is_skipped_for_failed_task(tmp_path):
    kernel, task_id, _artifact, _contract = _succeeded_task(tmp_path)
    try:
        kernel.storage.set_status(task_id, "failed")
        fake = FakeReflector(ReflectionResult())
        kernel.reflector = fake
        summary = kernel.reflect_task(task_id)
        assert summary["skipped"] == "task is not succeeded"
        assert fake.calls == 0
    finally:
        kernel.close()


def test_reflection_rejects_invalid_evidence(tmp_path):
    kernel, task_id, _artifact, _contract = _succeeded_task(tmp_path)
    try:
        kernel.reflector = FakeReflector(
            ReflectionResult(
                facts=[
                    ReflectionFact(
                        text="Invented fact", kind="lesson", evidence=["bogus"]
                    )
                ]
            )
        )
        summary = kernel.reflect_task(task_id)
        assert summary["facts"] == 0
        assert kernel.registry.load_memory("notes") == []
        events = [event["type"] for event in kernel.storage.get_events(task_id)]
        assert "fact_rejected" in events
    finally:
        kernel.close()


def test_reflection_sensitive_style_becomes_pending(tmp_path):
    kernel, task_id, _artifact, _contract = _succeeded_task(tmp_path)
    try:
        kernel.reflector = FakeReflector(
            ReflectionResult(
                style={"tone": "friendly", "approval": "balanced"},
            )
        )
        summary = kernel.reflect_task(task_id)
        profile = kernel.registry.get("notes")
        assert profile.effective_style()["tone"] == "friendly"
        assert profile.effective_style()["approval"] == "strict"
        assert summary["suggestions"] == 1
        changes = kernel.registry.list_changes("notes")
        assert changes[0].kind == "style"
        kernel.registry.approve_change("notes", changes[0].change_id)
        assert kernel.registry.get("notes").effective_style()["approval"] == "balanced"
    finally:
        kernel.close()


def test_reflection_rejects_trivial_task_fact(tmp_path):
    kernel, task_id, artifact, _contract = _succeeded_task(tmp_path)
    try:
        kernel.reflector = FakeReflector(
            ReflectionResult(
                facts=[
                    ReflectionFact(
                        text=(
                            "The task to create x was completed and passed all "
                            "acceptance tests."
                        ),
                        kind="project_fact",
                        evidence=[artifact["id"]],
                    )
                ]
            )
        )
        summary = kernel.reflect_task(task_id)
        assert summary["facts"] == 0
        assert kernel.registry.load_memory("notes") == []
        events = [event["type"] for event in kernel.storage.get_events(task_id)]
        assert "fact_rejected" in events
    finally:
        kernel.close()


def test_similar_sop_note_not_duplicated(tmp_path):
    settings = make_settings(tmp_path)
    registry = AgentRegistry(settings, Storage(settings))
    registry.create_agent(_agent())
    first = registry.update_profile(
        "notes",
        sop_notes_append=["Always verify the file after writing."],
        reason="test",
    )
    second = registry.update_profile(
        "notes",
        sop_notes_append=["Always verify the file after writing!"],
        reason="test",
    )
    assert first.version == 2
    assert second.version == 2
    assert len(second.sop_notes) == 1


def test_reflection_failure_does_not_break_task(tmp_path):
    kernel, task_id, _artifact, _contract = _succeeded_task(tmp_path)
    try:
        kernel.reflector = FakeReflector(error=RuntimeError("reflection down"))
        # Reflect_task itself raises; the kernel wrapper in _execute catches it.
        with pytest.raises(RuntimeError, match="reflection down"):
            kernel.reflect_task(task_id)
        assert kernel.storage.get_task(task_id)["status"] == "succeeded"
    finally:
        kernel.close()
