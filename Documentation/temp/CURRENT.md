# CURRENT — Zuri Agent

## Active

- Rebuild Zuri from scratch in `D:\Projects\My projects\Zuri Agent`.
- Old project renamed to `D:\Projects\My projects\Zuri Agent(Fail)`; nothing
  from it is trusted or reused by default.
- Hard requirements from user:
  - DeepSeek API is available and is the main model provider.
  - Local-first; no Gemini/Google Cloud dependency.
  - You talk to a Boss; Boss plans, assigns specialists, reports.
  - You must see exactly what each agent did; the Boss must not be able to fake
    success.
  - Specialists must be genuinely powerful (tools + SOPs + memory + checks).
  - Instagram was only an example; **not scheduled**.
- Current step: **Slice 1D implemented and internally verified — awaiting user
  confirmation.** The local web dashboard is available. Next: user choice of
  Engineering department or UI polish.
- Slice 1A evidence (2026-11-09):
  - 29 automated tests pass.
  - HR created proposal `p_e5bd52ef05` → agent `notes` (write_file only).
  - `zuri run "Use the notes agent ..."` → `t_15fb0257746e`, assignee `notes`,
    only its tool granted. First verify failed on `file_contains` case
    sensitivity; fixed to case-insensitive by default and optional
    `case_sensitive: true`; reverify → 6/6 checks, succeeded.
  - Wrong delete confirmations aborted and agent stayed.
  - Correct two confirmations soft-deleted to
    `agents/.trash/notes-20261109-153000-5bcd23`; restore succeeded.
  - Audit events recorded in `agent_events` + `data/agent_ledger.jsonl`.
  - User test follow-up: one run failed with `Connection error.` (transient
    network; `zuri ping` returned OK). Retried → `t_cdf1b1b8cc6c` succeeded,
    assignee `notes`, 4/4 checks, ~$0.001642.
  - Added simple commands: `last`, `verify-last`, `guide`, `ping`; clearer
    two-step delete prompts; restore reports "still active" instead of ERROR.
  - 29 tests pass.
  - User test 2026-11-10: `t_76272e742abb` succeeded ("Create notes/hello.md
    with 'hello'"), assignee worker, 3/3 checks, ~$0.001440; `last` and
    `verify-last` worked. **1A confirmed.**
  - Understanding layer added after user feedback:
    - `zuri explain` / `zuri explain <id>`: plain-language story of what
      happened, who did it, checks, evidence, cost. No raw JSON, no task-id
      copying.
    - `zuri last`, `verify-last`, `guide`, `ping`.
    - Test strategy: `Documentation/Planning/Zuri2/05_Test_Strategy.md`.
    - 44 tests pass; failed-task explain shows the error (`Connection error.`);
      Liar Test still passes; `zuri ping` OK.
  - The assistant owns testing from now on; the user does not run test commands.
- Slice 1A plan:
  `Documentation/Planning/Zuri2/02_Slice1A_Agent_Lifecycle.md`
  - Folder layout: `agents/<id>/profile.json`, `memory.jsonl`, `profiles/`.
  - Boss drafts agent specs; user approves creation.
  - Deletion: two explicit confirmations, soft-delete + snapshot + restore.
  - Audit ledger for agent actions.
  - Boss picks an assignee; kernel runs that agent with only its tools.
- After 1A: 1B Agent Mind, 1C Resilience, 1D Company kernel.
- Slice 1B implemented (2026-11-10):
  - 58 automated tests pass.
  - Versioned profile/SOP/style; evidence-linked memory; reflection only after
    verified tasks; rollback; forget; pending changes for sensitive updates.
  - Live verified tasks: `t_afe545433cd1`, `t_9154c52019c9`, `t_235d6dc2a23a`,
    `t_fdb37ee10075` — reflection added evidence-linked lessons/SOP notes.
  - Sensitive style (initiative/risk/approval) became a pending change, not
    auto-applied; user rejected it in the live test.
  - Trivial "task completed" facts rejected; near-duplicate SOP notes
    suppressed; duplicate pending changes reused.
  - Fixed: sensitive style auto-apply, trivial facts, duplicate SOPs, Windows
    atomic-write lock.
  - Commands: `agent mind/remember/forget/style/rollback/changes/
    approve-change/reject-change`; `zuri explain` shows the learning summary.
  - The assistant owns testing; the user does not run test commands.
- Slice 1C implemented (2026-11-10):
  - 67 automated tests pass.
  - `report_blocked` control tool with reasons: policy_legal, missing_input,
    missing_access, tool_unavailable, external_failure, ambiguity.
  - Policy hard stops for disallowed goals/alternatives; no illegal/ToS bypass.
  - Bounded alternative planner (up to 3): another agent, different tool,
    smaller steps, or ask the user; each attempt is verified.
  - Budget-limited attempts; blocked status and report with every attempt.
  - Live policy block: `t_1b6d4837edff` (credential theft) stopped before
    planning; no API cost; explain/last show the reason.
  - Live resilience loop: `t_5c896fd1d26b` — simulated blocked notes attempt,
    real DeepSeek planner proposed alternatives, real worker succeeded on
    attempt 2; file verified; ~$0.001904.
  - `zuri explain` shows attempts and "succeeded after N attempts"; blocked
    tasks show why and what is needed.
  - Test-only `assistant` agent created during the live resilience test was
    soft-deleted with two confirmations (cleanup).
- Next: 1D Company kernel/dashboard after user confirmation.
- Slice 1D implemented (2026-11-10):
  - 70 automated tests pass.
  - Local chat-style dashboard (`zuri serve`, `http://127.0.0.1:8765`):
    submit requests, task list/detail, artifacts, checks, attempts, timeline,
    agent mind viewer, approvals, cost ledger.
  - One-at-a-time in-process job queue; approvals run through the same queue.
  - CLI `approvals`, `costs`, `serve`; cost summary total/month/by-agent/recent.
  - Live web run: `t_2bc2b0ccc51c` via POST `/api/run`, assignee notes, 3/3
    checks, artifact, report verified, ~$0.001924; summary/tasks/agents/costs
    endpoints OK; server stopped, port free.
  - Limits: localhost/no login, in-memory queue (not durable), one worker,
    basic UI.
- Next: user opens the dashboard and decides Engineering department vs UI
  polish. The assistant owns testing; no command homework.
- New requirements (2026-11-09):
  - **Dynamic agent mind:** create an agent with little detail; it builds a
    versioned profile/SOP/memory from verified work and user feedback. User can
    inspect, correct, forget and roll back. Tool/permission/model/scope changes
    need user approval.
  - **Configurable behavior:** user controls Boss reply style and each agent's
    working style (tone, length, initiative, risk, approvals).
  - **Resilience/creativity:** when a method is blocked, try bounded
    alternatives, sub-tasks or other agents; ask the user for missing input;
    report `blocked` with evidence. Never fake success; never bypass
    law/platform rules/permissions.
  - Plans: `03_Slice1B_Agent_Mind.md`, `04_Slice1C_Resilience.md`.
- GitHub repo: `https://github.com/ElixirOfRehan/Zuri-Agent.git`
  - Pushed `main` (latest `86a0a33`; initial `76f278c`).
  - Commit email uses `ElixirOfRehan@users.noreply.github.com` because
    `ra57000rehan@gmail.com` is private on GitHub (push was rejected until the
    noreply address was used).
  - `.env`, `data/`, `workspace/`, agent memory/trash are gitignored.
- Slice 0 user test:
  - `zuri liar-test` rejected the fake claim.
  - `zuri run "Create notes/test.md ..."` → `t_64b1feaa9e32` succeeded.
  - `show`/`verify` show latest-run checks only after the run-id fix.
  - No Git repository exists, so no commit was made.
- Slice 0 evidence (2026-11-09):
  - 17 automated tests pass (`.venv\Scripts\python.exe -m pytest -q`).
  - Liar Test: task `t_26bfae9532ac` → `failed`; fake success rejected.
  - Live DeepSeek run: task `t_c29b37553ab7` → `succeeded`; file
    `notes/hello.md`; 3/3 checks; 3995 tokens; ~$0.001528 estimated.
  - User live test: `t_64b1feaa9e32` succeeded (notes/test.md),
    `t_027e04cca932` Liar Test rejected.
  - Fixed after user test: repeated `verify` accumulated checks in the report.
    Verification runs now have `run_id`; reports/show use the latest run and
    mention older runs. New task `t_e50b6cedb7d4` verified 3 times →
    "latest of 3 runs", 3 checks, cost ~$0.0015.
  - Commands: `zuri doctor`, `zuri liar-test`, `zuri run ...`, `zuri show`,
    `zuri verify`, `zuri report`.
- Changes from user after approval:
  - Instagram was only an example; **not scheduled**.
  - Boss can propose creating/deleting agents (Slice 1). Deletion requires
    **two explicit user confirmations**, soft-delete with snapshot + restore,
    and kernel enforcement. The Boss cannot do it alone.

## Decisions

- Build path: `D:\Projects\My projects\Zuri Agent`.
- Models: DeepSeek `deepseek-v4-pro` (Boss/hard work) and `deepseek-flash`
  (cheap workers). Provider must be swappable.
- Runtime: Python 3.12 via `uv` (system Python 3.14 is too new for some deps).
- No Google Cloud requirement. Core kernel is framework-agnostic; Slice 0 uses
  a thin DeepSeek runner, with an ADK adapter evaluated later.
- Local storage: SQLite (tasks/ledger) + files for artifacts.
- Interface: CLI first, local web dashboard second.

## Next

- 1D is internally verified and awaiting user confirmation.
- User opens `zuri.cmd serve` → `http://127.0.0.1:8765` and sends a request.
- Then choose: (a) Engineering department (REA/OpenCode), or (b) UI polish.
- The user gives goals in chat; no command homework.
- The assistant runs all tests and reports plain-language results.

## Open questions

- Monthly model budget cap.
- Whether voice stays in scope for v2 or comes later.
