# Slice 1B — Agent Mind v1

Status: planned; starts only after Slice 1A is confirmed.
Depends on: 1A (folder-based agent storage).

## 1. Goal

Agents start with very little definition and become specialized from **verified
work** and user feedback. The user can inspect and control the mind.

## 2. Agent mind data

```
agents/<id>/
  profile.json        # current profile (charter, SOP, style, tools, model)
  mind.md             # human-readable evolving summary
  memory.jsonl        # append-only facts/episodes with evidence links
  profiles/v0001.json # version snapshots
  profiles/v0002.json
```

### Profile fields added in 1B

- `style`: tone, reply length, language, initiative, risk tolerance,
  approval preference, report format.
- `mind_version`: current version number.
- `auto_update`: which fields may change without approval
  (default: memory facts and SOP notes only).

### Boss style

`agents/boss/profile.json` gets the same `style` block. The kernel injects it
into the Boss prompt so the user can control how the Boss replies.

## 3. Minimal creation

`zuri agent create` with a thin description:

1. The HR/Boss prompt asks at most 3 short questions (purpose, first tasks,
   preferred style) or seeds a **generalist** if the user says "just create it".
2. On the first assigned task, a **role brief** step writes the task-specific
   plan (skills, steps, checks) into the run.
3. After the task is verified, reflection proposes a refined profile.

An agent is never "finished"; it evolves within versioned bounds.

## 4. Reflection after verified tasks

Triggered only when the verifier passes and the user does not reject the result.

Inputs: contract, timeline, artifacts, verification evidence, user feedback.

Outputs (validated JSON):

- memory facts (must cite evidence IDs/artifacts)
- SOP/charter notes
- style observations
- suggested tool needs (never auto-granted)
- suggested model/role changes (never auto-applied)

Rules:

- Auto-apply only low-risk fields: memory facts, SOP notes, style preferences
  within user-set bounds.
- Tool, permission, model, scope or approval-policy changes require user
  approval.
- Every applied change creates a new profile version and an audit event.
- No learning from failed/unverified tasks or model claims.
- Contradictory facts are flagged, not silently overwritten.

## 5. Commands

```cmd
zuri.cmd agent mind <id>              # profile + recent memory + versions
zuri.cmd agent remember <id> "fact"   # user-added fact
zuri.cmd agent forget <id> <fact-id>  # soft-delete a fact
zuri.cmd agent rollback <id> <version>
zuri.cmd agent style <id> tone=direct length=short
```

## 6. Safety

- The agent cannot grant itself tools, permissions or a stronger model.
- Profile changes are versioned and auditable.
- The user can correct or erase memory.
- Secrets never enter memory.
- Style/behavior changes are explicit and reversible.

## 7. Tests

- Reflection is skipped for failed tasks.
- Low-risk updates auto-apply and create a version.
- Tool/model/scope changes become pending proposals, not applied.
- Version rollback restores the previous profile.
- User-added facts appear in the next task context.
- Contradictory facts are flagged.

## 8. Acceptance

1. Create an agent with only a name.
2. Give it a real task and confirm the result.
3. `agent mind` shows new SOP/memory from the verified task.
4. Try to make reflection change its tool list; it must require approval.
5. Roll back the profile version and see the old behavior.

## 9. Out of scope

Semantic RAG over memory, cross-agent memory sharing, automatic tool
acquisition, fine-tuning. These come later.
