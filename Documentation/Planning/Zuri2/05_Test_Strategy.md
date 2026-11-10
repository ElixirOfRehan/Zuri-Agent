# Test Strategy — Zuri Agent

Owner: the assistant. The user gives goals and reads plain-language results; the
user is not expected to run commands or interpret raw logs.

## Principles

1. **Deterministic first.** Logic is tested with fake models/workers so tests do
   not depend on an API call.
2. **Live API second.** Each slice gets a real DeepSeek smoke test.
3. **Adversarial by default.** Every slice includes cases outside the happy path.
4. **Every bug becomes a regression test.** No fix without a test.
5. **Evidence, not claims.** Test results include task ids, artifacts, hashes and
   checks. "It should work" is not a result.

## Test layers

| Layer | What it covers | Tool |
| --- | --- | --- |
| Unit | models, sandbox, paths, redaction, cost math | pytest |
| Integration (deterministic) | storage, verifier, registry, kernel with fake Boss/Worker | pytest |
| Adversarial | wrong confirmations, escapes, tampered files, duplicates, unknown assignees, malformed input | pytest |
| Live smoke | real DeepSeek Boss/Worker end-to-end | `zuri run`, `zuri explain` |
| Regression | every fixed bug keeps its test | pytest |
| Observability | plain-language explainer matches the ledger | `zuri explain` |

## Matrix (current + planned)

### Contract and models
- [x] at least one deliverable
- [x] at least one acceptance test
- [x] test path must match a deliverable
- [x] `file_contains` needs text
- [x] invalid/absolute/traversal paths rejected
- [x] budget bounds
- [x] case-insensitive `file_contains` by default; optional strict mode
- [x] invalid agent id rejected
- [ ] contract with duplicate deliverables
- [ ] extremely large deliverable list
- [ ] malformed Boss JSON (live model + retry)

### Sandbox and tools
- [x] absolute and rooted paths rejected
- [x] `..` traversal rejected
- [x] workspace escape by resolved path rejected
- [x] unknown tool rejected
- [x] tool not granted to the agent rejected
- [x] file write size limit
- [x] read size limit/truncation
- [ ] symlink/junction escape after creation
- [ ] concurrent writes to the same path

### Verifier
- [x] missing ledger artifact fails
- [x] missing file fails
- [x] tampered file (hash mismatch) fails
- [x] empty file fails `file_not_empty`
- [x] case-insensitive contains
- [x] strict case-sensitive contains
- [x] Unicode case folding
- [x] latest verification run only in report
- [x] re-verification is recorded as a new run
- [ ] binary file content check (rejected or handled explicitly)
- [ ] 0-byte vs whitespace-only semantics

### Agent registry and lifecycle
- [x] create/list/get
- [x] duplicate id rejected
- [x] reserved/system id rejected for user creation
- [x] unknown tools rejected
- [x] unknown model rejected
- [x] proposal approve/reject
- [x] double approve rejected
- [x] approve after reject rejected
- [x] delete requires two exact confirmations
- [x] wrong first/second confirmation aborts
- [x] system agent delete rejected
- [x] soft-delete snapshot + restore
- [x] restore while active explains "still active"
- [x] multiple delete/restore cycles
- [x] audit events
- [ ] deleting an agent referenced by a running task
- [ ] restore when multiple snapshots exist with same id
- [ ] profile mutation by the agent itself (must be blocked)

### Agent mind (1B)
- [x] style defaults and validation
- [x] profile version snapshot on update
- [x] rollback creates a new version
- [x] user remember/forget memory
- [x] memory evidence validation
- [x] pending tool/model/style/scope/prompt changes
- [x] approve/reject pending changes
- [x] duplicate pending changes reused
- [x] reflection only after verified tasks
- [x] reflection failure does not undo success
- [x] sensitive style changes become pending, not auto-applied
- [x] trivial "task completed" facts rejected
- [x] near-duplicate SOP notes suppressed
- [x] style/SOP/memory injected into worker prompt
- [x] Boss style/notes injected into planning prompt
- [ ] reflection prompt injection from file content
- [ ] memory cap/compaction over hundreds of tasks

