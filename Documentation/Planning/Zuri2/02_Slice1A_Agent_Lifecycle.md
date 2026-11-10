# Slice 1A — Agent lifecycle and registry

Status: **implemented 2026-11-09 — awaiting user test**
Date: 2026-11-09
Depends on: Slice 0 (confirmed)

## 1. What this slice adds

The Boss can **propose** creating or deleting a specialist; the kernel and the
user stay in control. A created agent becomes a real assignee for tasks.

In scope:

1. Agent registry (`agents/<id>.json`) with enabled/disabled state.
2. Create flow: Boss drafts an agent spec → user approves → registry adds it.
3. Delete flow: **two explicit confirmations** → soft-delete with snapshot →
   restore command. No hard delete.
4. Audit ledger for every agent action.
5. Task assignment: Boss sees the enabled agents, picks one, and the kernel
   runs that agent with only its allowed tools.

Out of scope (later slices): queue/scheduler, dashboard, long-term memory,
shell/browser tools, budgets beyond the existing per-task budget.

## 2. Exact files and responsibilities

| File | Change |
| --- | --- |
| `app/models.py` | `AgentSpec` id validation (slug), reserved ids, `AgentProposal` model |
| `app/registry.py` | **new**: list/get/create/disable/restore, proposals, trash snapshots |
| `app/storage.py` | `agent_events` table: `add_agent_event`, `get_agent_events` |
| `app/llm.py` | `propose_agent()` (HR prompt); pass assignee list to Boss planning |
| `app/agents.py` | load the chosen assignee spec; keep Boss/Worker/Liar behavior |
| `app/tools.py` | `ToolSet` filters definitions by the agent's `tools` list |
| `app/kernel.py` | load registry, validate `contract.assignee`, run assigned agent |
| `app/cli.py` | `agent list/show/create/approve/reject/delete/restore/history` |
| `agents/hr.json` | **new**: HR prompt for drafting an AgentSpec |
| `tests/test_registry.py` | **new**: create, duplicate, reserved id, delete, restore |
| `tests/test_assignee.py` | **new**: Boss assignee validation + tool filtering |
| `Documentation/...` | tracker/history updates |

Agent storage is folder-based from the start so Agent Mind (1B) can grow
without a migration:

```
agents/<id>/
  profile.json      # current identity, charter, style, tools, model
  memory.jsonl      # evidence-linked facts and episodes (1B fills this)
  profiles/         # version snapshots (v0001.json, v0002.json, ...)
```

System agents (`boss`, `worker`, `hr`) move into the same layout. Deleting an
agent snapshots the whole folder.

No database reset; the existing DB gets the new `agent_events` table.

## 3. Data flow

### Create agent

```
user: zuri agent create "an agent that writes clean markdown notes"
  → Boss/HR (DeepSeek V4 Pro) drafts an AgentSpec JSON
  → kernel validates it (id slug, reserved id, known tools)
  → saved as data/agent_proposals/<proposal_id>.json
  → CLI prints the full spec and: zuri agent approve <proposal_id>
user: zuri agent approve <proposal_id>
  → agents/<id>.json written
  → audit event agent_created
```

The Boss cannot create the file. Approval is a separate user action.

### Delete agent (two confirmations)

```
user: zuri agent delete notes
  → CLI shows: role, tools, model, created date
  → prompt 1: type the exact agent id
  → prompt 2: type DELETE <id>
  → if either does not match: abort, nothing changes
  → snapshot to agents/.trash/<id>-<timestamp>/agent.json + metadata.json
  → agents/<id>.json removed
  → audit events agent_delete_confirmed / agent_soft_deleted
user: zuri agent restore notes
  → latest trash snapshot copied back; audit event agent_restored
```

The Boss has no tool that can confirm. Confirmation is CLI-only and
kernel-checked.

### Task assignment

```
user request
  → Boss sees enabled assignees: worker, notes, ...
  → contract.assignee = "notes"
  → kernel loads agents/notes.json
  → worker toolset = only tools listed in that agent's spec
  → verifier unchanged
  → `zuri show` displays the assignee
```

## 4. Agent spec rules

- `id`: lowercase letters, digits, hyphen; 2–31 chars; unique; cannot be
  `boss`, `worker`, `hr`, `kernel`, `verifier`.
- `tools`: only tools that actually exist (`list_dir`, `read_file`,
  `write_file` in this slice).
- `model`: `deepseek-flash` or `deepseek-v4-pro`.
- `system_prompt`: required, non-empty; should contain the role, rules and
  workflow/SOP.
- Creating a full spec with detailed instructions is the user's path to a
  powerful agent; the HR prompt enforces the structure.

## 5. Safety

- Creation requires user approval; deletion requires two confirmations.
- Soft-delete only; snapshot and restore path exist.
- Every create/approve/reject/delete/restore writes an audit event in
  `agent_events` and `data/ledger.jsonl`.
- No secret values are logged.
- Deleting an agent does not delete its past tasks or artifacts.

## 6. Acceptance test (what the user will do)

1. Create:
   ```cmd
   zuri.cmd agent create "Create an agent named Notes that writes clean markdown notes with headings and bullet points."
   zuri.cmd agent approve <proposal-id>
   zuri.cmd agent list
   ```
2. Use it:
   ```cmd
   zuri.cmd run "Use the notes agent to create work/notes.md with a short checklist for Slice 1."
   zuri.cmd show <task-id>
   ```
   The contract's assignee must be the new agent; only its allowed tools appear.
3. Cancel a delete:
   ```cmd
   zuri.cmd agent delete notes
   ```
   Type the wrong id at either prompt → nothing changes.
4. Delete and restore:
   ```cmd
   zuri.cmd agent delete notes
   ```
   Type the exact id, then `DELETE <id>` → agent disabled, snapshot in
   `agents/.trash/`.
   ```cmd
   zuri.cmd agent restore notes
   zuri.cmd agent list
   ```

## 7. Tests (no API)

- Registry: create, duplicate rejection, reserved id rejection, delete callback
  mismatch aborts, delete snapshot, restore, audit events.
- Tool filtering: agent with subset of tools gets only those definitions.
- Assignee: unknown/disabled assignee fails before execution.
- Existing 17 tests still pass.

## 8. Why this design

- The Boss can propose but never mutate the registry.
- Two confirmations make accidental deletion hard; soft-delete makes mistakes
  recoverable; audit makes everything visible.
- Per-agent tools mean a “notes agent” cannot run anything it was not granted.
- This is the minimum needed to let the user build a real team of specialists.

## 9. Approval

Approve Slice 1A to implement exactly this. No queue, dashboard, memory, shell
or browser tools in this slice; those stay in later slices.
