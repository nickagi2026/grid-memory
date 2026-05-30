#!/usr/bin/env node
'use strict';
/**
 * instant-roi.js — Instant ROI Display
 *
 * Scans the Grid and computes high-level ROI metrics:
 * - Duplicates prevented
 * - Contradictions detected
 * - Opportunities found
 * - Decisions tracked
 * - Time saved estimate
 */

/**
 * Compute ROI metrics by scanning existing Grid entries.
 * @param {Object} grid — Grid store instance
 * @returns {Object} ROI report
 */
async function computeROI(grid) {
  const info = await grid.info();
  let result;

  try {
    result = await grid.read({ max: 500 });
  } catch (e) {
    result = { entries: [] };
  }

  const entries = result.entries || [];
  const totalEntries = info.total_entries || entries.length;

  // Count by type
  const typeCounts = {};
  for (const e of entries) {
    const t = e.type || 'observation';
    typeCounts[t] = (typeCounts[t] || 0) + 1;
  }

  // Detect duplicates: entries with very similar content
  const duplicatePairs = [];
  const seen = new Map();
  for (const e of entries) {
    const content = (e.content || '').toLowerCase().trim();
    // Check for exact matches (conservative dup detection)
    if (content.length > 20) {
      const existing = seen.get(content);
      if (existing) {
        duplicatePairs.push({ original: existing, duplicate: e.id });
      } else {
        seen.set(content, e.id);
      }
    }
  }

  // Detect contradictions: decisions with opposing content on same tag
  const contradictPairs = [];
  const decisionsByTag = {};
  for (const e of entries) {
    if (e.type === 'decision') {
      const tags = (e.tags || []).filter(t => !t.startsWith('_') && !t.startsWith('ws:'));
      for (const tag of tags) {
        if (!decisionsByTag[tag]) decisionsByTag[tag] = [];
        decisionsByTag[tag].push(e);
      }
    }
  }

  // Count contradictions: same tag, different agent, opposing language
  const decisionWords = /(?:not|don'?t|never|avoid|instead|but|however|oppose|reject|against|disagree)/i;
  for (const [tag, ents] of Object.entries(decisionsByTag)) {
    if (ents.length < 2) continue;
    const agents = new Set(ents.map(e => e.agent_id));
    if (agents.size < 2) continue;
    for (let i = 0; i < ents.length; i++) {
      for (let j = i + 1; j < ents.length; j++) {
        if (ents[i].agent_id !== ents[j].agent_id) {
          const ci = (ents[i].content || '').toLowerCase();
          const cj = (ents[j].content || '').toLowerCase();
          // Check for contradictory language
          if (decisionWords.test(ci) !== decisionWords.test(cj)) {
            contradictPairs.push({
              tag,
              entry_a: ents[i].id,
              entry_b: ents[j].id,
              agents: [ents[i].agent_id, ents[j].agent_id],
            });
          }
        }
      }
    }
  }

  // Detect opportunities: entries with "opportunity", "potential", "should"
  const opportunityEntries = entries.filter(e => {
    const c = (e.content || '').toLowerCase();
    return /opportunity|potential|should\s+(consider|explore|evaluate|investigate|look\s+into)|worth\s+(exploring|looking|considering)/i.test(c);
  });

  // Compute time savings estimate
  const dupSavings = duplicatePairs.length * 15;    // 15 min saved per duplicate prevented
  const contradictionSavings = contradictPairs.length * 30; // 30 min per contradiction caught
  const opportunityValue = opportunityEntries.length * 10;  // 10 min per opportunity identified
  const decisionValue = (typeCounts['decision'] || 0) * 5;  // 5 min per decision tracked
  const totalMinutes = dupSavings + contradictionSavings + opportunityValue + decisionValue;
  const hoursPerWeek = Math.max(0.5, Math.round(totalMinutes / 60 * 10) / 10);

  return {
    grid_summary: {
      total_entries: totalEntries,
      alive_entries: info.alive_entries || entries.length,
    },
    duplicates_prevented: duplicatePairs.length,
    contradictions_detected: contradictPairs.length,
    opportunities_found: opportunityEntries.length,
    decisions_tracked: typeCounts['decision'] || 0,
    entry_breakdown: typeCounts,
    time_saved_estimate: `~${hoursPerWeek} hours/week`,
    time_saved_minutes: Math.round(totalMinutes),
    details: {
      duplicate_pairs: duplicatePairs,
      contradiction_pairs: contradictPairs,
    },
  };
}

module.exports = { computeROI };
