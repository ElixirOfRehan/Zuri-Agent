# Zuri Agent 2.0 — Master Plan

Status: **approved**; Slice 0 implemented (2026-11-09), awaiting user test.
Date: 2026-11-09
Build path: `D:\Projects\My projects\Zuri Agent`

## 1. Why v1 failed

- The Boss's summary was the only window into the work; the user could not see
  what a worker actually did.
- Verification trusted model claims. A lying worker or Boss could end a task
  "successfully" with nothing to show.
- Agents were mostly prompts; they lacked detailed SOPs, tools, feedback and
  evals, so they could not work at a high level.
- The custom task engine was a lot of code to maintain and hard to inspect.

## 2. Goals

- You can inspect **every action and artifact** of every task without asking
  the Boss.
- The Boss **cannot fake success**; only the kernel/verifier can mark a task
  done.
- Specialists can be genuinely powerful: strong model + real tools + detailed
  SOPs + memory + budgets + feedback + tests.
- Local-first, DeepSeek-powered, no Gemini/Google Cloud dependency.
- Simple project layout, one slice at a time.

Non-goals for the first version: autonomous spending, posting to external
accounts without approval, multi-machine A2A, voice.

## 3. Hard requirements

1. DeepSeek API is the main model provider.
2. Boss/employee hierarchy; specialists only run when assigned.
3. Independent proof of work for every task.
4. Detailed, powerful specialist agents (first example later: Instagram).
5. All files organized under this project folder.
6. Secrets never appear in prompts, logs, reports or git.
7. The Boss may create or delete specialists only with user involvement; deletion
   requires **two explicit confirmations** and is kernel-enforced (Slice 1).
8. Agents build a **dynamic mind**: a versioned profile, SOP and memory that
   improve from verified work. A minimal agent definition is enough to start.
9. The user can manage how the Boss replies and how each agent works (tone,
   detail, initiative, risk, approvals).
10. When a method is blocked, agents must try bounded alternatives, sub-tasks or
    other agents instead of stopping. They never bypass legal/policy limits and
    never fake success.

## 4. Design in one picture

```
You (client)
  │  request / approval / audit
  ▼
Control plane (CLI now, local dashboard next)
  │
  ▼
KERNEL (deterministic)
  Intake → Contract → Plan → Dispatch → Execute → Verify → Report
  │            │           │          │          │
  │            │           │          │          └─ independent verifier
  │            │           │          └─ worker agents + tools
  │            │           └─ Boss (planner/router, cannot mark success)
  │            └─ TaskContract + acceptance tests + budget
  └─ Ledger + artifacts + approvals + costs + memory

Boss              = Chief of Staff (plans, assigns, summarizes)
Specialists       = narrow workers (Instagram, Engineering, Research, ...)
QA                = independent reviewer (agent + deterministic checks)
```

## 5. Trust model — Proof of Work

This is the answer to "I don't know what the agent did."

**TaskContract (required before work):**

- objective and context
- deliverables (paths/types)
- acceptance tests (commands/checks)
- constraints and forbidden actions
- risk level and approval class
- budget: tokens, money, time, max steps
- assignee and deadline

**Append-only ledger:** every event is recorded:

| Event | Examples |
| --- | --- |
| `tool_call` | command, file write, HTTP request, browser action |
| `tool_result` | exit code, output hash, response summary |
| `artifact_created` | file path + SHA-256 + producer |
| `message` | Boss ↔ worker messages |
| `verification` | check name, pass/fail, evidence |
| `approval` | requested, approved/rejected, by whom |
| `cost` | tokens and estimated price |

**Evidence kinds:** file, diff, command output, test result, screenshot, HTTP
response, browser action log, post/API ID.

**Independent verifier:**

- Runs the contract's deterministic checks first (files exist, hashes match,
  tests pass, schema valid, deliverable readable).
- Optional LLM judge only for qualitative criteria.
- Never accepts "I did it" as evidence.
- The Boss's report must cite evidence IDs; unlinked claims are flagged.

**Control-plane views (what you use):**

```
zuri run "<request>"            # returns task id
zuri task show <id>             # timeline of every action
zuri task show <id> --evidence  # raw evidence + artifacts
zuri task show <id> --cost      # tokens, model, price
zuri verify <id>                # re-run acceptance checks
zuri report <id>                # Boss summary with evidence links
```

**Liar test (Slice 0 acceptance):** a worker is told to claim success without
creating the deliverable. The verifier must fail the task, the ledger must show
no artifact, and the Boss must be unable to override it.

**Replay:** tasks can be re-verified from the ledger and stored artifacts.

## 6. Power model — how an agent becomes strong

An agent is not just a prompt. Each agent definition contains:

- **Role charter:** scope, responsibilities, what it must not do.
- **Model:** DeepSeek V4 Pro for hard reasoning; Flash for cheap/fast work.
- **SOP/playbook:** step-by-step workflows, checklists, examples.
- **Tools:** shell, files, HTTP, browser (Playwright), MCP (REA, etc.),
  scheduler, messaging, secret store.
