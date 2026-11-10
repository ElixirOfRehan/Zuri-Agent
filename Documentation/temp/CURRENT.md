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
- Current step: **Slice 1A implemented and internally verified — awaiting user
  test.** Slice 1B (Agent Mind) is next only after user confirmation.
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
- Slice 1A plan:
  `Documentation/Planning/Zuri2/02_Slice1A_Agent_Lifecycle.md`
  - Folder layout: `agents/<id>/profile.json`, `memory.jsonl`, `profiles/`.
  - Boss drafts agent specs; user approves creation.
  - Deletion: two explicit confirmations, soft-delete + snapshot + restore.
  - Audit ledger for agent actions.
  - Boss picks an assignee; kernel runs that agent with only its tools.
- After 1A: 1B Agent Mind, 1C Resilience, 1D Company kernel.
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
  - Pushed `main` (commit `304b9bd`; initial `76f278c`).
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

- User test Slice 1A with the simple path:
  1. `zuri.cmd guide`
  2. `zuri.cmd run "Create notes/hello.md with the text 'hello'"`
  3. `zuri.cmd last`
  4. `zuri.cmd verify-last`
  5. `zuri.cmd agent list` / `agent show notes`
  6. Deletion test: `agent delete notes` → wrong input aborts; repeat with
     `notes` then `DELETE notes`; `agent restore notes`.
- If the API fails with `Connection error`, run `zuri.cmd ping` and retry.
- After user confirms 1A: implement 1B (Agent Mind), then 1C (Resilience), then
  1D (Company kernel).
- Do not implement 1B before confirmation.

## Open questions

- Monthly model budget cap.
- Whether voice stays in scope for v2 or comes later.
