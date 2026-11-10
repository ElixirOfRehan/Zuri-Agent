from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .sandbox import normalize_relative

RESERVED_IDS = {"boss", "worker", "hr", "kernel", "verifier"}
AGENT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,30}$")


class TaskStatus(str, Enum):
    CREATED = "created"
    PLANNED = "planned"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class Deliverable(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str
    description: str = ""

    @field_validator("path")
    @classmethod
    def _path_must_be_relative(cls, value: str) -> str:
        return normalize_relative(value)


class AcceptanceTest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["file_exists", "file_not_empty", "file_contains"]
    path: str
    text: str | None = None
    case_sensitive: bool = False

    @field_validator("path")
    @classmethod
    def _path_must_be_relative(cls, value: str) -> str:
        return normalize_relative(value)

    @model_validator(mode="after")
    def _contains_needs_text(self) -> "AcceptanceTest":
        if self.type == "file_contains" and not (self.text or "").strip():
            raise ValueError("file_contains acceptance test needs non-empty text")
        return self


class Budget(BaseModel):
    model_config = ConfigDict(extra="ignore")

    max_steps: int = Field(default=12, ge=1, le=50)
    max_tokens: int = Field(default=30_000, ge=500, le=200_000)
    max_cost_usd: float = Field(default=0.10, gt=0, le=5.0)


class TaskContract(BaseModel):
    model_config = ConfigDict(extra="ignore")

    objective: str
    context: str = ""
    deliverables: list[Deliverable]
    acceptance_tests: list[AcceptanceTest]
    constraints: list[str] = []
    risk: Literal["low", "medium", "high"] = "low"
    approval_class: Literal["auto", "user"] = "auto"
    assignee: str = "worker"
    budget: Budget = Field(default_factory=Budget)

    @field_validator("objective")
    @classmethod
    def _objective_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("objective must not be empty")
        return value.strip()

    @model_validator(mode="after")
    def _paths_must_match_deliverables(self) -> "TaskContract":
        if not self.deliverables:
            raise ValueError("at least one deliverable is required")
        if not self.acceptance_tests:
            raise ValueError("at least one acceptance test is required")
        paths = {deliverable.path for deliverable in self.deliverables}
        for test in self.acceptance_tests:
            if test.path not in paths:
                raise ValueError(
                    f"acceptance test path {test.path!r} is not a deliverable path"
                )
        return self


class AgentSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    system_prompt: str
    model: str | None = None
    model_env: str | None = None
    tools: list[str] = []
    description: str = ""
    style: dict = {}
    source: str = "user"
    enabled: bool = True
    version: int = 1
    created_at: str = ""
    updated_at: str = ""

    @field_validator("id")
    @classmethod
    def _id_must_be_slug(cls, value: str) -> str:
        if not AGENT_ID_PATTERN.match(value):
            raise ValueError(
                "id must be lowercase letters, digits and hyphens (2-31 chars)"
            )
        return value

    @field_validator("name", "system_prompt")
    @classmethod
    def _must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value.strip()

    @field_validator("tools")
    @classmethod
    def _tools_unique(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))

    def resolve_model(self, settings) -> str:
        if self.model_env:
            import os

            value = os.getenv(self.model_env, "").strip()
            if value:
                return value
        if self.model:
            return self.model
        return settings.worker_model


class AgentProposal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    proposal_id: str
    request: str
    spec: AgentSpec
    status: Literal["pending", "approved", "rejected"] = "pending"
    created_at: str = ""


@dataclass
class WorkerOutcome:
    final_message: str
    steps: int = 0
    error: str | None = None
    tool_calls: int = 0


@dataclass
class VerificationResult:
    name: str
    passed: bool
    detail: str
    evidence: dict = field(default_factory=dict)
