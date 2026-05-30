/**
 * conflicts.js — Conflict Resolution Engine
 *
 * Detects semantic contradictions when agents write about the same topic.
 * If Agent A writes "the API is down" and Agent B writes "the API is healthy"
 * two minutes later, this engine detects the contradiction.
 *
 * Resolution strategies:
 *   auto — latest entry wins (with provenance note)
 *   flag — CONFLICT entry created for human review
 *
 * A CONFLICT entry is created when contradictory entries exist.
 * Contradiction detection is based on antonym/keyword matching
 * within the same tag scope within a time window.
 */

// ─── Conflict Patterns ─────────────────────────────────────────────────────

// Pairs of contradictory keywords/patterns
const CONTRADICTIONS = [
  // Status contradictions
  { a: ['up', 'online', 'healthy', 'running', 'available', 'operational', 'active', 'connected'],
    b: ['down', 'offline', 'unhealthy', 'stopped', 'unavailable', 'outage', 'inactive', 'disconnected'] },
  // Success contradictions
  { a: ['success', 'passed', 'completed', 'done', 'resolved', 'fixed'],
    b: ['failure', 'failed', 'error', 'crash', 'broken', 'unresolved'] },
  // Boolean contradictions
  { a: ['enabled', 'true', 'yes', 'on'],
    b: ['disabled', 'false', 'no', 'off'] },
  // Deployment contradictions
  { a: ['deployed', 'released', 'promoted'],
    b: ['rolled back', 'reverted', 'withdrawn', 'cancelled'] },
  // Capacity contradictions
  { a: ['scaled up', 'increased', 'added', 'grew'],
    b: ['scaled down', 'decreased', 'removed', 'shrunk'] },
  // Dedicated contradictory phrases
  { a: ['is working', 'works fine', 'no issues', 'all good'],
    b: ['not working', 'broken', 'has issues', 'failed'] },
];

// ─── Detect Contradictions ────────────────────────────────────────────────

function detectContradiction(existingContent, newContent) {
  const existing = existingContent.toLowerCase();
  const current = newContent.toLowerCase();

  for (const pair of CONTRADICTIONS) {
    const hasA = pair.a.some(word => word.includes(' ') ? existing.includes(word) : new RegExp('\\b' + word + '\\b').test(existing));
    const hasB = pair.b.some(word => word.includes(' ') ? existing.includes(word) : new RegExp('\\b' + word + '\\b').test(existing));
    const newHasA = pair.a.some(word => word.includes(' ') ? current.includes(word) : new RegExp('\\b' + word + '\\b').test(current));
    const newHasB = pair.b.some(word => word.includes(' ') ? current.includes(word) : new RegExp('\\b' + word + '\\b').test(current));

    // Existing entry says A, new entry says B (or vice versa)
    if ((hasA && newHasB) || (hasB && newHasA)) {
      return {
        contradiction: true,
        pattern_type: 'keyword',
        existing_position: pair.a.filter(w => w.includes(' ') ? existing.includes(w) : new RegExp('\\b' + w + '\\b').test(existing)).concat(pair.b.filter(w => w.includes(' ') ? existing.includes(w) : new RegExp('\\b' + w + '\\b').test(existing))),
        new_position: pair.a.filter(w => w.includes(' ') ? current.includes(w) : new RegExp('\\b' + w + '\\b').test(current)).concat(pair.b.filter(w => w.includes(' ') ? current.includes(w) : new RegExp('\\b' + w + '\\b').test(current))),
      };
    }
  }

  return { contradiction: false };
}

// ─── Check for Conflicts in Recent Entries ────────────────────────────────

async function findConflicts(grid, content, tags, agentId, workspace) {
  if (!content || tags.length === 0) return { hasConflict: false };

  // Scope to workspace when provided
  const queryTags = workspace ? [...tags, `ws:${workspace}`] : tags;
  const result = await grid.read({ tags: queryTags, max: 50, tagMode: 'AND' });
  const entries = result.entries || [];

  for (const entry of entries) {
    // Skip own entries
    if (entry.agent_id === agentId) continue;

    const check = detectContradiction(entry.content || '', content);
    if (check.contradiction) {
      return {
        hasConflict: true,
        existing_entry: entry.id,
        existing_agent: entry.agent_id,
        existing_content: entry.content?.slice(0, 200),
        existing_created: entry.created_at,
        pattern_type: check.pattern_type,
        existing_position: check.existing_position,
        new_position: check.new_position,
      };
    }
  }

  return { hasConflict: false };
}

// ─── Resolve Conflict — write CONFLICT entry ──────────────────────────────

async function resolveConflict(grid, conflictResult, newContent, newAgentId, workspace) {
  const wsTag = workspace ? `ws:${workspace}` : '';
  const tags = ['_conflict', `conflict_with:${conflictResult.existing_entry}`];
  if (wsTag) tags.push(wsTag);
  await grid.write({
    agent_id: '_system',
    type: 'observation',
    content: `CONFLICT: ${newAgentId} wrote content contradicting ${conflictResult.existing_agent}\n`
           + `New: ${newContent.slice(0, 200)}\n`
           + `Existing (${conflictResult.existing_agent}): ${conflictResult.existing_content}\n`
           + `Workspace: ${workspace || 'global'}\n`
           + `Resolution: latest entry auto-accepted (latest-wins strategy)`,
    tags,
    parent_entry: conflictResult.existing_entry,
  });

  return { resolved: true, method: 'auto-latest-wins' };
}

// ─── Module Exports ────────────────────────────────────────────────────────

module.exports = { detectContradiction, findConflicts, resolveConflict };
