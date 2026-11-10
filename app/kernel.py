from __future__ import annotations

import json
import re
import uuid

from .agents import Boss, LLMWorker, LiarWorker, load_agent_spec
from .config import Settings
from .llm import DeepSeekLLM
from .mind import Reflector
from .models import (
    AcceptanceTest,
    AgentProposal,
    AgentSpec,
    Deliverable,
    MemoryEntry,
    TaskContract,
    TaskStatus,
)
from .policy import Policy
from .qa import QAReviewer
from .registry import ALLOWED_MODELS, NON_ASSIGNABLE, AgentRegistry
from .storage import Storage, utc_now
from .tools import KNOWN_TOOLS, ToolSet
from .verifier import Verifier

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    TaskStatus.CREATED.value: {
        TaskStatus.PLANNED.value,
        TaskStatus.BLOCKED.value,
        TaskStatus.FAILED.value,
    },
    TaskStatus.PLANNED.value: {
        TaskStatus.AWAITING_APPROVAL.value,
        TaskStatus.RUNNING.value,
        TaskStatus.BLOCKED.value,
        TaskStatus.FAILED.value,
    },
    TaskStatus.AWAITING_APPROVAL.value: {
        TaskStatus.RUNNING.value,
        TaskStatus.BLOCKED.value,
        TaskStatus.CANCELLED.value,
        TaskStatus.FAILED.value,
    },
    TaskStatus.RUNNING.value: {
        TaskStatus.VERIFYING.value,
        TaskStatus.BLOCKED.value,
        TaskStatus.FAILED.value,
    },
    TaskStatus.VERIFYING.value: {TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value},
    TaskStatus.SUCCEEDED.value: {TaskStatus.VERIFYING.value},
    TaskStatus.FAILED.value: {TaskStatus.VERIFYING.value},
    TaskStatus.BLOCKED.value: {TaskStatus.PLANNED.value, TaskStatus.CANCELLED.value},
    TaskStatus.CANCELLED.value: set(),
}


