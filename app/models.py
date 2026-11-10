from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .sandbox import normalize_relative

RESERVED_IDS = {"boss", "worker", "hr", "kernel", "verifier", "qa"}
AGENT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,30}$")

STYLE_DEFAULTS = {
    "tone": "direct",
    "length": "short",
    "language": "en",
    "initiative": "ask",
    "risk": "low",
    "approval": "strict",
    "report_format": "evidence-first",
}
STYLE_OPTIONS = {
    "tone": {"direct", "friendly", "formal"},
    "length": {"short", "standard", "detailed"},
    "initiative": {"ask", "act"},
    "risk": {"low", "medium", "high"},
    "approval": {"strict", "balanced"},
    "report_format": {"evidence-first", "brief", "detailed"},
}


def effective_style(style: dict | None) -> dict:
    merged = dict(STYLE_DEFAULTS)
    merged.update(style or {})
    return merged


def validate_style(style: dict | None) -> dict:
    value = dict(style or {})
    unknown = set(value) - set(STYLE_DEFAULTS)
    if unknown:
        raise ValueError(f"unknown style keys: {', '.join(sorted(unknown))}")
    for key, allowed in STYLE_OPTIONS.items():
        if key in value and value[key] not in allowed:
            raise ValueError(
                f"invalid style value for {key}: {value[key]!r}; "
                f"allowed: {', '.join(sorted(allowed))}"
            )
    if "language" in value:
        language = str(value["language"])
        if not re.match(r"^[A-Za-z-]{2,16}$", language):
            raise ValueError("language must be 2-16 letters or hyphens")
        value["language"] = language
    return value


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
    max_attempts: int = Field(default=3, ge=0, le=5)


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
    sop_notes: list[str] = []
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

    @field_validator("style")
    @classmethod
    def _style_valid(cls, value: dict) -> dict:
        return validate_style(value)

    @field_validator("sop_notes")
    @classmethod
    def _sop_notes_valid(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for note in value:
            text = note.strip()
            if not text:
                continue
            if len(text) > 500:
                raise ValueError("each sop_note must be at most 500 chars")
            if text not in cleaned:
                cleaned.append(text)
        if len(cleaned) > 50:
            raise ValueError("at most 50 sop_notes")
        return cleaned

    def effective_style(self) -> dict:
        return effective_style(self.style)

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


class MemoryEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    ts: str
    kind: Literal["lesson", "preference", "project_fact", "user_fact"]
    text: str
    evidence: list[str] = []
    source_task: str | None = None
    created_by: str = "reflection"
    status: Literal["active", "forgotten"] = "active"

    @field_validator("text")
    @classmethod
    def _text_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("memory text must not be empty")
        return value.strip()


class AgentChange(BaseModel):
    model_config = ConfigDict(extra="ignore")

    change_id: str
    agent_id: str
    kind: Literal["tools", "model", "scope", "system_prompt", "style"]
    proposed: str
    reason: str = ""
    evidence: list[str] = []
    status: Literal["pending", "approved", "rejected"] = "pending"
    created_at: str = ""


class ReflectionFact(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    kind: Literal["lesson", "preference", "project_fact"]
    evidence: list[str] = []

    @field_validator("text")
    @classmethod
    def _text_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("fact text must not be empty")
        return value.strip()


class ReflectionSuggestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: Literal["tools", "model", "scope", "system_prompt"]
    proposed: str
    reason: str = ""


class ReflectionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    facts: list[ReflectionFact] = []
    sop_notes: list[str] = []
    style: dict = {}
    suggestions: list[ReflectionSuggestion] = []

    @field_validator("facts")
    @classmethod
    def _facts_bounded(cls, value: list[ReflectionFact]) -> list[ReflectionFact]:
        return value[:5]

    @field_validator("sop_notes")
    @classmethod
    def _notes_bounded(cls, value: list[str]) -> list[str]:
        cleaned = []
        for note in value:
            text = note.strip()
            if text and len(text) <= 500 and text not in cleaned:
                cleaned.append(text)
        return cleaned[:3]

    @field_validator("style")
    @classmethod
    def _style_valid(cls, value: dict) -> dict:
        return validate_style(value)

    @field_validator("suggestions")
    @classmethod
    def _suggestions_bounded(
        cls, value: list[ReflectionSuggestion]
    ) -> list[ReflectionSuggestion]:
        return value[:3]


class QAReview(BaseModel):
    model_config = ConfigDict(extra="ignore")

    verdict: Literal["pass", "fail"]
    issues: list[str] = []
    notes: list[str] = []

    @field_validator("issues", "notes")
    @classmethod
    def _bounded(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()][:10]


@dataclass
class WorkerOutcome:
    final_message: str
    steps: int = 0
    error: str | None = None
    tool_calls: int = 0
    blocked_reason: str | None = None
    blocked_detail: str = ""
    blocked_needed: str = ""
    goal_blocked: bool = False


class Alternative(BaseModel):
    model_config = ConfigDict(extra="ignore")

    approach: str
    agent_id: str | None = None
    risk: Literal["low", "medium", "high"] = "low"
    rationale: str = ""
    steps: list[str] = []

    @field_validator("approach")
    @classmethod
    def _approach_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("approach must not be empty")
        return value.strip()

    @field_validator("steps")
    @classmethod
    def _steps_clean(cls, value: list[str]) -> list[str]:
        return [step.strip() for step in value if step.strip()][:10]


@dataclass
class VerificationResult:
    name: str
    passed: bool
    detail: str
    evidence: dict = field(default_factory=dict)
