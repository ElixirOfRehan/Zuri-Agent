from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from .config import Settings
from .models import (
    RESERVED_IDS,
    AgentChange,
    AgentProposal,
    AgentSpec,
    MemoryEntry,
    effective_style,
    validate_style,
)
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

    def _profiles_dir(self, agent_id: str) -> Path:
        return self.agents_dir / agent_id / "profiles"

    def _memory_path(self, agent_id: str) -> Path:
        return self.agents_dir / agent_id / "memory.jsonl"

    def _changes_path(self, agent_id: str) -> Path:
        return self.agents_dir / agent_id / "pending_changes.json"

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

    # ----- mind: profile versions -----------------------------------------
    def list_versions(self, agent_id: str) -> list[int]:
        versions: list[int] = []
        for path in self._profiles_dir(agent_id).glob("v*.json"):
            try:
                versions.append(int(path.stem[1:]))
            except ValueError:
                continue
        return sorted(versions)

    def update_profile(
        self,
        agent_id: str,
        *,
        style: dict | None = None,
        sop_notes_append: list[str] | None = None,
        tools: list[str] | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
        name: str | None = None,
        description: str | None = None,
        reason: str,
        evidence: list[str] | None = None,
        actor: str = "user",
    ) -> AgentSpec:
        current = self.get(agent_id)
        if current is None:
            raise ValueError(f"agent not found: {agent_id}")
        updates: dict = {}
        changed: list[str] = []
        if style is not None:
            merged = {**current.style, **validate_style(style)}
            if effective_style(merged) != current.effective_style():
                updates["style"] = merged
                changed.append("style")
        if sop_notes_append:
            notes = list(current.sop_notes)
            for note in sop_notes_append:
                text = note.strip()
                if (
                    text
                    and len(text) <= 500
                    and not any(
                        self._similar_note(text, existing) for existing in notes
                    )
                ):
                    notes.append(text)
            if notes != current.sop_notes:
                updates["sop_notes"] = notes[:50]
                changed.append("sop_notes")
        if tools is not None:
            unknown = set(tools) - KNOWN_TOOLS
            if unknown:
                raise ValueError(f"unknown tools: {', '.join(sorted(unknown))}")
            if not tools:
                raise ValueError("an agent needs at least one tool")
            if tools != current.tools:
                updates["tools"] = tools
                changed.append("tools")
        if model is not None:
            if model not in ALLOWED_MODELS:
                raise ValueError(
                    f"model must be one of: {', '.join(sorted(ALLOWED_MODELS))}"
                )
            if model != current.model:
                updates["model"] = model
                changed.append("model")
        if system_prompt is not None:
            text = system_prompt.strip()
            if len(text) < 20:
                raise ValueError("system_prompt is too short")
            if text != current.system_prompt:
                updates["system_prompt"] = text
                changed.append("system_prompt")
        if name is not None and name.strip() != current.name:
            updates["name"] = name.strip()
            changed.append("name")
        if description is not None and description.strip() != current.description:
            updates["description"] = description.strip()
            changed.append("description")
        if not updates:
            return current
        updates["version"] = current.version + 1
        updates["updated_at"] = utc_now()
        updated = AgentSpec.model_validate({**current.model_dump(), **updates})
        self._write_profile(updated)
        self._write_json(
            self._profiles_dir(agent_id) / f"v{updated.version:04d}.json",
            updated.model_dump(),
        )
        self._audit(
            agent_id,
            "profile_updated",
            {
                "version": updated.version,
                "changed": changed,
                "reason": reason,
                "evidence": evidence or [],
                "actor": actor,
            },
        )
        return updated

    def rollback_profile(self, agent_id: str, version: int) -> AgentSpec:
        current = self.get(agent_id)
        if current is None:
            raise ValueError(f"agent not found: {agent_id}")
        snapshot = self._profiles_dir(agent_id) / f"v{version:04d}.json"
        if not snapshot.exists():
            raise ValueError(f"profile version not found: {version}")
        with open(snapshot, "r", encoding="utf-8") as handle:
            old = AgentSpec.model_validate(json.load(handle))
        updated = AgentSpec.model_validate(
            {
                **old.model_dump(),
                "version": current.version + 1,
                "updated_at": utc_now(),
            }
        )
        self._write_profile(updated)
        self._write_json(
            self._profiles_dir(agent_id) / f"v{updated.version:04d}.json",
            updated.model_dump(),
        )
        self._audit(
            agent_id,
            "profile_rolled_back",
            {
                "from_version": version,
                "new_version": updated.version,
            },
        )
        return updated

    # ----- mind: memory ----------------------------------------------------
    def load_memory(
        self, agent_id: str, include_forgotten: bool = False
    ) -> list[MemoryEntry]:
        path = self._memory_path(agent_id)
        if not path.exists():
            return []
        entries: list[MemoryEntry] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = MemoryEntry.model_validate_json(line)
            except Exception:
                continue
            if include_forgotten or entry.status == "active":
                entries.append(entry)
        return entries

    def append_memory(self, agent_id: str, entries: list[MemoryEntry]) -> list[MemoryEntry]:
        if not entries:
            return []
        if self.get(agent_id) is None:
            raise ValueError(f"agent not found: {agent_id}")
        path = self._memory_path(agent_id)
        with open(path, "a", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(entry.model_dump_json() + "\n")
        self._audit(
            agent_id,
            "memory_added",
            {"count": len(entries), "ids": [entry.id for entry in entries]},
        )
        return entries

    def remember_user_fact(self, agent_id: str, text: str) -> MemoryEntry:
        entry = MemoryEntry(
            id="m_" + uuid.uuid4().hex[:10],
            ts=utc_now(),
            kind="user_fact",
            text=text,
            evidence=["user"],
            created_by="user",
        )
        self.append_memory(agent_id, [entry])
        return entry

    def forget_memory(self, agent_id: str, memory_id: str) -> MemoryEntry:
        path = self._memory_path(agent_id)
        entries = []
        target: MemoryEntry | None = None
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    entry = MemoryEntry.model_validate_json(line)
                except Exception:
                    continue
                if entry.id == memory_id:
                    entry = entry.model_copy(update={"status": "forgotten"})
                    target = entry
                entries.append(entry)
        if target is None:
            raise ValueError(f"memory entry not found: {memory_id}")
        write_atomic(
            path,
            "".join(entry.model_dump_json() + "\n" for entry in entries).encode(
                "utf-8"
            ),
        )
        self._audit(
            agent_id, "memory_forgotten", {"memory_id": memory_id}
        )
        return target

    # ----- mind: pending changes ------------------------------------------
    def _load_changes(self, agent_id: str) -> list[AgentChange]:
        path = self._changes_path(agent_id)
        if not path.exists():
            return []
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return [AgentChange.model_validate(item) for item in data]

    def _save_changes(self, agent_id: str, changes: list[AgentChange]) -> None:
        self._write_json(
            self._changes_path(agent_id),
            [change.model_dump() for change in changes],
        )

    def add_change(
        self,
        agent_id: str,
        *,
        kind: str,
        proposed: str,
        reason: str = "",
        evidence: list[str] | None = None,
    ) -> AgentChange:
        if self.get(agent_id) is None:
            raise ValueError(f"agent not found: {agent_id}")
        if kind not in {"tools", "model", "scope", "system_prompt", "style"}:
            raise ValueError(f"unknown change kind: {kind}")
        change = AgentChange(
            change_id="c_" + uuid.uuid4().hex[:10],
            agent_id=agent_id,
            kind=kind,
            proposed=proposed,
            reason=reason,
            evidence=evidence or [],
            created_at=utc_now(),
        )
        changes = self._load_changes(agent_id)
        for existing in changes:
            if (
                existing.status == "pending"
                and existing.kind == kind
                and existing.proposed == proposed
            ):
                return existing
        changes.append(change)
        self._save_changes(agent_id, changes)
        self._audit(
            agent_id,
            "change_proposed",
            {"change_id": change.change_id, "kind": kind, "reason": reason},
        )
        return change

    def list_changes(
        self, agent_id: str, status: str | None = "pending"
    ) -> list[AgentChange]:
        changes = self._load_changes(agent_id)
        if status is None:
            return changes
        return [change for change in changes if change.status == status]

    def approve_change(self, agent_id: str, change_id: str) -> AgentChange:
        changes = self._load_changes(agent_id)
        selected = next(
            (change for change in changes if change.change_id == change_id), None
        )
        if selected is None:
            raise ValueError(f"change not found: {change_id}")
        if selected.status != "pending":
            raise ValueError(f"change is not pending: {selected.status}")
        if selected.kind == "tools":
            raw = selected.proposed.strip()
            if raw.startswith("["):
                tools = json.loads(raw)
            else:
                tools = [item.strip() for item in raw.split(",") if item.strip()]
            self.update_profile(
                agent_id,
                tools=tools,
                reason=selected.reason or "approved tool change",
                evidence=selected.evidence,
                actor="user",
            )
        elif selected.kind == "model":
            self.update_profile(
                agent_id,
                model=selected.proposed.strip(),
                reason=selected.reason or "approved model change",
                evidence=selected.evidence,
                actor="user",
            )
        elif selected.kind == "system_prompt":
            self.update_profile(
                agent_id,
                system_prompt=selected.proposed,
                reason=selected.reason or "approved prompt change",
                evidence=selected.evidence,
                actor="user",
            )
        elif selected.kind == "scope":
            self.update_profile(
                agent_id,
                sop_notes_append=[f"Scope: {selected.proposed.strip()}"],
                reason=selected.reason or "approved scope change",
                evidence=selected.evidence,
                actor="user",
            )
        elif selected.kind == "style":
            try:
                style = json.loads(selected.proposed)
            except json.JSONDecodeError as error:
                raise ValueError(f"style change is not valid JSON: {error}") from error
            self.update_profile(
                agent_id,
                style=style,
                reason=selected.reason or "approved style change",
                evidence=selected.evidence,
                actor="user",
            )
        updated = selected.model_copy(update={"status": "approved"})
        changes = [
            updated if change.change_id == change_id else change
            for change in changes
        ]
        self._save_changes(agent_id, changes)
        self._audit(
            agent_id,
            "change_approved",
            {"change_id": change_id, "kind": selected.kind},
        )
        return updated

    def reject_change(self, agent_id: str, change_id: str) -> AgentChange:
        changes = self._load_changes(agent_id)
        selected = next(
            (change for change in changes if change.change_id == change_id), None
        )
        if selected is None:
            raise ValueError(f"change not found: {change_id}")
        if selected.status != "pending":
            raise ValueError(f"change is not pending: {selected.status}")
        updated = selected.model_copy(update={"status": "rejected"})
        changes = [
            updated if change.change_id == change_id else change
            for change in changes
        ]
        self._save_changes(agent_id, changes)
        self._audit(
            agent_id,
            "change_rejected",
            {"change_id": change_id, "kind": selected.kind},
        )
        return updated

    def _audit(self, agent_id: str, action: str, data: dict) -> None:
        self.storage.add_agent_event(agent_id, action, data)

    @staticmethod
    def _similar_note(left: str, right: str) -> bool:
        def normalize(value: str) -> str:
            return re.sub(r"[^a-z0-9 ]+", " ", value.casefold()).strip()

        a = normalize(left)
        b = normalize(right)
        if not a or not b:
            return a == b
        return SequenceMatcher(None, a, b).ratio() >= 0.8
