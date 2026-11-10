# Zuri Agent — Project Rules

## Mission

Build a local-first AI company: a Boss agent that plans and delegates, and
specialist agents that do focused work under independent verification.

## Non-negotiable rules

1. **Evidence-first.** Every task result must point to observable evidence:
   files, hashes, command output, diffs, screenshots, test results, API
   responses.
2. **The Boss cannot mark success.** Only the kernel/verifier can move a task
   to `succeeded`, after acceptance checks pass.
3. **No silent work.** Every tool call, action, and artifact is recorded in an
   append-only ledger with agent, time, inputs (redacted), output summary and
   evidence IDs.
4. **Secrets never leak.** API keys and credentials live in `.env` or a local
   secret store, never in prompts, logs, reports, or git.
5. **Sandbox first.** Agents work inside `workspace/`; external effects,
   spending, publishing and destructive commands require approval.
6. **Honest failure.** Missing data or failed checks produce `failed` or
   `blocked`, never a fake success.
7. **One slice at a time.** Plan → user approves → implement one slice → user
   tests → user confirms → next slice.

## Working memory

- `Documentation/temp/CURRENT.md` — compact active tracker.
- `Documentation/temp/temp.md` — detailed investigation/history.
- `Documentation/temp/FUTURE.md` — ideas not scheduled.
- `Documentation/Planning/` — plans for approval.
- `Documentation/Context/` — confirmed architecture only.

## Style

Simple, explicit, observable. Prefer boring deterministic code around the
models. Models make decisions; code enforces process, permissions, budgets and
verification.
