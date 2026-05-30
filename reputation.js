/**
 * reputation.js — Agent Identity Reputation Scoring
 *
 * Tracks which agents produce high-value content vs noise.
 * Scores are based on: downstream references, confirmation count,
 * decision success rate, contradiction rate, and prune rate.
 *
 * Endpoints:
 *   GET /agents/reputation — full ranking
 *   GET /agents/reputation/:agent_id — single agent profile
 */

const { Grid } = require('./reference/store.js');

// ─── Score Weights ─────────────────────────────────────────────────────────

const WEIGHTS = {
  entries_written: 0.05,       // baseline participation
  times_referenced: 0.25,      // other agents reference this agent's entries
  decisions_made: 0.20,        // decisions as signal of agency
  blocker_ratio_penalty: 0.20, // penalty for high blocker-to-decision ratio
  avg_content_length: 0.05,    // signal: longer content tends to be more substantive
  tag_diversity: 0.05,         // breadth of knowledge
};

// ─── Calculate Score for a Single Agent ────────────────────────────────────

async function scoreAgent(grid, agentId) {
  // Reuse scoreAll's single pass for consistency — avoids duplicate grid reads
  const all = await scoreAll(grid);
  const found = all.agents.find(a => a.agent === agentId);
  if (found) return found;
  return { agent: agentId, score: 0, total_entries: 0, times_referenced: 0, decisions_made: 0, blockers_recorded: 0, successful_decisions: 0, failed_decisions: 0, partial_decisions: 0, top_type: 'unknown', tag_count: 0 };
}

// ─── Score All Agents (O(n) — single pass through entries) ───────────────────

async function scoreAll(grid) {
  // One pass: read all entries, aggregate per-agent, and count cross-references
  const entries = (await grid.read({ max: 500 })).entries || [];

  // Per-agent aggregation + cross-reference counting
  const agentStats = {};
  const agentIds = new Set();

  // First pass: aggregate stats and collect all agent IDs
  for (const e of entries) {
    const agentId = e.agent_id;
    if (!agentId || agentId.startsWith('_')) continue;
    agentIds.add(agentId);

    if (!agentStats[agentId]) {
      agentStats[agentId] = { total: 0, by_type: {}, tags: new Set(), decisions: 0, blockers: 0, total_length: 0, times_referenced: 0, successful_decisions: 0, failed_decisions: 0, partial_decisions: 0 };
    }
    const s = agentStats[agentId];
    s.total++;
    s.by_type[e.type] = (s.by_type[e.type] || 0) + 1;
    (e.tags || []).forEach(t => s.tags.add(t));
    s.total_length += (e.content || '').length;
    if (e.type === 'decision') s.decisions++;
    if (e.type === 'blocker') s.blockers++;
    if (e.outcome && e.outcome.result === 'success') s.successful_decisions++;
    if (e.outcome && e.outcome.result === 'failure') s.failed_decisions++;
    if (e.outcome && e.outcome.result === 'partial') s.partial_decisions++;
  }

  // Second pass: count cross-references with word-boundary matching
  for (const e of entries) {
    const content = e.content || '';
    for (const agentId of agentIds) {
      if (e.agent_id !== agentId && new RegExp('\\b' + agentId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\b').test(content)) {
        agentStats[agentId].times_referenced++;
      }
    }
  }

  const scores = [];
  for (const [agentId, s] of Object.entries(agentStats)) {
    const avgLength = s.total > 0 ? s.total_length / s.total : 0;
    const tagDiv = s.tags.size;

    let score = 0;
    score += Math.min(s.total * WEIGHTS.entries_written, 5);
    score += Math.min(s.times_referenced * WEIGHTS.times_referenced, 15);
    score += Math.min(s.decisions * WEIGHTS.decisions_made, 10);
    score += Math.min(avgLength * WEIGHTS.avg_content_length, 3);
    score += Math.min(tagDiv * WEIGHTS.tag_diversity, 3);

    // Outcome factor: successful decisions boost score, failures penalize
    if (s.successful_decisions > 0) score += Math.min(10, s.successful_decisions * 2);
    if (s.failed_decisions > 0) score -= Math.min(5, s.failed_decisions * 2);

    // Penalty for high blocker-to-decision ratio (indicates noise)
    if (s.decisions > 0 && s.blockers > s.decisions * 2) score -= 5;

    // Normalize to 0-100
    score = Math.max(0, Math.min(100, Math.round(score * 2)));

    scores.push({
      agent: agentId,
      score,
      total_entries: s.total,
      times_referenced: s.times_referenced,
      decisions_made: s.decisions,
      blockers_recorded: s.blockers,
      successful_decisions: s.successful_decisions,
      failed_decisions: s.failed_decisions,
      partial_decisions: s.partial_decisions,
      top_type: Object.entries(s.by_type).sort((a, b) => b[1] - a[1])[0]?.[0] || 'unknown',
      tag_count: s.tags.size,
    });
  }

  scores.sort((a, b) => b.score - a.score);
  return { agents: scores, total: scores.length, scored_at: new Date().toISOString() };
}

// ─── Module Exports ────────────────────────────────────────────────────────

module.exports = { scoreAgent, scoreAll };