### Policy and resilience (1C)
- [x] goal policy block before planning (live + unit)
- [x] `report_blocked` tool and blocked reasons
- [x] alternative planner uses another agent
- [x] every alternative is verified
- [x] exhausted alternatives produce `blocked` with attempts
- [x] alternatives are filtered by policy
- [x] zero alternatives allowed -> blocked
- [x] `goal_blocked` stops without planning alternatives
- [x] Liar Test remains rejected
- [x] live alternative loop (real planner + real worker)
- [ ] budget exhaustion during alternatives
- [ ] planner invalid JSON live retry
- [ ] concurrent alternative attempts
- [ ] policy false-positive/negative review

### Kernel and assignment
- [x] Boss gets the assignee list
- [x] unknown assignee rejected
- [x] non-assignable system role rejected
- [x] assigned agent gets only its tools
- [x] planner failure becomes a failed task with a reason
- [x] liar test cannot succeed
- [x] budget check after planning
- [ ] worker timeout/partial output
- [ ] concurrent task execution
- [ ] task cancellation
- [ ] approval flow for a `user` contract
- [ ] agent deleted between planning and execution

### API / provider
- [x] missing key rejected clearly
- [x] `zuri ping` live connection
- [x] transient `Connection error.` surfaced; retry succeeded
- [x] SDK retries increased to 3
- [ ] 401/invalid key
- [ ] 402/insufficient balance
- [ ] 429/rate limit
- [ ] timeout
- [ ] malformed/empty response
- [ ] model unavailable

### Storage and evidence
- [x] task/event/artifact/verification/cost tables
- [x] JSONL ledger copy
- [x] content-addressed artifacts
- [x] agent audit ledger
- [x] SQLite migration for `run_id`
- [ ] database corruption/recovery
- [ ] disk full/permission denied
- [ ] very large artifact
- [ ] concurrent DB writers

### Security and secrets
- [x] API key never printed by `doctor`/`ping`/reports
- [x] `sk-...` and `Bearer ...` redaction helper
- [x] `.env` and data ignored by Git
- [ ] malicious file content attempting to redirect the agent
- [ ] prompt injection in read files
- [ ] secret in workspace file accidentally logged

### CLI / understanding
- [x] `guide`
- [x] `last`
- [x] `verify-last`
- [x] `explain` plain language
- [x] `show --json` raw evidence
- [x] `ping`
- [ ] `explain` for failed task with error
- [ ] `explain` for awaiting-approval task
- [ ] Windows cmd and PowerShell parity (paths, quoting)

## Definition of done for each slice

1. All existing tests pass.
2. New deterministic tests for every new behavior and edge case.
3. Live DeepSeek smoke test passes.
4. Liar Test still passes.
5. `zuri explain` gives a plain-language result matching the ledger.
6. The assistant reports: what changed, test counts, task ids, cost, failures,
   and known limitations. The user is not asked to run test commands.
7. Git commit + push (when the repo is configured).

### Web dashboard and queue (1D)
- [x] dashboard HTML loads
- [x] summary endpoint (tasks/agents/queue/cost)
- [x] task detail endpoint
- [x] agent list/detail endpoints
- [x] cost summary + per-status task filter
- [x] POST run enqueues and completes a job (fake runner)
- [x] POST approve enqueues and completes (fake approver)
- [x] run refused without API key
- [x] live web run (real DeepSeek, real task)
- [ ] queue survives server restart
- [ ] multiple workers/concurrency
- [ ] UI authentication / non-loopback binding
- [ ] monthly hard budget cap

## Current status

- 70 automated tests pass.
- Liar Test passes.
- Live verified tasks through Slice 1D; reflection, blocked/alternative paths
  and the web dashboard are live-tested.

## Known limits

- Live model behavior can vary; deterministic fakes cover the logic.
- Network/provider failures are external; the system must fail honestly.
- Concurrency, cancellation and long-running queues are not implemented yet.
- The chat UI is a later slice; `explain` is the current understanding layer.
