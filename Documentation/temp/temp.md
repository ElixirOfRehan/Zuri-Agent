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
- Remote: initial `76f278c`, docs `304b9bd`, mind `9ce411a`, resilience `44a8b5a`,
  dashboard `86a0a33`, engineering `ea946b3`.
- `.env`, `data/`, `workspace/` contents, agent memory and trash are ignored.

## 2026-11-10 — User 1A test passed

User ran the simple path:
- `zuri.cmd guide`
- `zuri.cmd run "Create notes/hello.md with the text 'hello'"` →
  `t_76272e742abb` succeeded; assignee `worker`; 3/3 checks; ~$0.001440.
- `zuri.cmd last` and `zuri.cmd verify-last` both worked.

Slice 1A is verified on the user's machine. Awaiting explicit "confirm 1A"
before starting 1B (Agent Mind).

## 2026-11-10 — Slice 1B implemented (internal)

Scope delivered:
- `AgentSpec` style defaults/validation, `sop_notes`, versioned profile.
- `AgentRegistry`: `update_profile`, `rollback_profile`, `list_versions`,
  memory `load/append/remember/forget`, pending changes `add/list/approve/reject`.
- `MemoryEntry`, `AgentChange`, `ReflectionResult` models.
- `DeepSeekLLM.reflect` + `Reflector`; reflection runs only after a verified
  task and never changes task success.
- Prompt context now includes style, SOP notes and active memory for workers;
  Boss prompt includes its style/notes.
- CLI: `agent mind/remember/forget/style/rollback/changes/approve-change/
  reject-change`; `zuri explain` shows learning summary.
- Reflection safe fields auto-apply (tone/length/language/report_format/SOP
  notes/facts). Sensitive fields (tools/model/scope/system_prompt/risk/
  initiative/approval) become pending changes.
- Facts require evidence from the task/artifacts/checks.
- Trivial "task completed" facts are rejected; near-duplicate SOP notes are
  suppressed; duplicate pending changes are reused.

Bugs found and fixed during testing:
1. Reflection auto-applied `approval=balanced` and `initiative=act`; now
   sensitive style becomes a pending change. Live task `t_9154c52019c9`
   confirmed the pending change and no auto-apply.
2. Reflection wrote trivial "task completed" facts; now filtered. Live task
   `t_fdb37ee10075` added only a useful lesson.
3. Near-duplicate SOP notes; now similarity check (>=0.8) suppresses them.
4. Windows `os.replace` PermissionError on memory rewrite; atomic write now
   retries and falls back to in-place write.
5. Workers did not see style/memory; now injected into prompts.

Verification:
- 58 tests pass.
- Live verified tasks: `t_afe545433cd1`, `t_9154c52019c9`, `t_235d6dc2a23a`,
  `t_fdb37ee10075`.
- Style/remember/forget/rollback/changes/reject-change tested live.
- Liar Test still passes; API ping OK.

Awaiting user confirmation of 1B before 1C.

## 2026-11-10 — Slice 1C implemented (internal)

Scope delivered:
- `report_blocked` control tool available to every agent; reasons:
  policy_legal, missing_input, missing_access, tool_unavailable,
  external_failure, ambiguity.
- `WorkerOutcome` carries blocked reason/detail/needed/goal_blocked.
- `Policy` hard stops for disallowed goals and alternatives (credential theft,
  malware, license/DRM bypass, unauthorized access, destructive disk/delete).
- `DeepSeekLLM.plan_alternatives`: up to 3 safe alternatives with another
  agent, different approach, smaller steps, or user input.
- Kernel resilience loop: initial attempt + up to `budget.max_attempts`
  alternatives; verifies every attempt; agent can change; blocked status with
  full attempt report. Policy/legal goal stops immediately.
- `explain`/`last`/`show` show attempts, reason and what is needed.
- `verify` refuses blocked tasks with a clear message.

Live tests:
- Policy block: `t_1b6d4837edff` (credential theft) blocked before planning,
  zero cost.
- Resilience loop: `t_5c896fd1d26b` — first attempt simulated blocked, real
  DeepSeek planner proposed 3 alternatives, real worker succeeded on attempt 2;
  file verified; ~$0.001904. Report/explain show both attempts.
- Test-only `assistant` agent was soft-deleted with two confirmations.

Verification:
- 67 tests pass (policy, blocked tool, alternative agent, exhaustion,
  alternative policy filter, zero alternatives, goal_blocked, liar).
- Liar Test still passes.
- No illegal/ToS bypass: policy block stops; alternatives are filtered.

Awaiting user confirmation of 1C before 1D.

## 2026-11-10 — Slice 1D implemented (internal)

Scope delivered:
- FastAPI local dashboard (`app/web.py`) with inline HTML/CSS/JS:
  chat input, task list/detail, checks/artifacts/attempts/timeline, agent mind,
  approvals, cost ledger.
- In-process one-at-a-time `JobQueue` (`app/scheduler.py`); UI and approvals
  return job ids and poll.
