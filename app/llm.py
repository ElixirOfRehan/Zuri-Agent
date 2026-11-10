from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI
from pydantic import ValidationError

from .config import Settings
from .models import (
    AgentSpec,
    Alternative,
    MemoryEntry,
    QAReview,
    ReflectionResult,
    TaskContract,
    WorkerOutcome,
)
from .redact import preview, redact
from .storage import Storage
from .tools import ToolSet


def _strip_fences(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```[A-Za-z0-9_-]*\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    return value.strip()


class DeepSeekLLM:
    def __init__(self, settings: Settings, storage: Storage):
        self.settings = settings
        self.storage = storage
        self.client = OpenAI(
            api_key=settings.api_key or "sk-missing",
            base_url=settings.base_url,
            timeout=settings.request_timeout_s,
            max_retries=3,
        )

    def _chat(
        self,
        *,
        model: str,
        messages: list[dict],
        agent: str,
        task_id: str,
        tools: list[dict] | None = None,
        response_format: dict | None = None,
        temperature: float = 0.2,
    ):
        if not self.settings.has_api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY is missing. Put it in the project .env file."
            )
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if response_format:
            kwargs["response_format"] = response_format
        if self.settings.thinking == "disabled":
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        try:
            response = self.client.chat.completions.create(**kwargs)
        except Exception as error:  # noqa: BLE001
            if "thinking" in str(error).lower() and "extra_body" in kwargs:
                kwargs.pop("extra_body", None)
                response = self.client.chat.completions.create(**kwargs)
            else:
                raise
        usage = response.usage
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        cost = self.settings.estimate_cost(model, prompt_tokens, completion_tokens)
        self.storage.add_cost(
            task_id, agent, model, prompt_tokens, completion_tokens, cost
        )
        self.storage.add_event(
            task_id,
            agent,
            "llm_call",
            {
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": round(cost, 6),
            },
        )
        return response.choices[0].message

    def plan_contract(
        self,
        request: str,
        boss_spec: AgentSpec,
        task_id: str,
        assignees: list[AgentSpec] | None = None,
    ) -> TaskContract:
        model = boss_spec.resolve_model(self.settings) or self.settings.boss_model
        schema = json.dumps(TaskContract.model_json_schema(), indent=2)
        assignee_block = ""
        if assignees:
            lines = "\n".join(
                f"- {spec.id}: {spec.name} - {spec.description}"
                for spec in assignees
            )
            assignee_block = (
                "\n\nAvailable assignees (choose exactly one id):\n" + lines
            )
        style = boss_spec.effective_style()
        style_block = (
            "\n\nBoss behavior style: "
            + ", ".join(f"{key}={value}" for key, value in style.items())
        )
        if boss_spec.sop_notes:
            style_block += "\nBoss learned notes:\n" + "\n".join(
                f"- {note}" for note in boss_spec.sop_notes[-10:]
            )
        system = (
            boss_spec.system_prompt.strip()
            + style_block
            + assignee_block
            + "\n\nYou must return ONLY a JSON object matching this schema:\n"
            + schema
        )
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": request},
        ]
        last_error = ""
        for _attempt in range(2):
            message = self._chat(
                model=model,
                messages=messages,
                agent="boss",
                task_id=task_id,
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            content = _strip_fences(message.content or "")
            try:
                data = json.loads(content)
                return TaskContract.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as error:
                last_error = str(error)
                messages = messages + [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            "That contract is invalid: "
                            + last_error
                            + "\nReturn a corrected JSON contract only."
                        ),
                    },
                ]
        raise ValueError(f"Boss could not produce a valid contract: {last_error}")

    def propose_agent(
        self,
        request: str,
        hr_spec: AgentSpec,
        existing_ids: set[str],
        allowed_tools: set[str],
        allowed_models: set[str],
    ) -> AgentSpec:
        model = hr_spec.resolve_model(self.settings) or self.settings.boss_model
        schema = json.dumps(AgentSpec.model_json_schema(), indent=2)
        context = (
            "\n\nExisting agent ids (do not reuse): "
            + (", ".join(sorted(existing_ids)) or "(none)")
            + "\nAllowed tools: "
            + ", ".join(sorted(allowed_tools))
            + "\nAllowed models: "
            + ", ".join(sorted(allowed_models))
        )
        system = (
            hr_spec.system_prompt.strip()
            + context
            + "\n\nReturn ONLY a JSON object matching this schema:\n"
            + schema
        )
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": request},
        ]
        last_error = ""
        for _attempt in range(2):
            message = self._chat(
                model=model,
                messages=messages,
                agent="hr",
                task_id="registry",
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            content = _strip_fences(message.content or "")
            try:
                data = json.loads(content)
                return AgentSpec.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as error:
                last_error = str(error)
                messages = messages + [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            "That agent definition is invalid: "
                            + last_error
                            + "\nReturn a corrected JSON agent definition only."
                        ),
                    },
                ]
        raise ValueError(f"HR could not produce a valid agent definition: {last_error}")

    def ping(self) -> str:
        message = self._chat(
            model=self.settings.worker_model,
            messages=[{"role": "user", "content": "Reply with the word pong."}],
            agent="doctor",
            task_id="ping",
            temperature=0.0,
        )
        return (message.content or "").strip()

    def reflect(
        self,
        task_id: str,
        contract: TaskContract,
        profile: AgentSpec,
        artifacts: list[dict],
        verifications: list[dict],
        memory: list[MemoryEntry],
    ) -> ReflectionResult:
        model = self.settings.reflector_model or self.settings.worker_model
        allowed = [task_id, f"task:{task_id}"]
        allowed.extend(artifact["id"] for artifact in artifacts)
        allowed.extend(check["name"] for check in verifications)
        payload = {
            "task": {"id": task_id, "contract": contract.model_dump()},
            "profile": {
                "id": profile.id,
                "name": profile.name,
                "system_prompt": profile.system_prompt,
                "sop_notes": profile.sop_notes,
                "style": profile.effective_style(),
            },
            "artifacts": [
                {"id": item["id"], "path": item["path"], "sha256": item["sha256"]}
                for item in artifacts
            ],
            "verifications": [
                {
                    "name": item["name"],
                    "passed": item["passed"],
                    "detail": item["detail"],
                }
                for item in verifications
            ],
            "existing_memory": [
                {"id": item.id, "kind": item.kind, "text": item.text}
                for item in memory[-20:]
            ],
            "allowed_evidence": allowed,
        }
        system = (
            "You are the reflection step of a small AI company. The task was "
            "independently verified. Extract only lessons that are supported by "
            "the provided evidence.\n\n"
            "Return ONLY JSON matching this schema:\n"
            + json.dumps(ReflectionResult.model_json_schema(), indent=2)
            + "\n\nRules:\n"
            "- facts: at most 5. Each fact needs evidence from allowed_evidence.\n"
            "- Do not repeat facts or notes already present in existing_memory "
            "or the profile's sop_notes.\n"
            "- Prefer reusable lessons and preferences; do not record trivial "
            "facts like 'the task completed successfully'.\n"
            "- sop_notes: at most 3 short, reusable procedure notes that are not "
            "semantic duplicates of existing sop_notes.\n"
            "- style: only these keys: tone (direct|friendly|formal), length "
            "(short|standard|detailed), language, initiative (ask|act), risk "
            "(low|medium|high), approval (strict|balanced), report_format "
            "(evidence-first|brief|detailed). Omit keys you are unsure about.\n"
            "- suggestions: at most 3 for tools/model/scope/system_prompt. These "
            "are NOT applied automatically; they become pending user approvals.\n"
            "- Never include secrets, credentials or invented results.\n"
            "- Use only what is in the payload; no outside assumptions."
        )
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, indent=2, ensure_ascii=False)},
        ]
        last_error = ""
        for _attempt in range(2):
            message = self._chat(
                model=model,
                messages=messages,
                agent="reflector",
                task_id=task_id,
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            content = _strip_fences(message.content or "")
            try:
                return ReflectionResult.model_validate(json.loads(content))
            except (json.JSONDecodeError, ValidationError) as error:
                last_error = str(error)
                messages = messages + [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            "That reflection is invalid: "
                            + last_error
                            + "\nReturn corrected JSON only."
                        ),
                    },
                ]
        raise ValueError(f"Reflection failed validation: {last_error}")

    def run_worker(
        self,
        contract: TaskContract,
        worker_spec: AgentSpec,
        toolset: ToolSet,
        task_id: str,
        memory: list[MemoryEntry] | None = None,
        attempt_context: str | None = None,
    ) -> WorkerOutcome:
        model = worker_spec.resolve_model(self.settings) or self.settings.worker_model
        style = worker_spec.effective_style()
        context = (
            "\n\nBehavior style: "
            + ", ".join(f"{key}={value}" for key, value in style.items())
        )
        if worker_spec.sop_notes:
            context += "\nLearned SOP notes:\n" + "\n".join(
                f"- {note}" for note in worker_spec.sop_notes[-10:]
            )
        if memory:
            context += "\nRelevant evidence-backed memory:\n" + "\n".join(
                f"- [{entry.kind}] {entry.text}" for entry in memory[-10:]
            )
        context += (
            "\n\nIf you cannot complete the task, call report_blocked with a "
            "reason and what is needed. Never claim success when blocked."
        )
        if attempt_context:
            context += "\n\nRetry guidance:\n" + attempt_context
        messages: list[dict] = [
            {
                "role": "system",
                "content": worker_spec.system_prompt.strip() + context,
            },
            {
                "role": "user",
                "content": (
                    "Work contract (JSON):\n"
                    + json.dumps(contract.model_dump(), indent=2, ensure_ascii=False)
                ),
            },
        ]
        steps = 0
        tool_calls = 0
        while steps < contract.budget.max_steps:
            if self.storage.total_cost(task_id) > contract.budget.max_cost_usd:
                return WorkerOutcome(
                    final_message="",
                    steps=steps,
                    tool_calls=tool_calls,
                    error="budget exceeded: max_cost_usd",
                )
            if self.storage.total_tokens(task_id) > contract.budget.max_tokens:
                return WorkerOutcome(
                    final_message="",
                    steps=steps,
                    tool_calls=tool_calls,
                    error="budget exceeded: max_tokens",
                )
            steps += 1
            message = self._chat(
                model=model,
                messages=messages,
                agent="worker",
                task_id=task_id,
                tools=toolset.definitions(),
                temperature=0.2,
            )
            if message.tool_calls:
                assistant = message.model_dump(exclude_none=True)
                messages.append(assistant)
                for call in message.tool_calls:
                    name = call.function.name
                    raw_arguments = call.function.arguments or "{}"
                    try:
                        arguments = json.loads(raw_arguments)
                    except json.JSONDecodeError:
                        arguments = {}
                    self.storage.add_event(
                        task_id,
                        "worker",
                        "tool_call",
                        {
                            "name": name,
                            "arguments": self._log_arguments(name, arguments),
                        },
                    )
                    result = toolset.execute(name, arguments)
                    tool_calls += 1
                    self.storage.add_event(
                        task_id,
                        "worker",
                        "tool_result",
                        {
                            "name": name,
                            "result_preview": preview(result),
                        },
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": result,
                        }
                    )
                    if toolset.blocked is not None:
                        data = toolset.blocked
                        self.storage.add_event(
                            task_id, "worker", "blocked", data
                        )
                        return WorkerOutcome(
                            final_message="",
                            steps=steps,
                            tool_calls=tool_calls,
                            blocked_reason=data.get("reason"),
                            blocked_detail=data.get("detail", ""),
                            blocked_needed=data.get("needed", ""),
                            goal_blocked=bool(data.get("goal_blocked", False)),
                        )
                continue
            final_message = message.content or ""
            self.storage.add_event(
                task_id,
                "worker",
                "message",
                {"content": preview(final_message)},
            )
            return WorkerOutcome(
                final_message=final_message,
                steps=steps,
                tool_calls=tool_calls,
            )
        return WorkerOutcome(
            final_message="",
            steps=steps,
            tool_calls=tool_calls,
            error="budget exceeded: max_steps",
        )

    def review_task(
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
        model = self.settings.qa_model or self.settings.boss_model
        payload = {
            "task_id": task_id,
            "contract": contract.model_dump(),
            "assignee": {
                "id": assignee.id,
                "name": assignee.name,
                "description": assignee.description,
            },
            "artifacts": [
                {
                    "path": item["path"],
                    "sha256": item["sha256"],
                    "bytes": item["bytes"],
                }
                for item in artifacts
            ],
            "contents": contents,
            "verifications": [
                {
                    "name": item["name"],
                    "passed": item["passed"],
                    "detail": item["detail"],
                }
                for item in verifications
            ],
            "commands": commands,
            "worker_messages": messages,
        }
        system = (
            qa_spec.system_prompt.strip()
            + "\n\nReturn ONLY JSON matching this schema:\n"
            + json.dumps(QAReview.model_json_schema(), indent=2)
        )
        qa_messages: list[dict] = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(payload, indent=2, ensure_ascii=False),
            },
        ]
        last_error = ""
        for _attempt in range(2):
            message = self._chat(
                model=model,
                messages=qa_messages,
                agent="qa",
                task_id=task_id,
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            content = _strip_fences(message.content or "")
            try:
                return QAReview.model_validate(json.loads(content))
            except (json.JSONDecodeError, ValidationError) as error:
                last_error = str(error)
                qa_messages = qa_messages + [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            "That QA review is invalid: "
                            + last_error
                            + "\nReturn corrected JSON only."
                        ),
                    },
                ]
        raise ValueError(f"QA review failed validation: {last_error}")

    def plan_alternatives(
        self,
        task_id: str,
        request: str,
        contract: TaskContract,
        profile: AgentSpec,
        blocked_reason: str,
        blocked_detail: str,
        blocked_needed: str,
        attempts: list[dict],
        assignees: list[AgentSpec],
    ) -> list[Alternative]:
        model = self.settings.resilience_model or self.settings.boss_model
        system = (
            "You are the resilience planner of a small AI company. A worker is "
            "blocked. Propose up to 3 safe alternative approaches.\n\n"
            "Return ONLY JSON: {\"alternatives\": [ {\"approach\": string, "
            "\"agent_id\": string or null, \"risk\": \"low|medium|high\", "
            "\"rationale\": string, \"steps\": [string]} ]}\n\n"
            "Rules:\n"
            "- Alternatives must be legal, within platform rules and permissions.\n"
            "- Never propose bypassing a license, DRM, paywall, authentication or "
            "access control.\n"
            "- You may use a different available agent, another tool, a smaller "
            "sub-task, or a request for missing input.\n"
            "- If the goal itself is disallowed, return an empty list.\n"
            "- Prefer low-risk alternatives; include steps.\n"
            "- Do not repeat an approach that already failed."
        )
        payload = {
            "request": request,
            "contract": contract.model_dump(),
            "agent": {
                "id": profile.id,
                "name": profile.name,
                "tools": profile.tools,
                "description": profile.description,
            },
            "blocked": {
                "reason": blocked_reason,
                "detail": blocked_detail,
                "needed": blocked_needed,
            },
            "previous_attempts": attempts,
            "available_agents": [
                {
                    "id": spec.id,
                    "name": spec.name,
                    "description": spec.description,
                    "tools": spec.tools,
                }
                for spec in assignees
            ],
        }
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, indent=2, ensure_ascii=False)},
        ]
        last_error = ""
        for _attempt in range(2):
            message = self._chat(
                model=model,
                messages=messages,
                agent="resilience",
                task_id=task_id,
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            content = _strip_fences(message.content or "")
            try:
                data = json.loads(content)
                raw = data.get("alternatives", [])
                if not isinstance(raw, list):
                    raise ValueError("alternatives must be a list")
                return [Alternative.model_validate(item) for item in raw[:3]]
            except (json.JSONDecodeError, ValidationError, ValueError) as error:
                last_error = str(error)
                messages = messages + [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            "That plan is invalid: "
                            + last_error
                            + "\nReturn corrected JSON only."
                        ),
                    },
                ]
        raise ValueError(f"Resilience planner failed: {last_error}")

    @staticmethod
    def _log_arguments(name: str, arguments: dict) -> dict:
        if name == "write_file":
            content = str(arguments.get("content", ""))
            return {
                "path": arguments.get("path"),
                "content_preview": preview(content, 300),
                "content_chars": len(content),
            }
        return {key: preview(str(value), 300) for key, value in arguments.items()}
