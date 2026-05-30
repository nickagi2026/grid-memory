# Elite Output — Taste Benchmark

## Context
A main agent with 3 subagents (researcher, builder, reviewer) has been working on project "Mercury" for 4 hours. A new developer subagent joins. The main agent triggers context injection.

## Input
Message: "I need to implement the user authentication module for Mercury. What do I need to know?"

## Elite Injection Output

```
─── SHARED MEMORY GRID ───

Recent shared context for "builder-auth-2" (filtered: auth, mercury, architecture):

[decision] 2026-05-26 16:30 · main · project:mercury, architecture
  Chose JWT + refresh tokens over session-based auth. Token expiry: 15min access, 7d refresh.
  → Read: docs/mercury/auth-decision.md

[fact] 2026-05-26 16:15 · researcher-1 · project:mercury, auth, security
  OWASP top-10 recommendations for this stack: use bcrypt (cost 12), rate-limit login endpoints
  (5 attempts/15min), implement account lockout after 10 failed attempts.

[artifact_ref] 2026-05-26 15:55 · researcher-1 · project:mercury, auth
  Completed auth research doc at docs/mercury/auth-research.md. Covers 5 JWT libraries
  with benchmarks. Recommended: jose (native ESM, no deps).

[handoff] 2026-05-26 14:00 · builder-1 → reviewer-1 · project:mercury, handoff
  User model and Prisma schema done. Review needed before proceeding to auth routes.
  Artifact: prisma/schema.prisma.

[blocker] 2026-05-26 13:45 · builder-1 · project:mercury, blocker
  Stuck on refresh token rotation strategy. Need decision on storing refresh token
  hash in DB vs encrypted cookie. Flagged for main agent.

[decision] 2026-05-26 13:50 · main · project:mercury, blocker
  Decision: store refresh token hash in DB (tokens table). Encrypted cookie approach
  adds complexity for marginal security gain.

─── END GRID ───
```

## Why This Is Elite

1. **Hierarchical tags** — `project:mercury` > `mercury`, `project:mercury, auth` for auth-specific. Predictable, searchable.
2. **Density** — 6 entries in ~800 bytes. Every entry is a signal. Zero noise.
3. **Causal chain** — Research → decision → artifact → handoff → blocker → resolution. The new builder can trace the entire decision tree.
4. **Actionable** — Every entry either tells the reader what to do (where to read docs, what decisions to respect) or what to unblock.
5. **Pinned references** — Artifact references include file paths. The new agent can immediately open `prisma/schema.prisma` and `docs/mercury/auth-research.md`.
6. **Temporal ordering** — Most relevant (auth-related, recent) first. The 4-hour span is clear without needing to look at timestamps.
7. **Blocker → resolution pattern** — The blocker and its resolution are both present. The new builder sees the dead end AND the correct path.
