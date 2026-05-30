# Domain Knowledge — Shared Memory for Multi-Agent Teams

## The Problem

Every agent in a multi-agent system starts fresh. Subagents have no awareness of what other subagents did. The main agent manually reconstructs context between spawns. This is the single biggest productivity killer in multi-agent setups.

## Why File-Based Works

The Grid uses flat JSON files for storage. This is a deliberate choice:

1. **Zero dependencies** — No Redis, no SQLite, no external services. Works on a fresh install.
2. **Debug-friendly** — Open `store.json` in any editor. Read the raw entries.
3. **Git-trackable** — The grid can be committed to a project repo for persistent context across sessions.
4. **Subagent-safe** — Subagents can read/write to the same file without needing network access.

## Memory Architecture Context

The Grid integrates with (but doesn't replace) the existing 4-layer memory architecture:

| Layer | What It Is | Storage | The Grid's Role |
|-------|-----------|---------|-----------------|
| 1 — Working | Session scratchpad | In-memory | Not involved |
| 2 — Episodic | Conversation history | memory/YYYY-MM-DD.md | Mirrors key decisions here so subagents see them |
| 3 — Semantic | Long-term user knowledge | MEMORY.md, USER.md | Seeds initial state; Grid augments for multi-agent |
| 4 — Self-Model | Agent self-knowledge | SELF_MODEL.md | Not involved |

The Grid fills the gap between Layer 2 and Layer 3: it's the cross-agent ephemeral-context layer.

## When to Use vs Not Use

### Use The Grid when:
- Spawning a subagent and you want it to know what happened before
- A subagent completes work and the main agent needs its results
- Multiple subagents work on different parts of the same project
- You need to remember decisions made in a previous session
- You want to hand off context between research → build → review cycles

### Don't use The Grid when:
- A single agent works without subagents on a trivial task
- The information is transient and will never be referenced again
- You're storing secrets, credentials, or private keys (the Grid rejects these)
- A simple file write would suffice (the Grid adds structure where none is needed)
