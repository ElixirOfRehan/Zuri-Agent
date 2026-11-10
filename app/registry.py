from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings
from .models import RESERVED_IDS, AgentProposal, AgentSpec
from .sandbox import write_atomic
from .storage import Storage, utc_now
from .tools import KNOWN_TOOLS

ALLOWED_MODELS = {"deepseek-flash", "deepseek-v4-pro"}
NON_ASSIGNABLE = {"boss", "hr", "kernel", "verifier"}


class AgentRegistry:
    def __init__(self, settings: Settings, storage: Storage):
        self.settings = settings
        self.storage = storage
        self.agents_dir = settings.root / "agents"
        self.trash_dir = self.agents_dir / ".trash"
        self.proposals_dir = settings.data_dir / "agent_proposals"
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        self.proposals_dir.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy()
        self._ensure_layouts()

    # ----- paths and json -------------------------------------------------
    def _profile_path(self, agent_id: str) -> Path:
        return self.agents_dir / agent_id / "profile.json"

    @staticmethod
    def _dump(data: dict | AgentSpec) -> bytes:
        payload = data.model_dump() if isinstance(data, AgentSpec) else data
        return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    def _write_profile(self, spec: AgentSpec) -> None:
        write_atomic(self._profile_path(spec.id), self._dump(spec))

    def _write_json(self, path: Path, data: dict) -> None:
        write_atomic(
            path,
            (json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n").encode(
                "utf-8"
            ),
        )

    def _read_spec(self, path: Path) -> AgentSpec:
        with open(path, "r", encoding="utf-8") as handle:
            return AgentSpec.model_validate(json.load(handle))

    # ----- migration / layout --------------------------------------------
    def _migrate_legacy(self) -> None:
        for agent_id in ("boss", "worker"):
            legacy = self.agents_dir / f"{agent_id}.json"
            target = self._profile_path(agent_id)
            if legacy.exists() and not target.exists():
                folder = target.parent
                folder.mkdir(parents=True, exist_ok=True)
                shutil.move(str(legacy), str(target))
                self._audit(agent_id, "agent_migrated", {"from": str(legacy)})

    def _ensure_layouts(self) -> None:
        for folder in self.agents_dir.iterdir():
            if not folder.is_dir() or folder.name.startswith("."):
                continue
            profile = folder / "profile.json"
            if not profile.exists():
                continue
            memory = folder / "memory.jsonl"
            memory.touch(exist_ok=True)
            profiles = folder / "profiles"
            profiles.mkdir(exist_ok=True)
            spec = self._read_spec(profile)
            first = profiles / "v0001.json"
            if not first.exists():
                self._write_json(first, spec.model_dump())

    # ----- read ------------------------------------------------------------
    def list_agents(self, include_disabled: bool = True) -> list[AgentSpec]:
        agents: list[AgentSpec] = []
        for folder in sorted(self.agents_dir.iterdir(), key=lambda p: p.name):
            if not folder.is_dir() or folder.name.startswith("."):
                continue
            profile = folder / "profile.json"
            if not profile.exists():
                continue
            spec = self._read_spec(profile)
            if include_disabled or spec.enabled:
                agents.append(spec)
        return agents

    def get(self, agent_id: str) -> AgentSpec | None:
        path = self._profile_path(agent_id)
        if not path.exists():
            return None
        return self._read_spec(path)

    def exists(self, agent_id: str) -> bool:
        return self._profile_path(agent_id).exists()

    def assignable(self) -> list[AgentSpec]:
        return [
            spec
            for spec in self.list_agents()
            if spec.enabled and spec.id not in NON_ASSIGNABLE
        ]

    # ----- validation ------------------------------------------------------
    def _validate_user_spec(self, spec: AgentSpec) -> None:
        if spec.id in RESERVED_IDS:
            raise ValueError(f"agent id is reserved: {spec.id}")
        if self.exists(spec.id):
            raise ValueError(f"agent already exists: {spec.id}")
        if not spec.tools:
            raise ValueError("an agent needs at least one tool")
        unknown = set(spec.tools) - KNOWN_TOOLS
        if unknown:
            raise ValueError(f"unknown tools: {', '.join(sorted(unknown))}")
        if spec.model not in ALLOWED_MODELS:
            raise ValueError(
                f"model must be one of: {', '.join(sorted(ALLOWED_MODELS))}"
            )
        if len(spec.system_prompt.strip()) < 20:
            raise ValueError("system_prompt is too short; describe the role and SOP")

    # ----- create ----------------------------------------------------------
    def create_agent(self, spec: AgentSpec, source: str = "user") -> AgentSpec:
        if source == "user":
            self._validate_user_spec(spec)
        else:
            unknown = set(spec.tools) - KNOWN_TOOLS
            if unknown:
                raise ValueError(f"unknown tools: {', '.join(sorted(unknown))}")
        now = utc_now()
        spec = spec.model_copy(
            update={
                "source": source,
                "enabled": True,
                "version": spec.version or 1,
                "created_at": spec.created_at or now,
                "updated_at": now,
            }
        )
        folder = self.agents_dir / spec.id
        (folder / "profiles").mkdir(parents=True, exist_ok=True)
        (folder / "memory.jsonl").touch(exist_ok=True)
        self._write_profile(spec)
        self._write_json(folder / "profiles" / "v0001.json", spec.model_dump())
        self._audit(
            spec.id,
            "agent_created",
            {
                "source": source,
                "name": spec.name,
                "tools": spec.tools,
                "model": spec.model,
            },
        )
        return spec

    # ----- proposals -------------------------------------------------------
    def _proposal_path(self, proposal_id: str) -> Path:
        return self.proposals_dir / f"{proposal_id}.json"

    def propose_create(self, request: str, spec: AgentSpec) -> AgentProposal:
        self._validate_user_spec(spec)
        proposal = AgentProposal(
            proposal_id="p_" + uuid.uuid4().hex[:10],
            request=request,
            spec=spec,
            status="pending",
            created_at=utc_now(),
        )
        self._write_json(self._proposal_path(proposal.proposal_id), proposal.model_dump())
        self._audit(
            spec.id,
            "agent_proposed",
            {"proposal_id": proposal.proposal_id, "request": request},
        )
        return proposal

    def get_proposal(self, proposal_id: str) -> AgentProposal | None:
        path = self._proposal_path(proposal_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as handle:
            return AgentProposal.model_validate(json.load(handle))

    def list_proposals(self, status: str | None = None) -> list[AgentProposal]:
        proposals: list[AgentProposal] = []
        for path in sorted(self.proposals_dir.glob("*.json")):
            with open(path, "r", encoding="utf-8") as handle:
                proposal = AgentProposal.model_validate(json.load(handle))
            if status is None or proposal.status == status:
                proposals.append(proposal)
        return proposals

    def approve_proposal(self, proposal_id: str) -> AgentProposal:
        proposal = self.get_proposal(proposal_id)
        if proposal is None:
            raise ValueError(f"proposal not found: {proposal_id}")
        if proposal.status != "pending":
            raise ValueError(f"proposal is not pending: {proposal.status}")
        self.create_agent(proposal.spec, source="user")
        proposal = proposal.model_copy(update={"status": "approved"})
        self._write_json(self._proposal_path(proposal_id), proposal.model_dump())
        self._audit(
            proposal.spec.id,
            "agent_proposal_approved",
            {"proposal_id": proposal_id},
        )
        return proposal

    def reject_proposal(self, proposal_id: str) -> AgentProposal:
        proposal = self.get_proposal(proposal_id)
        if proposal is None:
            raise ValueError(f"proposal not found: {proposal_id}")
        if proposal.status != "pending":
            raise ValueError(f"proposal is not pending: {proposal.status}")
        proposal = proposal.model_copy(update={"status": "rejected"})
        self._write_json(self._proposal_path(proposal_id), proposal.model_dump())
        self._audit(
            proposal.spec.id,
            "agent_proposal_rejected",
            {"proposal_id": proposal_id},
        )
        return proposal

    # ----- delete / restore ------------------------------------------------
    def delete_agent(self, agent_id: str, confirm1: str, confirm2: str) -> str:
        spec = self.get(agent_id)
        if spec is None:
            raise ValueError(f"agent not found: {agent_id}")
        if agent_id in RESERVED_IDS:
            raise ValueError(f"system agent cannot be deleted: {agent_id}")
        if confirm1 != agent_id:
            self._audit(agent_id, "agent_delete_aborted", {"step": 1})
            raise ValueError("first confirmation did not match the agent id")
        expected = f"DELETE {agent_id}"
        if confirm2 != expected:
            self._audit(agent_id, "agent_delete_aborted", {"step": 2})
            raise ValueError(f"second confirmation must be exactly: {expected}")

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        trash_path = self.trash_dir / f"{agent_id}-{stamp}-{uuid.uuid4().hex[:6]}"
        source = self.agents_dir / agent_id
        shutil.copytree(source, trash_path)
        self._write_json(
            trash_path / "delete_meta.json",
            {
                "agent_id": agent_id,
                "deleted_at": utc_now(),
                "deleted_by": "user",
                "confirmations": 2,
            },
        )
        shutil.rmtree(source)
        self._audit(
            agent_id,
            "agent_soft_deleted",
            {"trash_path": str(trash_path)},
        )
        return str(trash_path)

    def restore_agent(self, agent_id: str) -> Path:
        if self.exists(agent_id):
            raise ValueError(f"agent already exists: {agent_id}")
        candidates = [
            path
            for path in sorted(self.trash_dir.glob(f"{agent_id}-*"), reverse=True)
            if path.is_dir()
        ]
        if not candidates:
            raise ValueError(f"no trash snapshot for agent: {agent_id}")
        source = candidates[0]
        target = self.agents_dir / agent_id
        shutil.copytree(source, target)
        meta = target / "delete_meta.json"
        if meta.exists():
            meta.unlink()
        self._audit(
            agent_id,
            "agent_restored",
            {"from": str(source)},
        )
        return target

    # ----- history ---------------------------------------------------------
    def history(self, agent_id: str, limit: int = 100) -> list[dict]:
        return self.storage.get_agent_events(agent_id, limit)

    def _audit(self, agent_id: str, action: str, data: dict) -> None:
        self.storage.add_agent_event(agent_id, action, data)
