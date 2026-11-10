from __future__ import annotations

import argparse
import json
import sys

from .config import Settings
from .kernel import Kernel


def _short(value: object, limit: int = 500) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "..."


def _print_task_summary(task: dict) -> None:
    print(f"Task:    {task['id']}")
    print(f"Status:  {task['status']}")
    print(f"Created: {task['created_at']}")
    print(f"Request: {task['request']}")
    print("")


def cmd_run(args: argparse.Namespace) -> int:
    settings = Settings.load()
    if not settings.has_api_key:
        print("ERROR: DEEPSEEK_API_KEY is missing. Put it in the project .env file.")
        return 2
    kernel = Kernel(settings)
    try:
        task_id = kernel.plan_and_run(" ".join(args.request), args.auto_approve)
        task = kernel.storage.get_task(task_id)
        _print_task_summary(task)
        if task["status"] == "awaiting_approval":
            print(f"Approval needed. Run: zuri approve {task_id}")
        else:
            print(kernel.build_report(task_id))
        return 0 if task["status"] in ("succeeded", "awaiting_approval") else 1
    finally:
        kernel.close()


def cmd_show(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        data = kernel.task_data(args.task_id)
        if args.json:
            print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
            return 0
        _print_task_summary(data["task"])
        contract = data["contract"]
        if contract:
            print("Contract:")
            print(f"  Objective: {contract['objective']}")
            print(f"  Assignee: {contract['assignee']}")
            print(f"  Risk: {contract['risk']} | Approval: {contract['approval_class']}")
            print("  Deliverables:")
            for item in contract["deliverables"]:
                print(f"    - {item['path']}")
            print("  Acceptance tests:")
            for item in contract["acceptance_tests"]:
                text = f" text={item['text']!r}" if item.get("text") else ""
                print(f"    - {item['type']} {item['path']}{text}")
            print("")
        print("Timeline:")
        for event in data["events"]:
            print(
                f"  [{event['event_id']}] {event['ts']} "
                f"{event['agent']}/{event['type']} {_short(event['data'])}"
            )
        print("")
        print("Artifacts:")
        for artifact in data["artifacts"]:
            print(
                f"  - {artifact['path']} sha256={artifact['sha256']} "
                f"{artifact['bytes']} bytes (artifact {artifact['id']})"
            )
        if not data["artifacts"]:
            print("  (none)")
        print("")
        print("Verifications (latest run):")
        for item in data["verifications"]:
            marker = "PASS" if item["passed"] else "FAIL"
            print(f"  [{marker}] {item['name']}: {item['detail']}")
        if not data["verifications"]:
            print("  (none)")
        if data.get("verification_runs", 0) > 1:
            print(
                f"  (showing latest of {data['verification_runs']} runs; "
                "older runs remain in the ledger)"
            )
        print("")
        print("Cost:")
        for item in data["costs"]:
            print(
                f"  - {item['agent']}/{item['model']}: "
                f"{item['prompt_tokens']}+{item['completion_tokens']} tokens "
                f"${item['cost_usd']:.6f}"
            )
        print(
            f"  Total: {data['total_tokens']} tokens, "
            f"${data['total_cost_usd']:.6f} (estimated)"
        )
        if data["task"].get("report"):
            print("")
            print(data["task"]["report"])
        return 0
    finally:
        kernel.close()


def cmd_verify(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        task = kernel.storage.get_task(args.task_id)
        if task is None:
            print(f"ERROR: task not found: {args.task_id}")
            return 2
        if task["status"] == "blocked":
            print(
                f"Task is blocked; nothing to verify. "
                f"Use: zuri explain {args.task_id}"
            )
            return 1
        kernel.reverify(args.task_id)
        task = kernel.storage.get_task(args.task_id)
        _print_task_summary(task)
        for item in kernel.storage.get_verifications(args.task_id):
            marker = "PASS" if item["passed"] else "FAIL"
            print(f"[{marker}] {item['name']}: {item['detail']}")
        return 0 if task["status"] == "succeeded" else 1
    finally:
        kernel.close()


def cmd_report(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        task = kernel.storage.get_task(args.task_id)
        if task is None:
            print(f"ERROR: task not found: {args.task_id}")
            return 2
        print(task.get("report") or kernel.build_report(args.task_id))
        return 0
    finally:
        kernel.close()


def cmd_approve(args: argparse.Namespace) -> int:
    settings = Settings.load()
    if not settings.has_api_key:
        print("ERROR: DEEPSEEK_API_KEY is missing. Put it in the project .env file.")
        return 2
    kernel = Kernel(settings)
    try:
        kernel.approve(args.task_id)
        task = kernel.storage.get_task(args.task_id)
        _print_task_summary(task)
        print(kernel.build_report(args.task_id))
        return 0 if task["status"] == "succeeded" else 1
    finally:
        kernel.close()


def cmd_tasks(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        for task in kernel.storage.list_tasks(args.limit):
            print(
                f"{task['id']}  {task['created_at']}  {task['status']:<18} "
                f"{task['request'][:80]}"
            )
        return 0
    finally:
        kernel.close()


def cmd_last(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        tasks = kernel.storage.list_tasks(1)
        if not tasks:
            print('No tasks yet. Run: zuri run "Create notes/hello.md with hello"')
            return 0
        task = tasks[0]
        data = kernel.task_data(task["id"])
        contract = data["contract"]
        checks = data["verifications"]
        passed = sum(1 for item in checks if item["passed"])
        error = next(
            (
                event["data"].get("error")
                for event in reversed(data["events"])
                if event["type"] == "error" and event["data"].get("error")
            ),
            None,
        )
        resilience_end = next(
            (
                event["data"]
                for event in reversed(data["events"])
                if event["type"] == "resilience_exhausted"
            ),
            None,
        )
        attempts = [
            event["data"]
            for event in data["events"]
            if event["type"] == "resilience_attempt"
        ]
        print(f"Latest task: {task['id']}")
        print(f"Status:      {task['status']}")
        print(f"Assignee:    {contract['assignee'] if contract else '-'}")
        print(f"Request:     {task['request']}")
        if error:
            print(f"Reason:      {error}")
        if resilience_end:
            print(
                f"Reason:      {resilience_end.get('reason')} "
                f"(need: {resilience_end.get('needed') or 'user input'})"
            )
        if attempts:
            print(f"Attempts:    {len(attempts)}")
        if checks:
            print(f"Checks:      {passed}/{len(checks)} passed (latest run)")
            for item in checks:
                if not item["passed"]:
                    print(f"  FAIL {item['name']}: {item['detail']}")
        else:
            print("Checks:      none")
        if data["artifacts"]:
            print("Artifacts:")
            for artifact in data["artifacts"]:
                print(
                    f"  - {artifact['path']} "
                    f"sha256={artifact['sha256'][:16]}... {artifact['bytes']} bytes"
                )
        print(
            f"Cost:        {data['total_tokens']} tokens, "
            f"${data['total_cost_usd']:.6f} (estimated)"
        )
        print("")
        print(f"Full details: zuri show {task['id']}")
        if task["status"] == "blocked":
            print(f"Explain:      zuri explain {task['id']}")
        else:
            print("Re-check:     zuri verify-last")
        return 0
    finally:
        kernel.close()


def cmd_explain(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        if args.task_id:
            task = kernel.storage.get_task(args.task_id)
        else:
            tasks = kernel.storage.list_tasks(1)
            task = kernel.storage.get_task(tasks[0]["id"]) if tasks else None
        if task is None:
            print("No task to explain yet.")
            return 0
        data = kernel.task_data(task["id"])
        contract = data["contract"]
        checks = data["verifications"]
        error = next(
            (
                event["data"].get("error")
                for event in reversed(data["events"])
                if event["type"] == "error" and event["data"].get("error")
            ),
            None,
        )
        attempts = [
            event["data"]
            for event in data["events"]
            if event["type"] == "resilience_attempt"
        ]
        resilience_end = next(
            (
                event["data"]
                for event in reversed(data["events"])
                if event["type"] == "resilience_exhausted"
            ),
            None,
        )
        policy_block = next(
            (
                event["data"]
                for event in reversed(data["events"])
                if event["type"] == "policy_block"
            ),
            None,
        )

        print(f"Task: {task['id']}")
        print(f"You asked: {task['request']}")
        print("")
        if contract:
            spec = kernel.registry.get(contract["assignee"])
            who = contract["assignee"]
            if spec:
                who += f" ({spec.name})"
            print(f"The Boss assigned it to: {who}")
            print("")
            print("The Boss planned:")
            print(f"  Goal: {contract['objective']}")
            print("  Deliverable(s):")
            for item in contract["deliverables"]:
                print(f"    - {item['path']}")
            print("  Checks:")
            for item in contract["acceptance_tests"]:
                if item["type"] == "file_contains":
                    detail = f"contains {item.get('text')!r}"
                elif item["type"] == "file_not_empty":
                    detail = "is not empty"
                else:
                    detail = "exists"
                print(f"    - {item['path']} {detail}")
        elif policy_block:
            print("The request was blocked by policy before planning.")
            print(f"Reason: {policy_block.get('reason')}")
        else:
            print("The Boss could not create a valid plan.")
        print("")
        print("What happened:")
        if policy_block and not contract:
            print("  - No worker ran; the request was blocked before planning.")
        else:
            tool_events = [
                event for event in data["events"] if event["type"] == "tool_call"
            ]
            if tool_events:
                for event in tool_events:
                    payload = event["data"]
                    arguments = payload.get("arguments", {})
                    target = arguments.get("path") or arguments.get("name") or ""
                    print(
                        f"  - The worker used {payload.get('name')} on {target or 'the workspace'}."
                    )
            else:
                print("  - The worker did not use any tools.")
            if data["artifacts"]:
                print("  - Files recorded as evidence:")
                for artifact in data["artifacts"]:
                    print(
                        f"      {artifact['path']} "
                        f"({artifact['bytes']} bytes, sha256 {artifact['sha256'][:12]}...)"
                    )
            else:
                print("  - No files were recorded.")
            if checks:
                passed = sum(1 for item in checks if item["passed"])
                print(f"  - The independent verifier ran {len(checks)} checks: "
                      f"{passed} passed, {len(checks) - passed} failed.")
                for item in checks:
                    if not item["passed"]:
                        print(f"      FAIL: {item['name']} - {item['detail']}")
            else:
                print("  - No verification ran.")
        if error:
            print(f"  - Error: {error}")
        if policy_block:
            print(f"  - Policy block: {policy_block.get('reason')}")
        if attempts:
            print("  - Attempts:")
            for attempt in attempts:
                status = "succeeded" if attempt.get("success") else "failed"
                detail = attempt.get("detail") or "no detail"
                print(
                    f"      #{attempt.get('attempt')} {attempt.get('agent')} "
                    f"[{attempt.get('approach')}]: {status} - {detail}"
                )
        if resilience_end:
            needed = (
                resilience_end.get("needed") or "user input"
            ).rstrip(".")
            print(
                f"  - Blocked because: {resilience_end.get('reason')}. "
                f"Need: {needed}."
            )
        mind_update = next(
            (
                event["data"]
                for event in reversed(data["events"])
                if event["type"] == "mind_updated"
            ),
            None,
        )
        qa_review = next(
            (
                event["data"]
                for event in reversed(data["events"])
                if event["type"] == "qa_review"
            ),
            None,
        )
        if mind_update:
            facts = mind_update.get("facts", 0)
            notes = mind_update.get("sop_notes", 0)
            suggestions = mind_update.get("suggestions", 0)
            print(
                f"  - The agent's mind was updated: "
                f"{facts} fact{'s' if facts != 1 else ''}, "
                f"{notes} SOP note{'s' if notes != 1 else ''}, "
                f"{suggestions} pending suggestion"
                f"{'s' if suggestions != 1 else ''} "
                f"(profile v{mind_update.get('version', '?')})."
            )
        if qa_review:
            print(
                f"  - QA review: {qa_review.get('verdict', 'unknown')}."
            )
            for issue in qa_review.get("issues", []):
                print(f"      QA issue: {issue}")
        print("")
        if task["status"] == "succeeded":
            print("Result: VERIFIED.")
            print(
                "This means the file exists, it matches the fingerprint recorded "
                "when it was written, and every acceptance check passed."
            )
            if len(attempts) > 1:
                print(f"It succeeded after {len(attempts)} attempts.")
        elif task["status"] == "blocked":
            print("Result: BLOCKED.")
            if resilience_end:
                needed = (
                    resilience_end.get("needed") or "user input"
                ).rstrip(".")
                print(
                    f"Reason: {resilience_end.get('reason')}. Need: {needed}."
                )
            if attempts:
                print(
                    "The system tried the safe alternatives above and stopped."
                )
            else:
                print(
                    "No work ran because the request is disallowed or blocked "
                    "before execution."
                )
            print("Nothing was silently marked successful.")
        elif task["status"] == "awaiting_approval":
            print("Result: waiting for your approval before any work starts.")
        else:
            print("Result: NOT VERIFIED.")
            print(
                "This means the system did not accept the work. Read the failed "
                "checks or error above; nothing was silently marked successful."
            )
        print("")
        print(
            f"Cost: {data['total_tokens']} tokens, "
            f"${data['total_cost_usd']:.6f} (estimated)."
        )
        print(
            "You can ask me to explain a task, re-check it, or show the raw "
            "timeline. You do not need to copy command ids."
        )
        return 0
    finally:
        kernel.close()


def cmd_verify_last(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        tasks = kernel.storage.list_tasks(1)
        if not tasks:
            print("No tasks to verify.")
            return 0
        task_id = tasks[0]["id"]
        task = kernel.storage.get_task(task_id)
        if task and task["status"] == "blocked":
            print(
                f"Task is blocked; nothing to verify. Use: zuri explain {task_id}"
            )
            return 1
        kernel.reverify(task_id)
        task = kernel.storage.get_task(task_id)
        print(f"Task:   {task_id}")
        print(f"Status: {task['status']}")
        for item in kernel.storage.get_verifications(task_id):
            marker = "PASS" if item["passed"] else "FAIL"
            print(f"[{marker}] {item['name']}: {item['detail']}")
        return 0 if task["status"] == "succeeded" else 1
    finally:
        kernel.close()


def cmd_guide(args: argparse.Namespace) -> int:
    print("Zuri - simple test guide")
    print("")
    print("1. See the team:        zuri.cmd agent list")
    print("2. Run a safe task:     zuri.cmd run \"Create notes/hello.md with the text 'hello'\"")
    print("3. See the last result: zuri.cmd last")
    print("4. Re-check it:         zuri.cmd verify-last")
    print("5. Explain it simply:   zuri.cmd explain")
    print("6. Full raw timeline:   zuri.cmd show <task-id>")
    print("")
    print("Web dashboard:          zuri.cmd serve   (then open http://127.0.0.1:8765)")
    print("")
    print("Create an agent:")
    print("  zuri.cmd agent create \"Create an agent named Notes that writes markdown.\"")
    print("  zuri.cmd agent approve <proposal-id>")
    print("Use it:")
    print("  zuri.cmd run \"Use the notes agent to create work/notes.md with a checklist.\"")
    print("")
    print("Delete an agent (two confirmations):")
    print("  zuri.cmd agent delete notes")
    print("  step 1: type exactly  notes")
    print("  step 2: type exactly  DELETE notes")
    print("  anything else aborts and nothing is deleted.")
    print("  restore: zuri.cmd agent restore notes")
    return 0


def cmd_ping(args: argparse.Namespace) -> int:
    settings = Settings.load()
    if not settings.has_api_key:
        print("ERROR: DEEPSEEK_API_KEY is missing. Put it in the project .env file.")
        return 2
    kernel = Kernel(settings)
    try:
        reply = kernel.llm.ping()
        print("API OK")
        print(f"Model: {settings.worker_model}")
        print(f"Reply: {reply[:120]}")
        return 0
    except Exception as error:  # noqa: BLE001
        print(f"API FAILED: {error}")
        return 1
    finally:
        kernel.close()


def cmd_agent_mind(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        spec = kernel.registry.get(args.agent_id)
        if spec is None:
            print(f"ERROR: agent not found: {args.agent_id}")
            return 2
        print(f"Agent: {spec.id} ({spec.name})")
        print(f"Version: {spec.version} | Source: {spec.source}")
        print(
            "Style: "
            + ", ".join(f"{key}={value}" for key, value in spec.effective_style().items())
        )
        print("SOP notes:")
        if spec.sop_notes:
            for note in spec.sop_notes:
                print(f"  - {note}")
        else:
            print("  (none)")
        memory = kernel.registry.load_memory(spec.id)
        print("Memory (active):")
        if memory:
            for entry in memory:
                print(
                    f"  [{entry.id}] {entry.kind}: {entry.text} "
                    f"(evidence: {', '.join(entry.evidence) or 'none'})"
                )
        else:
            print("  (empty)")
        print("Profile versions: " + ", ".join(str(v) for v in kernel.registry.list_versions(spec.id)))
        changes = kernel.registry.list_changes(spec.id, "pending")
        print("Pending changes:")
        if changes:
            for change in changes:
                print(
                    f"  [{change.change_id}] {change.kind}: {change.proposed} "
                    f"- {change.reason or 'no reason'}"
                )
        else:
            print("  (none)")
        history = kernel.registry.history(spec.id, 8)
        if history:
            print("Recent history:")
            for event in history:
                print(f"  {event['ts']} {event['action']}")
        return 0
    finally:
        kernel.close()


def cmd_agent_remember(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        text = " ".join(args.text)
        entry = kernel.registry.remember_user_fact(args.agent_id, text)
        print(f"Remembered for {args.agent_id}: {entry.text}")
        print(f"Memory id: {entry.id}")
        return 0
    finally:
        kernel.close()


def cmd_agent_forget(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        entry = kernel.registry.forget_memory(args.agent_id, args.memory_id)
        print(f"Forgot memory {entry.id} for {args.agent_id}.")
        return 0
    finally:
        kernel.close()


def cmd_agent_style(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        style: dict = {}
        for item in args.assignments:
            if "=" not in item:
                print(f"ERROR: style value must be key=value: {item}")
                return 2
            key, value = item.split("=", 1)
            style[key.strip()] = value.strip()
        spec = kernel.registry.update_profile(
            args.agent_id,
            style=style,
            reason="user style update",
            actor="user",
        )
        print(f"Style for {spec.id}:")
        for key, value in spec.effective_style().items():
            print(f"  {key}={value}")
        return 0
    finally:
        kernel.close()


def cmd_agent_rollback(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        raw = args.version.lower().lstrip("v")
        version = int(raw)
        spec = kernel.registry.rollback_profile(args.agent_id, version)
        print(
            f"Agent {spec.id} restored from v{version:04d}; "
            f"new version is v{spec.version:04d}."
        )
        return 0
    finally:
        kernel.close()


def cmd_agent_changes(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        status = None if args.all else "pending"
        changes = kernel.registry.list_changes(args.agent_id, status)
        if not changes:
            print("No pending changes.")
            return 0
        for change in changes:
            print(
                f"{change.change_id}  {change.kind:<13} {change.status:<9} "
                f"{change.proposed} - {change.reason or 'no reason'}"
            )
        return 0
    finally:
        kernel.close()


def cmd_agent_approve_change(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        change = kernel.registry.approve_change(
            args.agent_id, args.change_id
        )
        print(f"Approved {change.change_id} ({change.kind}) for {args.agent_id}.")
        return 0
    finally:
        kernel.close()


def cmd_agent_reject_change(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        change = kernel.registry.reject_change(
            args.agent_id, args.change_id
        )
        print(f"Rejected {change.change_id} ({change.kind}) for {args.agent_id}.")
        return 0
    finally:
        kernel.close()


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = Settings.load()
    if not settings.has_api_key:
        print("WARNING: DEEPSEEK_API_KEY is missing; tasks will fail.")
    print(f"Zuri dashboard: http://127.0.0.1:{args.port}")
    print("Local only. Press Ctrl+C to stop.")
    uvicorn.run(
        "app.web:app",
        host="127.0.0.1",
        port=args.port,
        log_level="info",
    )
    return 0


def cmd_approvals(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        tasks = kernel.storage.list_tasks_by_status("awaiting_approval", 50)
        if not tasks:
            print("No approvals waiting.")
            return 0
        for task in tasks:
            print(f"{task['id']}  {task['created_at']}  {task['request']}")
            print(f"  approve: zuri approve {task['id']}")
        return 0
    finally:
        kernel.close()


def cmd_costs(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        data = kernel.storage.cost_summary()
        print(
            f"Total: ${data['total_cost_usd']:.6f} | "
            f"{data['total_tokens']} tokens"
        )
        print(f"This month: ${data['monthly_cost_usd']:.6f}")
        print("By agent:")
        for item in data["by_agent"]:
            print(
                f"  {item['agent']}/{item['model']}: "
                f"{item['calls']} calls, ${item['cost_usd']:.6f}"
            )
        print("Recent tasks:")
        for item in data["recent_tasks"][:10]:
            print(
                f"  {item['task_id']}  {item['tokens']} tokens  "
                f"${item['cost_usd']:.6f}"
            )
        return 0
    finally:
        kernel.close()


def cmd_liar(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        result = kernel.liar_test()
        print(f"Task: {result['task_id']}")
        print(f"Status: {result['status']}")
        for item in result["verifications"]:
            marker = "PASS" if item["passed"] else "FAIL"
            print(f"[{marker}] {item['name']}: {item['detail']}")
        if result["liar_rejected"]:
            print("LIAR TEST PASSED: the fake success claim was rejected.")
            return 0
        print("LIAR TEST FAILED: the system accepted a fake success claim.")
        return 1
    finally:
        kernel.close()


def cmd_doctor(args: argparse.Namespace) -> int:
    settings = Settings.load()
    settings.ensure()
    kernel = Kernel(settings)
    try:
        print(f"Root:      {settings.root}")
        print(f"Data:      {settings.data_dir}")
        print(f"Workspace: {settings.workspace_dir}")
        print(f"DB:        {settings.db_path} ({'present' if settings.db_path.exists() else 'not created yet'})")
        print(f"API key:   {'SET' if settings.has_api_key else 'NOT SET'}")
        print(f"Boss model:   {settings.boss_model}")
        print(f"Worker model: {settings.worker_model}")
        print(f"Boss spec:   {settings.boss_spec_path} ({'ok' if settings.boss_spec_path.exists() else 'MISSING'})")
        print(f"Worker spec: {settings.worker_spec_path} ({'ok' if settings.worker_spec_path.exists() else 'MISSING'})")
        print(f"HR spec:     {settings.hr_spec_path} ({'ok' if settings.hr_spec_path.exists() else 'MISSING'})")
        print("Agents:")
        for spec in kernel.registry.list_agents():
            print(
                f"  - {spec.id:<14} {spec.source:<7} {spec.model:<16} "
                f"tools={','.join(spec.tools) or '-'}"
            )
        return 0
    finally:
        kernel.close()


def cmd_agent_list(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        for spec in kernel.registry.list_agents():
            print(
                f"{spec.id:<16} {('enabled' if spec.enabled else 'disabled'):<9} "
                f"{spec.model or '-':<16} tools={','.join(spec.tools) or '-':<28} "
                f"{spec.name} - {spec.description}"
            )
        return 0
    finally:
        kernel.close()


def cmd_agent_show(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        spec = kernel.registry.get(args.agent_id)
        if spec is None:
            print(f"ERROR: agent not found: {args.agent_id}")
            return 2
        print(json.dumps(spec.model_dump(), indent=2, ensure_ascii=False))
        folder = kernel.registry.agents_dir / spec.id
        versions = sorted((folder / "profiles").glob("v*.json"))
        memory_file = folder / "memory.jsonl"
        if memory_file.exists():
            with open(memory_file, encoding="utf-8") as handle:
                memory_lines = sum(1 for _ in handle)
        else:
            memory_lines = 0
        print(f"Versions: {', '.join(path.stem for path in versions) or '(none)'}")
        print(f"Memory entries: {memory_lines}")
        history = kernel.registry.history(spec.id, 20)
        if history:
            print("History:")
            for event in history:
                print(
                    f"  [{event['event_id']}] {event['ts']} {event['action']} "
                    f"{json.dumps(event['data'], ensure_ascii=False)[:300]}"
                )
        return 0
    finally:
        kernel.close()


def cmd_agent_create(args: argparse.Namespace) -> int:
    settings = Settings.load()
    if not settings.has_api_key:
        print("ERROR: DEEPSEEK_API_KEY is missing. Put it in the project .env file.")
        return 2
    description = " ".join(args.description) if args.description else ""
    if not description.strip():
        try:
            description = input(
                "Describe the agent (or press Enter for a generalist): "
            ).strip()
        except EOFError:
            description = ""
    if not description.strip():
        description = "Create a generalist file worker with a clear starting charter."
    kernel = Kernel(settings)
    try:
        proposal = kernel.propose_agent(description)
        print(f"Proposal: {proposal.proposal_id}")
        print(json.dumps(proposal.spec.model_dump(), indent=2, ensure_ascii=False))
        print("")
        print(f"Approve: zuri agent approve {proposal.proposal_id}")
        print(f"Reject:  zuri agent reject {proposal.proposal_id}")
        return 0
    finally:
        kernel.close()


def cmd_agent_proposals(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        status = None if args.all else "pending"
        proposals = kernel.registry.list_proposals(status)
        if not proposals:
            print("No proposals.")
            return 0
        for proposal in proposals:
            print(
                f"{proposal.proposal_id}  {proposal.status:<9}  "
                f"{proposal.spec.id:<16}  {proposal.spec.name} - "
                f"{proposal.spec.description}"
            )
        return 0
    finally:
        kernel.close()


def cmd_agent_approve(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        proposal = kernel.registry.approve_proposal(args.proposal_id)
        print(f"Agent '{proposal.spec.id}' created from {proposal.proposal_id}.")
        print("Use it with: zuri run \"Use the <id> agent to ...\"")
        return 0
    finally:
        kernel.close()


def cmd_agent_reject(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        proposal = kernel.registry.reject_proposal(args.proposal_id)
        print(f"Proposal {proposal.proposal_id} rejected.")
        return 0
    finally:
        kernel.close()


def cmd_agent_delete(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        spec = kernel.registry.get(args.agent_id)
        if spec is None:
            print(f"ERROR: agent not found: {args.agent_id}")
            return 2
        print(f"Agent: {spec.id}")
        print(f"Name:  {spec.name}")
        print(f"Model: {spec.model}")
        print(f"Tools: {', '.join(spec.tools) or '-'}")
        print("")
        print("Two confirmations are required. Type anything else to abort.")
        try:
            confirm1 = input(
                f"Step 1 of 2 - type exactly the agent id ({spec.id}): "
            ).strip()
            confirm2 = input(
                f"Step 2 of 2 - type exactly DELETE {spec.id}: "
            ).strip()
        except EOFError:
            print("ABORTED - nothing was deleted.")
            return 2
        try:
            trash = kernel.registry.delete_agent(spec.id, confirm1, confirm2)
        except ValueError as error:
            print(f"ABORTED - nothing was deleted. Reason: {error}")
            return 2
        print(f"Agent '{spec.id}' soft-deleted.")
        print(f"Snapshot: {trash}")
        print(f"Restore:  zuri agent restore {spec.id}")
        return 0
    finally:
        kernel.close()


def cmd_agent_restore(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        if kernel.registry.get(args.agent_id) is not None:
            print(
                f"Agent '{args.agent_id}' is still active; nothing to restore. "
                "Delete it first with two confirmations."
            )
            return 0
        path = kernel.registry.restore_agent(args.agent_id)
        print(f"Agent '{args.agent_id}' restored to {path}.")
        return 0
    finally:
        kernel.close()


def cmd_agent_history(args: argparse.Namespace) -> int:
    settings = Settings.load()
    kernel = Kernel(settings)
    try:
        events = kernel.registry.history(args.agent_id, 100)
        if not events:
            print("No agent events.")
            return 0
        for event in events:
            print(
                f"[{event['event_id']}] {event['ts']} {event['action']} "
                f"{json.dumps(event['data'], ensure_ascii=False)}"
            )
        return 0
    finally:
        kernel.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zuri", description="Local-first AI company with evidence-first verification"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run one request through Boss and Worker")
    run.add_argument("request", nargs="+", help="What you want done")
    run.add_argument(
        "--auto-approve",
        action="store_true",
        help="Skip the approval gate even if the Boss asks for it",
    )
    run.set_defaults(func=cmd_run)

    show = sub.add_parser("show", help="Show a task timeline and evidence")
    show.add_argument("task_id")
    show.add_argument("--json", action="store_true", help="Print raw JSON")
    show.set_defaults(func=cmd_show)

    verify = sub.add_parser("verify", help="Re-run the acceptance checks")
    verify.add_argument("task_id")
    verify.set_defaults(func=cmd_verify)

    report = sub.add_parser("report", help="Print the kernel-verified report")
    report.add_argument("task_id")
    report.set_defaults(func=cmd_report)

    approve = sub.add_parser("approve", help="Approve a waiting task and run it")
    approve.add_argument("task_id")
    approve.set_defaults(func=cmd_approve)

    tasks = sub.add_parser("tasks", help="List recent tasks")
    tasks.add_argument("--limit", type=int, default=20)
    tasks.set_defaults(func=cmd_tasks)

    last = sub.add_parser("last", help="Show a short summary of the latest task")
    last.set_defaults(func=cmd_last)

    explain = sub.add_parser(
        "explain", help="Explain a task in plain language"
    )
    explain.add_argument("task_id", nargs="?")
    explain.set_defaults(func=cmd_explain)

    verify_last = sub.add_parser("verify-last", help="Re-run checks on the latest task")
    verify_last.set_defaults(func=cmd_verify_last)

    guide = sub.add_parser("guide", help="Show the simple test steps")
    guide.set_defaults(func=cmd_guide)

    ping = sub.add_parser("ping", help="Test the DeepSeek API connection")
    ping.set_defaults(func=cmd_ping)

    serve = sub.add_parser("serve", help="Start the local web dashboard")
    serve.add_argument("--port", type=int, default=8765)
    serve.set_defaults(func=cmd_serve)

    approvals = sub.add_parser("approvals", help="List tasks waiting for approval")
    approvals.set_defaults(func=cmd_approvals)

    costs = sub.add_parser("costs", help="Show cost ledger")
    costs.set_defaults(func=cmd_costs)

    agent = sub.add_parser("agent", help="Manage specialist agents")
    agent_sub = agent.add_subparsers(dest="agent_command", required=True)

    agent_list = agent_sub.add_parser("list", help="List agents")
    agent_list.set_defaults(func=cmd_agent_list)

    agent_show = agent_sub.add_parser("show", help="Show one agent")
    agent_show.add_argument("agent_id")
    agent_show.set_defaults(func=cmd_agent_show)

    agent_create = agent_sub.add_parser(
        "create", help="Boss/HR drafts a new agent proposal"
    )
    agent_create.add_argument("description", nargs="*")
    agent_create.set_defaults(func=cmd_agent_create)

    agent_proposals = agent_sub.add_parser("proposals", help="List proposals")
    agent_proposals.add_argument("--all", action="store_true")
    agent_proposals.set_defaults(func=cmd_agent_proposals)

    agent_approve = agent_sub.add_parser("approve", help="Approve a proposal")
    agent_approve.add_argument("proposal_id")
    agent_approve.set_defaults(func=cmd_agent_approve)

    agent_reject = agent_sub.add_parser("reject", help="Reject a proposal")
    agent_reject.add_argument("proposal_id")
    agent_reject.set_defaults(func=cmd_agent_reject)

    agent_delete = agent_sub.add_parser(
        "delete", help="Soft-delete an agent (two confirmations)"
    )
    agent_delete.add_argument("agent_id")
    agent_delete.set_defaults(func=cmd_agent_delete)

    agent_restore = agent_sub.add_parser("restore", help="Restore a soft-deleted agent")
    agent_restore.add_argument("agent_id")
    agent_restore.set_defaults(func=cmd_agent_restore)

    agent_history = agent_sub.add_parser("history", help="Show agent audit events")
    agent_history.add_argument("agent_id")
    agent_history.set_defaults(func=cmd_agent_history)

    agent_mind = agent_sub.add_parser("mind", help="Show an agent's mind")
    agent_mind.add_argument("agent_id")
    agent_mind.set_defaults(func=cmd_agent_mind)

    agent_remember = agent_sub.add_parser("remember", help="Add a user fact")
    agent_remember.add_argument("agent_id")
    agent_remember.add_argument("text", nargs="+")
    agent_remember.set_defaults(func=cmd_agent_remember)

    agent_forget = agent_sub.add_parser("forget", help="Forget a memory entry")
    agent_forget.add_argument("agent_id")
    agent_forget.add_argument("memory_id")
    agent_forget.set_defaults(func=cmd_agent_forget)

    agent_style = agent_sub.add_parser("style", help="Update agent style")
    agent_style.add_argument("agent_id")
    agent_style.add_argument("assignments", nargs="+")
    agent_style.set_defaults(func=cmd_agent_style)

    agent_rollback = agent_sub.add_parser(
        "rollback", help="Restore an older profile version"
    )
    agent_rollback.add_argument("agent_id")
    agent_rollback.add_argument("version")
    agent_rollback.set_defaults(func=cmd_agent_rollback)

    agent_changes = agent_sub.add_parser(
        "changes", help="Show pending profile changes"
    )
    agent_changes.add_argument("agent_id")
    agent_changes.add_argument("--all", action="store_true")
    agent_changes.set_defaults(func=cmd_agent_changes)

    agent_approve_change = agent_sub.add_parser(
        "approve-change", help="Approve a pending profile change"
    )
    agent_approve_change.add_argument("agent_id")
    agent_approve_change.add_argument("change_id")
    agent_approve_change.set_defaults(func=cmd_agent_approve_change)

    agent_reject_change = agent_sub.add_parser(
        "reject-change", help="Reject a pending profile change"
    )
    agent_reject_change.add_argument("agent_id")
    agent_reject_change.add_argument("change_id")
    agent_reject_change.set_defaults(func=cmd_agent_reject_change)

    liar = sub.add_parser("liar-test", help="Prove a fake success claim is rejected")
    liar.set_defaults(func=cmd_liar)

    doctor = sub.add_parser("doctor", help="Check local configuration")
    doctor.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, RuntimeError, FileNotFoundError) as error:
        print(f"ERROR: {error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
