# Zuri Agent

Local-first AI company: you talk to a **Boss** agent; it writes a work contract,
assigns a specialist, and an **independent verifier** decides whether the work is
actually done.

**Core promise:** you can see every action and every artifact. No task succeeds
because an AI said so; it succeeds only when the evidence matches the ledger.

Status: **Slice 2B (OpenCode + QA) implemented — awaiting user
confirmation.** Parallel departments and UI polish remain.

## Web dashboard (local)

```powershell
.\zuri.cmd serve
```

Open `http://127.0.0.1:8765`.

- Talk to Zuri in a chat-style box; the task runs in a one-at-a-time queue.
- See every task: status, assignee, checks, artifacts, attempts, cost, timeline.
- See agent minds: style, SOP notes, memory, versions, pending changes.
- Approve tasks waiting for approval.
- See the cost ledger.

It binds to `127.0.0.1` only and has no login. The queue is in memory: stopping
the server loses queued jobs (completed tasks remain in the database).

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
.\zuri.cmd approvals       # tasks waiting for approval
.\zuri.cmd costs           # cost ledger
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

## Engineering agent and shell

The seeded `engineering` agent has `list_dir`, `read_file`, `write_file`, and
`run_command`. It can run:

```powershell
.\zuri.cmd run "Use the engineering agent to create work/hello.py that prints hello, run it with python, and save the output to work/run.txt."
```

`run_command` is structured (`program` + argument list), runs with the workspace
as cwd, and has no shell. It is allowlisted (`python`, `node`, `npm`, `git`,
`pytest`, `rea`) and blocks:

- unknown programs,
- absolute paths and `..` traversal in arguments,
- `git push/pull/fetch/clone/remote/submodule`, global/system git config,
- `npm install/publish/exec/ci/link` (network/install actions).

Every command and its output is logged (`command_output` events). Set
`ZURI_SHELL_ENABLED=0` to disable the tool, or `ZURI_ALLOWED_COMMANDS` to narrow
the allowlist.

**Important:** this is not an OS sandbox. Python/Node code runs with your user
permissions and may read files or use the network. Use the engineering agent
only on trusted work, and review its commands.

REA is available through the `rea` CLI from inside the workspace, for example
`rea --version` or `rea inspect-android-package <relative-apk>` after copying a
target into the workspace.

## OpenCode and QA

The Engineering agent can delegate substantial code edits to OpenCode through
`run_opencode`:

- OpenCode can read/edit workspace files only.
- Shell, network, external directories, web search and subagents are denied.
- REA MCP is disabled for the nested OpenCode run; the Engineering agent uses
  `rea` itself.
- The nested run is `--pure` and uses a controlled config.
- Its token/cost usage is recorded in the Zuri cost ledger.

After an engineering task passes the deterministic verifier, a QA reviewer
checks the deliverables, command evidence and code/content:

- verdict `pass` or `fail`,
- concrete issues and notes,
- stored in the task report, `zuri explain`, and dashboard,
- **advisory**: it does not override the verifier or fake success.

Disable QA with `ZURI_QA_ENABLED=0`. Configure models with
`ZURI_OPENCODE_MODEL` and `ZURI_QA_MODEL`.

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
