#!/usr/bin/env node
'use strict';
/**
 * decision-graph.js — Decision Graph API
 *
 * Builds a graph of decisions with rationale, outcomes, and linked entries.
 * Tracks decision-maker rankings, success rates, and pattern analysis.
 *
 * Endpoints (registered in server.js):
 *   GET /decisions/graph   — Full decision graph
 *   GET /decisions/stats   — Decision analysis stats
 *
 * Usage:
 *   const { getGraph, getStats } = require('./decision-graph.js');
 *   const graph = await getGraph(grid, { depth: 3 });
 *   const stats = await getStats(grid);
 */


// ─── Helpers ──────────────────────────────────────────────────────────────────

function now() {
  return new Date().toISOString();
}

function extractConfidence(content) {
  if (!content) return 'medium';
  const lower = content.toLowerCase();
  if (lower.includes('confidence: high') || lower.includes('high confidence')) return 'high';
  if (lower.includes('confidence: low') || lower.includes('low confidence')) return 'low';
  if (lower.includes('confidence: medium') || lower.includes('medium confidence')) return 'medium';
  return 'medium';
}

function extractRationale(content) {
  if (!content) return '';
  // Look for "Rationale:" or "Reason:" lines
  for (const line of content.split('\n')) {
    const trimmed = line.trim();
    if (trimmed.startsWith('Rationale:')) return trimmed.slice('Rationale:'.length).trim();
    if (trimmed.startsWith('Reason:')) return trimmed.slice('Reason:'.length).trim();
  }
  return '';
}

function extractOutcome(content) {
  if (!content) return null;
  const lower = content.toLowerCase();
  if (lower.includes('outcome: success') || lower.includes('result: won')) return 'success';
  if (lower.includes('outcome: failure') || lower.includes('result: lost')) return 'failure';
  if (lower.includes('outcome: partial') || lower.includes('partial success')) return 'partial';
  return null;
}

function extractDelta(content) {
  if (!content) return '';
  // Look for delta metrics in content
  for (const line of content.split('\n')) {
    const trimmed = line.trim();
    if (trimmed.startsWith('Delta:')) return trimmed.slice('Delta:'.length).trim();
    if (trimmed.startsWith('Value:')) return trimmed.slice('Value:'.length).trim();
    if (trimmed.startsWith('Impact:')) return trimmed.slice('Impact:'.length).trim();
  }
  return '';
}

// ─── Build Decision Graph ────────────────────────────────────────────────────

async function getGraph(grid, options = {}) {
  const maxDepth = options.depth || 5;

  // Get all decision entries
  const result = await grid.read({ type: 'decision', max: 500 });
  let decisions = result.entries || [];

  if (decisions.length === 0) {
    // Fallback: search broader
    const broadResult = await grid.read({ max: 200 });
    decisions = (broadResult.entries || []).filter(e => e.type === 'decision');
  }

  // Also get all entries to find linked children
  const allResult = await grid.read({ max: 500 });
  const allEntries = allResult.entries || [];

  // Build lookup by ID
  const entryMap = new Map();
  for (const e of allEntries) {
    entryMap.set(e.id, e);
  }

  // Build parent->children index
  const childrenIndex = new Map(); // parentId -> child entries
  for (const e of allEntries) {
    if (e.parent_entry) {
      if (!childrenIndex.has(e.parent_entry)) childrenIndex.set(e.parent_entry, []);
      childrenIndex.get(e.parent_entry).push(e);
    }
  }

  // Build graph nodes for each decision
  const nodes = [];

  for (const decision of decisions) {
    const outcome = extractOutcome(decision.content)
      || (decision.outcome ? decision.outcome.result : null);

    const node = {
      id: decision.id,
      agent: decision.agent_id,
      decision: (decision.content || '').split('\n')[0].slice(0, 100),
      rationale: extractRationale(decision.content),
      outcome: outcome,
      delta: extractDelta(decision.content),
      timestamp: decision.created_at,
      tags: decision.tags || [],
      confidence: extractConfidence(decision.content),
      children: [],
    };

    // Attach linked children (chain depth-limited)
    node.children = _getLinkedChildren(decision.id, childrenIndex, entryMap, maxDepth);

    nodes.push(node);
  }

  return {
    total_nodes: nodes.length,
    max_depth: maxDepth,
    generated_at: now(),
    nodes,
  };
}

