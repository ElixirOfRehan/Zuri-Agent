# Slice 1D — Company kernel and local dashboard

Status: **implemented 2026-11-10 — awaiting user confirmation**

## What was added

- **Local chat-style dashboard** (`zuri serve`):
  - send a request and watch the job run,
  - task list with status, assignee, checks, attempts and cost,
  - task detail with plain report, artifacts, checks, resilience attempts and
    timeline,
  - agent mind viewer (style, SOP notes, memory, versions, pending changes),
  - approvals list with an Approve button,
  - cost ledger.
- **One-at-a-time job queue**: `app/scheduler.py` with an in-process
  `ThreadPoolExecutor`. UI submissions and approvals return a job id; the UI
  polls it. The queue is in memory, not durable across restarts.
- **Cost ledger**: `Storage.cost_summary()` with total, monthly, by-agent and
  recent-task costs; CLI `zuri costs`.
- **Approvals inbox**: CLI `zuri approvals`; UI approval cards.
- **Web API**: `/api/summary`, `/api/tasks/{id}`, `/api/agents`,
  `/api/agents/{id}`, `/api/costs`, `/api/run`, `/api/jobs/{id}`,
  `/api/tasks/{id}/approve`.
- **Tests**: FastAPI endpoints with fake runner/approver, cost summary/status
  filtering, plus a live web run.

## Files

- `app/web.py` — FastAPI app, HTML/CSS/JS, endpoints.
- `app/scheduler.py` — in-process job queue.
- `app/storage.py` — `cost_summary`, `list_tasks_by_status`.
- `app/cli.py` — `serve`, `approvals`, `costs`.
- `tests/test_web.py`, `tests/test_storage_costs.py`.
- `pyproject.toml` — fastapi, uvicorn, httpx.

## Live proof

- Server on `127.0.0.1:8766`; page 200.
- `POST /api/run` → job succeeded → task `t_2bc2b0ccc51c`, assignee notes,
  3/3 checks, 1 artifact, report verified, ~$0.001924.
- Summary returned 20 tasks, 4 agents, total cost.
- Server stopped; port free.

## Limits

- Localhost only, no authentication; do not expose it on a network.
- One worker; no durable queue across server restarts.
- Basic UI; polish comes later.
- Cost cap is informational (per-task budgets remain enforced); no monthly
  hard cap yet.

## Acceptance for the user

Open the dashboard, send a safe request, watch the job finish, inspect the task
detail and agent mind. Approve a task if one appears. No command copying.
