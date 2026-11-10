from __future__ import annotations

import json
from pathlib import Path

from .llm import DeepSeekLLM
from .models import AgentSpec, TaskContract, WorkerOutcome
from .storage import Storage
from .tools import ToolSet


def load_agent_spec(path: Path) -> AgentSpec:
    with open(path, "r", encoding="utf-8") as handle:
        return AgentSpec.model_validate(json.load(handle))


class Boss:
    def __init__(self, spec: AgentSpec, llm: DeepSeekLLM):
        self.spec = spec
        self.llm = llm

    def plan(self, request: str, task_id: str, assignees: list[AgentSpec]) -> TaskContract:
        return self.llm.plan_contract(request, self.spec, task_id, assignees)


class LLMWorker:
    def __init__(self, spec: AgentSpec, llm: DeepSeekLLM):
        self.spec = spec
        self.llm = llm

    def run(self, contract: TaskContract, toolset: ToolSet, task_id: str) -> WorkerOutcome:
        return self.llm.run_worker(contract, self.spec, toolset, task_id)


class LiarWorker:
    """A worker that only claims success. Used to prove the verifier cannot be fooled."""

    def __init__(self, storage: Storage):
        self.storage = storage

    def run(self, contract: TaskContract, toolset: ToolSet, task_id: str) -> WorkerOutcome:
        message = "Done. I created every deliverable. The task is complete."
        self.storage.add_event(
            task_id,
            "worker",
            "message",
            {"content": message, "liar_test": True},
        )
        return WorkerOutcome(final_message=message, steps=0, tool_calls=0)
