# temp — Zuri Agent working history

## 2026-11-09 — Rebuild start

Old project: `D:\Projects\My projects\Zuri Agent` (custom Python orchestrator,
SQLite task engine, DeepSeek, OpenCode sessions, voice). Read its docs:
`README.md`, `PROJECT_PLAN.md`, `docs/architecture.md`, `docs/how-zuri-works.md`,
`Zuri/SYSTEM.md`, `Documentation/temp/*`. Strengths kept in design: on-disk
deliverable verification, approvals, budgets, honest failure, local-first.
Weaknesses: bespoke orchestration, loose contracts, no eval harness, file
memory, hard to see what a worker actually did.

User requirements (this rebuild):
- DeepSeek API key available; use DeepSeek.
- Boss/employee hierarchy; specialists only run when assigned.
- User must verify what agents did; Boss must not be trusted blindly.
- Agents should be very powerful; example: Instagram automation specialist.
- Build in `D:\Projects\My projects\Zuri Agent`, organized and simple.
- Old folder must be renamed `Zuri Agent(Fail)`.

Process stop/rename:
- No Python/old-Zuri process was running.
- Folder rename failed: Sysinternals `handle64.exe` showed node.exe PID 506960
  (a current REA MCP server) held a File handle on the folder.
- Killed only PID 506960 (`taskkill /T /F`), re-checked handles (none), rename
  succeeded to `Zuri Agent(Fail)`.
- New empty project created; current OpenCode session and REA servers were left
  alone.

Research notes:
- google-adk 2.14.0 (Python >=3.11). ADK 2.0 graph workflow runtime, Task API,
  A2A, sessions/memory/artifacts, eval, Cloud Run/Agent Runtime deploy.
- google-agents-cli 1.13.0: Google Cloud lifecycle wrapper (scaffold/eval/
  deploy/publish). Model-agnostic via ADK/LiteLLM, but deploy targets are
  Google Cloud. Not required for this project.
- agents-cli models can swap to Claude/OpenAI via LiteLLM; DeepSeek needs a
  provider spike.
- DeepSeek current API: `deepseek-v4-pro`, `deepseek-flash`; 1M context; tool
  calls; JSON; OpenAI + Anthropic-compatible endpoints; very cheap.
- Machine: i5-8350U, ~15.4 GB RAM, Intel UHD 620 (no real GPU) → local models
  are not a practical main brain.

Key design direction:
- Deterministic kernel + Boss + specialists + QA + append-only evidence
  ledger. Kernel/verifier owns task truth; Boss reports with evidence IDs.
- Agent power = model + tools + detailed SOP + memory + budgets + feedback +
  evals, not a single prompt.
- Start with one worker; add Instagram only after the trust loop is proven.

No implementation started; Slice 0 plan awaiting approval.

## 2026-11-09 — Slice 0 implemented (approved)

User approved the plan, then added:
- Instagram was only an example; do not schedule it.
- Boss can create/delete agents (Slice 1); deletion must ask the user **twice**
  and is kernel-enforced; soft-delete + snapshot + restore.

Plan updated accordingly. Slice 0 built:

- Python 3.12 venv via uv; deps: openai 3.46, pydantic 2.14,
  python-dotenv, pytest.
- `app/`: config, sandbox, models, storage (SQLite + JSONL ledger +
  content-addressed artifacts), DeepSeek adapter, tools (list_dir, read_file,
  write_file), Boss/Worker/LiarWorker, independent verifier, kernel, CLI.
- `agents/boss.json` (deepseek-v4-pro) and `agents/worker.json`
  (deepseek-flash).
- CLI: `run`, `show`, `verify`, `report`, `approve`, `tasks`, `liar-test`,
  `doctor`; wrapper `zuri.cmd`.
- Boss writes a strict JSON TaskContract; Worker executes with tools; every
  action logged; only the verifier can mark success.
- Ledger artifact match is required: a file on disk without a logged artifact
  fails verification.

Verification:
- `pytest -q`: 17 passed.
- `zuri liar-test`: task `t_26bfae9532ac` failed; fake success rejected.
- Live run: `t_c29b37553ab7` ("Create notes/hello.md with ...") succeeded;
  contract + 3 checks + artifact sha256 + cost ~$0.001528; worker wrote and
  re-read the file.
- Fixed during build: Windows rooted path `/x` was treated as relative; now
  rejected.

Decision: Slice 0 uses a thin DeepSeek runner (OpenAI-compatible), not ADK.
The kernel is framework-agnostic; an ADK adapter can be evaluated later
without changing the trust loop.

Awaiting user test and confirmation before Slice 1.

## 2026-11-09 — User test + verification-run fix

User ran Slice 0 in cmd:
- `zuri liar-test`: `t_027e04cca932` failed as expected (fake success rejected).
- `zuri run "Create notes/test.md ..."`: `t_64b1feaa9e32` succeeded, 3/3
  checks, ~$0.001529.
- `zuri show` revealed that repeated `verify` calls accumulated 9 checks and the
  report said "All 9 checks".

Fix:
- `verifications` gained `run_id` (with ALTER TABLE migration for the existing
  DB).
