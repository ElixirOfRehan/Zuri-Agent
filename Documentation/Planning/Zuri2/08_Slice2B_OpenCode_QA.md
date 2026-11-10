# Slice 2B — OpenCode delegation and QA reviewer

Status: **implemented 2026-11-10 — awaiting user confirmation**
Depends on: Slice 2 (Engineering + tool layer).

## What was added

- `run_opencode` tool for the Engineering agent:
  - invokes `opencode run --format json --model ... --dir <workspace> --pure`,
  - controlled `OPENCODE_CONFIG_CONTENT`: edit allow, bash/network/external/
    websearch/task deny, REA MCP disabled,
  - project config disabled,
  - captures OpenCode text, session id, tokens and cost; adds cost to the Zuri
    ledger; logs `opencode_run` evidence.
- Seeded `qa` reviewer profile (system, not assignable).
- `QAReviewer` + `DeepSeekLLM.review_task`:
  - reviews verified engineering tasks (artifacts, contents, checks, command
    evidence, worker messages),
  - returns `{verdict: pass|fail, issues, notes}`,
  - stored as `qa_review`, shown in report, `explain`, and dashboard,
  - advisory only; the verifier still owns success.
- Auto QA after success for assignees with `run_command` (Engineering).
- QA can be disabled with `ZURI_QA_ENABLED=0`; models configurable.
- HR prompt allows `run_opencode` for code/test roles.

## Live proof

- OpenCode tool: created `work/opencode.txt` with `opencode works.`; exit 0;
  session recorded; cost ~$0.006080; shell/network denied; file verified.
- QA review of engineering task `t_69bc923bf609`: verdict `pass` with notes;
  report/explain updated.
- Auto QA on task `t_419984968c39`: succeeded, QA `pass`; engineering mind
  updated.
- 93 automated tests pass.

## Security

- OpenCode has edit permission in the workspace only; no shell, network,
  external directories, web search or subagents.
- QA is read-only (no tools; reviews content/evidence) and advisory.
- Not an OS sandbox; the engineering agent's own `run_command` still runs with
  user permissions.

## Limits

- QA does not execute tools; it reviews recorded evidence.
- OpenCode sessions are not reused across calls.
- No parallel departments yet.