- **Permissions:** workspace, command allowlist, network, external effects.
- **Memory:** task history, facts, preferences, past artifacts.
- **Budgets:** max steps, time, tokens, cost; concurrency.
- **Quality gates:** self-check + independent QA + acceptance tests.
- **Feedback:** corrections become new SOP examples and eval cases.
- **Evals:** golden tasks per role, regression before changes.

"Peak level" comes from this full stack plus iteration — not from a magic
sentence in the prompt.

### Dynamic mind (agent history that builds itself)

An agent can be created with very little detail. Its definition grows from
verified work:

- **Profile** (versioned): charter, SOP/playbook, style, tools, model, approval
  policy.
- **Memory**: evidence-linked episodes, user preferences, project facts,
  lessons learned.
- **Reflection step** after every verified task: extract lessons and proposed
  profile updates from the contract, timeline, evidence and user feedback.
- Safe fields (SOP notes, style, memory facts) can auto-apply; changes to
  tools, permissions, model or scope require **user approval**.
- Every profile change is versioned with an audit record and rollback
  (`profiles/v0001.json`, `v0002.json`, ...).
- No learning from unverified claims; facts must cite evidence. The user can
  inspect, correct or forget memory.
- Minimal creation: the Boss asks at most 3 short questions or seeds a
  generalist. The first task creates a task-specific role brief; after
  verification, the agent's mind is refined.

### Configurable behavior

Boss and agent profiles include style/behavior settings:

- tone (direct, friendly, formal), reply length, language
- initiative (ask first vs act within sandbox)
- risk tolerance and approval policy
- report format and evidence level

The kernel injects these into prompts. The user can edit them; they cannot be
silently changed by the model.

### Resilience and creative problem solving

When a worker cannot complete a step, it returns a **blocked reason**:
`policy/legal`, `missing_input`, `missing_access`, `tool_unavailable`,
`external_failure` or `ambiguity`.

Then the kernel runs a bounded alternative loop:

1. Generate at least 3 alternative approaches with feasibility, cost and risk.
2. Try the safest viable ones within the task budget.
3. Decompose into smaller steps, use another tool, or delegate sub-tasks to
   other agents.
4. If still blocked, ask the user for the missing input/approval, or report
   `blocked` with everything tried and what would unblock it.

Hard rule: alternatives may not bypass law, platform rules, permissions or
safety policy. If the goal itself is disallowed, the agent stops and explains;
it does not look for a workaround. Verification still applies to every
alternative.

## 7. Organization

Start small:

| Role | Count | Notes |
| --- | --- | --- |
| Client (you) | 1 | Requests, approvals, final audit |
| Boss / Chief of Staff | 1 | Plans, writes contracts, assigns, reports |
| Worker specialists | 1 → 3 | One domain each; run only when assigned |
| QA / verifier | 1 | Independent checks; cannot be the worker |

Later: department managers only when a department has several specialists.

Candidate specialists after the trust loop works:

- **Engineering** (REA + OpenCode for reverse engineering/coding)
- **Research** (web research, source gathering, summaries)
- **Ops/Finance** (scheduling, cost reports, approvals inbox)
- Instagram automation stays an **example only**, not a scheduled slice.

**Agent lifecycle (Slice 1):** the Boss can propose creating or deleting a
specialist, but it cannot do either by itself.

- **Create:** Boss writes a spec (role, SOP, model, tools, permissions, budget);
  the user approves; the registry adds it.
- **Delete (two confirmations):** the user names the agent; the kernel shows
  exactly what will be removed; confirmation #1; confirmation #2; then a
  **soft delete** — the definition and memory are snapshotted to
  `agents/.trash/<id>-<timestamp>` and the agent is disabled. Every step is in
  the ledger. A restore command exists. No hard delete in v2 by default.

## 8. Architecture components

1. **Kernel** — task state machine, scheduler, contracts, dispatch, budgets,
   approvals. Deterministic Python.
2. **Agent runtime** — ADK 2.x graph workflows; DeepSeek through
   LiteLLM/OpenAI-compatible adapter. If the ADK+DeepSeek integration is not
   clean, the kernel is framework-agnostic and we swap the runner.
3. **Tool layer** — typed tools with permission checks; every call wrapped by
   the ledger.
4. **Verifier** — deterministic check runner + optional LLM judge.
5. **Ledger + artifact store** — SQLite (WAL) for state; JSONL event stream;
   files stored content-addressed by SHA-256.
6. **Control plane** — CLI first (`zuri`), local dashboard second.
7. **Registry** — agent definitions in `agents/` as YAML/JSON.
8. **Secrets** — `.env` / Windows Credential Manager; redaction everywhere.
9. **Memory** — SQLite + files; RAG later.

## 9. Data model (initial)

`tasks`, `contracts`, `runs`, `events`, `artifacts`, `evidence`,
`verifications`, `approvals`, `costs`, `agents`, `memories`.

States: `created → planned → awaiting_approval → queued → running →
verifying → succeeded | failed | blocked | cancelled`.

Rules:
- Invalid transitions are rejected in code.
- `succeeded` requires at least one passing verification with evidence.
- The Boss can request a transition; the kernel decides.

## 10. Tech stack

