from __future__ import annotations

from pathlib import Path

import pytest

from app.models import AgentSpec
from app.registry import AgentRegistry
from app.storage import Storage

from .util import make_settings


def _spec(agent_id: str = "notes", tools: list[str] | None = None) -> AgentSpec:
    return AgentSpec(
        id=agent_id,
        name=agent_id.title(),
        description="Test agent",
        model="deepseek-flash",
        tools=tools or ["list_dir", "read_file", "write_file"],
        system_prompt="You are a careful test agent. Follow the contract and write files.",
    )


def _registry(tmp_path):
    settings = make_settings(tmp_path)
    storage = Storage(settings)
    return settings, storage, AgentRegistry(settings, storage)


def test_create_list_and_get(tmp_path):
    _settings, _storage, registry = _registry(tmp_path)
    spec = registry.create_agent(_spec())
    assert spec.version == 1
    assert spec.enabled is True
    assert registry.get("notes").name == "Notes"
    assert [agent.id for agent in registry.list_agents()] == ["notes"]


def test_reserved_id_rejected(tmp_path):
    _settings, _storage, registry = _registry(tmp_path)
    with pytest.raises(ValueError, match="reserved"):
        registry.create_agent(_spec("boss"))


def test_duplicate_rejected(tmp_path):
    _settings, _storage, registry = _registry(tmp_path)
    registry.create_agent(_spec())
    with pytest.raises(ValueError, match="already exists"):
        registry.create_agent(_spec())


def test_unknown_tool_rejected(tmp_path):
    _settings, _storage, registry = _registry(tmp_path)
    with pytest.raises(ValueError, match="unknown tools"):
        registry.create_agent(_spec(tools=["shell"]))


def test_delete_requires_two_confirmations(tmp_path):
    _settings, _storage, registry = _registry(tmp_path)
    registry.create_agent(_spec())

    with pytest.raises(ValueError, match="first confirmation"):
        registry.delete_agent("notes", "wrong", "DELETE notes")
    assert registry.get("notes") is not None

    with pytest.raises(ValueError, match="second confirmation"):
        registry.delete_agent("notes", "notes", "delete notes")
    assert registry.get("notes") is not None

    trash = registry.delete_agent("notes", "notes", "DELETE notes")
    assert registry.get("notes") is None
    assert (Path(trash) / "profile.json").exists()
    actions = [event["action"] for event in registry.history("notes")]
    assert "agent_soft_deleted" in actions


def test_restore_latest_snapshot(tmp_path):
    _settings, _storage, registry = _registry(tmp_path)
    registry.create_agent(_spec())
    registry.delete_agent("notes", "notes", "DELETE notes")
    assert registry.get("notes") is None
    registry.restore_agent("notes")
    assert registry.get("notes") is not None
    actions = [event["action"] for event in registry.history("notes")]
    assert "agent_restored" in actions


def test_proposal_approve_and_reject(tmp_path):
    _settings, _storage, registry = _registry(tmp_path)
    proposal = registry.propose_create("Make a notes agent", _spec())
    assert proposal.status == "pending"
    approved = registry.approve_proposal(proposal.proposal_id)
    assert approved.status == "approved"
    assert registry.get("notes") is not None

    second = registry.propose_create("Another agent", _spec("research"))
    rejected = registry.reject_proposal(second.proposal_id)
    assert rejected.status == "rejected"
    assert registry.get("research") is None


def test_system_agent_cannot_be_deleted(tmp_path):
    _settings, _storage, registry = _registry(tmp_path)
    registry.create_agent(_spec("worker"), source="system")
    with pytest.raises(ValueError, match="system agent"):
        registry.delete_agent("worker", "worker", "DELETE worker")
