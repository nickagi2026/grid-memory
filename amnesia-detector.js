#!/usr/bin/env node
'use strict';
/**
 * amnesia-detector.js — Organizational Amnesia Detector™
 *
 * Detects when the same problem has been solved multiple times across
 * different teams, projects, or time periods — then surfaces the pattern.
 *
 * Identifies:
 *   - Gaps: Topics discussed 30+ days ago with zero references since
 *   - Orphans: Decisions made but never acted upon
 *   - Stale decisions: Decisions older than 60 days with no review/update
 *   - Single-points-of-failure: Topics/knowledge held by only one agent
 *
 * Endpoint (registered in server.js):
 *   GET /amnesia/detect — Run full amnesia detection scan
 *
 * Usage:
 *   const { detect } = require('./amnesia-detector.js');
 *   const result = await detect(grid);
 */


// ─── Configuration ───────────────────────────────────────────────────────────

const DEFAULT_CONFIG = {
  gapDays: 30,          // Topics not referenced in 30+ days
  orphanDays: 14,       // Decisions without outcomes for 14+ days
  staleDecisionDays: 60, // Decisions older than 60 days without review
  keywordRelevance: true, // Use keyword-based topic extraction
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function now() {
  return new Date().toISOString();
}

function daysSince(dateStr) {
  if (!dateStr) return Infinity;
  const then = new Date(dateStr).getTime();
  const nowMs = Date.now();
  if (isNaN(then)) return Infinity;
  return Math.floor((nowMs - then) / (1000 * 60 * 60 * 24));
}

function getAgeInDays(createdAt) {
  return daysSince(createdAt);
}

function extractKeyTopics(content) {
  if (!content) return [];
  const topics = new Set();

  // Extract topic-prefixed tags from structured content
  const topicPatterns = [
    /Topic:\s*([^\n]+)/gi,
    /Subject:\s*([^\n]+)/gi,
    /Domain:\s*([^\n]+)/gi,
    /Area:\s*([^\n]+)/gi,
    /Category:\s*([^\n]+)/gi,
  ];
  for (const pat of topicPatterns) {
    let match;
    while ((match = pat.exec(content)) !== null) {
      topics.add(match[1].trim().toLowerCase());
    }
  }

  // Extract noun phrases (simple heuristic: 2-4 word sequences after keywords)
  const keywordIndicators = [
    /(?:using|implementing|deploying|migrating to|switching to|building with)\s+([\w\s-]{3,50})/gi,
    /(?:database|framework|tool|platform|language|service|system|architecture):\s*([\w\s-]{3,50})/gi,
  ];
  for (const pat of keywordIndicators) {
    let match;
    while ((match = pat.exec(content)) !== null) {
      const topic = match[1].trim().toLowerCase();
      if (topic.length >= 3 && topic.length <= 50) {
        topics.add(topic);
      }
    }
  }

  return [...topics].slice(0, 10);
}

function extractTagsAsTopics(tags) {
  if (!tags || tags.length === 0) return [];
  return tags
    .filter(t => !t.startsWith('ws:') && !t.startsWith('agent:') && !t.startsWith('stage:') && !t.startsWith('client:'))
    .map(t => t.toLowerCase());
}

function extractDecisionText(content) {
  if (!content) return 'Unknown decision';
  const firstLine = content.split('\n')[0].trim();
  if (firstLine.length > 100) return firstLine.slice(0, 100) + '...';
  return firstLine;
}

// ─── Amnesia Detector ────────────────────────────────────────────────────────

async function detect(grid, config = {}) {
  const cfg = { ...DEFAULT_CONFIG, ...config };
  const nowIso = now();

  // Get all entries
  const allResult = await grid.read({ max: 500 });
  const allEntries = allResult.entries || [];

  // Also get export data for complete picture (includes expired entries for analysis)
  let fullEntries = allEntries;
  try {
    const exportResult = await grid.exportAll();
    if (exportResult.entries && exportResult.entries.length > allEntries.length) {
      fullEntries = exportResult.entries;
    }
  } catch (e) {
    // Fall back to query results
  }

  if (fullEntries.length === 0) {
    return {
      gaps: [],
      orphans: [],
      stale_decisions: [],
      single_points_of_failure: [],
      amnesia_score: 0,
      summary: 'No entries found in the Grid. Start writing to enable amnesia detection.',
    };
  }

  // ── 1. Gaps: Topics discussed 30+ days ago with zero references since ──
  const gaps = _findGaps(fullEntries, cfg.gapDays, nowIso);

  // ── 2. Orphans: Decisions made but never acted upon ──
  const orphans = _findOrphans(fullEntries, cfg.orphanDays, nowIso);

  // ── 3. Stale decisions: Decisions older than 60 days with no review/update ──
  const staleDecisions = _findStaleDecisions(fullEntries, cfg.staleDecisionDays, nowIso);

  // ── 4. Single-points-of-failure: Topics held by only one agent ──
  const spofs = _findSinglePointsOfFailure(fullEntries);

  // ── 5. Amnesia Score ──
  const amnesiaScore = _calculateAmnesiaScore(fullEntries, gaps, orphans, staleDecisions, spofs);

  // ── 6. Summary ──
  const summary = _buildSummary(gaps, orphans, staleDecisions, spofs, amnesiaScore, fullEntries.length);

  return {
    gaps,
    orphans,
    stale_decisions: staleDecisions,
    single_points_of_failure: spofs,
    amnesia_score: Math.round(amnesiaScore * 100) / 100,
    summary,
  };
}

// ─── Gap Detection ───────────────────────────────────────────────────────────

function _findGaps(entries, gapDays, nowIso) {
  // Build topic -> last referenced date index
  const topicLastRef = new Map(); // topic -> { lastDate, count, agents }
  const topicAgents = new Map();

  for (const e of entries) {
    const contentTopics = extractKeyTopics(e.content);
    const tagTopics = extractTagsAsTopics(e.tags);
    const allTopics = [...new Set([...contentTopics, ...tagTopics])];

    for (const topic of allTopics) {
      if (!topic || topic.length < 2) continue;

      const existing = topicLastRef.get(topic) || { lastDate: null, count: 0, agents: new Set() };
      if (!existing.lastDate || e.created_at > existing.lastDate) {
        existing.lastDate = e.created_at;
      }
      existing.count++;
      if (e.agent_id) existing.agents.add(e.agent_id);
      topicLastRef.set(topic, existing);
    }
  }

  // Find gaps (topics last referenced > gapDays ago)
  const gaps = [];
  for (const [topic, data] of topicLastRef.entries()) {
    if (!data.lastDate) continue;
    const days = daysSince(data.lastDate);
    if (days > gapDays && data.count >= 1) {
      const severity = days > gapDays * 3 ? 'high' : days > gapDays * 2 ? 'medium' : 'low';
      gaps.push({
        topic,
        last_referenced: data.lastDate,
        days_since: days,
        severity,
        reference_count: data.count,
        known_agents: [...data.agents],
      });
    }
  }

  // Sort by days since (most stale first)
  gaps.sort((a, b) => b.days_since - a.days_since);

  // Limit to top 20 gaps
  return gaps.slice(0, 20);
}

// ─── Orphan Detection ────────────────────────────────────────────────────────

function _findOrphans(entries, orphanDays, nowIso) {
  // Find decision entries that have no outcome tracking child entries
  const decisionEntries = entries.filter(e => e.type === 'decision');
  const orphans = [];

  for (const d of decisionEntries) {
    // Check if decision has direct outcome
    const hasDirectOutcome = d.outcome ||
      (d.content && (d.content.includes('Outcome: success') ||
                     d.content.includes('Outcome: failure') ||
                     d.content.includes('Outcome: partial') ||
                     d.content.includes('Result: won') ||
                     d.content.includes('Result: lost')));

    // Check if any child entries reference outcome
    let hasChildOutcome = false;
    for (const e of entries) {
      if (e.parent_entry === d.id) {
        const content = e.content || '';
        if (content.includes('Outcome:') || content.includes('Decision Outcome') ||
            content.includes('Win/Loss Result') || content.includes('ROI Achievement')) {
          hasChildOutcome = true;
          break;
        }
      }
    }

    const ageDays = getAgeInDays(d.created_at);

    if (!hasDirectOutcome && !hasChildOutcome && ageDays >= orphanDays) {
      orphans.push({
        decision: extractDecisionText(d.content),
        agent: d.agent_id || 'unknown',
        made_at: d.created_at,
        days_orphaned: ageDays,
        entry_id: d.id,
      });
    }
  }

  // Sort by days orphaned (most severe first)
  orphans.sort((a, b) => b.days_orphaned - a.days_orphaned);
  return orphans.slice(0, 20);
}

// ─── Stale Decision Detection ────────────────────────────────────────────────

function _findStaleDecisions(entries, staleDays, nowIso) {
  const decisions = entries.filter(e => e.type === 'decision');
  const stale = [];

  for (const d of decisions) {
    const ageDays = getAgeInDays(d.created_at);
    if (ageDays < staleDays) continue;

    // Check if decision has been updated/reviewed recently
    // (via child entries or direct update)
    let lastReviewed = d.last_read_at || null;
    let hasRecentChild = false;
    let lastChildDate = null;

    for (const e of entries) {
      if (e.parent_entry === d.id) {
        if (lastChildDate === null || e.created_at > lastChildDate) {
          lastChildDate = e.created_at;
        }
        if (e.type === 'observation' || e.type === 'state_update') {
          const childAge = getAgeInDays(e.created_at);
          if (childAge < staleDays * 0.5) {
            hasRecentChild = true;
          }
        }
      }
    }

    if (!hasRecentChild) {
      stale.push({
        decision: extractDecisionText(d.content),
        agent: d.agent_id || 'unknown',
        age_days: ageDays,
        last_reviewed: lastReviewed || null,
        last_child_entry: lastChildDate || null,
        entry_id: d.id,
        severity: ageDays > staleDays * 2 ? 'high' : ageDays > staleDays * 1.5 ? 'medium' : 'low',
      });
    }
  }

  stale.sort((a, b) => b.age_days - a.age_days);
  return stale.slice(0, 20);
}

// ─── Single-Point-of-Failure Detection ──────────────────────────────────────

function _findSinglePointsOfFailure(entries) {
  // Build topic -> agent mapping
  const topicAgentMap = new Map(); // topic -> Set of agent IDs

  for (const e of entries) {
    const contentTopics = extractKeyTopics(e.content);
    const tagTopics = extractTagsAsTopics(e.tags);
    const allTopics = [...new Set([...contentTopics, ...tagTopics])];

    for (const topic of allTopics) {
      if (!topic || topic.length < 2) continue;
      if (!topicAgentMap.has(topic)) {
        topicAgentMap.set(topic, { agents: new Set(), entryCount: 0, lastEntry: null });
      }
      const data = topicAgentMap.get(topic);
      data.agents.add(e.agent_id || 'unknown');
      data.entryCount++;
      if (!data.lastEntry || e.created_at > data.lastEntry) {
        data.lastEntry = e.created_at;
      }
    }
  }

  const spofs = [];
  for (const [topic, data] of topicAgentMap.entries()) {
    if (data.agents.size === 1) {
      const agent = [...data.agents][0];
      const daysSinceLast = data.lastEntry ? daysSince(data.lastEntry) : Infinity;

      spofs.push({
        topic,
        held_by: agent,
        entry_count: data.entryCount,
        days_since_last_entry: daysSinceLast,
        risk: `If "${agent}" becomes unavailable, knowledge of "${topic}" is lost`,
        severity: daysSinceLast > 90 ? 'high' : daysSinceLast > 30 ? 'medium' : 'low',
      });
    }
  }

  spofs.sort((a, b) => b.days_since_last_entry - a.days_since_last_entry);
  return spofs.slice(0, 20);
}

// ─── Amnesia Score ───────────────────────────────────────────────────────────

function _calculateAmnesiaScore(entries, gaps, orphans, staleDecisions, spofs) {
  if (entries.length === 0) return 0;

  // Base score components (0-1, weighted)
  const gapWeight = Math.min(gaps.length / Math.max(entries.length, 1) * 5, 0.25);
  const orphanWeight = Math.min(orphans.length / Math.max(entries.filter(e => e.type === 'decision').length, 1) * 3, 0.25);
  const staleWeight = Math.min(staleDecisions.length / Math.max(entries.filter(e => e.type === 'decision').length, 1) * 3, 0.25);
  const spofWeight = Math.min(spofs.length / Math.max(entries.length, 1) * 5, 0.25);

  // Severity multipliers
  const highSeverityCount = [...gaps, ...orphans, ...staleDecisions, ...spofs]
    .filter(i => i.severity === 'high').length;
  const severityBonus = Math.min(highSeverityCount * 0.05, 0.2);

  const score = Math.min(gapWeight + orphanWeight + staleWeight + spofWeight + severityBonus, 1);
  return Math.round(score * 100) / 100;
}

// ─── Summary Builder ─────────────────────────────────────────────────────────

function _buildSummary(gaps, orphans, staleDecisions, spofs, amnesiaScore, totalEntries) {
  const parts = [];

  if (totalEntries === 0) return 'No entries in Grid.';

  if (gaps.length > 0) {
    parts.push(`${gaps.length} knowledge gap(s) found — topics last discussed 30+ days ago`);
  }
  if (orphans.length > 0) {
    parts.push(`${orphans.length} orphaned decision(s) — never acted upon`);
  }
  if (staleDecisions.length > 0) {
    parts.push(`${staleDecisions.length} stale decision(s) — no review in 60+ days`);
  }
  if (spofs.length > 0) {
    parts.push(`${spofs.length} single-point(s)-of-failure — knowledge held by one agent`);
  }

  if (parts.length === 0) {
    return `No significant amnesia detected. ${totalEntries} entries analyzed. Amnesia score: ${amnesiaScore}/1.0.`;
  }

  return `Amnesia score: ${amnesiaScore}/1.0. ${parts.join('. ')}. Total entries analyzed: ${totalEntries}.`;
}

// ─── CLI Entry Point ─────────────────────────────────────────────────────────

async function main() {
  const { Grid } = require('./reference/store.js');
  const grid = new Grid();

  try {
    const result = await detect(grid);
    console.log(JSON.stringify(result, null, 2));
  } catch (err) {
    console.error(JSON.stringify({ error: err.message }, null, 2));
    process.exit(1);
  }
}

if (require.main === module) {
  main();
}

module.exports = { detect };
