# Taste Model — What Makes Grid Output Excellent

## The Target

When an agent reads The Grid, it should feel like walking into a war room where the previous shift left a clean, annotated whiteboard. Every entry should answer "why should I care?" without the reader asking.

## Signal vs Noise

| Signal | Noise |
|--------|-------|
| "Chose Express over Fastify. Rationale: middleware ecosystem." | "Looked at some frameworks" |
| "Deprecated: the old cache layer is being replaced by Redis." | "Changed some cache stuff" |
| "PR #42: auth module — ready for review. 2 concerns flagged." | "Did some work on auth" |
| Tags: `project:alpha, auth, review` | Tags: `stuff, things, work` |

## The 3-Second Test

An agent should understand the state of a project within 3 seconds of reading The Grid's injection block. If the agent needs to ask follow-up questions, the block failed.

## Compression Quality

When The Grid compresses old entries, a summary like:
```
[decision] 2026-05-25 · main · project:alpha, architecture
  Decisions made on 2026-05-25 (3 entries): database (PostgreSQL), framework (Express), auth (JWT)
```
is better than 3 separate entries that have already been read by every subsequent agent.

## Consistency Markers

- Tags always follow `domain:value` format (`project:alpha > alpha`)
- Types always use the controlled vocabulary (9 types)
- Content is always actionable — it says what was decided/found/done, not what was "thought about"
- No entry is written without answering "who would find this useful?"