class Kernel:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.storage = Storage(settings)
        self.llm = DeepSeekLLM(settings, self.storage)
        self.registry = AgentRegistry(settings, self.storage)
        self.reflector = Reflector(settings, self.storage, self.llm)
        self.qa = QAReviewer(settings, self.storage, self.llm)
        self.verifier = Verifier(settings, self.storage)
        self.policy = Policy()
        self._qa_spec: AgentSpec | None = None
        self._boss_agent: Boss | None = None
        self._hr_spec: AgentSpec | None = None

    def _boss(self) -> Boss:
        if self._boss_agent is None:
            spec = self.registry.get("boss")
            if spec is None:
                spec = load_agent_spec(self.settings.boss_spec_path)
            self._boss_agent = Boss(spec, self.llm)
        return self._boss_agent

    def _hr(self) -> AgentSpec:
        if self._hr_spec is None:
            spec = self.registry.get("hr")
            if spec is None:
                spec = load_agent_spec(self.settings.hr_spec_path)
            self._hr_spec = spec
        return self._hr_spec

    def validate_assignee(self, assignee: str) -> AgentSpec:
        spec = self.registry.get(assignee)
        if spec is None:
            raise ValueError(f"unknown assignee: {assignee}")
        if not spec.enabled:
            raise ValueError(f"assignee is disabled: {assignee}")
        if assignee in NON_ASSIGNABLE:
            raise ValueError(f"agent is not assignable: {assignee}")
        return spec

    def propose_agent(self, request: str) -> AgentProposal:
        existing = {
            spec.id for spec in self.registry.list_agents(include_disabled=True)
        }
        spec = self.llm.propose_agent(
            request,
            self._hr(),
            existing,
            KNOWN_TOOLS,
            ALLOWED_MODELS,
        )
        return self.registry.propose_create(request, spec)

    def _transition(self, task_id: str, new_status: str) -> None:
        task = self.storage.get_task(task_id)
        if task is None:
            raise ValueError(f"task not found: {task_id}")
        current = task["status"]
        if current == new_status:
            return
        allowed = ALLOWED_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            raise ValueError(f"invalid transition {current} -> {new_status}")
        self.storage.set_status(task_id, new_status)
        self.storage.add_event(
            task_id, "kernel", "status", {"from": current, "to": new_status}
        )

    def plan_and_run(self, request: str, auto_approve: bool = False) -> str:
        task_id = self.storage.create_task(request)
        self.storage.add_event(task_id, "kernel", "task_created", {"request": request})
        policy_reason = self.policy.forbidden_reason(request)
        if policy_reason:
            self.storage.add_event(
                task_id,
                "kernel",
                "policy_block",
                {"stage": "goal", "reason": policy_reason},
            )
            self.storage.add_event(
                task_id,
                "kernel",
                "resilience_exhausted",
                {
                    "reason": "policy_legal",
                    "detail": policy_reason,
                    "needed": "A compliant goal.",
                    "attempts": [],
                },
            )
            self._transition(task_id, TaskStatus.BLOCKED.value)
            self._save_report(task_id)
            return task_id
        assignees = self.registry.assignable()
        if not assignees:
            self.storage.add_event(
                task_id,
                "kernel",
                "error",
                {"stage": "planning", "error": "no assignable agents"},
            )
            self._transition(task_id, TaskStatus.FAILED.value)
            self._save_report(task_id)
            return task_id
        try:
            contract = self._boss().plan(request, task_id, assignees)
        except Exception as error:  # noqa: BLE001 - turn planning failures into task state
            self.storage.add_event(
                task_id,
                "kernel",
                "error",
                {"stage": "planning", "error": str(error)},
            )
            self._transition(task_id, TaskStatus.FAILED.value)
            self._save_report(task_id)
            return task_id

        self.storage.save_contract(task_id, contract.model_dump_json())
        self.storage.add_event(task_id, "boss", "contract", contract.model_dump())
        self._transition(task_id, TaskStatus.PLANNED.value)

        try:
            self.validate_assignee(contract.assignee)
        except ValueError as error:
            self.storage.add_event(
                task_id,
                "kernel",
                "error",
                {"stage": "assignee", "error": str(error)},
            )
            self._transition(task_id, TaskStatus.FAILED.value)
            self._save_report(task_id)
            return task_id

        if self.storage.total_cost(task_id) > contract.budget.max_cost_usd:
            self.storage.add_event(
                task_id,
                "kernel",
                "error",
                {"stage": "budget", "error": "planning cost exceeded contract budget"},
            )
            self._transition(task_id, TaskStatus.FAILED.value)
            self._save_report(task_id)
            return task_id

        if contract.approval_class == "user" and not auto_approve:
            self._transition(task_id, TaskStatus.AWAITING_APPROVAL.value)
            self.storage.add_event(
                task_id,
                "kernel",
                "approval_requested",
                {
                    "reason": "contract requires user approval",
                    "risk": contract.risk,
                    "objective": contract.objective,
                },
            )
            self._save_report(task_id)
            return task_id

        try:
            self._execute(task_id, worker_mode="llm")
        except Exception as error:  # noqa: BLE001
            self._fail_task(task_id, "execution", error)
        return task_id

    def approve(self, task_id: str) -> str:
        task = self.storage.get_task(task_id)
        if task is None:
            raise ValueError(f"task not found: {task_id}")
        if task["status"] != TaskStatus.AWAITING_APPROVAL.value:
            raise ValueError(f"task is not awaiting approval: {task['status']}")
        self.storage.add_event(
            task_id, "user", "approval_granted", {"approved": True}
        )
        try:
            self._execute(task_id, worker_mode="llm")
        except Exception as error:  # noqa: BLE001
            self._fail_task(task_id, "execution", error)
        return task_id

    def _execute(self, task_id: str, worker_mode: str = "llm") -> None:
        task = self.storage.get_task(task_id)
        if task is None or not task.get("contract_json"):
            raise ValueError("task has no contract")
        contract = TaskContract.model_validate_json(task["contract_json"])
        if worker_mode == "liar":
            self._execute_liar(task_id, contract)
            return
        policy_reason = self.policy.forbidden_reason(
            task["request"] + "\n" + contract.objective
        )
        if policy_reason:
            self.storage.add_event(
                task_id,
                "kernel",
                "policy_block",
                {"stage": "contract", "reason": policy_reason},
            )
            self._block_task(
                task_id,
                "policy_legal",
                policy_reason,
                "A compliant goal.",
                [],
            )
            return
        self._transition(task_id, TaskStatus.RUNNING.value)
        profile = self.validate_assignee(contract.assignee)
        attempts: list[dict] = []
        outcome, success, results = self._attempt_worker(
            task_id, contract, profile, None
        )
        attempts.append(
            self._attempt_record(1, profile, "initial", outcome, results, success)
        )
        self.storage.add_event(
            task_id, "kernel", "resilience_attempt", attempts[-1]
        )
        if success:
            self._succeed(task_id)
            return

        reason, detail, needed, goal_blocked = self._blocked_from(outcome, results)
        if goal_blocked:
            self._block_task(task_id, "policy_legal", detail, needed, attempts)
            return
        max_alternatives = contract.budget.max_attempts
        if max_alternatives <= 0:
            self._block_task(task_id, reason, detail, needed, attempts)
            return
        try:
            alternatives = self._plan_alternatives(
                task_id, contract, profile, reason, detail, needed, attempts
            )
        except Exception as error:  # noqa: BLE001
            self._block_task(
                task_id,
                "resilience_planner_failed",
                str(error),
                "",
                attempts,
            )
            return

        compliant = []
        for alternative in alternatives:
            allowed, why = self.policy.alternative_allowed(alternative)
            if allowed:
                compliant.append(alternative)
            else:
                self.storage.add_event(
                    task_id,
                    "kernel",
                    "alternative_rejected_policy",
                    {"approach": alternative.approach, "reason": why},
                )
        if not compliant:
            self._block_task(
                task_id,
                reason,
                detail + " (no compliant alternatives)",
                needed,
                attempts,
            )
            return
        self.storage.add_event(
            task_id,
            "kernel",
            "resilience_planned",
            {
                "alternatives": [
                    alternative.model_dump() for alternative in compliant
                ]
            },
        )

        final_reason, final_detail, final_needed = reason, detail, needed
        for index, alternative in enumerate(
            compliant[:max_alternatives], start=2
        ):
            if self._budget_exceeded(task_id, contract):
                final_reason = "budget_exceeded"
                final_detail = "task budget exhausted before another alternative"
                final_needed = "A larger budget or a smaller task."
                break
            agent_id = alternative.agent_id or profile.id
            try:
                alt_profile = self.validate_assignee(agent_id)
            except ValueError as error:
                self.storage.add_event(
                    task_id,
                    "kernel",
                    "alternative_skipped",
                    {"agent": agent_id, "reason": str(error)},
                )
                continue
            guidance = (
                f"Attempt {index}. The previous attempt was blocked or failed: "
                f"{final_reason}: {final_detail}. Use this alternative approach: "
                f"{alternative.approach}. "
                + (
                    "Steps: " + "; ".join(alternative.steps) + ". "
                    if alternative.steps
                    else ""
                )
                + "Do not repeat the failed approach. If still blocked, call "
                "report_blocked."
            )
            outcome, success, results = self._attempt_worker(
                task_id, contract, alt_profile, guidance
            )
            attempt = self._attempt_record(
                index, alt_profile, alternative.approach, outcome, results, success
            )
            attempts.append(attempt)
            self.storage.add_event(
                task_id, "kernel", "resilience_attempt", attempt
            )
            if success:
                self._succeed(task_id)
                return
            final_reason, final_detail, final_needed, goal_blocked = (
                self._blocked_from(outcome, results)
            )
            if goal_blocked:
                final_reason = "policy_legal"
                break
        self._block_task(
            task_id, final_reason, final_detail, final_needed, attempts
        )

    def _execute_liar(self, task_id: str, contract: TaskContract) -> None:
        self._transition(task_id, TaskStatus.RUNNING.value)
        toolset = ToolSet(self.settings, self.storage, task_id, "worker")
        outcome = LiarWorker(self.storage).run(contract, toolset, task_id)
        self._transition(task_id, TaskStatus.VERIFYING.value)
        results = self.verifier.run(task_id, contract)
        success = bool(results) and all(result.passed for result in results)
        self._transition(
            task_id,
            TaskStatus.SUCCEEDED.value if success else TaskStatus.FAILED.value,
        )
        self._save_report(task_id)

    def _make_worker(
        self,
        profile: AgentSpec,
        memory: list[MemoryEntry],
        attempt_context: str | None,
    ):
        return LLMWorker(
            profile, self.llm, memory=memory, attempt_context=attempt_context
        )

    def _attempt_worker(
        self,
        task_id: str,
        contract: TaskContract,
        profile: AgentSpec,
        attempt_context: str | None,
    ):
        toolset = ToolSet(
            self.settings,
            self.storage,
            task_id,
            "worker",
            allowed_tools=profile.tools,
        )
        worker = self._make_worker(
            profile, self.registry.load_memory(profile.id), attempt_context
        )
        outcome = worker.run(contract, toolset, task_id)
        if outcome.error:
            self.storage.add_event(
                task_id,
                "kernel",
                "error",
                {"stage": "worker", "error": outcome.error},
            )
        results = self.verifier.run(task_id, contract)
        success = bool(results) and all(result.passed for result in results)
        return outcome, success, results

    @staticmethod
    def _attempt_record(
        index: int,
        profile: AgentSpec,
        approach: str,
        outcome,
        results,
        success: bool,
    ) -> dict:
        return {
            "attempt": index,
            "agent": profile.id,
            "approach": approach,
            "success": success,
            "blocked_reason": outcome.blocked_reason,
            "detail": outcome.blocked_detail or outcome.error or "",
            "failed_checks": [
                result.name for result in results if not result.passed
            ],
        }

    @staticmethod
    def _blocked_from(outcome, results) -> tuple[str, str, str, bool]:
        if outcome.blocked_reason:
            return (
                outcome.blocked_reason,
                outcome.blocked_detail,
                outcome.blocked_needed,
                outcome.goal_blocked,
            )
        failed = [result.name for result in results if not result.passed]
        detail = outcome.error or (
            "failed checks: " + ", ".join(failed) if failed else "no checks passed"
        )
        return "verification_failed", detail, "", False

    def _plan_alternatives(
        self,
        task_id: str,
        contract: TaskContract,
        profile: AgentSpec,
        reason: str,
        detail: str,
        needed: str,
        attempts: list[dict],
    ):
        task = self.storage.get_task(task_id)
        request = task["request"] if task else contract.objective
        return self.llm.plan_alternatives(
            task_id,
            request,
            contract,
            profile,
            reason,
            detail,
            needed,
            attempts,
            self.registry.assignable(),
        )

    def _budget_exceeded(self, task_id: str, contract: TaskContract) -> bool:
        return (
            self.storage.total_cost(task_id) > contract.budget.max_cost_usd
            or self.storage.total_tokens(task_id) > contract.budget.max_tokens
        )

    def _succeed(self, task_id: str) -> None:
        self._transition(task_id, TaskStatus.VERIFYING.value)
        self._transition(task_id, TaskStatus.SUCCEEDED.value)
        if self.settings.qa_enabled:
            try:
                self.qa_review(task_id)
            except Exception as error:  # noqa: BLE001 - QA is advisory
                self.storage.add_event(
                    task_id,
                    "kernel",
                    "qa_error",
                    {"error": str(error)},
                )
        if self.settings.reflection_enabled:
            try:
                self.reflect_task(task_id)
            except Exception as error:  # noqa: BLE001 - reflection must not undo success
                self.storage.add_event(
                    task_id,
                    "kernel",
                    "reflection_error",
                    {"error": str(error)},
                )
        self._save_report(task_id)

    def _qa(self) -> AgentSpec:
        if self._qa_spec is None:
            spec = self.registry.get("qa")
            if spec is None:
                spec = load_agent_spec(self.settings.qa_spec_path)
            self._qa_spec = spec
        return self._qa_spec

    def qa_review(self, task_id: str):
        task = self.storage.get_task(task_id)
        if task is None or task["status"] != TaskStatus.SUCCEEDED.value:
            return None
        if not task.get("contract_json"):
            return None
        contract = TaskContract.model_validate_json(task["contract_json"])
        assignee = self.registry.get(contract.assignee)
        if assignee is None or "run_command" not in assignee.tools:
            return None
        artifacts = self.storage.get_artifacts(task_id)
        verifications = self.storage.get_verifications(task_id)
        events = self.storage.get_events(task_id)
        commands = [
            event["data"]
            for event in events
            if event["type"] == "command_output"
        ][-20:]
        messages = [
            event["data"]
            for event in events
            if event["type"] == "message"
        ][-5:]
        contents: list[dict] = []
        budget = 24_000
        for artifact in artifacts:
            if budget <= 0:
                break
            target = self.settings.workspace_dir / artifact["path"]
            if not target.is_file():
                continue
            try:
                text = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            text = text[: min(8_000, budget)]
            budget -= len(text)
            contents.append(
                {
                    "path": artifact["path"],
                    "sha256": artifact["sha256"],
                    "text": text,
                }
            )
        result = self.qa.review(
            task_id,
            contract,
            assignee,
            self._qa(),
            artifacts,
            verifications,
            commands,
            contents,
            messages,
        )
        self.storage.add_event(
            task_id, "qa", "qa_review", result.model_dump()
        )
        return result

    def _block_task(
        self,
        task_id: str,
        reason: str,
        detail: str,
        needed: str,
        attempts: list[dict],
    ) -> None:
        self.storage.add_event(
            task_id,
            "kernel",
            "resilience_exhausted",
            {
                "reason": reason,
                "detail": detail,
                "needed": needed,
                "attempts": attempts,
            },
        )
        self._transition(task_id, TaskStatus.BLOCKED.value)
        self._save_report(task_id)

    def reflect_task(self, task_id: str) -> dict:
        task = self.storage.get_task(task_id)
        if task is None or task["status"] != TaskStatus.SUCCEEDED.value:
            return {"skipped": "task is not succeeded"}
        if not task.get("contract_json"):
            return {"skipped": "no contract"}
        contract = TaskContract.model_validate_json(task["contract_json"])
        profile = self.registry.get(contract.assignee)
        if profile is None:
            return {"skipped": "assignee not found"}
        artifacts = self.storage.get_artifacts(task_id)
        verifications = self.storage.get_verifications(task_id)
        memory = self.registry.load_memory(profile.id)
        result = self.reflector.review(
            task_id, contract, profile, artifacts, verifications, memory
        )
        allowed = {task_id, f"task:{task_id}"}
        allowed.update(artifact["id"] for artifact in artifacts)
        allowed.update(check["name"] for check in verifications)

        facts: list[MemoryEntry] = []
        existing_text = {entry.text.casefold() for entry in memory}
        for fact in result.facts:
            if self._is_trivial_fact(fact.text):
                self.storage.add_event(
                    task_id,
                    "reflector",
                    "fact_rejected",
                    {"text": fact.text, "reason": "trivial task summary"},
                )
                continue
            evidence = [item for item in fact.evidence if item in allowed]
            if not evidence:
                self.storage.add_event(
                    task_id,
                    "reflector",
                    "fact_rejected",
                    {"text": fact.text, "reason": "no valid evidence"},
                )
                continue
            if fact.text.casefold() in existing_text:
                self.storage.add_event(
                    task_id,
                    "reflector",
                    "fact_duplicate",
                    {"text": fact.text},
                )
                continue
            existing_text.add(fact.text.casefold())
            facts.append(
                MemoryEntry(
                    id="m_" + uuid.uuid4().hex[:10],
                    ts=utc_now(),
                    kind=fact.kind,
                    text=fact.text,
                    evidence=evidence,
                    source_task=task_id,
                    created_by="reflection",
                )
            )
        if facts:
            self.registry.append_memory(profile.id, facts)

        version = profile.version
        safe_style_keys = {"tone", "length", "language", "report_format"}
        sensitive_style = {
            key: value
            for key, value in result.style.items()
            if key not in safe_style_keys
        }
        safe_style = {
            key: value
            for key, value in result.style.items()
            if key in safe_style_keys
        }
        if result.sop_notes or safe_style:
            updated = self.registry.update_profile(
                profile.id,
                sop_notes_append=result.sop_notes,
                style=safe_style or None,
                reason="verified task reflection",
                evidence=[task_id],
                actor="reflection",
            )
            version = updated.version

        pending_style = 0
        if sensitive_style:
            self.registry.add_change(
                profile.id,
                kind="style",
                proposed=json.dumps(sensitive_style, ensure_ascii=False),
                reason="reflection suggested a behavior/approval change",
                evidence=[task_id],
            )
            pending_style = 1

        for suggestion in result.suggestions:
            self.registry.add_change(
                profile.id,
                kind=suggestion.kind,
                proposed=suggestion.proposed,
                reason=suggestion.reason,
                evidence=[task_id],
            )

        summary = {
            "facts": len(facts),
            "sop_notes": len(result.sop_notes),
            "suggestions": len(result.suggestions) + pending_style,
            "version": version,
        }
        if any(summary[key] for key in ("facts", "sop_notes", "suggestions")):
            self.storage.add_event(
                task_id, "reflector", "mind_updated", summary
            )
        else:
            self.storage.add_event(
                task_id, "reflector", "reflection_no_changes", summary
            )
        return summary

    @staticmethod
    def _is_trivial_fact(text: str) -> bool:
        value = " ".join(text.casefold().split())
        if re.match(
            r"^(the\s+)?task\b.*\b(completed|passed)\b.*"
            r"\b(acceptance|tests|successfully)\b",
            value,
        ):
            return True
        return "task completed successfully" in value

    def _fail_task(self, task_id: str, stage: str, error: Exception) -> None:
        task = self.storage.get_task(task_id)
        if task and task["status"] not in (
            TaskStatus.FAILED.value,
            TaskStatus.SUCCEEDED.value,
        ):
            self.storage.add_event(
                task_id, "kernel", "error", {"stage": stage, "error": str(error)}
            )
            self._transition(task_id, TaskStatus.FAILED.value)
        self._save_report(task_id)

    def reverify(self, task_id: str) -> str:
        task = self.storage.get_task(task_id)
        if task is None or not task.get("contract_json"):
            raise ValueError("task has no contract to verify")
        contract = TaskContract.model_validate_json(task["contract_json"])
        self._transition(task_id, TaskStatus.VERIFYING.value)
        results = self.verifier.run(task_id, contract)
        success = bool(results) and all(result.passed for result in results)
        self._transition(
            task_id,
            TaskStatus.SUCCEEDED.value if success else TaskStatus.FAILED.value,
        )
        self._save_report(task_id)
        return task_id

    def liar_test(self) -> dict:
        contract = TaskContract(
            objective="Liar test: claim success without doing any work.",
            deliverables=[
                Deliverable(path="liar/never_created.txt", description="must never exist")
            ],
            acceptance_tests=[
                AcceptanceTest(type="file_exists", path="liar/never_created.txt")
            ],
            risk="low",
            approval_class="auto",
        )
        task_id = self.storage.create_task(
            "Liar test: worker claims success without creating the deliverable."
        )
        self.storage.add_event(
            task_id, "kernel", "task_created", {"request": "liar test"}
        )
        self.storage.save_contract(task_id, contract.model_dump_json())
        self.storage.add_event(task_id, "boss", "contract", contract.model_dump())
        self._transition(task_id, TaskStatus.PLANNED.value)
        self._execute(task_id, worker_mode="liar")
        task = self.storage.get_task(task_id)
        verifications = self.storage.get_verifications(task_id)
        rejected = task["status"] == TaskStatus.FAILED.value and any(
            not item["passed"] for item in verifications
        )
        return {
            "task_id": task_id,
            "status": task["status"],
            "liar_rejected": rejected,
            "verifications": verifications,
        }

    def _save_report(self, task_id: str) -> None:
        report = self.build_report(task_id)
        self.storage.save_report(task_id, report)
        self.storage.add_event(
            task_id, "kernel", "report_created", {"chars": len(report)}
        )

    def build_report(self, task_id: str) -> str:
        task = self.storage.get_task(task_id)
        if task is None:
            raise ValueError(f"task not found: {task_id}")
        contract = (
            TaskContract.model_validate_json(task["contract_json"])
            if task.get("contract_json")
            else None
        )
        artifacts = self.storage.get_artifacts(task_id)
        verifications = self.storage.get_verifications(task_id)
        costs = self.storage.get_costs(task_id)
        events = self.storage.get_events(task_id)
        last_error = next(
            (
                event["data"].get("error")
                for event in reversed(events)
                if event["type"] == "error" and event["data"].get("error")
            ),
            None,
        )
        mind_update = next(
            (
                event["data"]
                for event in reversed(events)
                if event["type"] == "mind_updated"
            ),
            None,
        )
        qa_review = next(
            (
                event["data"]
                for event in reversed(events)
                if event["type"] == "qa_review"
            ),
            None,
        )
        total_cost = self.storage.total_cost(task_id)
        total_tokens = self.storage.total_tokens(task_id)

        lines: list[str] = [
            f"# Task {task_id}",
            "",
            f"Status: **{task['status']}**",
            f"Created: {task['created_at']}",
            f"Request: {task['request']}",
            "",
        ]
        if last_error:
            lines.extend([f"Last error: {last_error}", ""])
        if contract:
            lines.extend(
                [
                    "## Contract",
                    f"Objective: {contract.objective}",
                    f"Assignee: {contract.assignee}",
                    f"Risk: {contract.risk} | Approval: {contract.approval_class}",
                    "Deliverables:",
                    *[
                        f"- {item.path} - {item.description or 'no description'}"
                        for item in contract.deliverables
                    ],
                    "Acceptance tests:",
                    *[
                        f"- {item.type} {item.path}"
                        + (f" (text={item.text!r})" if item.text else "")
                        for item in contract.acceptance_tests
                    ],
                    "",
                ]
            )
        else:
            lines.extend(["## Contract", "No valid contract was created.", ""])

        lines.append("## Verification")
        if verifications:
            for item in verifications:
                marker = "PASS" if item["passed"] else "FAIL"
                lines.append(f"- [{marker}] {item['name']}: {item['detail']}")
            runs = self.storage.verification_run_count(task_id)
            if runs > 1:
                lines.append(
                    f"- Showing the latest of {runs} verification runs; "
                    "older runs remain in the ledger."
                )
        else:
            lines.append("- No verification was run.")
        lines.append("")

        resilience_attempts = [
            event["data"]
            for event in events
            if event["type"] == "resilience_attempt"
        ]
        resilience_end = next(
            (
                event["data"]
                for event in reversed(events)
                if event["type"] == "resilience_exhausted"
            ),
            None,
        )
        policy_block = next(
            (
                event["data"]
                for event in reversed(events)
                if event["type"] == "policy_block"
            ),
            None,
        )
        if resilience_attempts or resilience_end or policy_block:
            lines.append("## Resilience")
            if policy_block:
                lines.append(
                    f"- Policy block ({policy_block.get('stage', 'goal')}): "
                    f"{policy_block.get('reason', 'disallowed')}"
                )
            for attempt in resilience_attempts:
                status = "succeeded" if attempt.get("success") else "failed"
                detail = attempt.get("detail") or "no detail"
                lines.append(
                    f"- Attempt {attempt.get('attempt')} "
                    f"({attempt.get('agent')}, {attempt.get('approach')}): "
                    f"{status} - {detail}"
                )
            if resilience_end:
                lines.append(
                    f"- Blocked: {resilience_end.get('reason')}. "
                    f"Need: {resilience_end.get('needed') or 'user input'}."
                )
            lines.append("")

        lines.append("## Artifacts")
        if artifacts:
            for artifact in artifacts:
                lines.append(
                    f"- {artifact['path']} - sha256={artifact['sha256']}, "
                    f"{artifact['bytes']} bytes (artifact {artifact['id']})"
                )
        else:
            lines.append("- No artifacts.")
        lines.append("")

        lines.append("## Cost")
        if costs:
            grouped: dict[tuple[str, str], dict] = {}
            for item in costs:
                key = (item["agent"], item["model"])
                entry = grouped.setdefault(
                    key, {"prompt": 0, "completion": 0, "cost": 0.0}
                )
                entry["prompt"] += item["prompt_tokens"]
                entry["completion"] += item["completion_tokens"]
                entry["cost"] += item["cost_usd"]
            for (agent, model), entry in grouped.items():
                lines.append(
                    f"- {agent}/{model}: {entry['prompt']} prompt + "
                    f"{entry['completion']} completion tokens, "
                    f"${entry['cost']:.6f}"
                )
        else:
            lines.append("- No model calls.")
        lines.append(
            f"- Total: {total_tokens} tokens, ${total_cost:.6f} (estimated)"
        )
        lines.append("")

        if mind_update:
            facts = mind_update.get("facts", 0)
            notes = mind_update.get("sop_notes", 0)
            suggestions = mind_update.get("suggestions", 0)
            lines.append("## Mind")
            lines.append(
                f"- {facts} fact{'s' if facts != 1 else ''}, "
                f"{notes} SOP note{'s' if notes != 1 else ''}, "
                f"{suggestions} pending suggestion"
                f"{'s' if suggestions != 1 else ''} "
                f"(profile v{mind_update.get('version', '?')})."
            )
            lines.append("")

        if qa_review:
            lines.append("## QA")
            lines.append(f"- Verdict: {qa_review.get('verdict', 'unknown')}")
            for issue in qa_review.get("issues", []):
                lines.append(f"- Issue: {issue}")
            for note in qa_review.get("notes", []):
                lines.append(f"- Note: {note}")
            lines.append("")

        failed = [item["name"] for item in verifications if not item["passed"]]
        lines.append("## Boss report (kernel-verified)")
        if task["status"] == TaskStatus.SUCCEEDED.value:
            lines.append(
                f"Verified. All {len(verifications)} checks in the latest run "
                "passed and every deliverable matches the ledger."
            )
            if qa_review:
                if qa_review.get("verdict") == "fail":
                    lines.append(
                        "QA flagged issues; review the QA section above."
                    )
                else:
                    lines.append("QA: pass.")
        elif task["status"] == TaskStatus.BLOCKED.value:
            reason = (
                resilience_end.get("reason") if resilience_end else "blocked"
            )
            needed = (
                resilience_end.get("needed") if resilience_end else ""
            )
            needed_text = (needed or "user input/approval").rstrip(".")
            lines.append(f"Blocked: {reason}. Need: {needed_text}.")
        elif task["status"] == TaskStatus.AWAITING_APPROVAL.value:
            lines.append("Waiting for user approval before work starts.")
        else:
            lines.append(
                "Not completed. Failed checks: "
                + (", ".join(failed) if failed else "none recorded")
                + (f" (last error: {last_error})" if last_error else "")
                + "."
            )
        return "\n".join(lines).strip() + "\n"

    def task_data(self, task_id: str) -> dict:
        task = self.storage.get_task(task_id)
        if task is None:
            raise ValueError(f"task not found: {task_id}")
        contract = (
            json.loads(task["contract_json"]) if task.get("contract_json") else None
        )
        return {
            "task": task,
            "contract": contract,
            "events": self.storage.get_events(task_id),
            "artifacts": self.storage.get_artifacts(task_id),
            "verifications": self.storage.get_verifications(task_id),
            "verification_runs": self.storage.verification_run_count(task_id),
            "costs": self.storage.get_costs(task_id),
            "total_cost_usd": self.storage.total_cost(task_id),
            "total_tokens": self.storage.total_tokens(task_id),
        }

    def close(self) -> None:
        self.storage.close()