- `Verifier.run` creates a run id; storage returns the latest run by default.
- Report/show display the latest run and note older runs.
- `verify` prints the latest run only.
- New task `t_e50b6cedb7d4` verified 3 times → 3 checks, "latest of 3 runs".
- 17 tests still pass.

Status: awaiting explicit user confirmation of Slice 0 before Slice 1.

## 2026-11-09 — Slice 0 confirmed; Slice 1A planned

User confirmed Slice 0 after re-running `show` and `verify` with the run-id
fix. No commit (project has no Git repository).

Slice 1A plan written:
`Documentation/Planning/Zuri2/02_Slice1A_Agent_Lifecycle.md`

Scope:
- Agent registry in `agents/<id>.json`; id slug rules; reserved ids.
- Boss/HR drafts an AgentSpec; user approves; registry writes it.
- Delete needs two explicit confirmations; soft-delete snapshot to
  `agents/.trash/<id>-<timestamp>/`; restore; audit in `agent_events` and
  `data/ledger.jsonl`.
- Boss sees enabled assignees; kernel runs the chosen agent with only its
  allowed tools.
- Out of scope: queue, dashboard, memory, shell/browser tools.

Awaiting user approval of Slice 1A before implementation.

## 2026-11-09 — Agent Mind, resilience, GitHub repo

User added requirements:
1. **Dynamic history / mind:** if an agent is created with little detail, it
   should become defined by the work it receives. It needs a growing,
   evidence-linked profile/SOP/memory.
2. **User control of behavior:** the user can manage how the Boss replies and
   how agents work (style, initiative, risk, approvals).
3. **Creative resilience:** if a method is blocked, agents should not stop;
   they try alternatives, multiple steps, or other agents. If the goal itself
   is illegal/disallowed, they must stop and explain rather than bypass.
4. Provide GitHub repo: `https://github.com/ElixirOfRehan/Zuri-Agent.git`
   (empty; created by user).

Design decisions:
- Slice 1A revised to folder-based agent storage from the start:
  `agents/<id>/profile.json`, `memory.jsonl`, `profiles/vNNNN.json`.
- New plans:
  - `03_Slice1B_Agent_Mind.md` — minimal creation, style config, memory,
    reflection only after verified tasks, versioning, approval for
    tool/permission/model changes, rollback.
  - `04_Slice1C_Resilience.md` — blocked reasons, >=3 alternatives, scoring,
    sub-task/other-agent delegation, user escalation, legal/policy hard stops,
    budgets.
- Order: 1A (registry/lifecycle) → 1B (mind) → 1C (resilience) →
  1D (company kernel/dashboard).
- GitHub: git 2.53 installed; global user.name/email unset; repo reachable and
  empty; no init/commit/push yet. Need user confirmation and commit identity.

## 2026-11-09 — Slice 1A implemented (approved)

User approved revised Slice 1A ("go ahead"). Implemented:

- Folder-based agents: `agents/<id>/profile.json`, `memory.jsonl`, `profiles/`.
  System agents migrated: boss, worker; added hr.
- `AgentSpec` fields/validation (slug, tools subset, model, style placeholder,
  source/enabled/version).
- `AgentRegistry`: list/get/create/proposals/approve/reject/delete/restore,
  audit events, legacy migration, trash snapshots.
- `agent_events` table + `data/agent_ledger.jsonl`.
- HR prompt + `DeepSeekLLM.propose_agent`; Boss planning receives assignee list.
- Kernel validates assignee, runs only that agent's tools.
- CLI: `agent list/show/create/proposals/approve/reject/delete/restore/history`.
- Delete requires two exact confirmations; soft-delete; restore.

Live verification:
- 29 tests pass.
- HR proposal `p_e5bd52ef05` → agent `notes` (write_file only).
- Task `t_15fb0257746e` assigned to notes; only write_file granted.
- First verification failed on case-sensitive `file_contains`; fixed to
  case-insensitive default with optional `case_sensitive: true`; reverify → 6/6
  checks, succeeded.
- Wrong delete confirmation aborted; correct confirmations soft-deleted to
  `.trash`; restore succeeded; audit history complete.

No GitHub commit/push yet (identity unset).

## 2026-11-10 — Slice 1A test follow-up + GitHub push

User test:
- One `zuri run` failed immediately with `Connection error.` (no model usage).
  Direct API check + `zuri ping` showed DeepSeek is reachable; retried and the
  same task succeeded: `t_cdf1b1b8cc6c`, assignee notes, 4/4 checks,
  ~$0.001642.
- Deletion abort worked as designed (user typed the REM comments as
  confirmations). Prompts are now clearer (step 1/2, exact text, ABORTED).
- `agent restore notes` while the agent is active now explains "still active"
  instead of an ERROR.
- Added `last`, `verify-last`, `guide`, `ping` so verification does not require
  copying task ids.
- OpenAI SDK retries increased to 3 for transient connection errors.
- Reports now show the last error reason for failed tasks.

GitHub:
- Local git initialized; `user.name=Rehan`,
  `user.email=ElixirOfRehan@users.noreply.github.com`.
- First push rejected: `GH007` because `ra57000rehan@gmail.com` is private.
- Amended to the GitHub noreply email; pushed `main`.
- Remote: initial `76f278c`, docs `304b9bd`.
- `.env`, `data/`, `workspace/` contents, agent memory and trash are ignored.