/**
 * Recursively collect linked decision children up to depth.
 */
function _getLinkedChildren(parentId, childrenIndex, entryMap, depth) {
  if (depth <= 0) return [];
  const children = childrenIndex.get(parentId) || [];
  if (children.length === 0) return [];

  const linked = [];
  for (const child of children) {
    const childNode = {
      id: child.id,
      agent: child.agent_id,
      type: child.type,
      content: (child.content || '').slice(0, 150),
      timestamp: child.created_at,
      tags: child.tags || [],
      outcome: child.outcome ? child.outcome.result : extractOutcome(child.content),
    };

    // Recurse into children of children
    if (child.type === 'decision') {
      childNode.children = _getLinkedChildren(child.id, childrenIndex, entryMap, depth - 1);
    }

    linked.push(childNode);
  }

  return linked;
}

// ─── Decision Stats ──────────────────────────────────────────────────────────

async function getStats(grid) {
  const result = await grid.read({ type: 'decision', max: 500 });
  let decisions = result.entries || [];

  if (decisions.length === 0) {
    const broadResult = await grid.read({ max: 200 });
    decisions = (broadResult.entries || []).filter(e => e.type === 'decision');
  }

  // Get all entries for outcome cross-referencing
  const allResult = await grid.read({ max: 500 });
  const allEntries = allResult.entries || [];

  // Build children index for outcomes
  const childrenIndex = new Map();
  for (const e of allEntries) {
    if (e.parent_entry) {
      if (!childrenIndex.has(e.parent_entry)) childrenIndex.set(e.parent_entry, []);
      childrenIndex.get(e.parent_entry).push(e);
    }
  }

  // ── Decision-maker rankings ──
  const agentStats = new Map(); // agentId -> { decisions, outcomes, success, failure }

  for (const d of decisions) {
    const agent = d.agent_id || 'unknown';
    if (!agentStats.has(agent)) {
      agentStats.set(agent, { decisions: 0, outcomes: 0, success: 0, failure: 0, partial: 0 });
    }
    const stats = agentStats.get(agent);
    stats.decisions++;

    // Check direct outcome
    const directOutcome = extractOutcome(d.content) || (d.outcome ? d.outcome.result : null);
    if (directOutcome) {
      stats.outcomes++;
      if (directOutcome === 'success') stats.success++;
      else if (directOutcome === 'failure') stats.failure++;
      else if (directOutcome === 'partial') stats.partial++;
    }

    // Check child entries for outcomes
    const children = childrenIndex.get(d.id) || [];
    for (const child of children) {
      const childOutcome = extractOutcome(child.content) || (child.outcome ? child.outcome.result : null);
      if (childOutcome && childOutcome !== directOutcome) {
        stats.outcomes++;
        if (childOutcome === 'success') stats.success++;
        else if (childOutcome === 'failure') stats.failure++;
        else if (childOutcome === 'partial') stats.partial++;
      }
    }
  }

  const decisionMakers = [];
  for (const [agent, stats] of agentStats.entries()) {
    decisionMakers.push({
      agent,
      total_decisions: stats.decisions,
      tracked_outcomes: stats.outcomes,
      successes: stats.success,
      failures: stats.failure,
      partial: stats.partial,
      success_rate: stats.outcomes > 0
        ? Math.round((stats.success / stats.outcomes) * 1000) / 10 + '%'
        : '0%',
      outcome_coverage: stats.decisions > 0
        ? Math.round((stats.outcomes / stats.decisions) * 100) + '%'
        : '0%',
    });
  }

  decisionMakers.sort((a, b) => {
    const rateA = parseFloat(a.success_rate) || 0;
    const rateB = parseFloat(b.success_rate) || 0;
    return rateB - rateA;
  });

  // ── Pattern analysis ──
  const patterns = [];
  const noRationaleCount = decisions.filter(d => !extractRationale(d.content)).length;
  if (noRationaleCount > 0) {
    patterns.push({
      pattern: 'Decisions without documented rationale',
      count: noRationaleCount,
      percentage: Math.round((noRationaleCount / decisions.length) * 100) + '%',
      insight: `${noRationaleCount} of ${decisions.length} decisions lack a rationale. Encourage documenting reasoning.`,
    });
  }

  const noOutcomeCount = decisions.filter(d => {
    return !extractOutcome(d.content) && !d.outcome;
  }).length;
  if (noOutcomeCount > 0) {
    patterns.push({
      pattern: 'Decisions without tracked outcomes',
      count: noOutcomeCount,
      percentage: Math.round((noOutcomeCount / decisions.length) * 100) + '%',
      insight: `${noOutcomeCount} decisions have no outcome recorded. Track outcomes to measure decision quality.`,
    });
  }

  // Topic analysis
  const topicCounts = new Map();
  for (const d of decisions) {
    for (const tag of d.tags || []) {
      if (tag.startsWith('agent:') || tag.startsWith('stage:') || tag.startsWith('ws:') || tag.startsWith('client:')) continue;
      topicCounts.set(tag, (topicCounts.get(tag) || 0) + 1);
    }
  }
  const topTopics = [...topicCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([topic, count]) => ({ topic, count }));

  // ── Overall stats ──
  const totalOutcomes = decisions.filter(d => {
    return extractOutcome(d.content) || d.outcome;
  }).length;

  const totalSuccess = decisions.filter(d => {
    const o = extractOutcome(d.content) || (d.outcome ? d.outcome.result : null);
    return o === 'success';
  }).length;

  const totalFailure = decisions.filter(d => {
    const o = extractOutcome(d.content) || (d.outcome ? d.outcome.result : null);
    return o === 'failure';
  }).length;

  const totalPartial = decisions.filter(d => {
    const o = extractOutcome(d.content) || (d.outcome ? d.outcome.result : null);
    return o === 'partial';
  }).length;

  return {
    total_decisions: decisions.length,
    decisions_with_outcomes: totalOutcomes,
    outcome_coverage: decisions.length > 0
      ? Math.round((totalOutcomes / decisions.length) * 100) + '%'
      : '0%',
    overall_success_rate: totalOutcomes > 0
      ? Math.round((totalSuccess / totalOutcomes) * 100) + '%'
      : '0%',
    outcomes: {
      success: totalSuccess,
      failure: totalFailure,
      partial: totalPartial,
    },
    decision_makers: decisionMakers,
    top_topics: topTopics,
    patterns,
    generated_at: now(),
  };
}

// ─── CLI Entry Point ─────────────────────────────────────────────────────────

async function main() {
  const { Grid } = require('./reference/store.js');
  const grid = new Grid();
  const command = process.argv[2] || 'graph';

  try {
    if (command === 'graph') {
      const result = await getGraph(grid, { depth: parseInt(process.argv[3], 10) || 5 });
      console.log(JSON.stringify(result, null, 2));
    } else if (command === 'stats') {
      const result = await getStats(grid);
      console.log(JSON.stringify(result, null, 2));
    } else {
      console.error('Usage: node decision-graph.js [graph|stats]');
      process.exit(1);
    }
  } catch (err) {
    console.error(JSON.stringify({ error: err.message }, null, 2));
    process.exit(1);
  }
}

if (require.main === module) {
  main();
}

module.exports = { getGraph, getStats };
