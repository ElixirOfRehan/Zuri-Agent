from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .config import Settings
from .kernel import Kernel
from .scheduler import JobQueue


class RunRequest(BaseModel):
    request: str


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Zuri Agent</title>
<style>
  :root {
    --bg: #0f1115; --panel: #171a21; --panel2: #1e222b; --text: #e8ecf1;
    --muted: #8b95a5; --line: #2a303c; --accent: #6ea8ff; --good: #3ddc97;
    --bad: #ff6b6b; --warn: #ffcc66; --radius: 12px;
    --mono: ui-monospace, SFMono-Regular, Consolas, monospace;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text);
    font: 14px/1.5 system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }
  header { padding: 18px 22px; border-bottom: 1px solid var(--line);
    display: flex; gap: 14px; align-items: center; flex-wrap: wrap;
    background: linear-gradient(180deg, #151922, #0f1115); }
  h1 { font-size: 18px; margin: 0; letter-spacing: .2px; }
  .sub { color: var(--muted); font-size: 12px; }
  .chips { margin-left: auto; display: flex; gap: 8px; flex-wrap: wrap; }
  .chip { border: 1px solid var(--line); background: var(--panel);
    padding: 5px 10px; border-radius: 999px; font-size: 12px; color: var(--muted); }
  .chip b { color: var(--text); font-weight: 600; }
  main { display: grid; grid-template-columns: 360px 1fr; gap: 16px;
    padding: 16px; max-width: 1500px; margin: 0 auto; }
  @media (max-width: 980px) { main { grid-template-columns: 1fr; } }
  .stack { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
  .card { background: var(--panel); border: 1px solid var(--line);
    border-radius: var(--radius); padding: 14px; }
  .card h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .6px;
    color: var(--muted); margin: 0 0 10px; }
  textarea { width: 100%; min-height: 88px; resize: vertical; background: var(--panel2);
    color: var(--text); border: 1px solid var(--line); border-radius: 10px;
    padding: 10px; font: inherit; outline: none; }
  textarea:focus { border-color: var(--accent); }
  button { background: var(--accent); color: #0b1220; border: 0; border-radius: 9px;
    padding: 8px 13px; font-weight: 700; cursor: pointer; }
  button:hover { filter: brightness(1.08); }
  button.ghost { background: var(--panel2); color: var(--text);
    border: 1px solid var(--line); font-weight: 600; }
  button.small { padding: 4px 8px; font-size: 12px; }
  .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .muted { color: var(--muted); }
  .list { display: flex; flex-direction: column; gap: 8px; }
  .task { text-align: left; width: 100%; background: var(--panel2);
    border: 1px solid var(--line); border-radius: 10px; padding: 9px 10px;
    color: var(--text); font: inherit; cursor: pointer; }
  .task:hover { border-color: var(--accent); }
  .task .top { display: flex; gap: 8px; align-items: center; }
  .task .req { color: var(--muted); font-size: 12px; margin-top: 3px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .badge { font-size: 11px; padding: 2px 7px; border-radius: 999px;
    border: 1px solid var(--line); color: var(--muted); }
  .succeeded { color: var(--good); border-color: #2a5f49; }
  .failed { color: var(--bad); border-color: #6a2a2a; }
  .blocked { color: var(--warn); border-color: #6a572a; }
  .running, .queued { color: var(--accent); border-color: #2a496a; }
  .awaiting_approval { color: var(--warn); border-color: #6a572a; }
  .detail h2 { color: var(--text); text-transform: none; letter-spacing: 0;
    font-size: 16px; margin: 0 0 6px; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  @media (max-width: 760px) { .grid2 { grid-template-columns: 1fr; } }
  .kv { display: grid; grid-template-columns: 120px 1fr; gap: 4px 10px;
    font-size: 13px; }
  .kv .k { color: var(--muted); }
  ul.clean { margin: 6px 0 0 18px; padding: 0; }
  ul.clean li { margin: 3px 0; }
  pre { background: #0b0e13; border: 1px solid var(--line); border-radius: 10px;
    padding: 10px; overflow: auto; font: 12px/1.45 var(--mono); white-space: pre-wrap; }
  .timeline { max-height: 360px; overflow: auto; font: 12px/1.45 var(--mono);
    border-top: 1px solid var(--line); margin-top: 8px; }
  .ev { padding: 4px 0; border-bottom: 1px solid #1d222b; color: var(--muted); }
  .ev b { color: var(--text); font-weight: 600; }
  .job { font-size: 12px; color: var(--muted); min-height: 18px; }
  .err { color: var(--bad); }
  .pill { background: var(--panel2); border: 1px solid var(--line);
    border-radius: 999px; padding: 3px 8px; font-size: 12px; color: var(--muted); }
  .agent { display: flex; gap: 8px; align-items: center; justify-content: space-between;
    background: var(--panel2); border: 1px solid var(--line); border-radius: 10px;
    padding: 7px 9px; }
  .agent button { background: transparent; color: var(--accent); padding: 2px 4px; }
  .costbar { height: 8px; background: #0b0e13; border-radius: 99px; overflow: hidden;
    border: 1px solid var(--line); margin: 6px 0; }
  .costbar span { display: block; height: 100%; background: var(--accent); width: 0; }
  .hint { color: var(--muted); font-size: 12px; }
</style>
</head>
<body>
<header>
  <div>
    <h1>Zuri Agent</h1>
    <div class="sub">Boss plans. Workers act. The verifier decides.</div>
  </div>
  <div class="chips">
    <div class="chip">API <b id="api-key">?</b></div>
    <div class="chip">Queue <b id="queue">?</b></div>
    <div class="chip">Month <b id="month-cost">?</b></div>
    <div class="chip">Total <b id="total-cost">?</b></div>
  </div>
</header>
<main>
  <div class="stack">
    <section class="card">
      <h2>Talk to Zuri</h2>
      <textarea id="prompt" placeholder="Tell Zuri what to do... e.g. Create work/notes.md with a short checklist."></textarea>
      <div class="row" style="margin-top:8px">
        <button id="send" onclick="submitRun()">Send</button>
        <span class="job" id="job">Ready.</span>
      </div>
    </section>

    <section class="card">
      <h2>Approvals</h2>
      <div id="approvals" class="list"><div class="muted">No approvals waiting.</div></div>
    </section>

    <section class="card">
      <h2>Agents</h2>
      <div id="agents" class="list"></div>
    </section>

    <section class="card">
      <h2>Cost</h2>
      <div id="cost" class="hint">Loading...</div>
    </section>
  </div>

  <div class="stack">
    <section class="card">
      <h2>Tasks</h2>
      <div id="tasks" class="list"><div class="muted">Loading...</div></div>
    </section>
    <section class="card detail" id="detail">
      <h2>Task detail</h2>
      <div class="muted">Pick a task to see what happened, or send a new request.</div>
    </section>
  </div>
</main>
<script>
const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = (v) => "$" + Number(v || 0).toFixed(6);
let currentTask = null;

async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || ("HTTP " + response.status));
  return data;
}

function badge(status) {
  return `<span class="badge ${esc(status)}">${esc(status)}</span>`;
}

function renderSummary(data) {
  $("api-key").textContent = data.api_key_set ? "set" : "missing";
  $("queue").textContent = `${data.queue.running} running / ${data.queue.queued} queued`;
  $("month-cost").textContent = money(data.cost.monthly_cost_usd);
  $("total-cost").textContent = money(data.cost.total_cost_usd);
  const tasks = data.tasks || [];
  $("tasks").innerHTML = tasks.length ? tasks.map((t) => `
    <button class="task" onclick="showTask('${esc(t.id)}')">
      <div class="top">${badge(t.status)}<span class="pill">${esc(t.id)}</span>
        <span class="muted">${esc(t.assignee || "-")}</span></div>
      <div class="req">${esc(t.request)}</div>
      <div class="row" style="margin-top:4px">
        <span class="muted">checks ${t.checks_passed}/${t.checks_total}</span>
        <span class="muted">${money(t.cost_usd)}</span>
        ${t.attempts > 1 ? `<span class="pill">${t.attempts} attempts</span>` : ""}
        ${t.reason ? `<span class="muted err">${esc(t.reason)}</span>` : ""}
      </div>
    </button>`).join("") : `<div class="muted">No tasks yet.</div>`;

  const approvals = tasks.filter((t) => t.status === "awaiting_approval");
  $("approvals").innerHTML = approvals.length ? approvals.map((t) => `
    <div class="agent">
      <div><div>${badge(t.status)} <b>${esc(t.id)}</b></div>
      <div class="muted">${esc(t.request)}</div></div>
      <button class="small" onclick="approveTask('${esc(t.id)}')">Approve</button>
    </div>`).join("") : `<div class="muted">No approvals waiting.</div>`;

  const agents = data.agents || [];
  $("agents").innerHTML = agents.map((a) => `
    <div class="agent">
      <div><b>${esc(a.id)}</b> <span class="muted">v${esc(a.version)}</span>
        <div class="muted">${esc(a.description || "")}</div></div>
      <button onclick="showAgent('${esc(a.id)}')">Mind</button>
    </div>`).join("") || `<div class="muted">No agents.</div>`;

  const cost = data.cost;
  const byAgent = (cost.by_agent || []).slice(0, 5).map((a) =>
    `<div class="row" style="justify-content:space-between">
      <span>${esc(a.agent)}/${esc(a.model)}</span>
      <span class="muted">${a.calls} calls · ${money(a.cost_usd)}</span>
    </div>`).join("");
  $("cost").innerHTML = `
    <div>Total: <b>${money(cost.total_cost_usd)}</b> · ${Number(cost.total_tokens).toLocaleString()} tokens</div>
    <div class="muted">This month: ${money(cost.monthly_cost_usd)}</div>
    <div class="costbar"><span style="width:${Math.min(100, (cost.total_cost_usd || 0) * 100)}%"></span></div>
    ${byAgent}`;
}

async function refresh() {
  try { renderSummary(await api("/api/summary")); }
  catch (error) { $("job").innerHTML = `<span class="err">${esc(error.message)}</span>`; }
}

async function submitRun() {
  const request = $("prompt").value.trim();
  if (!request) return;
  $("send").disabled = true;
  $("job").textContent = "Queued...";
  try {
    const job = await api("/api/run", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({request})
    });
    await pollJob(job.job_id);
    $("prompt").value = "";
  } catch (error) {
    $("job").innerHTML = `<span class="err">${esc(error.message)}</span>`;
  } finally { $("send").disabled = false; }
}

async function approveTask(taskId) {
  $("job").textContent = "Approving...";
  try {
    const job = await api(`/api/tasks/${encodeURIComponent(taskId)}/approve`, {method: "POST"});
    await pollJob(job.job_id);
  } catch (error) { $("job").innerHTML = `<span class="err">${esc(error.message)}</span>`; }
}

async function pollJob(jobId) {
  for (;;) {
    const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    $("job").textContent = `${job.kind}: ${job.status}` + (job.error ? ` — ${job.error}` : "");
    if (job.status === "succeeded") {
      await refresh();
      if (job.task_id) await showTask(job.task_id);
      return job;
    }
    if (job.status === "failed") throw new Error(job.error || "job failed");
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}

function list(items, render, empty) {
  if (!items || !items.length) return `<div class="muted">${empty}</div>`;
  return `<ul class="clean">${items.map(render).join("")}</ul>`;
}

async function showTask(id) {
  try {
    const data = await api(`/api/tasks/${encodeURIComponent(id)}`);
    currentTask = id;
    const task = data.task, contract = data.contract || {};
    const checks = data.verifications || [];
    const artifacts = data.artifacts || [];
    const attempts = data.attempts || [];
    const mind = data.mind_update;
    const policy = data.policy_block;
    const end = data.resilience_end;
    const events = (data.events || []).slice(-40).reverse();
    const checksHtml = checks.map((c) =>
      `<li><span class="${c.passed ? '' : 'err'}">[${c.passed ? 'PASS' : 'FAIL'}]</span>
        ${esc(c.name)}: ${esc(c.detail)}</li>`).join("");
    const artifactsHtml = artifacts.map((a) =>
      `<li>${esc(a.path)} — ${a.bytes} bytes, sha256 ${esc(a.sha256.slice(0, 16))}…</li>`).join("");
    const attemptsHtml = attempts.map((a) =>
      `<li>#${a.attempt} ${esc(a.agent)} [${esc(a.approach)}]: ${a.success ? "succeeded" : "failed"}
        ${a.detail ? "— " + esc(a.detail) : ""}</li>`).join("");
    const eventsHtml = events.map((e) =>
      `<div class="ev"><b>${esc(e.agent)}/${esc(e.type)}</b> ${esc(JSON.stringify(e.data)).slice(0, 300)}</div>`).join("");
    $("detail").innerHTML = `
      <div class="row" style="justify-content:space-between">
        <div><h2>${esc(task.id)}</h2><div class="muted">${esc(task.request)}</div></div>
        ${badge(task.status)}
      </div>
      <div class="grid2" style="margin-top:12px">
        <div>
          <div class="kv">
            <span class="k">Assignee</span><span>${esc(contract.assignee || "-")}</span>
            <span class="k">Goal</span><span>${esc(contract.objective || "-")}</span>
            <span class="k">Risk</span><span>${esc(contract.risk || "-")} / ${esc(contract.approval_class || "-")}</span>
            <span class="k">Cost</span><span>${money(data.total_cost_usd)} · ${Number(data.total_tokens).toLocaleString()} tokens</span>
          </div>
          <h2 style="margin-top:14px">Checks</h2>
          ${list(checks, (c) => `<li><span class="${c.passed ? '' : 'err'}">[${c.passed ? 'PASS' : 'FAIL'}]</span> ${esc(c.name)}: ${esc(c.detail)}</li>`, "No checks.")}
          <h2 style="margin-top:14px">Artifacts</h2>
          ${list(artifacts, (a) => `<li>${esc(a.path)} — ${a.bytes} bytes, sha256 ${esc(a.sha256.slice(0, 16))}…</li>`, "No artifacts.")}
          <h2 style="margin-top:14px">Attempts</h2>
          ${list(attempts, (a) => `<li>#${a.attempt} ${esc(a.agent)} [${esc(a.approach)}]: ${a.success ? "succeeded" : "failed"}${a.detail ? " — " + esc(a.detail) : ""}</li>`, "No retries.")}
          ${policy ? `<div class="err" style="margin-top:8px">Policy block: ${esc(policy.reason)}</div>` : ""}
          ${end ? `<div class="err" style="margin-top:8px">Blocked: ${esc(end.reason)}. Need: ${esc(end.needed || "user input")}</div>` : ""}
          ${mind ? `<div class="muted" style="margin-top:8px">Mind updated: ${mind.facts} facts, ${mind.sop_notes} SOP notes, ${mind.suggestions} pending suggestions (v${mind.version}).</div>` : ""}
        </div>
        <div>
          <h2>Plain report</h2>
          <pre>${esc(task.report || "No report yet.")}</pre>
          <h2 style="margin-top:12px">Timeline</h2>
          <div class="timeline">${eventsHtml || '<div class="muted">No events.</div>'}</div>
        </div>
      </div>`;
  } catch (error) {
    $("detail").innerHTML = `<h2>Task detail</h2><div class="err">${esc(error.message)}</div>`;
  }
}

async function showAgent(id) {
  try {
    const data = await api(`/api/agents/${encodeURIComponent(id)}`);
    const spec = data.spec;
    const style = Object.entries(spec.style || {}).map(([k, v]) => `${k}=${v}`).join(", ") || "defaults";
    const memory = data.memory || [];
    const changes = data.changes || [];
    $("detail").innerHTML = `
      <div class="row" style="justify-content:space-between">
        <div><h2>${esc(spec.id)} — ${esc(spec.name)}</h2>
        <div class="muted">v${esc(spec.version)} · ${esc(spec.source)} · ${esc(spec.model || "-")}</div></div>
        <span class="pill">${esc(spec.tools.join(", ") || "no tools")}</span>
      </div>
      <div class="grid2" style="margin-top:12px">
        <div>
          <h2>Style</h2><div>${esc(style)}</div>
          <h2 style="margin-top:12px">SOP notes</h2>
          ${list(spec.sop_notes, (n) => `<li>${esc(n)}</li>`, "No SOP notes.")}
          <h2 style="margin-top:12px">Charter</h2>
          <pre>${esc(spec.system_prompt)}</pre>
        </div>
        <div>
          <h2>Memory</h2>
          ${list(memory, (m) => `<li>[${esc(m.kind)}] ${esc(m.text)} <span class="muted">(${esc((m.evidence || []).join(", "))})</span></li>`, "No memory.")}
          <h2 style="margin-top:12px">Pending changes</h2>
          ${list(changes, (c) => `<li>${esc(c.kind)}: ${esc(c.proposed)} — ${esc(c.reason || "")}</li>`, "None.")}
          <h2 style="margin-top:12px">Versions</h2><div>${esc((data.versions || []).join(", "))}</div>
        </div>
      </div>`;
  } catch (error) {
    $("detail").innerHTML = `<div class="err">${esc(error.message)}</div>`;
  }
}

refresh();
setInterval(refresh, 8000);
</script>
</body>
</html>"""


def _kernel(settings: Settings) -> Kernel:
    return Kernel(settings)


def _task_summary(kernel: Kernel, task_id: str) -> dict | None:
    task = kernel.storage.get_task(task_id)
    if task is None:
        return None
    contract = json.loads(task["contract_json"]) if task.get("contract_json") else {}
    checks = kernel.storage.get_verifications(task_id)
    passed = sum(1 for item in checks if item["passed"])
    events = kernel.storage.get_events(task_id)
    attempts = [event["data"] for event in events if event["type"] == "resilience_attempt"]
    end = next(
        (
            event["data"]
            for event in reversed(events)
            if event["type"] == "resilience_exhausted"
        ),
        None,
    )
    policy = next(
        (
            event["data"]
            for event in reversed(events)
            if event["type"] == "policy_block"
        ),
        None,
    )
    return {
        "id": task["id"],
        "created_at": task["created_at"],
        "status": task["status"],
        "request": task["request"],
        "assignee": contract.get("assignee"),
        "checks_passed": passed,
        "checks_total": len(checks),
        "cost_usd": kernel.storage.total_cost(task_id),
        "attempts": len(attempts),
        "reason": (end or {}).get("reason") or (policy or {}).get("reason"),
    }


def create_app(settings: Settings | None = None, runner=None, approver=None, max_workers: int = 1) -> FastAPI:
    app_settings = settings or Settings.load()
    queue = JobQueue(app_settings, runner=runner, approver=approver, max_workers=max_workers)
    app = FastAPI(title="Zuri Agent", docs_url=None, redoc_url=None)
    app.state.settings = app_settings
    app.state.queue = queue

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(INDEX_HTML)

    @app.get("/api/summary")
    def summary():
        kernel = _kernel(app_settings)
        try:
            tasks = []
            for task in kernel.storage.list_tasks(30):
                item = _task_summary(kernel, task["id"])
                if item:
                    tasks.append(item)
            agents = [
                {
                    "id": spec.id,
                    "name": spec.name,
                    "description": spec.description,
                    "version": spec.version,
                    "tools": spec.tools,
                    "enabled": spec.enabled,
                }
                for spec in kernel.registry.list_agents()
            ]
            return {
                "api_key_set": app_settings.has_api_key,
                "tasks": tasks,
                "agents": agents,
                "queue": queue.status(),
                "cost": kernel.storage.cost_summary(),
            }
        finally:
            kernel.close()

    @app.get("/api/tasks/{task_id}")
    def task_detail(task_id: str):
        kernel = _kernel(app_settings)
        try:
            if kernel.storage.get_task(task_id) is None:
                raise HTTPException(404, "task not found")
            data = kernel.task_data(task_id)
            events = data["events"]
            data["attempts"] = [
                event["data"] for event in events if event["type"] == "resilience_attempt"
            ]
            data["resilience_end"] = next(
                (
                    event["data"]
                    for event in reversed(events)
                    if event["type"] == "resilience_exhausted"
                ),
                None,
            )
            data["policy_block"] = next(
                (
                    event["data"]
                    for event in reversed(events)
                    if event["type"] == "policy_block"
                ),
                None,
            )
            data["mind_update"] = next(
                (
                    event["data"]
                    for event in reversed(events)
                    if event["type"] == "mind_updated"
                ),
                None,
            )
            return data
        finally:
            kernel.close()

    @app.get("/api/agents")
    def agents():
        kernel = _kernel(app_settings)
        try:
            return [spec.model_dump() for spec in kernel.registry.list_agents()]
        finally:
            kernel.close()

    @app.get("/api/agents/{agent_id}")
    def agent_detail(agent_id: str):
        kernel = _kernel(app_settings)
        try:
            spec = kernel.registry.get(agent_id)
            if spec is None:
                raise HTTPException(404, "agent not found")
            return {
                "spec": spec.model_dump(),
                "memory": [entry.model_dump() for entry in kernel.registry.load_memory(agent_id)],
                "versions": kernel.registry.list_versions(agent_id),
                "changes": [change.model_dump() for change in kernel.registry.list_changes(agent_id)],
                "history": kernel.registry.history(agent_id, 30),
            }
        finally:
            kernel.close()

    @app.get("/api/costs")
    def costs():
        kernel = _kernel(app_settings)
        try:
            return kernel.storage.cost_summary()
        finally:
            kernel.close()

    @app.post("/api/run")
    def run(request: RunRequest):
        text = request.request.strip()
        if not text:
            raise HTTPException(400, "request is empty")
        if not app_settings.has_api_key:
            raise HTTPException(400, "DEEPSEEK_API_KEY is missing")
        job_id = queue.submit_run(text)
        return {"job_id": job_id}

    @app.post("/api/tasks/{task_id}/approve")
    def approve(task_id: str):
        kernel = _kernel(app_settings)
        try:
            task = kernel.storage.get_task(task_id)
            if task is None:
                raise HTTPException(404, "task not found")
            if task["status"] != "awaiting_approval":
                raise HTTPException(400, f"task is not awaiting approval: {task['status']}")
        finally:
            kernel.close()
        job_id = queue.submit_approve(task_id)
        return {"job_id": job_id}

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        item = queue.get(job_id)
        if item is None:
            raise HTTPException(404, "job not found")
        return item

    return app


app = create_app()
