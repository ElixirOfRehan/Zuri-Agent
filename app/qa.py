from __future__ import annotations

from .config import Settings
from .llm import DeepSeekLLM
from .models import AgentSpec, QAReview, TaskContract
from .storage import Storage


class QAReviewer:
    """Advisory review after the deterministic verifier passes."""

    def __init__(self, settings: Settings, storage: Storage, llm: DeepSeekLLM):
        self.settings = settings
        self.storage = storage
        self.llm = llm

    def review(
        self,
        task_id: str,
        contract: TaskContract,
        assignee: AgentSpec,
        qa_spec: AgentSpec,
        artifacts: list[dict],
        verifications: list[dict],
        commands: list[dict],
        contents: list[dict],
        messages: list[dict],
    ) -> QAReview:
        return self.llm.review_task(
            task_id,
            contract,
            assignee,
            qa_spec,
            artifacts,
            verifications,
            commands,
            contents,
            messages,
        )
