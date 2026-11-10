# Slice 1C — Resilience and creative problem solving v1

Status: planned; starts only after Slice 1B is confirmed.
Depends on: 1A (agents/assignees) and 1B (profile/memory).

## 1. Goal

When a direct method is blocked, the agent does not stop at "can't do it". It
tries bounded, compliant alternatives: another tool, a different source, a
smaller sub-task, another agent, or a request for the missing input. If nothing
works, it reports exactly what was tried and what is needed.

## 2. Blocked reasons

The worker returns one of:

- `policy_legal` — the goal or method is disallowed
- `missing_input` — data/credentials/information missing
- `missing_access` — permission/account/API access missing
- `tool_unavailable` — tool/engine unavailable
- `external_failure` — service/network failure
- `ambiguity` — request cannot be executed without clarification

## 3. Alternative loop (bounded)

1. Generate at least 3 alternatives with: approach, required tools, feasibility,
   cost, risk, time.
2. Reject illegal/ToS/destructive options before execution.
3. Try the safest viable alternative within the task budget.
4. If needed, decompose into sub-tasks and assign them to other agents; then
   combine the results.
5. Ask the user only when blocked by missing input/approval.
6. If everything fails: status `blocked`, with a full attempt report.

Limits: max alternatives, max attempts, token/cost/time budgets, no infinite
loops. Verification still applies to each alternative's output.

## 4. Hard boundaries

- Never bypass law, platform rules, permissions or safety policy.
- If the **goal itself** is disallowed, stop and explain; do not look for a
  workaround.
- If a **method** is blocked, a compliant alternative is allowed.
- No fake success; blocked is a valid, honest result.

## 5. Data and files

- `app/resilience.py` — alternative planner, scoring, policy filter, loop.
- `app/models.py` — `BlockedReason`, `Alternative`, `AttemptRecord`.
- `app/worker.py` / `app/llm.py` — worker returns structured blocked outcome.
- `app/kernel.py` — runs the alternative loop and records attempts.
- `app/cli.py` — `zuri show` displays attempts and the final blocked report.
- `app/policy.py` — hard-block rules for illegal/ToS/destructive actions.
- Tests: `tests/test_resilience.py`, `tests/test_policy.py`.

## 6. Report format

The user sees:

```
Status: blocked
Reason: missing_access
Tried:
  1. direct API — 401 unauthorized
  2. browser export — approval required
  3. manual CSV import — needs file from user
Need from you: <specific input/approval>
```

No vague "failed"; every attempt has evidence.

## 7. Tests

- A fake blocked worker triggers alternative planning.
- An illegal alternative is rejected before execution.
- Budget exhaustion stops the loop and reports blocked.
- Successful alternative completes and verifies.
- Sub-task delegation records parent/child links.
- The final report includes every attempt with evidence.

## 8. Acceptance

1. Ask for a task whose direct method is blocked (simulated tool failure).
2. The agent tries alternatives and reports which worked or why not.
3. If the goal is disallowed, it stops immediately and explains.
4. Nothing is marked succeeded without verification.

## 9. Out of scope

Autonomous external account creation, bypassing platform protections, and
unbounded self-directed exploration. Creativity stays inside policy and budget.
