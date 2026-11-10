# Zuri Agent

Local-first AI company: you talk to a **Boss** agent; it writes a work contract,
assigns a specialist, and an **independent verifier** decides whether the work is
actually done.

**Core promise:** you can see every action and every artifact. No task succeeds
because an AI said so; it succeeds only when the evidence matches the ledger.

Status: **Slice 1C implemented — awaiting user confirmation.** No later slice
started.

## Quick start

From this folder:

```powershell
.\zuri.cmd doctor
.\zuri.cmd liar-test
.\zuri.cmd run "Create notes/hello.md with the text 'Hello from Zuri'."
```

Inspect a task:

```powershell
.\zuri.cmd tasks
.\zuri.cmd last            # short summary of the newest task
.\zuri.cmd explain         # plain-language explanation of the newest task
.\zuri.cmd verify-last     # re-run checks on the newest task
.\zuri.cmd show <task-id>
.\zuri.cmd show <task-id> --json
.\zuri.cmd verify <task-id>
.\zuri.cmd report <task-id>
```

If a run fails:

```powershell
.\zuri.cmd ping            # test the DeepSeek connection
.\zuri.cmd last            # shows the failure reason
```

`.\zuri.cmd guide` prints the simple test steps.

Approve a risky task:

```powershell
.\zuri.cmd approve <task-id>
```

## Agents

Create (Boss/HR drafts, you approve):

```powershell
.\zuri.cmd agent create "Create an agent named Notes that writes clean markdown notes."
.\zuri.cmd agent approve <proposal-id>
.\zuri.cmd agent list
```

Use an agent by naming it in the request:

```powershell
.\zuri.cmd run "Use the notes agent to create work/notes.md with a checklist."
```

Delete (two confirmations required):

```powershell
.\zuri.cmd agent delete notes
# 1) type the exact agent id
# 2) type: DELETE notes
```

Soft delete only: the folder is snapshotted to `agents/.trash/`. Restore:

```powershell
.\zuri.cmd agent restore notes
```

Other agent commands:

```powershell
.\zuri.cmd agent show notes
.\zuri.cmd agent proposals
.\zuri.cmd agent history notes
.\zuri.cmd agent reject <proposal-id>
```

## Agent mind

Each agent has a versioned mind:

```powershell
.\zuri.cmd agent mind notes
.\zuri.cmd agent style notes tone=direct length=short
.\zuri.cmd agent remember notes "User prefers short checklists."
.\zuri.cmd agent forget notes <memory-id>
.\zuri.cmd agent rollback notes 1
.\zuri.cmd agent changes notes
.\zuri.cmd agent approve-change notes <change-id>
.\zuri.cmd agent reject-change notes <change-id>
```

After a task is independently verified, the agent reflects on it. Safe changes
(tone, length, language, report format, SOP notes, evidence-backed facts) apply
automatically and create a new profile version. Sensitive changes (tools,
model, scope, system prompt, risk, initiative, approval policy) become **pending
changes** that need your approval.

## Blocked tasks and resilience

When a worker cannot finish, it calls `report_blocked` with a reason. The system
then:

- stops immediately if the **goal itself** is disallowed (policy/legal),
- otherwise plans up to 3 compliant alternatives (another tool, another agent,
  smaller steps, or asking you for missing input),
- verifies every attempt,
- marks the task `blocked` if nothing works, with every attempt and what is
  needed.

`zuri explain` shows the attempts. Policy checks are heuristic hard stops, not a
legal opinion. They never silently fake success.

Each agent gets only the tools in its profile. System agents (`boss`, `hr`,
`worker`) cannot be deleted or re-created by the user.

## What is recorded

- Every model call: model, tokens, estimated cost.
- Every tool call: tool name, arguments preview, result preview.
- Every artifact: path, SHA-256, bytes, producer.
- Every verification check: pass/fail, detail, evidence.
- Every status change, approval, and agent-registry action.
- `data/ledger.jsonl` + `data/agent_ledger.jsonl` + SQLite `data/zuri.db`.

The worker cannot mark success. The Boss cannot mark success. Only the verifier
can, and only with a matching artifact in the ledger.

Content checks (`file_contains`) are case-insensitive by default; the contract
can set `case_sensitive: true` when exact case matters.

## Layout

| Folder | Purpose |
| --- | --- |
| `app/` | Kernel, DeepSeek adapter, tools, verifier, registry, CLI |
| `agents/<id>/` | `profile.json`, `memory.jsonl`, `profiles/` version snapshots |
| `workspace/` | Sandboxed files the agents create |
| `data/` | SQLite, ledgers, artifacts, proposals (not committed) |
| `tests/` | Automated tests (including the Liar Test) |
| `scripts/` | Setup helpers |
| `Documentation/` | Tracker, plans, confirmed architecture |

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\zuri.cmd liar-test
```

## Setup from scratch

```powershell
.\scripts\setup.ps1
# then put DEEPSEEK_API_KEY in .env
```

## Docs

- Tracker: `Documentation/temp/CURRENT.md`
- Master plan: `Documentation/Planning/Zuri2/01_Master_Plan.md`
- Slice 1A: `Documentation/Planning/Zuri2/02_Slice1A_Agent_Lifecycle.md`
- Agent Mind: `Documentation/Planning/Zuri2/03_Slice1B_Agent_Mind.md`
- Resilience: `Documentation/Planning/Zuri2/04_Slice1C_Resilience.md`
- Test strategy: `Documentation/Planning/Zuri2/05_Test_Strategy.md`
