#!/usr/bin/env node
'use strict';
/**
 * mike-dashboard.js — MIKE Dashboard API
 *
 * Revenue-generating business intelligence dashboard derived entirely from
 * existing Grid entries. No additional data sources required.
 *
 * Endpoints (registered in server.js):
 *   GET /mike/dashboard  — Full MIKE dashboard with client breakdowns
 *
 * Usage:
 *   const { generateDashboard } = require('./mike-dashboard.js');
 *   const dashboard = await generateDashboard(grid);
 */


// ─── Helpers ──────────────────────────────────────────────────────────────────

function now() {
  return new Date().toISOString();
}

function extractTagValue(tags, prefix) {
  for (const t of tags || []) {
    if (t.startsWith(prefix)) return t.slice(prefix.length);
  }
  return null;
}

function extractStage(tags) {
  return extractTagValue(tags, 'stage:') || 'detected';
}

function extractRevenueFromContent(content) {
  if (!content) return 0;
  // Try "Revenue:" pattern first
  const revMatch = content.match(/Revenue:\s*\$?([\d,]+(?:\.\d+)?)/);
  if (revMatch) return parseFloat(revMatch[1].replace(/,/g, ''));
  // Try "Estimated Annual Value:" pattern
  const valMatch = content.match(/Estimated Annual Value:\s*\$?([\d,]+(?:\.\d+)?)/);
  if (valMatch) return parseFloat(valMatch[1].replace(/,/g, ''));
  // Try "Value:" pattern
  const valMatch2 = content.match(/Value:\s*\$?([\d,]+(?:\.\d+)?)/);
  if (valMatch2) return parseFloat(valMatch2[1].replace(/,/g, ''));
  return 0;
}

function extractAccuracy(content) {
  if (!content) return null;
  const match = content.match(/Accuracy:\s*([\d.]+)%/);
  if (match) return parseFloat(match[1]);
  return null;
}

function extractAgentFromTags(tags) {
  return extractTagValue(tags, 'agent:');
}

function extractClientFromTags(tags) {
  return extractTagValue(tags, 'client:');
}

// ─── Main Dashboard Generator ────────────────────────────────────────────────

async function generateDashboard(grid) {
  // Pull all entries with a generous limit
  const allResult = await grid.read({ max: 500 });
  const entries = allResult.entries || [];

  if (entries.length === 0) {
    // Fall back to exportAll for complete data
    const full = await grid.exportAll();
    const alive = full.entries || [];
    return _buildDashboard(alive, grid);
  }

  return _buildDashboard(entries, grid);
}

