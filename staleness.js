/**
 * staleness.js — Memory Staleness Detection
 *
 * Scans high-tier entries and flags those that are stale:
 * - No recent references (not read or referenced recently)
 * - Contradicting entry exists on the same topic
 * - state_update on same topic exists
 *
 * Endpoints:
 *   GET /stale — returns stale entries with scores
 */

function findStale(grid, options = {}) {
  const thresholdDays = options.thresholdDays || 30;
  const now = Date.now();
  const thresholdMs = thresholdDays * 24 * 60 * 60 * 1000;

  // Load store directly for full access
  const store = grid._store || grid._loadStore();
  if (!store || !store.entries) return [];

  const entries = store.entries;
  const staleResults = [];

  // Index entries by tag for contradiction detection
  const tagIndex = {};
  for (const e of entries) {
    for (const tag of e.tags || []) {
      if (!tagIndex[tag]) tagIndex[tag] = [];
      tagIndex[tag].push(e);
    }
  }

  for (const entry of entries) {
    // Focus on high-tier entries (include working for contradiction/state_update detection)
    if (entry.memory_tier !== 'organization' && entry.memory_tier !== 'project' && entry.memory_tier !== 'working') continue;
    if (entry.status === 'draft') continue;

    const createdMs = new Date(entry.created_at).getTime();
    const ageDays = (now - createdMs) / (1000 * 60 * 60 * 24);
    let stalenessScore = 0;
    const reasons = [];

    // Factor 1: Age relative to threshold
    if (ageDays > thresholdDays) {
      stalenessScore += Math.min(40, (ageDays / thresholdDays) * 20);
      reasons.push(`entry is ${Math.round(ageDays)} days old (threshold: ${thresholdDays} days)`);
    }

    // Factor 2: Low read count or never read
    if (!entry.last_read_at) {
      stalenessScore += 15;
      reasons.push('never been read');
    } else {
      const lastReadMs = new Date(entry.last_read_at).getTime();
      const daysSinceRead = (now - lastReadMs) / (1000 * 60 * 60 * 24);
      if (daysSinceRead > thresholdDays / 2) {
        stalenessScore += 10;
        reasons.push(`last read ${Math.round(daysSinceRead)} days ago`);
      }
    }

    // Factor 3: Contradicting entry exists on same topic
    for (const tag of entry.tags || []) {
      const sameTag = tagIndex[tag] || [];
      for (const other of sameTag) {
        if (other.id === entry.id) continue;
        if (other.type === entry.type && other.type === 'decision') {
          // Different decisions on same tag suggest contradiction
          stalenessScore += 10;
          reasons.push(`contradicting decision exists on tag "${tag}"`);
          break;
        }
      }
    }

    // Factor 4: Newer state_update on same topic
    for (const tag of entry.tags || []) {
      const sameTag = tagIndex[tag] || [];
      for (const other of sameTag) {
        if (other.id === entry.id) continue;
        if (other.type === 'state_update' && other.created_at > entry.created_at) {
          stalenessScore += 15;
          reasons.push(`newer state_update exists on tag "${tag}"`);
          break;
        }
      }
    }

    if (stalenessScore > 0) {
      staleResults.push({
        entry_id: entry.id,
        agent_id: entry.agent_id,
        type: entry.type,
        tags: entry.tags,
        content: entry.content.slice(0, 200),
        created_at: entry.created_at,
        memory_tier: entry.memory_tier,
        staleness_score: Math.min(100, Math.round(stalenessScore)),
        reasons,
        age_days: Math.round(ageDays),
      });
    }
  }

  // Sort by staleness score descending
  staleResults.sort((a, b) => b.staleness_score - a.staleness_score);
  return staleResults;
}

module.exports = { findStale };