- `Storage.cost_summary()` total/monthly/by-agent/recent; `list_tasks_by_status`.
- CLI `serve`, `approvals`, `costs`; guide mentions the dashboard.
- Dependencies: fastapi, uvicorn; dev httpx.
- Tests: FastAPI endpoints with fake runner/approver, API-key refusal, cost
  summary/status filter.

Live test:
- Started `zuri serve` on 127.0.0.1:8766.
- GET `/` 200, title present.
- POST `/api/run` → job succeeded → `t_2bc2b0ccc51c`; assignee notes; 3/3
  checks; 1 artifact; report verified; ~$0.001924.
- `/api/summary` returned 20 tasks, 4 agents, total cost.
- Server stopped; port free.

Limits:
- Localhost only, no authentication.
- In-memory queue; restart loses queued jobs.
- One worker; basic UI; cost cap informational (per-task budgets enforced).

Verification: 70 tests pass; Liar Test still passes.
Awaiting user confirmation of 1D; next choice Engineering vs UI polish.

## 2026-11-10 — Slice 2 Engineering + tool layer implemented (internal)

Delivered:
- `run_command` tool (structured `program` + `arguments`, no shell, workspace
  cwd, allowlist python/node/npm/git/pytest/rea, timeout, output limit).
- Blocked: unknown programs, absolute/traversal args, git network/global
  config, npm install/publish/exec/ci/link.
- Every command recorded as `command_output` with exit code/stdout/stderr
  (bounded) and duration.
- Shell can be disabled with `ZURI_SHELL_ENABLED=0`; allowlist configurable.
- Seeded `engineering` agent (deepseek-v4-pro) with list/read/write/run_command
  and an engineering SOP; HR may grant run_command for code/test roles.
- README security warning: not an OS sandbox; code runs with user permissions.
- Fixed Windows console encoding crash in `show --json` by reconfiguring CLI
  output to UTF-8.

Live proof:
- `t_69bc923bf609`: engineering assigned; wrote work/hello.py; ran
  `python work/hello.py` (exit 0, stdout `hello from engineering`); wrote
  work/run.txt; verifier 6/6; ~$0.006691; command_output event recorded.
- `rea --version` reachable via run_command; toolchain git/pytest/npm versions
  tested.
- 84 tests pass; Liar Test still passes.

Awaiting user confirmation of Slice 2; next choice OpenCode/QA vs UI polish.

## 2026-11-10 — Slice 2B OpenCode + QA implemented (internal)

Delivered:
- `run_opencode` tool for Engineering:
  - `opencode run --format json --model ... --dir <workspace> --pure`,
  - controlled config: edit allow; bash/network/external/websearch/task deny;
    REA MCP disabled; project config disabled,
  - captures text/session/tokens/cost; records `opencode_run` evidence and adds
    cost to the Zuri ledger.
- QA reviewer (`qa` system profile, not assignable):
  - reviews verified engineering tasks from artifacts, contents, checks,
    command evidence and worker messages,
  - returns verdict/issues/notes; stored as `qa_review`; shown in report,
    explain, dashboard; advisory only.
  - auto-runs after success for agents with `run_command`; disabled with
    `ZURI_QA_ENABLED=0`; model configurable.
- HR prompt can grant `run_opencode` for code/test roles.

Live:
- OpenCode created `work/opencode.txt` (`opencode works.`) in 25s; cost
  ~$0.006080; restricted permissions; file verified.
- QA review of `t_69bc923bf609`: pass with notes; report/explain updated.
- Auto QA on `t_419984968c39`: pass; engineering mind updated.
- 93 tests pass.

Security: OpenCode edits workspace only; no shell/network; QA is read-only and
advisory. Engineering run_command still runs with user permissions.

Awaiting user confirmation of 2B; next choice UI polish vs parallel departments.






## 2026-11-10 — 1A confirmed; understanding + test ownership

User confirmed 1A but said they do not understand what is happening from
command output and do not want command homework. They want a chat-like
experience eventually; for now, build internals and own all testing.

Added:
- `zuri explain` / `zuri explain <id>`: plain-language story of the task:
  request, assignee, plan, tools used, files/evidence, checks, result, cost.
  No raw JSON, no task-id copying needed.
- `zuri guide` now includes explain.
- Test strategy: `Documentation/Planning/Zuri2/05_Test_Strategy.md` with unit,
  integration, adversarial, live, regression, observability layers and an
  edge-case matrix.
- `tests/test_edge_cases.py`: 15 additional adversarial tests (missing/
  tampered/empty files, Unicode case, verification runs, registry errors,
  invalid ids/models/tools, path escape, cost, redaction, multiple restores,
  planner failure).
- 44 tests pass. Liar Test passes. `zuri ping` OK.
- Failed task `t_a5bc72636dbb` explain shows `Connection error.`; retry task
  `t_cdf1b1b8cc6c` succeeded.
- The assistant owns testing from now on; the user gives goals and reads the
  plain-language result. The chat UI comes after the internals.

Next: implement Slice 1B (Agent Mind) internally.








