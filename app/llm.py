from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI
from pydantic import ValidationError

from .config import Settings
from .models import AgentSpec, TaskContract, WorkerOutcome
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
        system = (
            boss_spec.system_prompt.strip()
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

    def run_worker(
        self,
        contract: TaskContract,
        worker_spec: AgentSpec,
        toolset: ToolSet,
        task_id: str,
    ) -> WorkerOutcome:
        model = worker_spec.resolve_model(self.settings) or self.settings.worker_model
        messages: list[dict] = [
            {"role": "system", "content": worker_spec.system_prompt.strip()},
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
