from __future__ import annotations

from .config import Settings
from .llm import DeepSeekLLM
from .models import (
    AgentSpec,
    MemoryEntry,
    ReflectionResult,
    TaskContract,
)
from .storage import Storage


class Reflector:
    """Turns a verified task into evidence-backed lessons for one agent."""

    def __init__(self, settings: Settings, storage: Storage, llm: DeepSeekLLM):
        self.settings = settings
        self.storage = storage
        self.llm = llm

    def review(
        self,
        task_id: str,
        contract: TaskContract,
        profile: AgentSpec,
        artifacts: list[dict],
        verifications: list[dict],
        memory: list[MemoryEntry],
    ) -> ReflectionResult:
        return self.llm.reflect(
            task_id, contract, profile, artifacts, verifications, memory
        )
