# Failed Output — Anti-Example with Correction

## Anti-Example: What NOT to Do

### Bad Write
```json
{
  "agent_id": "",
  "content": "did some stuff with the database",
  "type": "note",
  "tags": ["stuff"]
}
```

**Why it fails** (Grid rejects it):
1. `agent_id` is empty → Grid: "Write rejected: agent_id is required"
2. `type` is "note" → Grid: "Invalid type 'note'. Valid types: decision, fact, task_status, artifact_ref, handoff, question, observation, blocker, state_update"
3. `tags: ["stuff"]` → useless. Can't be queried by any other agent
4. `content: "did some stuff with the database"` → zero information. What was done? What was decided? What was the outcome?

### Bad Read
```
No parameters. Just "give me memory".
```

**Result:** Returns the last N entries, which may be irrelevant, outdated, or from a completely different project. The agent wastes context understanding entries from project "alpha" when it's working on project "beta."

### Bad Context Injection
```
─── SHARED MEMORY GRID ───

FOUND 47 ENTRIES:

1. [note] agent:scout-1: "looked at the db"
2. [note] agent:scout-1: "did some stuff"
3. [note] agent:builder: "changed some files"
...45 more entries of similar quality...

─── END GRID ───
```

**Why it fails:** 47 entries with zero signal. Every entry lacks type fidelity, meaningful tags, and actionable content. The agent spends all its context budget on noise and has nothing left for the actual task.

---

## Corrected Versions

### Corrected Write
```json
{
  "agent_id": "builder-1",
  "type": "task_status",
  "tags": ["project:beta", "database", "migration"],
  "content": "Completed database migration script. Ran against staging — all tests pass. Key change: added composite index on (user_id, created_at) to speed up the dashboard query. Migration file: prisma/migrations/20260526_user_dashboard_idx.",
  "ttl_seconds": 28800
}
```

### Corrected Read
```
Read with: tags=["project:beta", "database"], max=5
```

**Result:** 5 entries, all relevant to the current project and domain. Usable context.

### Corrected Injection
```
─── SHARED MEMORY GRID ───

Recent shared context for "builder-2" (filtered: beta, database, migration):

[task_status] 2026-05-26 16:30 · builder-1 · project:beta, database, migration
  Completed migration script with composite index. All staging tests pass.

[decision] 2026-05-26 14:00 · main · project:beta, architecture
  Chose Prisma over TypeORM for the project. Rationale: better migration tooling.

[fact] 2026-05-26 13:00 · researcher-1 · project:beta, database
  Recommended composite indexes for the 3 most common query patterns.

─── END GRID ───
```

**Why corrected version works:** 3 entries, high signal-to-noise ratio, relevant tags, actionable content.
