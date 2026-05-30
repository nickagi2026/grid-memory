# Subagent Record Protocol — Writing to The Grid

When a subagent completes work, it should write structured entries to The Grid.
This protocol ensures consistency across all agents in the system.

## Required Fields

Every Grid write must include:

```json
{
  "agent_id": "<agent-id>",
  "type": "<one-of-9-types>",
  "content": "<what happened, what was decided, what was produced>",
  "tags": ["<domain>:<value>", "..."]
}
```

## Type Guide

| Type | When to Use | Content Template |
|------|-------------|------------------|
| `decision` | You made a choice that others should respect | "Chose X over Y. Rationale: ..." |
| `fact` | You discovered something the team should know | "Found that X behaves differently when Y. Impact: ..." |
| `task_status` | You completed or made progress on a task | "Completed [task]. Key results: ... Artifact: path/to/file" |
| `artifact_ref` | You created a file/artifact others need | "Created doc/spec at path/to/file. Contains coverage of ..." |
| `handoff` | You're passing work to another agent | "Completed my part. Next agent should: ... Known issues: ..." |
| `question` | You're stuck and need input | "Can't proceed without decision on X. Options considered: A, B, C." |
| `observation` | You noticed something worth sharing (low confidence) | "Noticed that X may be relevant. Investigated briefly: ..." |
| `blocker` | Something is blocking progress | "Blocked on [issue]. Impact: [scope]. Suggested resolution: ..." |
| `state_update` | The project/agent state changed | "State change: from [before] to [after]. Trigger: ..." |

## Tag Convention

Tags follow `domain:value` format for hierarchical querying:

```
project:alpha              — Project scope
architecture               — Architecture domain
auth, database, frontend   — Technical domain
review, wip, blocked       — Status tags
handoff                    — Handoff marker
decision:2026-05-26        — Decision by date (for expiry tracking)
```

## Handoff Pattern

When handing off between agents, always write a `handoff` entry AND a `task_status` entry:

```json
[
  {
    "agent_id": "builder-1",
    "type": "task_status",
    "tags": ["project:alpha", "auth-module", "wip"],
    "content": "Completed auth routes and JWT middleware. All 15 tests passing. Artifact: src/routes/auth.ts"
  },
  {
    "agent_id": "builder-1",
    "type": "handoff",
    "tags": ["project:alpha", "auth-module", "handoff"],
    "content": "Handing off to reviewer-1. Auth routes need security review. Known concern: rate limiting thresholds are placeholders.",
    "ttl_seconds": 3600
  }
]
```

## Reading from The Grid

When a subagent spawns, read with relevant tags:

```
Grid query: tags=["project:alpha", "auth-module"], max=10
```

The result will include all relevant decisions, task statuses, and handoffs.
No need to ask the user "what was decided" — The Grid surfaces it.