- Python 3.12 via `uv` (system 3.14 is too new for some dependencies).
- `google-adk` 2.x for agents/workflows; DeepSeek via LiteLLM or the
  OpenAI-compatible client.
- SQLite (WAL) + JSONL ledger + file artifacts.
- Playwright for browser automation; MCP for REA and external tools.
- CLI: Typer/Click. Dashboard: FastAPI + HTMX (later).
- pytest + eval cases.
- No Google Cloud requirement.

**Slice 0 spike:** prove DeepSeek works through the chosen runtime (chat, tool
calls, JSON output, retries, cost tracking). If ADK is awkward with DeepSeek,
fall back to a thin custom runner with the same kernel interfaces.

## 11. Security and approvals

- Agents work inside `workspace/`; path allowlist enforced in code.
- Shell command allowlist; dangerous commands require approval.
- External effects (post, send, deploy, spend, delete) require approval.
- Every network/tool action is logged.
- Secrets never enter prompts or logs; redaction on output.
- Per-task budgets, step limits, timeouts, concurrency limits.
- Append-only audit trail; no silent edits.
- Agent deletion: two explicit confirmations, soft-delete with snapshot, restore
  path, and a full audit record. The Boss cannot bypass either confirmation.

## 12. Instagram specialist (example, not scheduled)

The user used Instagram only as an example; it is not part of the build plan.
If it is ever requested:

Prerequisite: account type.

- **Business/Creator account:** official Instagram Graph API supports content
  publishing, insights, comments and messaging with the right permissions.
- **Personal account:** no official API for automation; browser automation is
  possible but risks account restrictions and violates ToS. Only with explicit
  user approval and rate limits.

Workflows: content calendar → drafts → **approval** → schedule/post → monitor →
analytics → reply drafts. Every post/DM has an action log and post/API ID.
Credentials live in the secret store; 2FA handled manually.

## 13. Slices

### Slice 0 — Trust loop (first implementation)

Status: **implemented, awaiting user test.**

Scope:
- Project scaffold with Python 3.12 + uv.
- DeepSeek provider spike (Boss model + worker model).
- Minimal kernel: task + contract + states.
- One Boss, one Worker (safe file/research task), one QA verifier.
- Append-only ledger + artifact store + evidence.
- CLI: `run`, `task show`, `verify`, `report`.
- Liar test + one eval case.

Acceptance:
- A real request runs end-to-end.
- Every tool call and artifact is visible.
- Liar test fails correctly; Boss cannot override.
- Cost/tokens recorded.
- User tests with a real request and confirms.

### Slice 1A — Agent lifecycle and registry

Status: **implemented, awaiting user test.**

Folder-based agent storage (`agents/<id>/profile.json`, `memory.jsonl`,
`profiles/`), create/approve flow, two-confirmation soft-delete with snapshot
and restore, audit events, Boss assignee selection, per-agent tool filtering.
Plan: `02_Slice1A_Agent_Lifecycle.md`.

### Slice 1B — Agent Mind v1

Status: **implemented, awaiting user confirmation.**

Minimal agent creation, configurable Boss/agent style, evidence-linked memory,
reflection after verified tasks, versioned profile updates, rollback, memory
viewer. Plan: `03_Slice1B_Agent_Mind.md`.

### Slice 1C — Resilience and creative problem solving v1

Blocked reasons, bounded alternative generation, sub-task decomposition,
delegation to other agents, user escalation, policy/legal hard stops.
Plan: `04_Slice1C_Resilience.md`.

### Slice 1D — Company kernel v0

Queue/scheduler, approvals inbox, budgets/cost ledger, dashboard v0 (task
timeline, evidence viewer, agent mind viewer).

### Slice 2 — Engineering specialist

REA/OpenCode integration for reverse engineering/coding, QA reviewer, second
department, parallel workflows.

### Slice 3 — Dashboard, memory and approvals UX

Full task timeline, evidence viewer, diffs/screenshots, approvals inbox,
semantic memory/RAG over past tasks and artifacts.

### Slice 4 — Scale

Voice, A2A boundaries, free fallback providers, eval suite and regression runs.

## 14. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| ADK + DeepSeek integration friction | Slice 0 spike; framework-agnostic kernel; fallback runner |
| Model quality/limits | Strong model for Boss, Flash for workers, fallback chain, evals |
| Rate limits | Queue, retries, provider fallback |
| Instagram ToS/account risk | Official API where possible, approvals, rate limits |
| Trust system overhead | Automate evidence capture; simple CLI views first |
| Scope explosion | One worker first; add roles only when evals justify |

## 15. Open decisions

1. Monthly model budget cap.
2. Dashboard now or after Slice 1.
3. Voice now or later.
4. ADK vs thin custom runner — decided by the Slice 0 spike, same interfaces.
5. Deletion UX: CLI text confirmation twice (default) and two dialogs later in
   the dashboard.

## 16. Approval

Approve this plan and Slice 0 scope. Then:

1. Put the DeepSeek key in `.env` locally (copy `.env.example`); never paste it
   in chat.
2. I implement Slice 0 only.
3. You test with a real request, inspect the evidence, run the liar test.
4. You confirm; then Slice 1.