async function _buildDashboard(entries, grid) {
  // ── Summary ──
  const uniqueAgents = new Set();
  const uniqueWorkspaces = new Set();
  let oldestEntry = null;
  let newestEntry = null;

  for (const e of entries) {
    if (e.agent_id) uniqueAgents.add(e.agent_id);
    if (e.workspace_id) uniqueWorkspaces.add(e.workspace_id);
    if (!oldestEntry || e.created_at < oldestEntry) oldestEntry = e.created_at;
    if (!newestEntry || e.created_at > newestEntry) newestEntry = e.created_at;
  }

  const summary = {
    total_entries: entries.length,
    unique_agents: uniqueAgents.size,
    unique_workspaces: uniqueWorkspaces.size,
    oldest_entry: oldestEntry || null,
    newest_entry: newestEntry || null,
  };

  // ── Client Breakdown ──
  // Group entries by client (from tags or workspace_id)
  const clientMap = new Map(); // clientName -> { entries[], agentSet, oppCount, decisionCount }

  for (const e of entries) {
    const client = extractClientFromTags(e.tags) || e.workspace_id || '_ungrouped';
    if (!clientMap.has(client)) {
      clientMap.set(client, { entries: [], agents: new Set(), opportunityCount: 0, decisionCount: 0 });
    }
    const bucket = clientMap.get(client);
    bucket.entries.push(e);
    if (e.agent_id) bucket.agents.add(e.agent_id);
    if (e.type === 'opportunity') bucket.opportunityCount++;
    if (e.type === 'decision') bucket.decisionCount++;
  }

  const clients = [];
  for (const [name, data] of clientMap.entries()) {
    clients.push({
      name,
      entries: data.entries.length,
      agents: data.agents.size,
      opportunities: data.opportunityCount,
      decisions: data.decisionCount,
    });
  }
  clients.sort((a, b) => b.entries - a.entries);

  // ── Opportunities Pipeline ──
  const stageCounts = { detected: 0, reviewed: 0, accepted: 0, assessment: 0, proposed: 0, won: 0, lost: 0 };
  // Stage-weighted pipeline with age decay (doc-aligned methodology)
  const STAGE_WEIGHTS = { detected: 0.1, reviewed: 0.3, accepted: 0.5, assessment: 0.7, proposed: 0.85, won: 1.0, lost: 0 };
  let totalPipelineValue = 0;
  let wonDealCount = 0;
  let lostDealCount = 0;
  let wonRevenue = 0;

  for (const e of entries) {
    if (e.type !== 'opportunity' && !(e.tags || []).includes('opportunity')) continue;
    const stage = extractStage(e.tags);
    if (stageCounts.hasOwnProperty(stage)) {
      stageCounts[stage]++;
    }
    const value = extractRevenueFromContent(e.content);
    if (stage === 'won') {
      wonDealCount++;
      wonRevenue += value;
    } else if (stage === 'lost') {
      lostDealCount++;
    } else {
      // Weighted pipeline: stage probability × age decay
      const weight = STAGE_WEIGHTS[stage] || 0.1;
      const ageDays = e.created_at ? (Date.now() - new Date(e.created_at).getTime()) / 86400000 : 0;
      const ageFactor = ageDays > 180 ? 0.5 : 1.0;
      totalPipelineValue += value * weight * ageFactor;
    }
  }

  const totalDeals = wonDealCount + lostDealCount;
  const winRate = totalDeals > 0 ? Math.round((wonDealCount / totalDeals) * 100) + '%' : '0%';

  const opportunities = {
    total: Object.values(stageCounts).reduce((a, b) => a + b, 0),
    by_stage: stageCounts,
    pipeline_value: '$' + totalPipelineValue.toLocaleString(),
    win_rate: winRate,
  };

  // ── Risks & Contradictions ──
  const risks = [];

  // Check for contradictions (entries with contradictory: tag)
  const contradictionEntries = entries.filter(e =>
    (e.tags || []).includes('contradiction') || (e.tags || []).some(t => t.startsWith('contradiction'))
  );
  if (contradictionEntries.length > 0) {
    risks.push({
      type: 'contradiction',
      severity: contradictionEntries.length > 5 ? 'high' : contradictionEntries.length > 2 ? 'medium' : 'low',
      details: `${contradictionEntries.length} contradictory entries detected`,
    });
  }

  // Check for stale entries (not read in 30+ days)
  const nowIso = now();
  const staleEntries = entries.filter(e => {
    if (!e.last_read_at) return false;
    const daysSinceRead = (new Date(nowIso) - new Date(e.last_read_at)) / (1000 * 60 * 60 * 24);
    return daysSinceRead > 30;
  });
  if (staleEntries.length > 0) {
    const staleRatio = staleEntries.length / entries.length;
    risks.push({
      type: 'stale',
      severity: staleRatio > 0.5 ? 'high' : staleRatio > 0.25 ? 'medium' : 'low',
      details: `${staleEntries.length} of ${entries.length} entries unread for 30+ days (${Math.round(staleRatio * 100)}%)`,
    });
  }

  // ── Revenue ──
  // Collect accuracy data from ROI entries
  const roiEntries = entries.filter(e =>
    (e.tags || []).includes('roi') || (e.content || '').includes('ROI Achievement')
  );
  const accuracies = [];
  for (const e of roiEntries) {
    const acc = extractAccuracy(e.content);
    if (acc !== null) accuracies.push(acc);
  }
  const avgAccuracy = accuracies.length > 0
    ? Math.round((accuracies.reduce((a, b) => a + b, 0) / accuracies.length) * 10) / 10 + '%'
    : '0%';

  const revenue = {
    won_deals: wonDealCount,
    total_revenue: '$' + wonRevenue.toLocaleString(),
    pipeline: '$' + totalPipelineValue.toLocaleString(),
    avg_accuracy: avgAccuracy,
  };

  // ── Decisions ──
  const decisionEntries = entries.filter(e => e.type === 'decision');
  const byMakerMap = new Map();

  for (const e of decisionEntries) {
    const agent = e.agent_id || 'unknown';
    if (!byMakerMap.has(agent)) {
      byMakerMap.set(agent, { count: 0, successCount: 0, totalOutcomes: 0 });
    }
    const maker = byMakerMap.get(agent);
    maker.count++;
    // Check for outcome on the entry itself
    if (e.outcome) {
      maker.totalOutcomes++;
      if (e.outcome.result === 'success') maker.successCount++;
    }
  }

  // Also check child entries for outcome data
  for (const maker of byMakerMap.values()) {
    // We already counted outcomes from entries — now derive success rate
  }

  const by_maker = [];
  for (const [agent, data] of byMakerMap.entries()) {
    const successRate = data.totalOutcomes > 0
      ? Math.round((data.successCount / data.totalOutcomes) * 100) + '%'
      : '0%';
    by_maker.push({ agent, count: data.count, success_rate: successRate });
  }
  by_maker.sort((a, b) => b.count - a.count);

  const recentDecisions = decisionEntries
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, 10)
    .map(e => ({
      id: e.id,
      agent: e.agent_id,
      content: (e.content || '').slice(0, 200),
      created_at: e.created_at,
      outcome: e.outcome ? e.outcome.result : null,
    }));

  const decisions = {
    total: decisionEntries.length,
    by_maker,
    recent: recentDecisions,
  };

  // ── Assemble ──
  return {
    summary,
    clients,
    opportunities,
    risks,
    revenue,
    decisions,
  };
}

// ─── CLI Entry Point ─────────────────────────────────────────────────────────

async function main() {
  const { Grid } = require('./reference/store.js');
  const grid = new Grid();
  try {
    const dashboard = await generateDashboard(grid);
    console.log(JSON.stringify(dashboard, null, 2));
  } catch (err) {
    console.error(JSON.stringify({ error: err.message }, null, 2));
    process.exit(1);
  }
}

if (require.main === module) {
  main();
}

module.exports = { generateDashboard };
