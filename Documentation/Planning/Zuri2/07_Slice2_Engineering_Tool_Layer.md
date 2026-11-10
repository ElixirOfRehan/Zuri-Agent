# Slice 2 — Engineering department and tool layer

Status: **implemented 2026-11-10 — awaiting user confirmation**
Depends on: Slice 1D.

## What was added

- `run_command` tool:
  - structured `program` + `arguments` (no shell),
  - workspace cwd,
  - allowlist: python, python3, py, node, npm, git, pytest, rea,
  - blocks absolute paths and `..` traversal in arguments,
  - blocks network/remote actions (`git push/pull/fetch/clone/remote/submodule`,
    global/system git config, npm install/publish/exec/ci/link),
  - timeout 1–600s, output limit, command_output evidence event,
  - can be disabled with `ZURI_SHELL_ENABLED=0`.
- Seeded **Engineering** agent:
  - tools: list_dir, read_file, write_file, run_command,
  - model: deepseek-v4-pro,
  - SOP: inspect, implement, test, verify, report; REA via CLI; honest blocked.
- HR prompt now allows run_command for code/test/REA roles.
- Tests: command execution, blocked program/paths, git/npm policy, timeout,
  shell disabled, output truncation, REA/toolchain reachability, agent profile.
- UTF-8-safe CLI output on Windows (fix for `show --json`).

## Files

- `app/tools.py` — run_command, policy, output logging.
- `app/config.py` — shell_enabled, allowed_commands.
- `agents/engineering/profile.json` + profiles.
- `agents/hr/profile.json` — run_command allowed.
- `.env.example` — shell settings.
- `tests/test_command_tool.py`.
- `app/cli.py` — UTF-8 output fix.

## Live proof

- Engineering agent appears in `agent list`.
- Task `t_69bc923bf609`:
  - assignee engineering,
  - wrote `work/hello.py`,
  - ran `python work/hello.py` → exit 0, stdout `hello from engineering`,
  - wrote `work/run.txt`,
  - verifier 6/6 checks, report verified,
  - ~$0.006691,
  - command_output event records program/args/exit/stdout/duration.
- `rea --version` is reachable through run_command (test).
- 84 automated tests pass.

## Security

This is not an OS sandbox. Python/Node code runs with the user's permissions and
can access files/network. The allowlist and path/command policy reduce casual
risk only. Use trusted tasks and review command_output events.

## Not included yet

OpenCode integration, a separate QA/review agent, parallel departments, browser
and HTTP tools, OS-level sandboxing, per-command approval prompts.
